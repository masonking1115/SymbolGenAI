"""Agent runner — wraps `claude -p` so the GUI can drive a Claude Code session.

There are two distinct call sites today:

  1. Chat turn  — user typed something into the GUI's right rail. The agent's
     job here is *advisory*: ack the request and append a one-line bullet
     to the changelog file. It must NOT edit the netlist or code on a chat
     turn — those edits only happen at "apply changelog" time.

  2. Apply pass — user clicked Generate. The agent reads the queued
     changelog and implements each item (Edit/Write on yaml + python). The
     pipeline (build_project → validate + lint → review) is run by the backend
     *after* this returns, NOT by the agent.

The same `claude` binary backs both. We swap the system-prompt suffix and
the prompt body to switch modes. Output is streamed back to the GUI line by
line so the user can watch tool calls in real time.

Auth: this re-uses whatever auth the user already has set up for `claude`.
No API key is read from the env. The subprocess inherits the user's env.

State on disk
-------------
  state/chats.json     — multi-session chat store: per-session transcript +
                         compacted summary. Replayed each chat turn so
                         multi-turn context works; the default session is the
                         one the GUI selects on load.
  state/chat.json      — legacy single transcript (migrated into chats.json)
  state/changelog.json — queued items: [{id, summary, source, ts}]
  state/status.json    — most recent pipeline status snapshot
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent          # test1/
REPO_ROOT = PROJECT_DIR.parent            # SymbolGenAI/ — the agent's working dir
STATE_DIR = HERE.parent / "state"         # test1/gui/state/
CHAT_FILE = STATE_DIR / "chat.json"       # legacy single transcript (migrated)
CHATS_FILE = STATE_DIR / "chats.json"     # multi-session chat store
CHANGELOG_FILE = STATE_DIR / "changelog.json"
DECISIONS_FILE = STATE_DIR / "decisions.json"   # last apply/fix run's per-item outcomes
STATUS_FILE = STATE_DIR / "status.json"

# Claude Code auto-memory dir for this project. The `claude -p` subprocess loads
# memory keyed by its working directory, which Claude slugifies as the absolute
# path with non-alphanumerics → '-' (e.g. C:\Users\mking\Downloads\HW-SW_CoDesigner
# → 'c--Users-mking-Downloads-HW-SW-CoDesigner'). Derive it from REPO_ROOT's
# parent (the working dir) so it isn't hardcoded to one user/path.
def _memory_dir() -> Path:
    cwd = REPO_ROOT.parent  # the dir the GUI/agent runs from (…/HW-SW_CoDesigner)
    # Claude slugifies with a lowercased drive letter on Windows.
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    if len(slug) >= 2 and slug[1] == "-":          # "C--Users…" → "c--Users…"
        slug = slug[0].lower() + slug[1:]
    return Path.home() / ".claude" / "projects" / slug / "memory"

MEMORY_DIR = _memory_dir()

CLAUDE = "claude"
# This backend's interpreter (the spike venv) — has PyMuPDF (fitz), so the sim
# agents can render datasheet PDFs to images via sim/read_pdf.py.
PY = sys.executable
MODEL = os.environ.get("TEST1_AGENT_MODEL", "sonnet")
MAX_HISTORY_TURNS = 30

# ---------------------------------------------------------------------------
# Per-agent model selection
# ---------------------------------------------------------------------------
# Each agent KIND can run on a different Claude model — extraction/verdict are
# fine on a fast/cheap model, while writing a new deck builder (generate-model)
# wants the strongest one. The choice is user-overridable from the GUI and
# persisted in state/agent_models.json; falls back to the per-kind default, then
# the global MODEL.
#
# MODEL_CATALOG is the EXACT set of Anthropic model IDs the picker offers — full
# pinned-snapshot ids that `claude -p --model` accepts verbatim (the CLI also
# accepts the short aliases opus/sonnet/haiku, but we expose explicit ids so the
# choice is unambiguous + reproducible). Source: Anthropic models overview
# (platform.claude.com/docs/.../models/overview), current as of 2026-05. Keep in
# sync when Anthropic ships/retires a model. tier: relative capability/cost for
# the GUI; label: menu text.
MODEL_CATALOG: list[dict] = [
    # --- latest generation ---
    {"id": "claude-opus-4-8",              "label": "Opus 4.8 (latest, most capable)", "family": "opus",   "tier": "frontier", "latest": True},
    {"id": "claude-sonnet-4-6",            "label": "Sonnet 4.6 (balanced)",           "family": "sonnet", "tier": "balanced", "latest": True},
    {"id": "claude-haiku-4-5-20251001",    "label": "Haiku 4.5 (fastest)",             "family": "haiku",  "tier": "fast",     "latest": True},
    # --- legacy, still available ---
    {"id": "claude-opus-4-7",              "label": "Opus 4.7",                         "family": "opus",   "tier": "frontier", "latest": False},
    {"id": "claude-opus-4-6",              "label": "Opus 4.6",                         "family": "opus",   "tier": "frontier", "latest": False},
    {"id": "claude-opus-4-5-20251101",     "label": "Opus 4.5",                         "family": "opus",   "tier": "frontier", "latest": False},
    {"id": "claude-opus-4-1-20250805",     "label": "Opus 4.1",                         "family": "opus",   "tier": "frontier", "latest": False},
    {"id": "claude-sonnet-4-5-20250929",   "label": "Sonnet 4.5",                       "family": "sonnet", "tier": "balanced", "latest": False},
]
MODEL_IDS = [m["id"] for m in MODEL_CATALOG]
# Short aliases still accepted (e.g. a persisted "opus") → resolve to the latest
# of that family, so old configs + the CLI aliases keep working.
_ALIAS_TO_ID = {
    "opus":   "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
}

def _canon_model(m: str | None) -> str | None:
    """A model string the picker/CLI accepts → a known full id, or None."""
    if not m:
        return None
    if m in MODEL_IDS:
        return m
    return _ALIAS_TO_ID.get(m)

AGENT_MODELS_FILE = STATE_DIR / "agent_models.json"

# Agent kinds whose model is user-selectable, with a sensible default + a label +
# a group (for GUI sectioning). Keep kind ids stable (persisted + sent over the
# API). Defaults are full ids: heavy authoring/repair agents on the frontier
# model, the lighter extraction/verdict/chat agents balanced.
# Each agent kind is tagged with a `group` (the category the GUI's per-agent
# model picker sections it under) and a default model. Groups are ordered for
# display by GROUP_ORDER below. Authoring/repair agents default to Opus;
# extraction/verdict/chat to Sonnet.
AGENT_KINDS: dict[str, dict] = {
    # --- Symbol ---
    "symbol_gen":    {"label": "Symbol generator",           "group": "Symbol",       "default": "claude-opus-4-8"},
    # --- Schematic generation ---
    "apply":         {"label": "Apply-changelog agent",      "group": "Schematic generation", "default": "claude-opus-4-8"},
    "lint_fix":      {"label": "Lint/validator fix agent",   "group": "Schematic generation", "default": "claude-opus-4-8"},
    "topology_adapt":{"label": "Topology-adapt agent",       "group": "Schematic generation", "default": "claude-opus-4-8"},
    # --- Simulation ---
    "sim_setup":     {"label": "Datasheet & scenario agent", "group": "Simulation",   "default": "claude-sonnet-4-6"},
    "sim_interpret": {"label": "Verdict agent",              "group": "Simulation",   "default": "claude-sonnet-4-6"},
    "sim_generate":  {"label": "SPICE-model generator",      "group": "Simulation",   "default": "claude-opus-4-8"},
    "sim_update":    {"label": "Schematic-sync agent",       "group": "Simulation",   "default": "claude-opus-4-8"},
    "sim_chat_edit": {"label": "Sim chat-edit agent",        "group": "Simulation",   "default": "claude-sonnet-4-6"},
    # --- Design review ---
    "rule_gen":      {"label": "Rule generator",             "group": "Design review", "default": "claude-opus-4-8"},
    # --- Chat ---
    "chat":          {"label": "Chat / thinking-partner",    "group": "Chat",         "default": "claude-sonnet-4-6"},
}
# Display order of the groups in the picker (any group not listed sorts last).
GROUP_ORDER: list[str] = [
    "Symbol", "Schematic generation", "Simulation", "Design review", "Chat",
]
# Back-compat alias (was sim-only); both names point at the same registry.
SIM_AGENT_KINDS = AGENT_KINDS


def _load_agent_models() -> dict:
    try:
        data = json.loads(AGENT_MODELS_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def model_for(kind: str) -> str:
    """Resolve the model id for an agent kind: user override → per-kind default →
    global MODEL. Canonicalized to a known id so a stale/aliased persisted value
    can't feed an unknown --model to claude."""
    override = _canon_model(_load_agent_models().get(kind))
    if override:
        return override
    default = SIM_AGENT_KINDS.get(kind, {}).get("default")
    return _canon_model(default) or _canon_model(MODEL) or "claude-sonnet-4-6"


def agent_model_config() -> dict:
    """The full per-kind model picture for the GUI: kind, label, current model id,
    default id, overridden flag, and the exact model catalog to choose from."""
    overrides = _load_agent_models()
    return {
        "models": MODEL_CATALOG,
        "groups": GROUP_ORDER,
        "agents": [
            {"kind": k, "label": v["label"], "group": v.get("group", "Other"),
             "model": model_for(k),
             "default": _canon_model(v["default"]),
             "overridden": _canon_model(overrides.get(k)) is not None}
            for k, v in AGENT_KINDS.items()
        ],
    }


def set_agent_model(kind: str, model: str | None) -> bool:
    """Set (or clear, with model=None) the model override for an agent kind.
    Accepts a full id or a short alias; stores the canonical full id. Returns
    False for an unknown kind or an unrecognized model."""
    if kind not in SIM_AGENT_KINDS:
        return False
    data = _load_agent_models()
    if model is None:
        data.pop(kind, None)
    else:
        canon = _canon_model(model)
        if not canon:
            return False
        data[kind] = canon
    _save(AGENT_MODELS_FILE, data)
    return True


# ---------------------------------------------------------------------------
# State helpers — JSON file is the source of truth; in-memory cache only
# inside one request to avoid race conditions across concurrent fetches.
# ---------------------------------------------------------------------------
def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        # Always UTF-8: changelog/chat carry EE glyphs (µ, ≥, Ω, –). Without an
        # explicit encoding, read_text() uses the platform default (cp1252 on
        # Windows) and mojibakes them (µF -> ÂµF), which would feed the apply
        # agent corrupted text. Match _save's UTF-8 write.
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 + ensure_ascii=False so the on-disk file holds real glyphs (round-
    # trips cleanly with the UTF-8 _load above), not \uXXXX escapes.
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def load_chat() -> list[dict]:
    """Legacy single transcript — only read during one-time migration."""
    return _load(CHAT_FILE, [])


# ---------------------------------------------------------------------------
# Multi-session chat store
# ---------------------------------------------------------------------------
# chats.json shape:
#   {"sessions": [{id, title, created, updated, summary, messages:[...]}],
#    "default_id": "<id>"}
# A session's `summary` holds compacted earlier context (null until compacted);
# `messages` is the live tail since the last compaction. The default session is
# the one selected when the GUI loads.
def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _general_session() -> dict:
    now = time.time()
    return {
        "id": _new_id(),
        "title": "General",
        "created": now,
        "updated": now,
        "summary": None,
        "messages": [],
    }


def load_sessions() -> dict:
    """Load the session store, migrating the legacy flat chat.json on first
    use and guaranteeing at least one session plus a valid default_id."""
    store = _load(CHATS_FILE, None)
    if store is None:
        legacy = load_chat()
        seed = _general_session()
        if isinstance(legacy, list) and legacy:
            seed["messages"] = legacy
        store = {"sessions": [seed], "default_id": seed["id"]}
        save_sessions(store)
        return store
    changed = False
    if not store.get("sessions"):
        seed = _general_session()
        store["sessions"] = [seed]
        store["default_id"] = seed["id"]
        changed = True
    if store.get("default_id") not in {s["id"] for s in store["sessions"]}:
        store["default_id"] = store["sessions"][0]["id"]
        changed = True
    if changed:
        save_sessions(store)
    return store


def save_sessions(store: dict) -> None:
    _save(CHATS_FILE, store)


def _find_session(store: dict, sid: str) -> dict | None:
    for s in store["sessions"]:
        if s["id"] == sid:
            return s
    return None


def _session_meta(s: dict, default_id: str | None) -> dict:
    return {
        "id": s["id"],
        "title": s.get("title", "Chat"),
        "created": s.get("created", 0),
        "updated": s.get("updated", 0),
        "is_default": s["id"] == default_id,
        "message_count": len(s.get("messages", [])),
        "has_summary": bool(s.get("summary")),
    }


def list_sessions() -> dict:
    store = load_sessions()
    did = store.get("default_id")
    return {
        "sessions": [_session_meta(s, did) for s in store["sessions"]],
        "default_id": did,
    }


def get_session(sid: str) -> dict | None:
    store = load_sessions()
    s = _find_session(store, sid)
    if not s:
        return None
    return {
        **_session_meta(s, store.get("default_id")),
        "messages": s.get("messages", []),
        "summary": s.get("summary"),
    }


def create_session(title: str | None = None) -> dict:
    store = load_sessions()
    s = _general_session()
    s["title"] = (title or "New chat").strip()[:60] or "New chat"
    store["sessions"].append(s)
    save_sessions(store)
    return _session_meta(s, store.get("default_id"))


def delete_session(sid: str) -> bool:
    store = load_sessions()
    kept = [s for s in store["sessions"] if s["id"] != sid]
    if len(kept) == len(store["sessions"]):
        return False
    store["sessions"] = kept
    if store.get("default_id") == sid:
        store["default_id"] = kept[0]["id"] if kept else None
    save_sessions(store)
    load_sessions()  # re-seed if that emptied the store
    return True


def rename_session(sid: str, title: str) -> bool:
    store = load_sessions()
    s = _find_session(store, sid)
    if not s:
        return False
    s["title"] = title.strip()[:60] or s.get("title", "Chat")
    s["updated"] = time.time()
    save_sessions(store)
    return True


def set_default_session(sid: str) -> bool:
    store = load_sessions()
    if not _find_session(store, sid):
        return False
    store["default_id"] = sid
    save_sessions(store)
    return True


def clear_session(sid: str) -> bool:
    store = load_sessions()
    s = _find_session(store, sid)
    if not s:
        return False
    s["messages"] = []
    s["summary"] = None
    s["updated"] = time.time()
    save_sessions(store)
    return True


def append_session_msg(sid: str, role: str, content: str) -> dict | None:
    store = load_sessions()
    s = _find_session(store, sid)
    if not s:
        return None
    entry = {
        "id": uuid.uuid4().hex[:10],
        "role": role,
        "content": content,
        "ts": time.time(),
    }
    s.setdefault("messages", []).append(entry)
    s["updated"] = entry["ts"]
    save_sessions(store)
    return entry


def load_changelog() -> list[dict]:
    return _load(CHANGELOG_FILE, [])


def save_changelog(items: list[dict]) -> None:
    _save(CHANGELOG_FILE, items)


def append_changelog(
    summary: str,
    source: str = "agent",
    sim_block: str | None = None,
    sim_type: str | None = None,
) -> dict:
    """Queue a changelog item. `source` records ORIGIN: "user" (manual add),
    "sim" (a simulation-interpret suggestion), or "agent". For sim-originated
    items, sim_block/sim_type identify which (block, sim_type) raised the
    suggestion — used to re-run ONLY that sim after the apply lands, so a
    user/manual edit never triggers a simulation (see app.py apply-and-generate).
    """
    items = load_changelog()
    entry = {
        "id": uuid.uuid4().hex[:8],
        "summary": summary.strip(),
        "source": source,
        "ts": time.time(),
    }
    if sim_block:
        entry["sim_block"] = sim_block
    if sim_type:
        entry["sim_type"] = sim_type
    items.append(entry)
    save_changelog(items)
    return entry


def clear_changelog() -> None:
    save_changelog([])


def remove_changelog(item_id: str) -> bool:
    items = load_changelog()
    new = [i for i in items if i["id"] != item_id]
    if len(new) == len(items):
        return False
    save_changelog(new)
    return True


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
_BASE_CONTEXT = f"""\
You are the in-GUI agent for the test1 (Bobcat carrier) Altium schematic pipeline.

The user is iterating on a hierarchical schematic via a browser GUI. They
can see the live rendered SVGs and a linter checklist. The actual pipeline
(build_project → connectivity validator + layout lint → design review) is
invoked by the GUI's backend (`python -m test1.altium.build_project`) — not by
you. Your job is to be the user's thinking partner and to plan + implement edits
to the YAML netlists and Python builders.

This is an ALTIUM pipeline (pure-Python altium_monkey), NOT KiCad — the KiCad
backend was removed. Any `.kicad_sym`/`.kicad_sch`/`eeschema`/`kicad-cli`/
`gen/build_*.py` reference is stale; the active builders live in `altium/`.

Project root: {PROJECT_DIR}
Key files:
  - netlist/<sheet>.yaml      declarative source of truth (parts + nets) — as-built
  - altium/build_<sheet>.py   Python placement/routing code per sheet
  - altium/layout_lint.py     visual/spatial linter (the geometry gate)
  - gen/validator.py          backend-neutral strict connectivity check (reused)
  - review/rules.py           deterministic design rules
  - design_requirements.md    spec
  - design_intent.md          CROSS-SHEET gotchas you can't derive from one sheet
                              (e.g. U10's LDO_SET_* pins are an FPGA-programmed
                              dynamic-VOUT feature) — READ THIS before any change
                              that touches a part's mode/topology, not just its value
  - Parts Library/<MPN>/      datasheets + symbols

Memory (cross-session facts about the user + project) lives under
{MEMORY_DIR} and is loaded
automatically. Read it if you need context about Mason's preferences or prior
decisions.

Be terse. The user can see your tool calls; don't narrate them.
"""

_CHAT_INSTRUCTIONS = f"""\
This is a CHAT TURN in a general, long-lived working session. You are the
user's thinking partner for this project. The PRIMARY purpose of this session
is to build and RETAIN deep context about the whole system — the schematic,
the parts library, the simulation work, and the design review — and to answer
the user's questions accurately. This is NOT primarily a "what should we
change" channel; do not steer every turn toward edits.

How to behave:
1. Prioritize understanding. When the user asks about the design, READ the
   relevant sources and answer from what you actually find — cite the file or
   the number. Proactively gather context you're missing instead of guessing.
   Useful sources:
     - netlist/*.yaml            as-built parts + nets
     - altium/build_<sheet>.py   placement/routing code per sheet
     - design_requirements.md    spec / intent
     - design_intent.md          cross-sheet gotchas (mode/topology decisions)
     - review/ findings + rules  design-review state
     - sim/cache/*, sim/results/ simulation params + outputs
     - Parts Library/<MPN>/      datasheets + symbols
2. Retain context. The earlier conversation in THIS session is replayed to you
   (and may begin with a compacted summary). Build on it; keep continuity.
3. Read freely: Read, Glob, Grep (Bash for grep/inspection). Answer in plain
   prose, terse — the user can see your tool calls, so don't narrate them.
4. DO NOT edit netlist/*.yaml or altium/*.py on a chat turn. Design edits happen
   only at apply-changelog time (a separate invocation).
5. Changelog is SECONDARY and opt-in. ONLY when the user EXPLICITLY asks for a
   design change should you append a one-line bullet to {CHANGELOG_FILE} (read
   it first, append {{"id": "<8-hex>", "summary": "<one line>", "source":
   "agent", "ts": <unix epoch>}}, write it back) and tell the user what you
   queued. If the user is asking a question, exploring, or building context,
   DO NOT touch the changelog.
"""


_COMPACT_INSTRUCTIONS = """\
This is a COMPACTION pass. You are given the running transcript of a chat
session (optionally preceded by an earlier summary). Produce a dense, faithful
briefing that preserves everything needed to continue the session seamlessly:
  - the user's goals, preferences, and how they want to work,
  - key facts learned about the schematic / library / simulation / review,
  - decisions made and their rationale,
  - open questions and anything still in progress,
  - any changelog items queued this session.
Write compact prose and bullets. Do NOT use any tools. Output ONLY the summary
text — no preamble, no sign-off.
"""

def _lint_expectations() -> str:
    """A briefing on the gates an edit must satisfy, built from the LIVE rule
    registry (so it can't drift from what the build actually enforces) plus the
    placement/routing idioms a builder edit must honor. Shared by the apply pass
    and the lint-fix pass so both write geometry the linter accepts."""
    try:
        from test1.altium.layout_lint import RULES
        errs = [r for r in RULES if r.get("severity") == "ERROR"]
        warns = [r for r in RULES if r.get("severity") == "WARNING"]
        err_lines = "\n".join(f"     - {r['id']}: {r['summary']}" for r in errs)
        warn_lines = "\n".join(f"     - {r['id']}: {r['summary']}" for r in warns)
    except Exception:
        err_lines = warn_lines = "     (rule registry unavailable)"
    return f"""\
GATES every build must pass (run by the backend: build_project -> connectivity
validator + layout lint). A clean build prints per sheet `E/W/I = 0/0/0` and
`FAILURES: none`. Write edits that hold to these:
  * CONNECTIVITY (hard, fails the build): every YAML net must resolve to one
    connected component. If you add/rename a part or net, wire it fully — no
    dangling pins, no split nets, refdes/pins must exist.
  * LAYOUT-LINT ERRORS (fail the build):
{err_lines}
  * LAYOUT-LINT WARNINGS (advisory, but aim for zero):
{warn_lines}
PLACEMENT / ROUTING IDIOMS (how altium/build_<sheet>.py stays lint-clean):
  - 100-mil grid; orthogonal wires only (no diagonals).
  - Draw the WIRE to a connection point BEFORE placing a port there, and use
    `port(side="auto")` so the body sits clear of the net (never impaling it).
  - GND power symbols point DOWN (270deg) at the bottom of their net; rails point
    UP (90deg). Don't put a GND symbol above its net.
  - Keep readable spacing between components; don't let a label/value/port text
    box land on a component body or another text box (text is linted as a 2-D box).
  - Add a new part with `place_from_netlist`, then route every one of its pins.
  - Don't run a wire through a body, a port body, or a third part's pin."""


_APPLY_INSTRUCTIONS = f"""\
This is an APPLY-CHANGELOG pass. The user just clicked Generate.

You will receive a list of changelog items the user accumulated. Your job:

0. FIRST read design_intent.md — it lists cross-sheet gotchas you can't see from
   one sheet (e.g. U10's LDO_SET_* pins are an FPGA-programmed dynamic-VOUT
   feature, so do NOT convert it to a fixed divider). If an item conflicts with a
   documented design-intent fact, STOP that item and report it (don't auto-apply).
1. Implement each item by editing the relevant files (netlist/*.yaml,
   altium/build_<sheet>.py, design_requirements.md). Use Read, Edit, Write.
   (This is the Altium pipeline — edit altium/build_*.py, NOT gen/build_*.py,
   which no longer exists.)

   VALUE↔MPN RECONCILIATION (e.g. a resistor whose `value:` no longer matches
   its `lib_id:` MPN): repoint the part to the CORRECT MPN for its value. The
   correct MPN may not have a symbol yet — check `Parts Library/<MPN>/`:
     • If `Parts Library/<MPN>/<MPN>.SchLib` exists → just repoint `lib_id`
       (and the matching `footprint`) in netlist/*.yaml.
     • If the `.SchLib` is MISSING but a datasheet PDF is present in
       `Parts Library/<MPN>/` → DO NOT STOP. CREATE THE SYMBOL FIRST, then
       repoint. Your CWD is the test1/ project dir, and the backend's venv Python
       is FIRST on your PATH — so run the authoring tool with a plain, unquoted
       `python` as ONE command (no `cd`, no `&&` chaining, no absolute path: a
       quoted/absolute interpreter or a `cd …&&` prefix hits the permission gate;
       bare `python` is allow-listed and resolves to the correct interpreter):

       (CASE 1 — value swap of an existing part) The new part is the SAME package
       and pin layout as a part already in the design (e.g. R40/R41 go from a
       5.11k MPN to a 3.65k MPN — same 0603 thin-film resistor, different value).
       DO NOT author from a fresh pin-spec, and DO NOT just copy the sibling's
       .SchLib file — a regenerated symbol lands pins on a clean grid that won't
       match the sibling's hand-tuned geometry (the sheet builder routes the old
       coordinates → placement SHORTS/splits nets → build fails), and a raw file
       copy leaves the WRONG internal symbol name. Use the clone mode, which
       copies the sibling geometry AND renames the symbol identity correctly:
           python -m altium.author_symbol "<NEW_MPN>" --clone-from "<SIBLING_MPN>"
       (The sibling is the MPN the refs point at TODAY. Clone needs equal-length
       MPNs — same-series swaps always are. Component VALUES live in the netlist,
       not the symbol, so you do not patch a value in the symbol.)

       (CASE 2 — genuinely new part, no equivalent sibling) Write
       `Parts Library/<MPN>/<MPN>.pinspec.json` (reference R/C/U/…, Value,
       Footprint, Manufacturer, MPN, and every pin from the datasheet), then:
           python -m altium.author_symbol "<MPN>"

       In BOTH cases, confirm the printed pin/unit count, THEN repoint the refs
       (R40/R41 or whichever) `lib_id` AND `footprint` together so value, MPN,
       and package all agree.
       Only STOP a value↔MPN item if NO datasheet exists for the correct MPN
       (then it's a genuine sourcing decision for a human).
2. Be conservative: make the smallest change that satisfies the bullet.
   If a bullet is ambiguous, do the most reasonable interpretation and
   note your assumption in the final summary. When a change depends on a
   part's datasheet behavior (a mode-select pin state, a min/max rating, a
   recommended component value), VERIFY it from the datasheet before editing —
   you can read datasheet TEXT with:
     python sim/read_pdf.py "<pdf path>" --pages <page-range> --text-only
   (datasheets live under library/<MPN>/). If the datasheet can't confirm a
   topology change is safe, STOP that item and report it for human approval
   rather than guessing — a documented STOP is better than a wrong edit.
3. Write edits that will PASS THE GATES (below). A value-only change (e.g. a
   resistor/cap value in netlist/*.yaml) is connectivity-safe; but adding,
   removing, or rewiring a PART changes geometry + connectivity, so place and
   route it per the idioms so the build stays clean.
4. DO NOT run the build yourself (`python -m test1.altium.build_project`) — the
   GUI backend will run it after you return.
5. When done, clear the changelog file ({CHANGELOG_FILE}) to an empty
   list [] so the next chat turn starts clean.
6. Finish with a terse summary block, one bullet per item, of what you
   actually changed.
7. BEFORE the prose summary, emit a machine-readable DECISIONS block so the GUI
   can show each item's outcome at a glance. Use EXACTLY this format, one line
   per changelog item, nothing else inside the fences:

   ```decisions
   <item-id-or-short-tag> | APPLIED | <one-line: what changed + value>
   <item-id-or-short-tag> | STOPPED | <one-line: why not applied / what's blocking>
   <item-id-or-short-tag> | CLARIFY | <one-line: the open question>
   ```

   Use APPLIED when you edited files for that item, STOPPED when you deliberately
   did not (e.g. infeasible/topology-conflict/needs human approval), CLARIFY when
   the item needs a decision before any edit. Keep each reason to one line.

{_lint_expectations()}
"""


def _build_chat_prompt(session: dict, new_user_msg: str) -> str:
    """Stitch the session's compacted summary + recent turns + the new user
    turn into one prompt string.

    `claude -p` is one-shot; multi-turn continuity comes from replaying the
    session. The live tail is capped at MAX_HISTORY_TURNS so prompts don't grow
    unbounded — older context lives in the (compacted) summary.
    """
    messages = session.get("messages", [])
    summary = session.get("summary")
    tail = messages[-MAX_HISTORY_TURNS:] if len(messages) > MAX_HISTORY_TURNS else messages
    lines = []
    if summary:
        lines.append("Summary of earlier conversation in this session:")
        lines.append(summary)
        lines.append("")
    if tail:
        lines.append("Prior conversation:")
        for t in tail:
            role = "User" if t["role"] == "user" else "You"
            lines.append(f"  {role}: {t['content']}")
        lines.append("")
    lines.append(f"Current user message: {new_user_msg}")
    return "\n".join(lines)


def _build_compact_prompt(session: dict) -> str:
    messages = session.get("messages", [])
    summary = session.get("summary")
    if not messages and not summary:
        return "There is nothing to summarize. Respond with: NOTHING_TO_COMPACT"
    lines = []
    if summary:
        lines.append("Earlier summary of this session:")
        lines.append(summary)
        lines.append("")
    lines.append("Conversation to compact (oldest first):")
    for t in messages:
        role = "User" if t["role"] == "user" else "Assistant"
        lines.append(f"  {role}: {t['content']}")
    return "\n".join(lines)


def _build_apply_prompt(changelog: list[dict]) -> str:
    if not changelog:
        return "The changelog is empty. Respond with: NO_CHANGES"
    bullets = "\n".join(f"  - [{i['id']}] {i['summary']}" for i in changelog)
    return f"Implement these queued changelog items:\n\n{bullets}"


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------
@dataclass
class AgentRun:
    run_id: str
    kind: str                        # "chat" | "apply" | "symbol-gen"
    events: list[dict] = field(default_factory=list)
    text: str = ""
    stream_log: str = ""             # full concise stream (thinking/assistant/tool),
                                     # never overwritten — persisted for after-the-fact audit
    status: str = "running"          # "running" | "ok" | "fail" | "cancelled"
    returncode: int | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    proc: asyncio.subprocess.Process | None = None   # the claude -p process
    cancelled: bool = False


_RUNS: dict[str, AgentRun] = {}


def get_run(run_id: str) -> AgentRun | None:
    return _RUNS.get(run_id)


def cancel_run(run_id: str) -> bool:
    """Terminate a running agent's `claude -p` process. The streaming loop in
    _run_subprocess then ends naturally (stdout closes) and notifies subscribers,
    so the SSE 'done' event reports status 'cancelled'. Returns False if the run
    is unknown or already finished."""
    run = _RUNS.get(run_id)
    if not run or run.status != "running":
        return False
    run.cancelled = True
    p = run.proc
    if p is not None and p.returncode is None:
        try:
            p.terminate()           # SIGTERM; claude -p exits, stdout EOFs
        except ProcessLookupError:
            pass
    return True


# Default startup-hang watchdog for any caller awaiting a spawned agent. A
# `claude -p` agent can block before producing output (seen on Windows: 0% CPU,
# never terminates) — without a deadline the awaiting coroutine hangs forever.
AGENT_RUN_TIMEOUT_S = 300


async def await_run_bounded(run: "AgentRun", *, timeout_s: float = AGENT_RUN_TIMEOUT_S,
                            should_cancel=None) -> str:
    """Wait for `run` to leave 'running', honoring an optional caller cancel flag
    AND a startup-hang watchdog. THE one way loop code should wait on an agent —
    no bare `while run.status == 'running'` polling (which can hang forever).

    `should_cancel` is an optional zero-arg callable; if it returns True we cancel
    the run and return 'cancelled'. On timeout we cancel and return 'timeout'.
    Otherwise returns the run's terminal status ('ok'/'fail'/'cancelled')."""
    waited = 0.0
    while run.status == "running":
        if should_cancel is not None and should_cancel():
            cancel_run(run.run_id)
            return "cancelled"
        if waited >= timeout_s:
            cancel_run(run.run_id)
            return "timeout"
        await asyncio.sleep(0.5)
        waited += 0.5
    return run.status


async def _spawn_claude(
    *,
    prompt: str,
    system_suffix: str,
    permission_mode: str = "acceptEdits",
    allowed_tools: list[str] | None = None,
    add_dir: Path | None = None,
    model: str | None = None,
    thinking_tokens: int | None = None,
) -> tuple[asyncio.subprocess.Process, list[str]]:
    """Spawn `claude -p` and return (proc, cmd). Output format is
    stream-json so we can parse per-event. `model` overrides the global MODEL
    (used by the per-agent model selection); falls back to MODEL when None.
    `thinking_tokens` overrides the default extended-thinking budget — set it low
    for mechanical passes (e.g. lint_fix) so the agent doesn't stall in a long
    think before acting."""
    cmd = [
        CLAUDE,
        "-p", prompt,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",                # stream-json requires verbose
        "--model", model or MODEL,
        "--permission-mode", permission_mode,
        "--append-system-prompt", _BASE_CONTEXT + "\n" + system_suffix,
        "--no-session-persistence",
    ]
    if allowed_tools:
        cmd.append("--allowedTools")
        cmd.extend(allowed_tools)
    if add_dir:
        cmd.extend(["--add-dir", str(add_dir)])
    env = os.environ.copy()
    # Put THIS backend's interpreter dir (the spike venv, which has PyMuPDF/fitz)
    # first on the agent's PATH, so a plain `python sim/read_pdf.py` resolves to
    # the fitz-having python. This lets the agent use a simple, quote-free command
    # (matches the Bash allow-list cleanly) instead of an absolute path it tends
    # to quote/slash-vary — which previously got denied and made it thrash into
    # PowerShell + scratch scripts. Also force UTF-8 so PDF text never crashes.
    py_dir = str(Path(sys.executable).parent)
    env["PATH"] = py_dir + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    # Enable extended thinking so the agent emits `thinking` blocks. We surface a
    # concise line per block (see _summarize_event) so the user can watch the
    # agent's reasoning live and verify it reaches conclusions for the RIGHT
    # reason — not just the right outcome (the prior no-change run was opaque).
    # Keep the budget modest: enough to reason about a topology/feasibility call,
    # not so large it bloats latency. Respect an existing override if set.
    env["MAX_THINKING_TOKENS"] = str(thinking_tokens if thinking_tokens is not None
                                     else int(os.environ.get("MAX_THINKING_TOKENS", "4000")))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(PROJECT_DIR),
        # Close stdin: this is a headless `claude -p` run. If the child inherits the
        # backend's stdin and ever tries to read it (a prompt fallback, a TTY probe)
        # it would block forever at 0% CPU — the exact lint-fix hang seen on Windows
        # that stalled the loop. DEVNULL makes any such read return EOF immediately.
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        # stream-json emits ONE JSON object per line, and a single line can be
        # large — a tool_use carrying file contents, or a long assistant message.
        # asyncio's default StreamReader limit is 64 KB, so readline() raises
        # LimitOverrunError ("Separator is found, but chunk is longer than limit")
        # and the whole agent reader dies mid-pass. Give it generous headroom.
        limit=16 * 1024 * 1024,   # 16 MB per line
    )
    return proc, cmd


def _summarize_event(ev: dict) -> str | None:
    """Best-effort one-line summary of a stream-json event for the GUI log.

    Returns None for events we don't want to surface (system init, etc.).
    """
    t = ev.get("type")
    if t == "assistant":
        msg = ev.get("message", {})
        for block in msg.get("content", []):
            btype = block.get("type")
            if btype == "thinking":
                # The agent's private reasoning. Surfacing a concise line lets the
                # user verify the agent UNDERSTANDS the problem and reaches its
                # conclusion for the right reason (not just the right outcome).
                txt = (block.get("thinking") or "").strip()
                if txt:
                    # collapse whitespace so multi-line reasoning is one tidy line
                    one = " ".join(txt.split())
                    return f"thinking: {one[:280]}"
            elif btype == "text":
                txt = block.get("text", "").strip()
                if txt:
                    return f"assistant: {txt[:240]}"
            elif block.get("type") == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                hint = ""
                if name in ("Read", "Edit", "Write"):
                    hint = f" {inp.get('file_path', '?')}"
                elif name == "Bash":
                    hint = f" {inp.get('command', '?')[:80]}"
                return f"tool: {name}{hint}"
    elif t == "user":
        # tool_result echoed back to the model — usually noise
        return None
    elif t == "result":
        sub = ev.get("subtype")
        if sub == "success":
            return None
        return f"result: {sub}"
    elif t == "system" and ev.get("subtype") == "init":
        return None
    return None


async def _parse_decisions(text: str) -> list[dict]:
    """Extract the ```decisions ... ``` block the apply pass emits into a list of
    {item, outcome, reason}. Tolerant: accepts the fenced block, or — as a
    fallback — bare 'id | OUTCOME | reason' lines anywhere in the text."""
    if not text:
        return []
    out: list[dict] = []
    # Prefer the fenced block.
    m = re.search(r"```decisions\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    body = m.group(1) if m else text
    for line in body.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[1].upper() in ("APPLIED", "STOPPED", "CLARIFY"):
            out.append({
                "item": parts[0],
                "outcome": parts[1].upper(),
                "reason": parts[2] if len(parts) >= 3 else "",
            })
    return out


async def _run_subprocess(run: AgentRun, proc: asyncio.subprocess.Process) -> None:
    """Stream the subprocess's stream-json output, parse each line, and
    fan out one-line summaries to SSE subscribers."""
    assert proc.stdout is not None
    run.proc = proc                  # handle so cancel_run can terminate it

    def push(line: str) -> None:
        run.text += line + "\n"
        run.stream_log += line + "\n"   # preserved even after run.text is replaced
        for q in list(run.subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    final_text: list[str] = []
    while True:
        try:
            raw = await proc.stdout.readline()
        except (asyncio.LimitOverrunError, ValueError):
            # A single stream-json line blew past even the (large) reader limit.
            # Don't let it kill the pass: drain the rest of this over-long line in
            # chunks (until the newline) and skip it, then keep reading. Losing one
            # giant event's detail is fine; aborting the whole agent run is not.
            try:
                while True:
                    chunk = await proc.stdout.read(65536)
                    if not chunk or chunk.endswith(b"\n"):
                        break
            except Exception:
                pass
            push("[raw] (skipped an over-long stream line)")
            continue
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            push(f"[raw] {line[:200]}")
            continue
        run.events.append(ev)
        summary = _summarize_event(ev)
        if summary:
            push(summary)
        if ev.get("type") == "result" and ev.get("subtype") == "success":
            final_text.append(ev.get("result", ""))

    # Drain stderr if anything is there.
    if proc.stderr is not None:
        err = await proc.stderr.read()
        if err:
            for el in err.decode("utf-8", errors="replace").splitlines():
                push(f"[stderr] {el}")

    run.returncode = await proc.wait()
    # A terminated proc has a nonzero/negative rc; report it as 'cancelled'
    # (not 'fail') so the UI distinguishes a user cancel from an agent error.
    run.status = "cancelled" if run.cancelled else ("ok" if run.returncode == 0 else "fail")
    # The final assistant text is the canonical user-visible answer.
    if final_text:
        run.text = "\n".join(final_text)
    # Persist the full concise stream (reasoning included) so a run — especially a
    # "leave-the-design-unchanged" run — is auditable after the fact, not just live.
    try:
        runs_dir = STATE_DIR / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        log_body = (
            f"# run {run.run_id} kind={run.kind} status={run.status} rc={run.returncode}\n\n"
            f"## stream (thinking / assistant / tools)\n{run.stream_log}\n"
            f"## final answer\n{run.text}\n"
        )
        (runs_dir / f"{run.run_id}.log").write_text(log_body, encoding="utf-8")
        # Parse the machine-readable DECISIONS block (apply/lint_fix only) into a
        # structured per-item outcome record the GUI can show without scraping prose.
        if run.kind in ("apply", "lint_fix"):
            decisions = _parse_decisions(run.text or run.stream_log)
            if decisions:
                _save(DECISIONS_FILE, {
                    "run_id": run.run_id,
                    "kind": run.kind,
                    "status": run.status,
                    "ts": run.events[-1].get("ts") if run.events else None,
                    "decisions": decisions,
                })
    except Exception:
        pass  # logging is best-effort; never let it break the run
    for q in list(run.subscribers):
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass


def _register(kind: str) -> AgentRun:
    run = AgentRun(run_id=uuid.uuid4().hex[:12], kind=kind)
    _RUNS[run.run_id] = run
    return run


async def start_chat_turn(session_id: str, user_msg: str) -> AgentRun:
    """Append the user's message to the session, kick off `claude -p`, return
    the AgentRun. Caller subscribes via SSE to see the response stream."""
    append_session_msg(session_id, "user", user_msg)
    store = load_sessions()
    session = _find_session(store, session_id) or {"messages": [], "summary": None}
    # Build from the session state EXCLUDING the just-appended user turn (it's
    # passed separately as the current message).
    prior = {**session, "messages": session.get("messages", [])[:-1]}
    prompt = _build_chat_prompt(prior, user_msg)
    proc, _cmd = await _spawn_claude(
        prompt=prompt,
        system_suffix=_CHAT_INSTRUCTIONS,
        permission_mode="acceptEdits",  # allows write to changelog.json
        model=model_for("chat"),
    )
    run = _register("chat")

    async def driver() -> None:
        await _run_subprocess(run, proc)
        # Persist the assistant's final text into the session transcript.
        if run.text.strip():
            append_session_msg(session_id, "assistant", run.text.strip())

    asyncio.create_task(driver())
    return run


async def start_compact(session_id: str) -> AgentRun | None:
    """Summarize a session and collapse its transcript. On completion the
    session's `summary` is replaced with the briefing and `messages` is
    emptied — future turns replay the summary instead of the full history."""
    store = load_sessions()
    session = _find_session(store, session_id)
    if not session:
        return None
    prompt = _build_compact_prompt(session)
    proc, _cmd = await _spawn_claude(
        prompt=prompt,
        system_suffix=_COMPACT_INSTRUCTIONS,
        permission_mode="acceptEdits",
    )
    run = _register("compact")

    async def driver() -> None:
        await _run_subprocess(run, proc)
        summary = run.text.strip()
        if not summary or summary == "NOTHING_TO_COMPACT":
            return
        st = load_sessions()
        s = _find_session(st, session_id)
        if s:
            s["summary"] = summary
            s["messages"] = []
            s["updated"] = time.time()
            save_sessions(st)

    asyncio.create_task(driver())
    return run


# Tool allowance for the design-editing agents (apply + lint-fix). Mirrors the
# sim agents' read-only datasheet capability so the agent can VERIFY a part's
# behavior from its datasheet (e.g. confirm an LDO's adjustable-mode pin state)
# instead of stalling on a permission-gated PDF read — the exact gap that made
# the CFF/adjustable-mode decision unverifiable. read_pdf.py is text-only and
# read-only; acceptEdits still governs all file writes.
# The apply/symbol-gen agents must run the SAME interpreter as this backend
# (sys.executable) — it's the venv that has altium_monkey (a bare `python` on
# PATH may be system Python without it). The spawned `claude -p`'s allowed_tools
# SCOPES Bash permissions, so the full interpreter path must be allowlisted here
# explicitly (settings.local.json does NOT govern these scoped subprocess
# agents). Without this, author_symbol invocations hit an approval gate the
# headless loop can't satisfy and stall.
_VENV_PY = sys.executable.replace("\\", "/")
_DESIGN_AGENT_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(python:*)", "Bash(python3:*)", "Bash(pdftotext:*)",
    "Bash(cd:*)", "Bash(ls:*)", "Bash(cat:*)",
    # Read-only git inspection (git diff/status/show/log) — agents reach for it to
    # see what the apply pass changed. Allowing it (it's read-only here) stops the
    # call from hitting the permission gate, which — now that the headless child's
    # stdin is /dev/null — would abort the agent (rc -1) instead of just prompting.
    "Bash(git:*)",
    # The backend's own interpreter, by full path (and a glob), so
    # `"<venv>/python.exe" -m test1.altium.author_symbol …` runs without a prompt.
    f'Bash({_VENV_PY}:*)',
    f'Bash("{_VENV_PY}":*)',
    "Bash(*altium_spike/.venv/Scripts/python.exe*)",
]


async def start_apply_pass() -> AgentRun:
    """Hand the queued changelog to the agent for implementation."""
    items = load_changelog()
    prompt = _build_apply_prompt(items)
    proc, _cmd = await _spawn_claude(
        prompt=prompt,
        system_suffix=_APPLY_INSTRUCTIONS,
        permission_mode="acceptEdits",
        allowed_tools=_DESIGN_AGENT_TOOLS,
        model=model_for("apply"),
    )
    run = _register("apply")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


# ---------------------------------------------------------------------------
# Closed-loop apply: after the apply pass, the backend builds + gates; if the
# build fails, this fix pass is handed the ACTUAL failures (lint.json issues +
# build output) and corrects them. Bounded by the orchestrator (apply_and_
# generate) to a few rounds. This is what closes the loop the way a human would:
# apply -> build -> read the gates -> fix -> rebuild, until clean.
_LINT_FIX_INSTRUCTIONS = f"""\
This is a LINT/VALIDATOR FIX pass. An apply pass just edited the design, the
backend built it, and the build DID NOT pass its gates. You are given the exact
failures. Fix them — and ONLY them — with the smallest edits to netlist/*.yaml
and altium/build_<sheet>.py.

TOOLS — IMPORTANT: Use ONLY Read, Grep, Glob, and Edit. Do NOT run ANY shell/Bash
command — no `git`, no `python`, no `cd`, no exploratory commands. You have the
exact failures and full file access already; everything you need is reachable by
Read/Grep. (This pass runs head-less with no terminal: a Bash command that needs
approval cannot be answered and will abort the whole pass before you fix anything.)

1. Read each failing sheet's builder (altium/build_<sheet>.py) and netlist
   (netlist/<sheet>.yaml) and fix the specific issues listed. A connectivity
   failure usually means a pin/net wasn't fully wired; a layout ERROR
   (off_grid / component_overlap / out_of_bounds / stub_t_short / diagonal_wire)
   means geometry to nudge to grid, move apart, or reroute.
2. Do NOT introduce new parts or change the design intent — you are repairing
   the apply pass's edits to pass the gates, not redesigning.
3. DO NOT run the build yourself — the backend rebuilds after you return and
   re-checks (you don't need git/python to see changes — Read the files). If a
   failure is genuinely not fixable by an edit here (e.g. it needs a design
   decision), say so in your summary rather than guessing.
4. Finish with a terse summary: which issues you fixed and how.

{_lint_expectations()}
"""


def _build_fix_prompt(failures: dict, round_no: int, max_rounds: int,
                      fix_warnings: bool = False) -> str:
    """failures = {exit, status, counts, issues:[...], tail:[build output lines]}.

    fix_warnings selects the loop scope: when False the pass clears ERRORs (the
    only gate that fails the build); when True it also clears WARNINGs, so both
    severities are listed and the agent is told warnings count this round."""
    issues = failures.get("issues", [])
    if fix_warnings:
        # ERRORs first, then WARNINGs — both are in scope this round.
        shown = ([i for i in issues if i.get("severity") == "ERROR"]
                 + [i for i in issues if i.get("severity") == "WARNING"]) or issues
    else:
        errs = [i for i in issues if i.get("severity") == "ERROR"]
        shown = errs or issues          # prioritize ERRORs; fall back to all
    lines = "\n".join(
        f"  - [{i.get('severity','?')}] {i.get('rule','?')} on sheet "
        f"'{i.get('sheet','?')}': {i.get('message','')}"
        for i in shown[:40]
    ) or "  (no structured lint issues — see build output below)"
    tail = "\n".join(failures.get("tail", [])[-25:])
    scope = ("Fix every ERROR **and WARNING** listed below — this loop clears "
             "warnings too. (INFO stays advisory.)"
             if fix_warnings else
             "Fix every ERROR listed below. WARN/INFO are advisory — do not "
             "spend this round on them.")
    return f"""\
Build gate FAILED (fix round {round_no} of {max_rounds}).
Exit code: {failures.get('exit')}   lint status: {failures.get('status')}   \
counts: {failures.get('counts')}

{scope}

Failing issues to fix:
{lines}

Build output (tail):
{tail}

Fix these now."""


async def start_lint_fix_pass(failures: dict, round_no: int, max_rounds: int,
                              fix_warnings: bool = False) -> AgentRun:
    """Spawn a bounded fix pass given the build's actual gate failures.

    fix_warnings widens the scope from ERROR-only to ERROR+WARNING (the
    "Errors + warnings fixed" loop tick); see _build_fix_prompt."""
    prompt = _build_fix_prompt(failures, round_no, max_rounds, fix_warnings)
    proc, _cmd = await _spawn_claude(
        prompt=prompt,
        system_suffix=_LINT_FIX_INSTRUCTIONS,
        permission_mode="acceptEdits",
        allowed_tools=_DESIGN_AGENT_TOOLS,
        model=model_for("lint_fix"),
        # Extended thinking OFF for this pass. Measured: with thinking enabled the
        # agent reads the files then spirals in an open-ended "reason about the
        # geometry" think (48+ thinking events, no Edit) and never finishes — the
        # original loop "hang". A small non-zero budget (1000) did NOT cap it. With
        # thinking_tokens=0 it reads → Edits → returns success (~85s). Lint fixes
        # are mechanical grid nudges; they don't need deliberation.
        thinking_tokens=0,
    )
    run = _register("lint_fix")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


async def start_topology_adapt(rule_id: str, candidate_mpn: str,
                                stuck_reason: str, sheet: str) -> AgentRun:
    """Dispatch the topology_adapt agent. Used by the missing-part flow
    when no candidate passes sim verification; tries restructuring the
    surrounding schematic to fit the best-margin candidate."""
    prompt = (f"You are revising the schematic to accommodate a part that "
              f"doesn't quite fit. Rule that needed the part: {rule_id}. "
              f"Best-margin candidate: {candidate_mpn}. Sheet: {sheet}. "
              f"Why it failed sim: {stuck_reason}.\n\n"
              f"Read test1/netlist/{sheet}.yaml and test1/altium/build_{sheet}.py. "
              f"Propose ONE LOCAL topology change that lets the candidate "
              f"satisfy its sim. Examples allowed: add a series resistor / "
              f"buffer / level shift; swap PMOS<->NMOS with rail inversion; "
              f"insert a second-stage filter; widen a decap bank; add a "
              f"gate resistor + clamp.\n\nHARD CONSTRAINTS:\n"
              f"  - Do NOT cross sheet boundaries.\n"
              f"  - Do NOT alter the parent rule's stated intent.\n"
              f"  - Make the change atomic - one refdes added/removed/edited "
              f"or one net rerouted.\n\nApply the change directly via Edit "
              f"on the YAML + build_{sheet}.py, then run python -m "
              f"test1.altium.build_project to verify lint + run the affected "
              f"sims. Report a one-line summary of what you changed and the "
              f"new sim margin.")
    proc, _cmd = await _spawn_claude(
        prompt=prompt,
        system_suffix="",
        permission_mode="acceptEdits",
        allowed_tools=_DESIGN_AGENT_TOOLS,
        model=model_for("topology_adapt"),
    )
    run = _register("topology_adapt")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


async def start_symbol_gen(mpn: str, datasheet_rel: str) -> AgentRun:
    """Generate a native Altium symbol for one MPN from its datasheet PDF.

    The model extracts the pinout into a small JSON pin-spec
    (`Parts Library/<MPN>/<MPN>.pinspec.json`), then authors the committed
    `Parts Library/<MPN>/<MPN>.SchLib` deterministically via
    `test1.altium.author_symbol`. No KiCad: the .SchLib is the GUI's source of
    truth (_primary_symbol_for) and what the build pipeline merges into
    parts.SchLib.
    """
    repo_root = PROJECT_DIR.parent
    parts_lib = PROJECT_DIR / "Parts Library"
    spec_file = parts_lib / mpn / f"{mpn}.pinspec.json"
    schlib_file = parts_lib / mpn / f"{mpn}.SchLib"
    datasheet_abs = parts_lib / mpn / datasheet_rel
    author_cmd = f'"{sys.executable}" -m test1.altium.author_symbol "{mpn}"'
    instructions = f"""\
Generate a native Altium schematic symbol for {mpn} from the datasheet at:
  {datasheet_abs}

Do it in two steps:

STEP 1 — Write a JSON pin-spec at:
  {spec_file}
(create the parent directory if needed). Schema:

  {{
    "mpn": "{mpn}",
    "description": "<short part description>",
    "reference": "<designator prefix: U/R/C/J/Q/D/L/...>",
    "properties": {{
      "Value": "<orderable part value, e.g. the full MPN or 10uF/10k>",
      "Footprint": "<package/footprint name from the datasheet, if known>",
      "Datasheet": "<datasheet URL if known, else the PDF filename>",
      "Manufacturer": "<manufacturer name>",
      "MPN": "<manufacturer part number>"
    }},
    "units": [
      {{ "unit": 1, "pins": [
        {{ "number": "<pin number/designator>", "name": "<pin name>",
           "type": "<electrical type>", "side": "<body side>" }},
        ...
      ]}}
    ]
  }}

  - "type" is one of: input, output, bidirectional, passive, power_in,
    power_out, tri_state, open_collector, open_emitter — chosen from the
    datasheet's ELECTRICAL characteristics, not just the pin name.
  - "side" is one of: left, right, top, bottom. Lay pins out by function:
    power_in on top, power_out/ground on bottom, inputs on left, outputs on
    right (match how the part is conventionally drawn).
  - "reference" is the schematic designator PREFIX for this part class
    (U for ICs, R resistors, C caps, J connectors, Q transistors, D diodes,
    L inductors). "properties" become Altium component parameters — fill in
    every field you can determine from the datasheet; omit a property only if
    genuinely unknown.
  - For a multi-unit part (e.g. a dual op-amp, or a multi-bank connector),
    list multiple objects in "units" with the pins grouped per unit. For a
    single-unit part, one unit with all pins is fine.
  - Include EVERY pin in the datasheet's pinout exactly once.

STEP 2 — Author the Altium library by running this command from {repo_root}:
  {author_cmd}
It reads the pin-spec and writes {schlib_file}. Confirm the command's printed
pin/unit count matches the datasheet, then print a one-line summary.
"""
    proc, _cmd = await _spawn_claude(
        prompt=instructions,
        system_suffix="",  # symbol gen doesn't need the chat instructions
        permission_mode="acceptEdits",
        add_dir=repo_root,  # let the agent write under Parts Library + run the build
        model=model_for("symbol_gen"),
    )
    run = _register("symbol-gen")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


# ---------------------------------------------------------------------------
# Rule generator (closed-loop design review) — dispatches the rule_gen agent
# with the doc bundle + predicate spec + existing user rules pre-written to
# tempfiles. The agent reads them, emits a JSON rules file at `out`, and the
# Python side (test1/review/rule_gen.py::_claude_generate) validates + retries.
# ---------------------------------------------------------------------------
async def start_rule_gen(doc_bundle_path: Path, predicate_spec_path: Path,
                         user_rules_path: Path, output_path: Path) -> AgentRun:
    """Dispatch the rule_gen agent. Inputs + output passed as file paths
    (claude -p can't take huge JSON blobs as args)."""
    prompt = _build_rule_gen_prompt(doc_bundle_path, predicate_spec_path,
                                    user_rules_path, output_path)
    proc, _cmd = await _spawn_claude(
        prompt=prompt,
        system_suffix="",
        permission_mode="acceptEdits",   # writes output_path
        allowed_tools=[
            "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch",
            "Bash(python:*)", "Bash(python3:*)", "Bash(pdftotext:*)",
            "Bash(cd:*)", "Bash(ls:*)", "Bash(cat:*)",
        ],
        add_dir=REPO_ROOT,
        model=model_for("rule_gen"),
    )
    run = _register("rule_gen")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


def _build_rule_gen_prompt(bundle: Path, spec: Path, user: Path, out: Path) -> str:
    return f"""You are generating a closed-loop design-review rule set for a
schematic project at {REPO_ROOT}.

Read these files:
  - Doc bundle:       {bundle}    (JSON: requirements_md, bobcat_pdf_text,
                                    datasheet_texts dict, url_texts dict,
                                    netlist_yamls dict)
  - Predicate spec:   {spec}      (JSON: closed list of allowed predicate
                                    kinds + their args)
  - Existing user rules: {user}   (JSON: rules with origin='user' you must
                                    NOT regenerate or contradict)

Emit a JSON file at {out} matching this exact schema (see
test1/review/rule_schema.py for Pydantic models):

  {{ "rules": [ {{... Rule object ...}}, ... ] }}

Each Rule has:
  - id:         SCREAMING_SNAKE_CASE, stable, unique within the file
  - family:     "schematic" | "simulation" | "design"
  - evaluation: "structural" | "semantic"
  - severity:   "ERROR" | "WARNING" | "INFO"
  - title:      one-line headline
  - applies_to: {{ refdes?, pins?, net?, rail?, sheet?, sim_block?,
                  sim_type?, mpn?, role_spec? }}
  - source:     list of {{doc, loc, quote}} — REQUIRED, >=1 entry, with a
                verbatim quote you can find in the cited doc
  - fix_hint:   short fix instruction
  - enabled:    true
  - origin:     "generated"

For structural rules: include "predicate": {{kind, ...args per spec}}.
For semantic rules: include "prompt": text the per-rule evaluator will
ask each pass.

Hard constraints:
  - Every rule.source[*].quote MUST be a verbatim substring of the cited
    doc (whitespace-normalized). Hallucinated quotes are rejected.
  - Generate AT LEAST 30 rules across the three families.
  - Use ONLY the predicate kinds in the spec — invented kinds are rejected.
  - DO NOT emit rules whose id collides with anything in the existing
    user rules file.

Reply with ONLY the JSON output written to {out}; no commentary.
"""


_SIM_PARAM_CACHE = PROJECT_DIR / "sim" / "cache" / "datasheet_params.json"
_SIM_CONFIG = PROJECT_DIR / "sim" / "cache" / "sim_config.json"


async def start_sim_setup(
    *,
    block_id: str,
    datasheets: list[dict],          # [{mpn, file}]
    sheet: str,                      # the block's netlist sheet, e.g. "power.yaml"
) -> AgentRun:
    """Context-first setup: read the datasheets + requirements + the CURRENT
    design (netlist), then determine the parameters to apply to the sim — both
    device model params AND the operating-point scenario — BEFORE the sim runs."""
    ds_lines = "\n".join(
        f"  - {d['mpn']}: {PROJECT_DIR / 'Parts Library' / d['mpn'] / d['file']}"
        for d in datasheets
    )
    all_mpns = sorted({d["mpn"] for d in datasheets})
    # The parts whose datasheet numbers actually feed an ngspice model param
    # (have a sim/param_map mapper). These are the ones the sim's accuracy
    # depends on and that the freshness check requires cached; the rest are
    # behavioral stubs or netlist-valued (caps, the DUT load).
    try:
        from test1.sim import param_map as _pm
        model_mpns = sorted(m for m in all_mpns if m in _pm._MAP)
    except Exception:
        model_mpns = []
    cached = dscache_cached_mpns()
    must_extract = [m for m in model_mpns if m not in cached]
    netlist_path = PROJECT_DIR / "netlist" / sheet
    instructions = f"""\
This is a SIM-SETUP pass for block '{block_id}'. The order is context FIRST,
then parameters, THEN the sim runs (done by the backend after you finish).
Setup OWNS the datasheet → parameter extraction: every device parameter the
sim uses is established HERE, before the run. The interpret pass downstream
only CONSUMES what you cache — it does not read datasheets — so a model part
you leave uncharacterized here will silently run on model defaults.

Datasheets for this block's parts:
{ds_lines}

Requirements (intent/spec):  {PROJECT_DIR / 'design_requirements.md'}
Current design (as-built):   {netlist_path}
Device-param cache:          {_SIM_PARAM_CACHE}
Sim-scenario cache:          {_SIM_CONFIG}

READING DATASHEET PDFs — the Read tool CANNOT rasterize these PDFs (no poppler),
so do NOT Read the .pdf directly and do NOT write your own pdf script. Use the
provided helper via BASH (not PowerShell). You are ALREADY in the test1/
directory — do NOT cd; do NOT write your own pdf script.

STEP 1 — TEXT FIRST (fast, reliable). Get the text layer of the EC-table pages:
    python sim/read_pdf.py "<pdf path>" --pages 4-9 --text-only
This prints the page text — most electrical specs (VOS, GBW, AOL, dropout, RON,
tON with their conditions) are readable straight from the text. Extract what you
can from text.
STEP 2 — IMAGES ONLY IF NEEDED (slower). If a value lives in a table whose layout
is garbled in the text, or in a graph, render JUST those 1-2 pages and Read the
PNGs:
    python sim/read_pdf.py "<pdf path>" --pages 6,7
Keep the page count tiny (1-2) — reading many high-res PNGs is slow. Prefer text;
reach for images only for the specific unreadable value.

Parts whose datasheet numbers FEED the sim (must be cached): {model_mpns or "(none — this block has no model-param parts)"}
Already in the param cache: {sorted(cached)}
You MUST extract these now (missing model parts): {must_extract or "(none — all model parts cached)"}

(The block's other parts are behavioral stubs or netlist-valued — caps, the DUT
load — and don't need datasheet params; characterize one only if it clarifies
the operating point.)

Your job — gain context, then establish ALL parameters before the sim runs:
1. Read the requirements AND the current netlist to understand the as-built
   circuit (what this block actually drives, at what voltages/currents).
2. DEVICE PARAMS — every part in "must be cached" above must end up in
   {_SIM_PARAM_CACHE}, keyed by MPN with sub-keys `model_params` and `spec`. For
   each such part NOT yet cached, read its datasheet PDF and extract the key
   electrical parameters. Use DESCRIPTIVE keys naming the value, its condition,
   and its UNIT (e.g. "DROPOUT_mV_max_VIN1V1_BIAS_3A", "RON_mOhm_max_VIN1V8_85C",
   "tON_us_typ_VIN1V8", "VOS_uV_max_25C", "GBW_MHz", "AOL_dB_min") — a
   deterministic code mapper (sim/param_map.py) converts these into ngspice
   model inputs, so accuracy + clear units matter more than matching a fixed
   name. Prefer worst-case numbers where they matter (max offset, min gain).
   Set `source`, `extracted_at`, and `needs_clarification` (null, or a question
   if a value that matters is ambiguous). Read {_SIM_PARAM_CACHE} first, MERGE,
   write it back. Do not drop already-cached parts. When you finish, every part
   in "must be cached" above must be present.
3. SIM SCENARIO — write {_SIM_CONFIG} keyed by '{block_id}' (read first, merge,
   write back):
     - operating_points_V: the REAL operating point(s) grounded in the
       requirements + the current design — e.g. if the LDO feeds the Bobcat
       core rails at 0.6-1.0V, use [0.6, 1.0], NOT an arbitrary default.
     - primary_vout_set_V: the single representative setpoint to sim by default.
     - load_note, rationale, sources (files you used), needs_clarification
       (null, or a question if intent is ambiguous).
4. Do NOT run the sim and do NOT edit netlists. Finish with one line:
   SETUP_DONE: <params cached for [MPNs]; scenario = one-sentence summary>
"""
    proc, _cmd = await _spawn_claude(
        prompt=instructions,
        system_suffix="",
        permission_mode="acceptEdits",   # writes the two cache files
        # Allow python (the venv is first on PATH → has fitz) + pdftotext so the
        # agent can run the PDF-render helper to read datasheet diagrams. A
        # narrowly-pinned prefix proved brittle — the agent quotes the path and
        # prepends `cd … &&`, which a `Bash(python sim/read_pdf.py:*)` matcher
        # rejects, making it thrash into PowerShell + ad-hoc pdf scripts. These
        # agents have tightly-scoped prompts, so allowing `python`/bash plumbing
        # is the pragmatic, non-thrashing choice (acceptEdits still governs writes).
        allowed_tools=[
            "Read", "Edit", "Write", "Glob", "Grep",
            "Bash(python:*)", "Bash(python3:*)", "Bash(pdftotext:*)",
            "Bash(cd:*)", "Bash(ls:*)", "Bash(cat:*)",
        ],
        model=model_for("sim_setup"),
    )
    run = _register("Sim setup")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


async def start_sim_interpret(
    *,
    block_id: str,
    sim_type: str,
    pass_criterion: str,
    datasheets: list[dict],          # [{mpn, file}]
    result_json: str,                # the raw ngspice result the GUI computed
) -> AgentRun:
    """Interpret the sim result against spec. Device parameters were already
    extracted into the cache by the setup pass; this pass CONSUMES them (inlined
    into the prompt so it needn't open the cache or a datasheet) — it does not
    extract/write params. Keeping interpret off the PDF-reading path is the
    latency fix: ngspice itself runs in <1s, so a slow interpret (re-reading
    datasheets) is what makes the GUI's interpret watchdog fire."""
    # Inline THIS block's cached params straight into the prompt, so the agent
    # cites from numbers it already has and (almost) never needs to read a PDF —
    # the slow path that was timing the pass out. Only the block's own MPNs.
    block_mpns = {d.get("mpn") for d in datasheets}
    try:
        _all = json.loads(_SIM_PARAM_CACHE.read_text())
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        _all = {}
    _cached = {m: e for m, e in _all.items() if m in block_mpns} if isinstance(_all, dict) else {}
    cached_params_block = (
        json.dumps(_cached, indent=2) if _cached
        else "(no cached params for this block's parts — it has none that feed a model)"
    )
    # Datasheets are a LAST-RESORT fallback now (a missing-from-cache number),
    # not the primary reference — list them but de-emphasize.
    ds_lines = "\n".join(
        f"  - {d['mpn']}: {PROJECT_DIR / 'Parts Library' / d['mpn'] / d['file']}"
        for d in datasheets
    )
    instructions = f"""\
This is a SIMULATION-INTERPRET pass for block '{block_id}', sim '{sim_type}'.

Datasheets for this block's parts (FALLBACK only — prefer the cached params below):
{ds_lines}

Spec: {PROJECT_DIR / 'design_requirements.md'}

The setup pass ALREADY extracted every device parameter this sim needs and
cached it. The cached params for this block's parts are inlined here so you do
NOT need to open the cache file or any datasheet:
{cached_params_block}

LATENCY — BE FAST. The sim is done; your job is a quick verdict, and the GUI
times the interpret pass out. Work from the numbers you ALREADY have: the result
JSON below and the cached params above. Those param keys already name the value,
its condition, and its unit (e.g. "VOS_uV_max_25C": 5) — cite them directly as
your datasheet reference. Do NOT re-read datasheets to "ground" or "double-check"
a number that is already cached, and do NOT read a part's datasheet just to
explain a result — the cached spec is the citation. Reading PDFs is the slow path
that makes this pass time out.
ONLY if a SPECIFIC number you must compare against is genuinely ABSENT from the
cached params above may you read it — at most ONE targeted, text-only call, then
stop (you are in test1/; plain `python`, no cd):
    python sim/read_pdf.py "<pdf path>" --pages <only the EC-table page> --text-only
Never render PNG images during interpret (vision reads are the slowest path and
stall the pass); the cached params are authoritative.

The GUI already ran the ngspice sim. Raw result JSON:
{result_json}

The block's nominal pass criterion was: {pass_criterion}

Your job:
1. Cross-check the sim RESULT against the cached params AND design requirements.
   State whether it meets spec, with the actual margin and the cached param you
   compared against (cite the param key/value — that IS the datasheet number).
   Do not modify the cache. Do not re-derive cached numbers from PDFs.
2. SUGGESTIONS are CIRCUIT-DESIGN changes ONLY — edits the schematic-generation
   phase can apply to netlist/*.yaml or altium/build_*.py and then regenerate the board.
   The changelog feeds an apply pass that edits the DESIGN, so every bullet must
   be an actionable circuit edit: change a component value, add/remove a part or
   decoupling cap, swap a part for a better one (e.g. a lower-RON load switch),
   change a pull resistor, change topology. State the target (what to change and
   to what value) and cite the datasheet/requirement that motivates it.

   Do NOT put simulation or test-setup items in SUGGESTIONS — no sweep ranges,
   operating points, "verify X", "re-run with…", or "add a sim". Those are not
   circuit changes and the apply pass can't act on them. If your finding is a
   sim-coverage gap or an open question (not a circuit edit), put it in CLARIFY.
   Only suggest a circuit change when the design actually warrants one; write
   "- none" if the circuit is fine as-is. Do NOT edit files or push yourself.
3. ITERATE (optional, HARD-capped at 3). If a clarification would be resolved
   by an INSTANT re-sim with a corrected SCENARIO parameter — e.g. the wrong
   operating point or load was used — you MAY fix it and re-run:
     a) update the scenario in {_SIM_CONFIG} (e.g. primary_vout_set_V, keyed by
        '{block_id}'),
     b) re-run (use bash):  python sim/iterate_sim.py --block {block_id} --sim-type {sim_type}
        (it prints the new result JSON). Re-read the result and continue.
   The CLI enforces a hard limit of 3 re-sims; once it returns limit_reached,
   STOP iterating and emit the verdict on the best result so far. ONLY iterate
   when a re-sim genuinely resolves the issue — do NOT iterate for circuit-
   design problems (those are SUGGESTIONS) or for questions needing external
   info (those stay in CLARIFY). If no re-sim is warranted, don't iterate.

Finish with a compact block exactly like (SUGGESTIONS is a bullet list of
circuit edits, one per line; "- none" if no circuit change is warranted):
  VERDICT: MEETS_SPEC | OUT_OF_SPEC | NEEDS_CLARIFICATION
  MARGIN: <one line, with the datasheet number you compared against>
  SUGGESTIONS:
  - <circuit edit: what to change, to what value, why (datasheet/req)>
  CLARIFY: <sim-coverage gap or open question, or "none">
  ITERATIONS: <how many re-sims you ran (0 if none), and what you changed>
"""
    # Reset the per-(block,sim) re-sim counter so the agent gets a fresh budget
    # of 3 this turn (the iterate_sim CLI enforces the cap).
    try:
        safe = f"{block_id}_{sim_type}".replace("/", "_")
        counter = PROJECT_DIR / "sim" / "cache" / f".iter_{safe}.json"
        counter.parent.mkdir(parents=True, exist_ok=True)
        counter.write_text(json.dumps({"count": 0}))
    except OSError:
        pass

    proc, _cmd = await _spawn_claude(
        prompt=instructions,
        system_suffix="",
        permission_mode="acceptEdits",   # auto-approves cache/scenario edits
        # Allow python (venv first on PATH → fitz) + pdftotext + plumbing so the
        # agent can run the bounded iterate CLI and the PDF-render helper without
        # a brittle pinned prefix (it quotes paths / prepends `cd &&`). Tightly-
        # scoped prompt; acceptEdits still governs writes.
        allowed_tools=[
            "Read", "Edit", "Write", "Glob", "Grep",
            "Bash(python:*)", "Bash(python3:*)", "Bash(pdftotext:*)",
            "Bash(cd:*)", "Bash(ls:*)", "Bash(cat:*)",
        ],
        model=model_for("sim_interpret"),
    )
    run = _register("Sim interpret")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


# ---------------------------------------------------------------------------
# SPICE-model lifecycle agents: GENERATE (no model yet) / UPDATE (model stale vs
# the schematic) / CHAT-EDIT (interactive block/param/model edits).
# ---------------------------------------------------------------------------
# These write CODE (a deck builder under sim/decks/) and edit the catalog, so
# they get a wider — but still sim-scoped — tool allowance than the
# extraction/verdict agents. acceptEdits governs writes; the prompts pin them to
# the sim layer and forbid touching the generator/linter/netlist.
_SIM_BUILD_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(python:*)", "Bash(python3:*)", "Bash(pdftotext:*)",
    "Bash(cd:*)", "Bash(ls:*)", "Bash(cat:*)",
]

# The deck-builder contract, shared by generate + update so both author decks the
# pipeline can actually dispatch + parse. Kept in one place so it can't drift.
_DECK_CONTRACT = f"""\
DECK-BUILDER CONTRACT — a block's SPICE model is a Python module
{PROJECT_DIR}/sim/decks/<block_id>.py that the sim layer dispatches. To stay
runnable + renderable it MUST:
  1. Expose `build_deck(*, mode: str, **kw) -> tuple[str, dict[str, list[str]]]`
     returning (ngspice deck text, trace_specs). Study the EXISTING builders as
     the template — sim/decks/ldo_rail.py (multi-mode + analyzers), opa_bias.py
     (feedback loop + refdes_map), pdn.py (cap-bank PDN). MATCH their structure.
  2. Read as-built component VALUES from the netlist via sim/design_extract.py
     (caps_on_net, resistor_value, sense_resistance, …) — NEVER hardcode a value
     that lives in netlist/<sheet>.yaml. Only genuinely off-sheet boundary values
     (source impedance, load current, enable timing) come from blocks.yaml.
  3. Use the shared device models in sim/models.py and boundary stubs in
     sim/stubs.py (emit_stub) rather than inventing inline models where one exists.
  4. Provide analyzer fn(s) returning a dict with an "overall": "OK"|"FAIL" key
     for each sim_type, and a `refdes_map()` mapping each deck element ref to its
     netlist refdes (or None for behavioral scaffolding) so the GUI ties the model
     back to the schematic.
  5. Be wired into sim/service.py dispatch (run_block_sim + build_deck_text +
     _refdes_map_for) AND have a blocks.yaml catalog entry (id, title, sheet,
     group, status: implemented, sim_types with rationale + a concrete `pass`,
     boundaries). Use sim/catalog_edit.py for surgical, comment-preserving
     blocks.yaml edits where possible.
  6. After the model matches the schematic, RECORD provenance so staleness
     tracking works:  python sim/deck_provenance.py --stamp <block_id>
  7. VERIFY before finishing: run the sim through the service, e.g.
       python -c "import sys; sys.path.insert(0,'.'); from test1.sim import service; \\
                  print(service.run_block_sim('<block_id>', '<sim_type>')['status'])"
     (cwd is test1/). status must be 'ran' (or 'no_simulator' if ngspice is
     absent — acceptable; means the deck built + dispatched).

GUARDRAILS — stay in the SIM LAYER. You MAY write sim/decks/*.py and edit
sim/blocks.yaml + sim/service.py. Do NOT touch netlist/*.yaml, altium/*, gen/*,
review/*, or the linter — the schematic is the INPUT, never edited here. Behavioral
models only: model device BEHAVIOR (regulation, gain, droop), not a transistor-
level transcription. If a value/intent is genuinely ambiguous, record it as a
needs_clarification note rather than guessing.
"""


async def start_sim_generate_model(
    *,
    block_id: str,
    title: str,
    sheet: str,                      # the block's netlist sheet, e.g. "power.yaml"
    datasheets: list[dict],          # [{mpn, file}]
    description: str = "",
    group: str = "",
) -> AgentRun:
    """Generate a NEW SPICE model for a block that has none. The agent reads the
    netlist sheet + datasheets, studies the existing deck builders as templates,
    and writes sim/decks/<block>.py + the service dispatch + a blocks.yaml entry,
    then verifies the sim runs. Guarded to the sim layer."""
    ds_lines = "\n".join(
        f"  - {d['mpn']}: {PROJECT_DIR / 'Parts Library' / d['mpn'] / d['file']}"
        for d in datasheets
    ) or "  (none listed — infer the block's parts from the netlist sheet)"
    netlist_path = PROJECT_DIR / "netlist" / sheet if sheet.endswith(".yaml") else f"(composed: {sheet})"
    instructions = f"""\
This is a GENERATE-SPICE-MODEL pass. Block '{block_id}' ({title!r}) has NO deck
builder yet — there is no SPICE model for it. Your job is to AUTHOR one from the
as-built schematic + datasheets, so the Simulation tab can run it.

Block:        {block_id}  —  {title}
Description:  {description or "(derive from the netlist + datasheets)"}
Netlist:      {netlist_path}
Datasheets:
{ds_lines}
Requirements: {PROJECT_DIR / 'design_requirements.md'}

{_DECK_CONTRACT}

READING DATASHEET PDFs — the Read tool can't rasterize PDFs (no poppler). Use the
helper via BASH, TEXT FIRST (you are already in test1/, do NOT cd):
    python sim/read_pdf.py "<pdf path>" --pages 4-9 --text-only
render an image only for a specific value unreadable as text.

Steps:
1. Read the netlist sheet to learn the block's real parts, nets, and values.
   Read the datasheets for the active devices' behavior (regulation, gain, RON,
   dropout, …). Read design_requirements.md for intent.
2. Decide the sim_types that make sense for THIS block (mirror how comparable
   blocks are tested — e.g. a rail → dc_op_point + a load step; an amp → dc/ac/
   settling). Each needs a rationale + a concrete, checkable `pass` criterion.
3. Write sim/decks/{block_id}.py per the contract, wire it into sim/service.py,
   and add the blocks.yaml entry (status: implemented).
4. Stamp provenance and VERIFY the sim runs (contract steps 6-7).
5. Finish with one line:
   MODEL_GENERATED: <block_id>; sim_types=[...]; verified status=<ran|no_simulator>
"""
    proc, _cmd = await _spawn_claude(
        prompt=instructions,
        system_suffix="",
        permission_mode="acceptEdits",
        allowed_tools=_SIM_BUILD_TOOLS,
        model=model_for("sim_generate"),
    )
    run = _register("Sim generate-model")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


async def start_sim_update_model(
    *,
    block_id: str,
    title: str,
    sheet: str,
    datasheets: list[dict],
    status_reason: str = "",         # why we think it's stale (provenance)
) -> AgentRun:
    """Update a block's EXISTING SPICE model + catalog entry to match the current
    schematic, after the netlist changed under it. The agent diffs the netlist
    against the deck's assumptions and brings the model back in sync, then
    re-stamps provenance. Guarded to the sim layer."""
    ds_lines = "\n".join(
        f"  - {d['mpn']}: {PROJECT_DIR / 'Parts Library' / d['mpn'] / d['file']}"
        for d in datasheets
    ) or "  (none listed)"
    netlist_path = PROJECT_DIR / "netlist" / sheet if sheet.endswith(".yaml") else f"(composed: {sheet})"
    instructions = f"""\
This is an UPDATE-SPICE-MODEL pass. Block '{block_id}' ({title!r}) HAS a model
(sim/decks/{block_id}.py), but the schematic changed under it{f' — {status_reason}' if status_reason else ''}.
Bring the model + its catalog entry back in sync with the as-built design.

Block:    {block_id}  —  {title}
Model:    {PROJECT_DIR / 'sim' / 'decks' / f'{block_id}.py'}
Netlist:  {netlist_path}   (the CURRENT schematic — the source of truth)
Catalog:  {PROJECT_DIR / 'sim' / 'blocks.yaml'}  (entry id '{block_id}')
Datasheets:
{ds_lines}

{_DECK_CONTRACT}

Steps:
1. Read the CURRENT netlist sheet and the EXISTING deck builder. Diff them:
   - parts/nets the deck references that no longer exist or were renamed,
   - new parts/nets in scope the deck should now include,
   - component values: confirm the deck reads them from design_extract (not
     hardcoded) — fix any that drifted.
2. Make the MINIMAL changes to sim/decks/{block_id}.py (+ service.py/blocks.yaml
   if the topology/sim_types genuinely changed) so the model reflects the new
   schematic. Don't gratuitously rewrite a working deck.
3. Re-stamp provenance and VERIFY (contract steps 6-7).
4. Finish with one line:
   MODEL_UPDATED: <block_id>; changes=<one-line summary>; verified status=<ran|no_simulator>
"""
    proc, _cmd = await _spawn_claude(
        prompt=instructions,
        system_suffix="",
        permission_mode="acceptEdits",
        allowed_tools=_SIM_BUILD_TOOLS,
        model=model_for("sim_update"),
    )
    run = _register("Sim update-model")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


async def start_sim_chat_edit(
    *,
    block_id: str,
    instruction: str,                # the user's natural-language edit request
    sheet: str = "",
) -> AgentRun:
    """Foundation for chat-driven sim editing: apply a natural-language request to
    a block's sim — its pass criteria / boundary params (catalog), its model
    (deck builder), or its functions. The interactive chat UI that drives this is
    gated on the user's forthcoming chat API; the agent + endpoint are ready so
    that hook is a thin wire-up, not new machinery.

    `instruction` is the user's request, e.g. "loosen the VDDIO droop limit to
    40mV", "add an output-noise sim", "model the LDO PSRR".
    """
    netlist_path = PROJECT_DIR / "netlist" / sheet if sheet.endswith(".yaml") else "(see the block's sheet)"
    instructions = f"""\
This is a SIM CHAT-EDIT pass for block '{block_id}'. Apply the user's request to
the block's simulation — its pass criteria / boundary params, its SPICE model
(deck builder), its sim_types, or its model parameters — whichever the request
calls for.

USER REQUEST:
{instruction}

Block model:   {PROJECT_DIR / 'sim' / 'decks' / f'{block_id}.py'}
Catalog entry: {PROJECT_DIR / 'sim' / 'blocks.yaml'} (id '{block_id}')
Netlist:       {netlist_path}

{_DECK_CONTRACT}

Behaviour:
1. Interpret the request and make the SMALLEST change that satisfies it. Prefer
   surgical catalog edits (sim/catalog_edit.py) for pass/param changes; edit the
   deck builder for model/topology/function changes.
2. If the request is ambiguous or would change the design intent, DON'T guess —
   finish with a CLARIFY line stating what you need.
3. If you changed the deck/topology, re-stamp provenance + verify (contract 6-7).
4. Finish with one line:
   CHAT_EDIT_DONE: <block_id>; <one-line summary of what changed>
   (or)  CLARIFY: <the question>
"""
    proc, _cmd = await _spawn_claude(
        prompt=instructions,
        system_suffix="",
        permission_mode="acceptEdits",
        allowed_tools=_SIM_BUILD_TOOLS,
        model=model_for("sim_chat_edit"),
    )
    run = _register("Sim chat-edit")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


def dscache_cached_mpns() -> list[str]:
    """MPNs already present in the param cache without a pending clarification."""
    try:
        data = json.loads(_SIM_PARAM_CACHE.read_text())
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return []
    return [m for m, e in data.items() if isinstance(e, dict) and not e.get("needs_clarification")]


async def stream_run(run_id: str) -> AsyncIterator[bytes]:
    """SSE generator — replay buffered events then live-tail."""
    run = _RUNS.get(run_id)
    if not run:
        # Not in memory (e.g. backend restarted after the run finished). Fall back
        # to the persisted reasoning log so a per-agent dropdown still shows what
        # the agent did + thought, then close.
        log = STATE_DIR / "runs" / f"{run_id}.log"
        if log.exists():
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                yield f"data: {json.dumps({'line': line})}\n\n".encode()
            yield b"event: done\ndata: {\"status\": \"replayed\"}\n\n"
        else:
            yield b"event: done\ndata: {\"status\": \"not_found\"}\n\n"
        return
    # Replay the full concise stream (thinking/assistant/tool lines), not just the
    # final answer — run.text gets overwritten with the final result on completion,
    # but stream_log preserves the whole reasoning trace for the dropdown.
    for line in (run.stream_log or run.text).splitlines():
        yield f"data: {json.dumps({'line': line})}\n\n".encode()
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    run.subscribers.append(q)
    try:
        while True:
            item = await q.get()
            if item is None:
                final = run.text.strip()
                yield (
                    f"event: done\n"
                    f"data: {json.dumps({'status': run.status, 'rc': run.returncode, 'text': final})}\n\n"
                ).encode()
                return
            yield f"data: {json.dumps({'line': item})}\n\n".encode()
    finally:
        try:
            run.subscribers.remove(q)
        except ValueError:
            pass
