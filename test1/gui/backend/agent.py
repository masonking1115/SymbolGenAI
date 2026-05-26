"""Agent runner — wraps `claude -p` so the GUI can drive a Claude Code session.

There are two distinct call sites today:

  1. Chat turn  — user typed something into the GUI's right rail. The agent's
     job here is *advisory*: ack the request and append a one-line bullet
     to the changelog file. It must NOT edit the netlist or code on a chat
     turn — those edits only happen at "apply changelog" time.

  2. Apply pass — user clicked Generate. The agent reads the queued
     changelog and implements each item (Edit/Write on yaml + python). The
     pipeline (gen_schematic.py → lint → review) is run by the backend
     *after* this returns, NOT by the agent.

The same `claude` binary backs both. We swap the system-prompt suffix and
the prompt body to switch modes. Output is streamed back to the GUI line by
line so the user can watch tool calls in real time.

Auth: this re-uses whatever auth the user already has set up for `claude`.
No API key is read from the env. The subprocess inherits the user's env.

State on disk
-------------
  state/chat.json      — conversation transcript (advisory; agent reads it
                         too, on each chat turn, so multi-turn context works)
  state/changelog.json — queued items: [{id, summary, source, ts}]
  state/status.json    — most recent pipeline status snapshot
"""

from __future__ import annotations

import asyncio
import json
import os
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
STATE_DIR = HERE.parent / "state"         # test1/gui/state/
CHAT_FILE = STATE_DIR / "chat.json"
CHANGELOG_FILE = STATE_DIR / "changelog.json"
STATUS_FILE = STATE_DIR / "status.json"

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
    return _load(CHAT_FILE, [])


def save_chat(history: list[dict]) -> None:
    _save(CHAT_FILE, history)


def load_changelog() -> list[dict]:
    return _load(CHANGELOG_FILE, [])


def save_changelog(items: list[dict]) -> None:
    _save(CHANGELOG_FILE, items)


def append_chat(role: str, content: str) -> dict:
    history = load_chat()
    entry = {
        "id": uuid.uuid4().hex[:10],
        "role": role,
        "content": content,
        "ts": time.time(),
    }
    history.append(entry)
    save_chat(history)
    return entry


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
You are the in-GUI agent for the test1 (Bobcat carrier) KiCad schematic pipeline.

The user is iterating on a hierarchical schematic via a browser GUI. They
can see the live rendered PNGs and a linter checklist. The actual pipeline
(gen_schematic.py → lint → run_review.py) is invoked by the GUI's backend
— not by you. Your job is to be the user's thinking partner and to plan
+ implement edits to the YAML netlists and Python builders.

Project root: {PROJECT_DIR}
Key files:
  - netlist/*.yaml          declarative source of truth (parts + nets)
  - gen/build_<sheet>.py    Python placement code per sheet
  - gen/layout_lint.py      visual/spatial linter
  - review/rules.py         deterministic design rules
  - design_requirements.md  spec
  - Parts Library/<MPN>/    datasheets + symbols

Memory (cross-session facts about the user + project) lives under
~/.claude/projects/-Users-masonking-Downloads-SymbolLibraryAI/memory/ and
is loaded automatically. Read it if you need context about Mason's
preferences or prior decisions.

Be terse. The user can see your tool calls; don't narrate them.
"""

_CHAT_INSTRUCTIONS = f"""\
This is a CHAT TURN. Rules:

1. DO NOT edit netlist/*.yaml or gen/*.py on a chat turn. Those edits
   happen only at apply-changelog time (separate invocation, different
   instructions).
2. When the user asks for changes to the schematic — even small ones —
   append a one-line bullet to the changelog by writing to
   {CHANGELOG_FILE} (read it first, append your entry, write it back).
   Each entry is a JSON object: {{"id": "<8-hex>", "summary": "<one line>",
   "source": "agent", "ts": <unix epoch>}}.
3. Respond to the user in plain prose. If you added changelog items, list
   them at the end so the user sees them. Keep it short (≤3 sentences plus
   the bullets).
4. If the user asks a question that doesn't require changes (e.g. "what
   does this part do?", "why is the bias circuit fail-safe?"), just
   answer — no changelog entry.
5. Tools you may use freely: Read, Grep (Bash with grep), Glob. Edit/Write
   should be limited to the changelog file on chat turns.
"""

_APPLY_INSTRUCTIONS = f"""\
This is an APPLY-CHANGELOG pass. The user just clicked Generate.

You will receive a list of changelog items the user accumulated. Your job:

1. Implement each item by editing the relevant files (netlist/*.yaml,
   gen/build_<sheet>.py, design_requirements.md). Use Read, Edit, Write.
2. Be conservative: make the smallest change that satisfies the bullet.
   If a bullet is ambiguous, do the most reasonable interpretation and
   note your assumption in the final summary.
3. DO NOT run gen_schematic.py yourself — the GUI backend will run it
   after you return.
4. When done, clear the changelog file ({CHANGELOG_FILE}) to an empty
   list [] so the next chat turn starts clean.
5. Finish with a terse summary block, one bullet per item, of what you
   actually changed.
"""


def _build_chat_prompt(history: list[dict], new_user_msg: str) -> str:
    """Stitch prior conversation + the new user turn into one prompt string.

    `claude -p` is one-shot; multi-turn continuity comes from replaying
    history. Capped at MAX_HISTORY_TURNS so prompts don't grow unbounded.
    """
    tail = history[-MAX_HISTORY_TURNS:] if len(history) > MAX_HISTORY_TURNS else history
    lines = []
    if tail:
        lines.append("Prior conversation:")
        for t in tail:
            role = "User" if t["role"] == "user" else "You"
            lines.append(f"  {role}: {t['content']}")
        lines.append("")
    lines.append(f"Current user message: {new_user_msg}")
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


async def start_chat_turn(user_msg: str) -> AgentRun:
    """Append the user's message to history, kick off `claude -p`, return
    the AgentRun. Caller subscribes via SSE to see the response stream."""
    append_chat("user", user_msg)
    history = load_chat()[:-1]  # exclude the just-appended user turn
    prompt = _build_chat_prompt(history, user_msg)
    proc, _cmd = await _spawn_claude(
        prompt=prompt,
        system_suffix=_CHAT_INSTRUCTIONS,
        permission_mode="acceptEdits",  # allows write to changelog.json
    )
    run = _register("chat")

    async def driver() -> None:
        await _run_subprocess(run, proc)
        # Persist the assistant's final text into chat history.
        if run.text.strip():
            append_chat("assistant", run.text.strip())

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
    """Generate a KiCad symbol for one MPN from its datasheet PDF."""
    sym_lib = PROJECT_DIR / "Parts Library" / "Bobcat" / "Bobcat.kicad_sym"
    datasheet_abs = PROJECT_DIR / "Parts Library" / mpn / datasheet_rel
    instructions = f"""\
Generate a KiCad symbol for {mpn} from the datasheet at:
  {datasheet_abs}

Append the new symbol definition to the existing symbol library:
  {sym_lib}

Match the s-expression style of symbols already in that file. Pin types
(input/output/passive/bidirectional/power_in/power_out) must match the
datasheet's electrical characteristics, not just the pin name. Lay out
pins by function: power on top/bottom, inputs on left, outputs on right.

After writing, print a one-line summary of the symbol you added.
"""
    proc, _cmd = await _spawn_claude(
        prompt=instructions,
        system_suffix="",  # symbol gen doesn't need the chat instructions
        permission_mode="acceptEdits",
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
    cached = dscache_cached_mpns()
    netlist_path = PROJECT_DIR / "netlist" / sheet
    instructions = f"""\
This is a SIM-SETUP pass for block '{block_id}'. The order is context FIRST,
then parameters, THEN the sim runs (done by the backend after you finish).

Datasheets for this block's parts:
{ds_lines}

Requirements (intent/spec):  {PROJECT_DIR / 'design_requirements.md'}
Current design (as-built):   {netlist_path}
Device-param cache:          {_SIM_PARAM_CACHE}
Sim-scenario cache:          {_SIM_CONFIG}

Already-cached device parts (don't re-read their PDFs unless you need a
clarification): {sorted(cached)}

Your job — gain context, then determine the parameters to apply:
1. Read the requirements AND the current netlist to understand the as-built
   circuit (what this block actually drives, at what voltages/currents). Read
   any not-yet-cached datasheets.
2. Write device model params per MPN into {_SIM_PARAM_CACHE} (descriptive keys
   with units, e.g. "DROPOUT_mV_max_VIN1V1_BIAS_3A"; a code mapper converts
   them to ngspice inputs). Read the file first, merge, write it back.
3. Determine the SIM SCENARIO and write {_SIM_CONFIG} keyed by '{block_id}'
   (read first, merge, write back):
     - operating_points_V: the REAL operating point(s) grounded in the
       requirements + the current design — e.g. if the LDO feeds the Bobcat
       core rails at 0.6-1.0V, use [0.6, 1.0], NOT an arbitrary default.
     - primary_vout_set_V: the single representative setpoint to sim by default.
     - load_note, rationale, sources (files you used), needs_clarification
       (null, or a question if intent is ambiguous).
4. Do NOT run the sim and do NOT edit netlists. Finish with one line:
   SETUP_DONE: <one-sentence summary of the scenario you chose>
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
    """Read the block's datasheets + requirements, extract/cache the key
    device parameters, and interpret the sim result against spec."""
    ds_lines = "\n".join(
        f"  - {d['mpn']}: {PROJECT_DIR / 'Parts Library' / d['mpn'] / d['file']}"
        for d in datasheets
    )
    cached = {m: True for m in dscache_cached_mpns()}
    cache_note = (
        f"Already-cached parts (DON'T re-read their PDFs unless you need a "
        f"clarification): {sorted(cached)}" if cached else
        "Nothing cached yet — read the PDFs below."
    )
    instructions = f"""\
This is a SIMULATION-INTERPRET pass for block '{block_id}', sim '{sim_type}'.

Datasheets for this block's parts:
{ds_lines}

Spec: {PROJECT_DIR / 'design_requirements.md'}
Parameter cache (read + update this JSON): {_SIM_PARAM_CACHE}

{cache_note}

The GUI already ran the ngspice sim. Raw result JSON:
{result_json}

The block's nominal pass criterion was: {pass_criterion}

Your job:
1. For any of this block's parts NOT already cached, read its datasheet and
   extract the key electrical parameters into {_SIM_PARAM_CACHE}, keyed by MPN
   with sub-keys `model_params` and `spec`. Use DESCRIPTIVE keys that name the
   value, its condition, and its UNIT (e.g. "DROPOUT_mV_max_VIN1V1_BIAS_3A",
   "RON_mOhm_max_VIN1V8_85C", "tON_us_typ_VIN1V8", "VOS_uV_max_25C", "GBW_MHz",
   "AOL_dB_typ"). A deterministic code-side mapper (sim/param_map.py) converts
   these into the ngspice model inputs, so accuracy + clear units matter more
   than matching a fixed name. Read {_SIM_PARAM_CACHE} first, merge, write it
   back. Set `source`, `extracted_at`, and `needs_clarification` (null, or a
   question if the datasheet is ambiguous about a value that matters here).
2. Cross-check the sim RESULT against the datasheet specs AND design
   requirements. State whether it meets spec, with the actual margin and a
   datasheet citation (section/page or the number).
3. SUGGESTIONS are CIRCUIT-DESIGN changes ONLY — edits the schematic-generation
   phase can apply to netlist/*.yaml or gen/*.py and then regenerate the board.
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
4. ITERATE (optional, HARD-capped at 3). If a clarification would be resolved
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
