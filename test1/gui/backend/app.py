"""FastAPI backend for the test1 GUI.

Wraps the existing pipeline CLIs (gen_schematic.py, run_review.py) as
subprocesses and exposes them over HTTP. Streams stdout/stderr line-by-line
via Server-Sent Events so the React frontend can show a live console.

Endpoints
---------
GET  /api/health              — liveness
GET  /api/state               — snapshot: artifacts on disk, last run status
GET  /api/sheets              — list of sheet PNGs available under kicad/render/
GET  /api/png/{name}          — serve a sheet PNG by name (no extension)
GET  /api/lint                — parsed lint report from last gen run (cached)
GET  /api/findings            — parsed review findings (JSON + error_log.md)
GET  /api/library             — directory listing of Parts Library/<MPN>/
GET  /api/library/{mpn}       — metadata for one MPN (datasheet, symbol, fingerprint)
GET  /api/file?path=...       — read a project-relative file (text)
POST /api/file                — write a project-relative file (text)
POST /api/run/generate        — start gen_schematic.py (returns run_id)
POST /api/run/review          — start run_review.py (returns run_id)
POST /api/run/autofix         — start run_review.py --autofix --apply-trivial
GET  /api/run/{run_id}/stream — SSE stream of stdout/stderr lines
GET  /api/run/{run_id}        — poll run status (alternative to stream)

Subprocess invocation
---------------------
Each `/api/run/*` endpoint spawns a Python subprocess against the project
root, captures stdout+stderr, and tags every line with a monotonic run_id.
The runs registry is in-memory; restarting the server drops history. Concurrent
runs are allowed but discouraged — the underlying scripts assume serial use.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import agent as agent_mod


# ---------------------------------------------------------------------------
# Paths — server lives at test1/gui/backend, project root is test1/
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent  # test1/
KICAD_DIR = PROJECT_DIR / "kicad"
RENDER_DIR = KICAD_DIR / "render"
LIBRARY_DIR = PROJECT_DIR / "Parts Library"
NETLIST_DIR = PROJECT_DIR / "netlist"
GEN_SCRIPT = PROJECT_DIR / "gen_schematic.py"
REVIEW_SCRIPT = PROJECT_DIR / "run_review.py"
ERROR_LOG = PROJECT_DIR / "error_log.md"
FINDINGS_JSON = PROJECT_DIR / "review" / "findings.json"
SEMANTIC_FINDINGS = PROJECT_DIR / "review" / "semantic_findings.json"
DESIGN_REQS = PROJECT_DIR / "design_requirements.md"


# ---------------------------------------------------------------------------
# Run registry
# ---------------------------------------------------------------------------
@dataclass
class Run:
    run_id: str
    kind: str                          # "generate" | "review" | "autofix"
    cmd: list[str]
    status: str = "running"            # "running" | "ok" | "fail"
    returncode: int | None = None
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=5000))
    subscribers: list[asyncio.Queue] = field(default_factory=list)


_RUNS: dict[str, Run] = {}


async def _stream_subprocess(run: Run) -> None:
    """Spawn the subprocess and fan out its output lines."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # Force --no-reopen by default so the server doesn't try to script
    # eeschema on the host machine. Keep keystrokes scoped to the user.
    proc = await asyncio.create_subprocess_exec(
        *run.cmd,
        cwd=str(PROJECT_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    assert proc.stdout is not None
    while True:
        chunk = await proc.stdout.readline()
        if not chunk:
            break
        line = chunk.decode("utf-8", errors="replace").rstrip("\n")
        run.lines.append(line)
        # Fan out to all SSE subscribers, drop on slow consumers.
        for q in list(run.subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass
    run.returncode = await proc.wait()
    run.status = "ok" if run.returncode == 0 else "fail"
    # Sentinel to close all SSE streams
    for q in list(run.subscribers):
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass


async def _start_run(kind: str, cmd: list[str]) -> str:
    """Register a run and kick off its subprocess on the current event loop.

    MUST be called from an async endpoint — `asyncio.create_task` requires a
    running loop, and FastAPI routes only have one if the endpoint itself is
    `async def`. Sync endpoints execute in a worker thread with no loop.
    """
    run_id = uuid.uuid4().hex[:12]
    run = Run(run_id=run_id, kind=kind, cmd=cmd)
    _RUNS[run_id] = run
    asyncio.create_task(_stream_subprocess(run))
    return run_id


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="test1 GUI backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Health --------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "project": str(PROJECT_DIR)}


# ---- Snapshot ------------------------------------------------------------
@app.get("/api/state")
def state() -> dict:
    sheets = sorted(p.stem for p in RENDER_DIR.glob("*.png")) if RENDER_DIR.exists() else []
    return {
        "project_dir": str(PROJECT_DIR),
        "sheets": sheets,
        "has_error_log": ERROR_LOG.exists(),
        "has_findings_json": FINDINGS_JSON.exists(),
        "has_semantic": SEMANTIC_FINDINGS.exists(),
        "runs": [
            {"run_id": r.run_id, "kind": r.kind, "status": r.status,
             "returncode": r.returncode, "lines": len(r.lines)}
            for r in _RUNS.values()
        ],
    }


# ---- Freshness -----------------------------------------------------------
def _max_mtime(paths: list[Path]) -> tuple[float, Path | None]:
    """Return (max mtime, path) over the given files, or (0, None) if empty."""
    best = 0.0
    best_p: Path | None = None
    for p in paths:
        if p.is_file():
            m = p.stat().st_mtime
            if m > best:
                best, best_p = m, p
    return best, best_p


def _min_mtime(paths: list[Path]) -> tuple[float, Path | None]:
    """Return (min mtime, path) over the given files. None if any path missing."""
    if not paths:
        return 0.0, None
    worst = float("inf")
    worst_p: Path | None = None
    for p in paths:
        if not p.is_file():
            return 0.0, p  # missing artifact means stale by definition
        m = p.stat().st_mtime
        if m < worst:
            worst, worst_p = m, p
    return worst, worst_p


@app.get("/api/freshness")
def freshness() -> dict:
    """Is the on-disk schematic newer than the YAML netlists + generator code?

    Outputs are stale if:
      - any expected output is missing, OR
      - any input file has mtime > min(output mtimes).

    Inputs:  netlist/*.yaml, gen/*.py, Parts Library/**/*.kicad_sym
    Outputs: kicad/*.kicad_sch, kicad/render/*.png

    Returns: status (fresh|stale|never), reason, newest_input, oldest_output.
    """
    inputs: list[Path] = []
    if NETLIST_DIR.exists():
        inputs.extend(sorted(NETLIST_DIR.glob("*.yaml")))
    gen_dir = PROJECT_DIR / "gen"
    if gen_dir.exists():
        inputs.extend(sorted(gen_dir.glob("*.py")))
    if LIBRARY_DIR.exists():
        inputs.extend(sorted(LIBRARY_DIR.glob("*/*.kicad_sym")))
    inputs.append(PROJECT_DIR / "gen_schematic.py")

    outputs: list[Path] = []
    if KICAD_DIR.exists():
        outputs.extend(sorted(KICAD_DIR.glob("*.kicad_sch")))
    if RENDER_DIR.exists():
        outputs.extend(sorted(RENDER_DIR.glob("*.png")))

    if not outputs or not any(p.is_file() for p in outputs):
        return {
            "status": "never",
            "reason": "No schematic artifacts on disk yet — run generator.",
            "newest_input": None,
            "oldest_output": None,
        }

    newest_in, newest_in_p = _max_mtime(inputs)
    oldest_out, oldest_out_p = _min_mtime(outputs)

    fresh = oldest_out >= newest_in and oldest_out > 0
    if fresh:
        return {
            "status": "fresh",
            "reason": "All outputs are newer than every input.",
            "newest_input": _stamp(newest_in_p, newest_in),
            "oldest_output": _stamp(oldest_out_p, oldest_out),
        }
    if oldest_out == 0 and oldest_out_p is not None:
        return {
            "status": "stale",
            "reason": f"Missing expected output: {oldest_out_p.relative_to(PROJECT_DIR)}",
            "newest_input": _stamp(newest_in_p, newest_in),
            "oldest_output": None,
        }
    return {
        "status": "stale",
        "reason": (
            f"Input {newest_in_p.relative_to(PROJECT_DIR) if newest_in_p else '?'}"
            f" is newer than oldest output"
            f" {oldest_out_p.relative_to(PROJECT_DIR) if oldest_out_p else '?'}."
        ),
        "newest_input": _stamp(newest_in_p, newest_in),
        "oldest_output": _stamp(oldest_out_p, oldest_out),
    }


def _stamp(p: Path | None, mtime: float) -> dict | None:
    if p is None:
        return None
    return {
        "path": str(p.relative_to(PROJECT_DIR)) if PROJECT_DIR in p.parents else str(p),
        "mtime": mtime,
    }


# ---- Sheet PNGs ----------------------------------------------------------
@app.get("/api/sheets")
def sheets() -> dict:
    if not RENDER_DIR.exists():
        return {"sheets": []}
    out = []
    for p in sorted(RENDER_DIR.glob("*.png")):
        st = p.stat()
        out.append({"name": p.stem, "size": st.st_size, "mtime": st.st_mtime})
    return {"sheets": out}


@app.get("/api/png/{name}")
def png(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        raise HTTPException(400, "bad name")
    p = RENDER_DIR / f"{name}.png"
    if not p.exists():
        raise HTTPException(404, "no such sheet")
    # No-cache so the frontend always sees the latest render after a regen.
    return FileResponse(p, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


# ---- Lint report ---------------------------------------------------------
_LINT_LINE = re.compile(
    r"^\s*\[(?P<sheet>[^\]]+)\]\s+(?P<sev>ERROR|WARNING|INFO)\s+"
    r"(?P<rule>\S+)\s+(?P<msg>.+?)(?:\s+\((?P<refs>[^)]*)\))?\s*$"
)


def _parse_lint_from_lines(lines: list[str]) -> list[dict]:
    """Pull layout-lint rows out of a gen_schematic.py run.

    The lint printer (gen/layout_lint.py print_report) prefixes each issue
    with the sheet name in brackets. Anything that doesn't match is dropped.
    """
    out = []
    for line in lines:
        m = _LINT_LINE.match(line)
        if not m:
            continue
        out.append({
            "sheet": m.group("sheet"),
            "severity": m.group("sev"),
            "rule": m.group("rule"),
            "message": m.group("msg").strip(),
            "refs": [r.strip() for r in (m.group("refs") or "").split(",") if r.strip()],
        })
    return out


@app.get("/api/lint")
def lint(run_id: str | None = None) -> dict:
    """Return lint issues parsed from the most recent (or named) generate run.

    Also returns the static set of rule IDs the linter checks for, so the
    frontend can render the full checklist (pass/fail per rule) even when
    nothing fired.
    """
    target: Run | None = None
    if run_id and run_id in _RUNS:
        target = _RUNS[run_id]
    else:
        for r in reversed(list(_RUNS.values())):
            if r.kind == "generate":
                target = r
                break
    issues = _parse_lint_from_lines(list(target.lines)) if target else []
    # Authoritative list of rule IDs from gen/layout_lint.py. Keep in sync if
    # new rules are added there. Source of truth is the linter module itself.
    rules = [
        {"id": "bbox_overlap", "summary": "Components overlap"},
        {"id": "bbox_too_close", "summary": "Components closer than 2.54 mm"},
        {"id": "refval_on_body", "summary": "Reference/value label collides with body"},
        {"id": "label_on_body", "summary": "Net label sits on top of a component body"},
        {"id": "diagonal_wire", "summary": "Wire is not strictly H or V"},
        {"id": "wire_through_body", "summary": "Wire crosses a part body"},
        {"id": "duplicate_wire", "summary": "Two wires occupy the same segment"},
        {"id": "redundant_junction", "summary": "Junction marker is redundant"},
        {"id": "dense_gnd_cluster", "summary": "GND symbols clustered tightly"},
    ]
    return {
        "run_id": target.run_id if target else None,
        "status": target.status if target else "unknown",
        "issues": issues,
        "rules": rules,
        "counts": {
            "ERROR": sum(1 for i in issues if i["severity"] == "ERROR"),
            "WARNING": sum(1 for i in issues if i["severity"] == "WARNING"),
            "INFO": sum(1 for i in issues if i["severity"] == "INFO"),
        },
    }


# ---- Review findings -----------------------------------------------------
@app.get("/api/findings")
def findings() -> dict:
    """Return review findings — preferring findings.json if present, falling
    back to a parsed error_log.md summary."""
    if FINDINGS_JSON.exists():
        try:
            data = json.loads(FINDINGS_JSON.read_text())
        except json.JSONDecodeError:
            data = []
    else:
        data = []
    semantic: list = []
    if SEMANTIC_FINDINGS.exists():
        try:
            semantic = json.loads(SEMANTIC_FINDINGS.read_text())
        except json.JSONDecodeError:
            semantic = []
    summary = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for f in data:
        sev = (f.get("severity") or "").upper()
        if sev in summary:
            summary[sev] += 1
    return {
        "findings": data,
        "semantic": semantic,
        "summary": summary,
        "error_log_exists": ERROR_LOG.exists(),
    }


@app.get("/api/error-log")
def error_log() -> dict:
    if not ERROR_LOG.exists():
        return {"content": "", "exists": False}
    return {"content": ERROR_LOG.read_text(), "exists": True}


# ---- Parts Library -------------------------------------------------------
@app.get("/api/library")
def library() -> dict:
    """List parts present in test1/Parts Library/.

    Each MPN directory typically contains a datasheet PDF and a fingerprint
    .json (when populated). A KiCad symbol file under test1/Parts Library/
    Bobcat/Bobcat.kicad_sym contains every project symbol — we just check
    whether the part's symbol exists by name in that library.
    """
    parts: list[dict] = []
    symbols_index = _load_symbol_index()
    if LIBRARY_DIR.exists():
        for d in sorted(LIBRARY_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            datasheets = sorted(d.glob("*.pdf"))
            fingerprint = (d / "fingerprint.json")
            parts.append({
                "mpn": d.name,
                "has_datasheet": bool(datasheets),
                "datasheet": datasheets[0].name if datasheets else None,
                "has_fingerprint": fingerprint.exists(),
                "has_symbol": d.name in symbols_index,
            })
    return {"parts": parts}


def _load_symbol_index() -> set[str]:
    """Return the set of MPNs (directory names) that have at least one
    top-level symbol defined in their per-MPN .kicad_sym file."""
    if not LIBRARY_DIR.exists():
        return set()
    out: set[str] = set()
    for d in LIBRARY_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if _primary_symbol_for(d.name) is not None:
            out.add(d.name)
    return out


def _top_level_symbol_names(text: str) -> list[str]:
    """Return the symbol names declared in a .kicad_sym file, dropping
    KiCad's internal `<name>_<unit>_<bodystyle>` aliases."""
    out: list[str] = []
    for name in re.findall(r'\(symbol\s+"([^"]+)"', text):
        if re.search(r'_\d+_\d+$', name):
            continue
        out.append(name)
    return out


def _primary_symbol_for(mpn: str) -> tuple[Path, str] | None:
    """Return (sym_file, actual_symbol_name) for an MPN, or None.

    Convention: each MPN directory contains <MPN>/<MPN>.kicad_sym, but the
    actual symbol *inside* the file is not guaranteed to be named exactly
    <MPN> — vendors ship things like `OPA2388IDR` or `MCP4728-E_UN`. We
    pick the first top-level symbol in the matching file.
    """
    direct = LIBRARY_DIR / mpn / f"{mpn}.kicad_sym"
    candidates: list[Path] = []
    if direct.exists():
        candidates.append(direct)
    # Fall back: any kicad_sym file in the MPN's directory.
    candidates.extend(sorted((LIBRARY_DIR / mpn).glob("*.kicad_sym")))
    seen: set[Path] = set()
    for f in candidates:
        if f in seen:
            continue
        seen.add(f)
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        names = _top_level_symbol_names(text)
        if names:
            return f, names[0]
    return None


def _symbol_file_for(mpn: str) -> Path | None:
    found = _primary_symbol_for(mpn)
    return found[0] if found else None


@app.get("/api/library/{mpn}")
def library_item(mpn: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", mpn):
        raise HTTPException(400, "bad mpn")
    d = LIBRARY_DIR / mpn
    if not d.exists() or not d.is_dir():
        raise HTTPException(404, "no such part")
    datasheets = [p.name for p in sorted(d.glob("*.pdf"))]
    notes = [p.name for p in sorted(d.glob("*.md"))]
    fingerprint: dict | None = None
    fp = d / "fingerprint.json"
    if fp.exists():
        try:
            fingerprint = json.loads(fp.read_text())
        except json.JSONDecodeError:
            fingerprint = None
    return {
        "mpn": mpn,
        "datasheets": datasheets,
        "notes": notes,
        "fingerprint": fingerprint,
        "has_symbol": mpn in _load_symbol_index(),
    }


# --- Symbol parser + renderer ----------------------------------------------
KICAD_CLI = "/Users/masonking/Downloads/kicad/build/kicad/KiCad.app/Contents/MacOS/kicad-cli"
SYM_CACHE = HERE.parent / "state" / "symbol-cache"


_SYM_BLOCK_RE = re.compile(
    r'\(symbol\s+"(?P<name>[^"]+)"(?P<body>.*?)(?=\n\s*\(symbol\s+"|\Z)',
    re.S,
)
_PROP_RE = re.compile(
    r'\(property\s+"(?P<key>[^"]+)"\s+"(?P<val>[^"]*)"', re.S
)
_PIN_RE = re.compile(
    r'\(pin\s+(?P<etype>\S+)\s+\S+\s+\(at\s+(?P<x>[-\d\.]+)\s+(?P<y>[-\d\.]+)\s+(?P<rot>[\d\.]+)\)'
    r'.*?\(name\s+"(?P<name>[^"]*)"'
    r'.*?\(number\s+"(?P<num>[^"]*)"',
    re.S,
)
_UNIT_NAME_RE = re.compile(r'"([^"]+_\d+_\d+)"')


def _find_symbol_block(mpn: str) -> tuple[str, str] | None:
    """Return (s-expr body, actual_symbol_name) for the symbol inside the
    MPN's library file. The actual name may differ from the MPN."""
    found = _primary_symbol_for(mpn)
    if found is None:
        return None
    sym_file, actual_name = found
    text = sym_file.read_text(errors="replace")
    needle = f'(symbol "{actual_name}"'
    i = text.find(needle)
    if i < 0:
        return None
    # Find matching close paren for the (symbol ...) block.
    depth = 0
    end = i
    while end < len(text):
        c = text[end]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end += 1
                break
        end += 1
    return text[i:end], actual_name


def _parse_symbol(mpn: str) -> dict | None:
    found = _find_symbol_block(mpn)
    if found is None:
        return None
    block, actual_name = found
    props: dict[str, str] = {}
    for m in _PROP_RE.finditer(block):
        props[m.group("key")] = m.group("val")
    pins: list[dict] = []
    for m in _PIN_RE.finditer(block):
        pins.append({
            "number": m.group("num"),
            "name": m.group("name") or "~",
            "etype": m.group("etype"),
            "x": float(m.group("x")),
            "y": float(m.group("y")),
            "rotation": int(float(m.group("rot"))),
        })
    pins.sort(key=lambda p: (
        0 if p["x"] < 0 else 1 if p["x"] > 0 else 2,
        int(p["number"]) if p["number"].isdigit() else 9999,
    ))
    units = sorted(set(_UNIT_NAME_RE.findall(block)))
    return {
        "name": actual_name,
        "mpn": mpn,
        "properties": props,
        "pins": pins,
        "pin_count": len(pins),
        "unit_names": units,
    }


def _render_symbol_svg(mpn: str) -> tuple[Path, str]:
    """Run kicad-cli to export the symbol as SVG. Cached on disk; cache is
    invalidated whenever the source library file's mtime increases.

    Returns (cache_dir, actual_symbol_name). SVG files are named
    <actual_symbol_name>_unitN.svg by kicad-cli, NOT the MPN.
    """
    found = _primary_symbol_for(mpn)
    if found is None:
        raise HTTPException(404, f"no symbol for {mpn}")
    sym_file, actual_name = found
    cache_dir = SYM_CACHE / mpn
    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp = cache_dir / ".source-mtime"
    src_mtime = sym_file.stat().st_mtime
    cached_mtime = float(stamp.read_text()) if stamp.exists() else -1.0
    expected = cache_dir / f"{actual_name}_unit1.svg"
    if expected.exists() and cached_mtime >= src_mtime:
        return cache_dir, actual_name
    proc = subprocess.run(
        [KICAD_CLI, "sym", "export", "svg",
         "--symbol", actual_name,
         "--output", str(cache_dir),
         str(sym_file)],
        capture_output=True, text=True, timeout=20,
    )
    if proc.returncode != 0:
        raise HTTPException(500, f"kicad-cli failed: {proc.stderr.strip() or proc.stdout.strip()}")
    stamp.write_text(str(src_mtime))
    return cache_dir, actual_name


@app.get("/api/library/{mpn}/symbol")
def library_symbol(mpn: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", mpn):
        raise HTTPException(400, "bad mpn")
    parsed = _parse_symbol(mpn)
    if parsed is None:
        return {"present": False, "mpn": mpn}
    try:
        cache, actual_name = _render_symbol_svg(mpn)
        units = sorted(p.name for p in cache.glob(f"{actual_name}_unit*.svg"))
    except HTTPException as e:
        units = []
        parsed["render_error"] = e.detail
    return {"present": True, **parsed, "svg_units": units}


@app.get("/api/library/{mpn}/symbol/svg/{unit}")
def library_symbol_svg(mpn: str, unit: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", mpn):
        raise HTTPException(400, "bad mpn")
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+\.svg", unit):
        raise HTTPException(400, "bad unit")
    cache, _ = _render_symbol_svg(mpn)
    p = cache / unit
    if not p.exists():
        raise HTTPException(404, "no such unit svg")
    return FileResponse(p, media_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/library/{mpn}/datasheet")
def library_datasheet(mpn: str, name: str | None = None):
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", mpn):
        raise HTTPException(400, "bad mpn")
    d = LIBRARY_DIR / mpn
    if not d.exists():
        raise HTTPException(404, "no such part")
    if name:
        if "/" in name or ".." in name:
            raise HTTPException(400, "bad name")
        target = d / name
    else:
        pdfs = sorted(d.glob("*.pdf"))
        if not pdfs:
            raise HTTPException(404, "no datasheet")
        target = pdfs[0]
    if not target.exists():
        raise HTTPException(404, "no such file")
    return FileResponse(target, media_type="application/pdf")


# ---- File read/write (project-relative) ---------------------------------
_ALLOWED_PREFIXES = (
    "netlist/",
    "design_requirements.md",
    "Voltai_Notes.md",
    "error_log.md",
    "review/semantic_findings.json",
)


def _resolve_under_project(rel: str) -> Path:
    if ".." in Path(rel).parts:
        raise HTTPException(400, "no parent refs")
    if not any(rel == p or rel.startswith(p) for p in _ALLOWED_PREFIXES):
        raise HTTPException(403, f"path not in allow-list: {rel}")
    p = (PROJECT_DIR / rel).resolve()
    if PROJECT_DIR.resolve() not in p.parents and p != PROJECT_DIR.resolve():
        raise HTTPException(400, "outside project")
    return p


class FileWrite(BaseModel):
    path: str
    content: str


@app.get("/api/file")
def file_read(path: str = Query(...)) -> dict:
    p = _resolve_under_project(path)
    if not p.exists():
        return {"path": path, "exists": False, "content": ""}
    return {"path": path, "exists": True, "content": p.read_text()}


@app.post("/api/file")
def file_write(payload: FileWrite) -> dict:
    p = _resolve_under_project(payload.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(payload.content)
    return {"ok": True, "path": payload.path, "bytes": len(payload.content)}


@app.get("/api/netlist")
def netlist_list() -> dict:
    if not NETLIST_DIR.exists():
        return {"files": []}
    return {"files": sorted(p.name for p in NETLIST_DIR.glob("*.yaml"))}


# ---- Run launchers -------------------------------------------------------
class GenerateOpts(BaseModel):
    no_reopen: bool = True


class ReviewOpts(BaseModel):
    no_semantic: bool = True
    autofix: bool = False
    apply_trivial: bool = False


@app.post("/api/run/generate")
async def run_generate(opts: GenerateOpts = GenerateOpts()) -> dict:
    if not GEN_SCRIPT.exists():
        raise HTTPException(500, "gen_schematic.py missing")
    cmd = [sys.executable, str(GEN_SCRIPT)]
    if opts.no_reopen:
        cmd.append("--no-reopen")
    return {"run_id": await _start_run("generate", cmd)}


@app.post("/api/run/review")
async def run_review(opts: ReviewOpts = ReviewOpts()) -> dict:
    if not REVIEW_SCRIPT.exists():
        raise HTTPException(500, "run_review.py missing")
    cmd = [sys.executable, str(REVIEW_SCRIPT),
           "--json", str(FINDINGS_JSON)]
    if opts.no_semantic:
        cmd.append("--no-semantic")
    if opts.autofix:
        cmd.append("--autofix")
        cmd.append("--non-interactive")
        if opts.apply_trivial:
            cmd.append("--apply-trivial")
    return {"run_id": await _start_run("review", cmd)}


@app.post("/api/run/autofix")
async def run_autofix() -> dict:
    """Convenience: review + autofix-trivial in one call."""
    if not REVIEW_SCRIPT.exists():
        raise HTTPException(500, "run_review.py missing")
    cmd = [sys.executable, str(REVIEW_SCRIPT),
           "--no-semantic",
           "--json", str(FINDINGS_JSON),
           "--autofix", "--apply-trivial", "--non-interactive"]
    return {"run_id": await _start_run("autofix", cmd)}


# NOTE: static "/api/run/latest" must be registered BEFORE the dynamic
# "/api/run/{run_id}" route — FastAPI matches in declaration order.
@app.get("/api/run/latest")
def run_latest_alias(kind: str = Query("generate")) -> dict:
    return run_latest(kind)


@app.get("/api/run/{run_id}")
def run_status(run_id: str) -> dict:
    r = _RUNS.get(run_id)
    if not r:
        raise HTTPException(404, "no such run")
    return {
        "run_id": r.run_id,
        "kind": r.kind,
        "status": r.status,
        "returncode": r.returncode,
        "cmd": r.cmd,
        "lines": list(r.lines),
    }


@app.get("/api/run/{run_id}/stream")
async def run_stream(run_id: str) -> StreamingResponse:
    r = _RUNS.get(run_id)
    if not r:
        raise HTTPException(404, "no such run")

    async def gen() -> AsyncIterator[bytes]:
        # First, replay anything already buffered.
        for line in list(r.lines):
            yield f"data: {json.dumps({'line': line})}\n\n".encode()
        # Then attach a subscriber queue for new lines.
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        r.subscribers.append(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    # Send a final status frame, then close.
                    yield (f"event: done\ndata: "
                           f"{json.dumps({'status': r.status, 'rc': r.returncode})}"
                           f"\n\n").encode()
                    break
                yield f"data: {json.dumps({'line': item})}\n\n".encode()
        finally:
            try:
                r.subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


# ---- Misc ----------------------------------------------------------------
@app.get("/api/requirements")
def requirements() -> dict:
    if not DESIGN_REQS.exists():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": DESIGN_REQS.read_text()}


# ---- Latest run summary (for stale-UI recovery) ---------------------------
_SHEET_LINE = re.compile(
    r"wrote\s+(?P<sheet>\S+\.kicad_sch)(?:\s+—\s+lint:\s+(?P<lint>.+))?"
)
_PHASE_KEYWORDS = [
    ("Phase 1", "loading"),
    ("Phase 2a", "deterministic-rules"),
    ("Phase 2b", "semantic-review"),
    ("Phase 3", "rendering"),
    ("Phase 4", "autofix"),
    ("kicad-cli", "kicad-cli"),
    ("Validation failed", "validate"),
]


def _classify_lines(lines: list[str]) -> list[dict]:
    """Walk a run's stdout and emit one structured event per significant line.

    Used by the GUI to render the details dropdown without having to teach
    the frontend about every script's print format.
    """
    out: list[dict] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("==="):
            out.append({"kind": "header", "text": s.strip("= ")})
            continue
        m = _SHEET_LINE.search(line)
        if m:
            out.append({
                "kind": "sheet",
                "sheet": m.group("sheet"),
                "lint": m.group("lint") or "",
                "text": s,
            })
            continue
        if "Traceback" in s or "ValidationError" in s or s.lower().startswith("error"):
            out.append({"kind": "error", "text": s})
            continue
        for needle, phase in _PHASE_KEYWORDS:
            if needle in s:
                out.append({"kind": "phase", "phase": phase, "text": s})
                break
        else:
            if s.startswith("[") and " " in s:
                out.append({"kind": "lint", "text": s})
            elif s.startswith(("tool:", "assistant:", "result:")):
                out.append({"kind": "agent", "text": s})
            else:
                out.append({"kind": "log", "text": s})
    return out


def run_latest(kind: str = "generate") -> dict:
    """Find the most recent run of `kind` and return its parsed phases.

    The frontend hits this on mount so a reload-mid-pipeline recovers
    the correct stepper position instead of staying stuck on whatever
    the in-memory state was.
    """
    target = None
    for r in reversed(list(_RUNS.values())):
        if r.kind == kind:
            target = r
            break
    if target is None:
        return {"present": False}
    return {
        "present": True,
        "run_id": target.run_id,
        "kind": target.kind,
        "status": target.status,
        "returncode": target.returncode,
        "phases": _classify_lines(list(target.lines)),
        "raw_tail": list(target.lines)[-30:],
    }


@app.get("/api/run/{run_id}/phases")
def run_phases(run_id: str) -> dict:
    r = _RUNS.get(run_id)
    if not r:
        raise HTTPException(404, "no such run")
    return {
        "run_id": r.run_id,
        "kind": r.kind,
        "status": r.status,
        "returncode": r.returncode,
        "phases": _classify_lines(list(r.lines)),
    }


# ---- Agent: chat + changelog + apply --------------------------------------
class ChatMessage(BaseModel):
    content: str


class ChangelogAdd(BaseModel):
    summary: str


@app.get("/api/chat/history")
def chat_history() -> dict:
    return {"messages": agent_mod.load_chat()}


@app.post("/api/chat/clear")
def chat_clear() -> dict:
    agent_mod.save_chat([])
    return {"ok": True}


@app.post("/api/chat")
async def chat_send(msg: ChatMessage) -> dict:
    """Send a user turn. The agent runs as a subprocess and may append
    bullets to the changelog. Frontend subscribes to /api/agent/{run_id}/stream
    to watch the response stream in."""
    content = msg.content.strip()
    if not content:
        raise HTTPException(400, "empty message")
    run = await agent_mod.start_chat_turn(content)
    return {"run_id": run.run_id, "kind": run.kind}


@app.get("/api/agent/{run_id}")
def agent_status(run_id: str) -> dict:
    run = agent_mod.get_run(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    return {
        "run_id": run.run_id,
        "kind": run.kind,
        "status": run.status,
        "returncode": run.returncode,
        "text": run.text,
    }


@app.get("/api/agent/{run_id}/stream")
async def agent_stream(run_id: str) -> StreamingResponse:
    if not agent_mod.get_run(run_id):
        raise HTTPException(404, "no such run")
    return StreamingResponse(
        agent_mod.stream_run(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/api/changelog")
def changelog_get() -> dict:
    return {"items": agent_mod.load_changelog()}


@app.post("/api/changelog")
def changelog_add(item: ChangelogAdd) -> dict:
    if not item.summary.strip():
        raise HTTPException(400, "empty summary")
    return agent_mod.append_changelog(item.summary, source="user")


@app.delete("/api/changelog/{item_id}")
def changelog_delete(item_id: str) -> dict:
    if not agent_mod.remove_changelog(item_id):
        raise HTTPException(404, "no such item")
    return {"ok": True}


@app.post("/api/changelog/clear")
def changelog_clear() -> dict:
    agent_mod.clear_changelog()
    return {"ok": True}


# ---- Generate with changelog-apply ----------------------------------------
class ApplyAndGenOpts(BaseModel):
    no_reopen: bool = True


@app.post("/api/run/apply-and-generate")
async def run_apply_and_generate(opts: ApplyAndGenOpts = ApplyAndGenOpts()) -> dict:
    """Three-stage pipeline:

      1. Spawn the agent in apply mode to implement queued changelog items.
      2. Wait for it to finish.
      3. Spawn gen_schematic.py via the existing run-registry path.

    The frontend tracks stage 1 via /api/agent/{run_id}/stream and stage 3
    via /api/run/{run_id}/stream. Both ids are returned up front.
    """
    if not GEN_SCRIPT.exists():
        raise HTTPException(500, "gen_schematic.py missing")

    items = agent_mod.load_changelog()
    apply_run_id: str | None = None
    if items:
        apply_run = await agent_mod.start_apply_pass()
        apply_run_id = apply_run.run_id

    async def chained() -> str:
        # If there's an apply run in flight, wait for it.
        if apply_run_id:
            ar = agent_mod.get_run(apply_run_id)
            assert ar is not None
            while ar.status == "running":
                await asyncio.sleep(0.25)
        # Now start the generate subprocess via the existing helper.
        cmd = [sys.executable, str(GEN_SCRIPT)]
        if opts.no_reopen:
            cmd.append("--no-reopen")
        return await _start_run("generate", cmd)

    generate_run_id = await chained()
    return {
        "apply_run_id": apply_run_id,
        "generate_run_id": generate_run_id,
        "queued_items": len(items),
    }


# ---- Symbol generation subagent -------------------------------------------
@app.post("/api/library/{mpn}/generate-symbol")
async def library_generate_symbol(mpn: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", mpn):
        raise HTTPException(400, "bad mpn")
    d = LIBRARY_DIR / mpn
    if not d.exists():
        raise HTTPException(404, "no such part")
    pdfs = sorted(d.glob("*.pdf"))
    if not pdfs:
        raise HTTPException(400, "no datasheet PDF in this part's folder")
    run = await agent_mod.start_symbol_gen(mpn, pdfs[0].name)
    return {"run_id": run.run_id, "datasheet": pdfs[0].name}


def main() -> None:
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
