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
MODEL = os.environ.get("TEST1_AGENT_MODEL", "sonnet")
MAX_HISTORY_TURNS = 30


# ---------------------------------------------------------------------------
# State helpers — JSON file is the source of truth; in-memory cache only
# inside one request to avoid race conditions across concurrent fetches.
# ---------------------------------------------------------------------------
def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))


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


def append_changelog(summary: str, source: str = "agent") -> dict:
    items = load_changelog()
    entry = {
        "id": uuid.uuid4().hex[:8],
        "summary": summary.strip(),
        "source": source,
        "ts": time.time(),
    }
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

_APPLY_INSTRUCTIONS = f"""\
This is an APPLY-CHANGELOG pass. The user just clicked Generate.

You will receive a list of changelog items the user accumulated. Your job:

1. Implement each item by editing the relevant files (netlist/*.yaml,
   altium/build_<sheet>.py, design_requirements.md). Use Read, Edit, Write.
   (This is the Altium pipeline — edit altium/build_*.py, NOT gen/build_*.py,
   which no longer exists.)
2. Be conservative: make the smallest change that satisfies the bullet.
   If a bullet is ambiguous, do the most reasonable interpretation and
   note your assumption in the final summary.
3. DO NOT run the build yourself (`python -m test1.altium.build_project`) — the
   GUI backend will run it after you return.
4. When done, clear the changelog file ({CHANGELOG_FILE}) to an empty
   list [] so the next chat turn starts clean.
5. Finish with a terse summary block, one bullet per item, of what you
   actually changed.
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
    status: str = "running"          # "running" | "ok" | "fail"
    returncode: int | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)


_RUNS: dict[str, AgentRun] = {}


def get_run(run_id: str) -> AgentRun | None:
    return _RUNS.get(run_id)


async def _spawn_claude(
    *,
    prompt: str,
    system_suffix: str,
    permission_mode: str = "acceptEdits",
    allowed_tools: list[str] | None = None,
    add_dir: Path | None = None,
) -> tuple[asyncio.subprocess.Process, list[str]]:
    """Spawn `claude -p` and return (proc, cmd). Output format is
    stream-json so we can parse per-event."""
    cmd = [
        CLAUDE,
        "-p", prompt,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",                # stream-json requires verbose
        "--model", MODEL,
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
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(PROJECT_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
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
            if block.get("type") == "text":
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


async def _run_subprocess(run: AgentRun, proc: asyncio.subprocess.Process) -> None:
    """Stream the subprocess's stream-json output, parse each line, and
    fan out one-line summaries to SSE subscribers."""
    assert proc.stdout is not None

    def push(line: str) -> None:
        run.text += line + "\n"
        for q in list(run.subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    final_text: list[str] = []
    while True:
        raw = await proc.stdout.readline()
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
    run.status = "ok" if run.returncode == 0 else "fail"
    # The final assistant text is the canonical user-visible answer.
    if final_text:
        run.text = "\n".join(final_text)
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


async def start_apply_pass() -> AgentRun:
    """Hand the queued changelog to the agent for implementation."""
    items = load_changelog()
    prompt = _build_apply_prompt(items)
    proc, _cmd = await _spawn_claude(
        prompt=prompt,
        system_suffix=_APPLY_INSTRUCTIONS,
        permission_mode="acceptEdits",
    )
    run = _register("apply")
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
    )
    run = _register("symbol-gen")
    asyncio.create_task(_run_subprocess(run, proc))
    return run


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
    )
    run = _register("sim-setup")
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
    extracted into the cache by the setup pass, so this pass only CONSUMES them
    (and the datasheets, for citations) — it does not extract/write params."""
    ds_lines = "\n".join(
        f"  - {d['mpn']}: {PROJECT_DIR / 'Parts Library' / d['mpn'] / d['file']}"
        for d in datasheets
    )
    instructions = f"""\
This is a SIMULATION-INTERPRET pass for block '{block_id}', sim '{sim_type}'.

Datasheets for this block's parts (for citing the numbers you compare against):
{ds_lines}

Spec: {PROJECT_DIR / 'design_requirements.md'}
Device-param cache (already populated by setup — READ-ONLY here): {_SIM_PARAM_CACHE}

The device parameters this sim used were extracted by the setup pass and are
in the param cache above. Do NOT re-extract or rewrite them. Read the cache and
the datasheets to ground your judgement; cite the datasheet number you compare
the result against.

The GUI already ran the ngspice sim. Raw result JSON:
{result_json}

The block's nominal pass criterion was: {pass_criterion}

Your job:
1. Cross-check the sim RESULT against the datasheet specs AND design
   requirements. State whether it meets spec, with the actual margin and a
   datasheet citation (section/page or the number). Use the cached params +
   the datasheets for context — do not modify {_SIM_PARAM_CACHE}.
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
     b) re-run:  python3 sim/iterate_sim.py --block {block_id} --sim-type {sim_type}
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
        # Whitelist the bounded iterate CLI so the agent can actually re-sim
        # (acceptEdits alone blocks arbitrary Bash in non-interactive -p mode).
        allowed_tools=[
            "Read", "Edit", "Write", "Glob", "Grep",
            "Bash(python3 sim/iterate_sim.py:*)",
            "Bash(python sim/iterate_sim.py:*)",
        ],
    )
    run = _register("sim-interpret")
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
        yield b"event: done\ndata: {\"status\": \"not_found\"}\n\n"
        return
    # Replay anything already buffered as text lines.
    for line in run.text.splitlines():
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
