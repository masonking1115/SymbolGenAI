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
