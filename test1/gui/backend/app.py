"""FastAPI backend for the test1 GUI.

Drives the Altium pipeline (`python -m test1.altium.build_project`, run_review.py)
as subprocesses and exposes them over HTTP. Streams stdout/stderr line-by-line
via Server-Sent Events so the React frontend can show a live console. (The
original KiCad pipeline is still selectable via SCHEMA_BACKEND=kicad.)

Endpoints
---------
GET  /api/health              — liveness
GET  /api/state               — snapshot: artifacts on disk, last run status
GET  /api/sheets              — list of rendered sheets (altium/out/render/*.svg)
GET  /api/png/{name}          — serve a sheet render by name (no extension)
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
import base64
import mimetypes
import subprocess
import sys
import time
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
REPO_ROOT = PROJECT_DIR.parent    # SymbolGenAI/ — cwd for `-m test1.altium...`

# Backend selector. The original GUI drove the KiCad pipeline (gen_schematic.py
# + kicad-cli renders). On this machine we drive the Altium backend
# (test1/altium/build_project.py), which renders SVGs and runs on Windows.
# Override with SCHEMA_BACKEND=kicad to restore the original behaviour.
BACKEND = os.environ.get("SCHEMA_BACKEND", "altium").lower()

KICAD_DIR = PROJECT_DIR / "kicad"
ALTIUM_OUT = PROJECT_DIR / "altium" / "out"
if BACKEND == "altium":
    RENDER_DIR = ALTIUM_OUT / "render"
    RENDER_EXT = "svg"
    RENDER_MEDIA = "image/svg+xml"
else:
    RENDER_DIR = KICAD_DIR / "render"
    RENDER_EXT = "png"
    RENDER_MEDIA = "image/png"
LIBRARY_DIR = PROJECT_DIR / "Parts Library"
NETLIST_DIR = PROJECT_DIR / "netlist"
GEN_SCRIPT = PROJECT_DIR / "gen_schematic.py"
REVIEW_SCRIPT = PROJECT_DIR / "run_review.py"
ERROR_LOG = PROJECT_DIR / "error_log.md"
FINDINGS_JSON = PROJECT_DIR / "review" / "findings.json"
SEMANTIC_FINDINGS = PROJECT_DIR / "review" / "semantic_findings.json"
# Fix queue: Apply-fix actions from the Review tab land here for the agent
# (in chat) to pick up, sanity-check, and execute. Survives backend restarts.
FIX_QUEUE_JSON = PROJECT_DIR / "review" / "fix_queue.json"
DESIGN_REQS = PROJECT_DIR / "design_requirements.md"
RESOURCES_DIR = PROJECT_DIR / "resources"
REQ_DOCS_DIR = RESOURCES_DIR / "requirements"   # uploaded requirement source docs
SKILLS_DIR = RESOURCES_DIR / "skills"           # agent skills (md), used by chat later

# Make the sim package importable as `test1.sim` (repo root on path).
sys.path.insert(0, str(PROJECT_DIR.parent))
from test1.sim import service as sim_service  # noqa: E402
from test1.sim import simconfig as sim_config  # noqa: E402
from test1.altium import symlib as symlib  # noqa: E402  — native Altium symbols


# ---------------------------------------------------------------------------
# Run registry
# ---------------------------------------------------------------------------
@dataclass
class Run:
    run_id: str
    kind: str                          # "generate" | "review" | "autofix"
    cmd: list[str]
    cwd: str | None = None             # subprocess cwd (default PROJECT_DIR)
    status: str = "running"            # "running" | "ok" | "fail"
    returncode: int | None = None
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=5000))
    subscribers: list[asyncio.Queue] = field(default_factory=list)


_RUNS: dict[str, Run] = {}


async def _stream_subprocess(run: Run) -> None:
    """Spawn the subprocess and fan out its output lines."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # Force UTF-8 for the child's stdout/stderr. Without this, Windows defaults
    # to cp1252 and the build crashes with UnicodeEncodeError the moment it
    # prints a non-ASCII glyph (e.g. the '->' arrows / 'Ω' / '²' in sheet
    # annotations), surfacing as a spurious build_failed ERROR in the lint.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Force --no-reopen by default so the server doesn't try to script
    # eeschema on the host machine. Keep keystrokes scoped to the user.
    proc = await asyncio.create_subprocess_exec(
        *run.cmd,
        cwd=run.cwd or str(PROJECT_DIR),
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


async def _start_run(kind: str, cmd: list[str], cwd: str | None = None) -> str:
    """Register a run and kick off its subprocess on the current event loop.

    MUST be called from an async endpoint — `asyncio.create_task` requires a
    running loop, and FastAPI routes only have one if the endpoint itself is
    `async def`. Sync endpoints execute in a worker thread with no loop.
    """
    run_id = uuid.uuid4().hex[:12]
    run = Run(run_id=run_id, kind=kind, cmd=cmd, cwd=cwd)
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
def state() -> JSONResponse:
    sheets = sorted(p.stem for p in RENDER_DIR.glob(f"*.{RENDER_EXT}")) if RENDER_DIR.exists() else []
    body = {
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
        "timestamp": time.time(),
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


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

    Inputs:  netlist/*.yaml, altium/*.py (+ gen/*.py core), Parts Library/**/*.SchLib
    Outputs (Altium backend): altium/out/*.SchDoc, altium/out/render/*.svg
             (KiCad fallback, SCHEMA_BACKEND=kicad: kicad/*.kicad_sch + *.png)

    Returns: status (fresh|stale|never), reason, newest_input, oldest_output.
    """
    inputs: list[Path] = []
    if NETLIST_DIR.exists():
        inputs.extend(sorted(NETLIST_DIR.glob("*.yaml")))
    gen_dir = PROJECT_DIR / "gen"
    if gen_dir.exists():
        inputs.extend(sorted(gen_dir.glob("*.py")))
    if LIBRARY_DIR.exists():
        inputs.extend(sorted(LIBRARY_DIR.glob("*/*.SchLib")))

    outputs: list[Path] = []
    if BACKEND == "altium":
        alt_dir = PROJECT_DIR / "altium"
        if alt_dir.exists():
            inputs.extend(sorted(alt_dir.glob("*.py")))
        if ALTIUM_OUT.exists():
            outputs.extend(sorted(ALTIUM_OUT.glob("*.SchDoc")))
        if RENDER_DIR.exists():
            outputs.extend(sorted(RENDER_DIR.glob(f"*.{RENDER_EXT}")))
    else:
        inputs.append(PROJECT_DIR / "gen_schematic.py")
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


# ---- Refresh/Cache-Bust --------------------------------------------------
@app.post("/api/refresh")
def refresh() -> JSONResponse:
    """Explicitly refresh all cached data from disk (schematic, lint, sheets, findings).

    The frontend calls this when the user clicks a refresh button or when
    switching back to the GUI after making changes in this chat. Returns
    the fresh state so the frontend doesn't need to poll multiple endpoints.
    """
    # Force re-read of all data from disk
    lint_resp = lint()
    sheets_resp = sheets()
    findings_resp = findings()

    # Extract bodies from JSONResponse objects and parse them
    lint_body = json.loads(lint_resp.body) if hasattr(lint_resp, 'body') else {}
    sheets_body = json.loads(sheets_resp.body) if hasattr(sheets_resp, 'body') else {}
    findings_body = json.loads(findings_resp.body) if hasattr(findings_resp, 'body') else {}

    # Return combined state so frontend gets everything in one call
    return JSONResponse({
        "ok": True,
        "timestamp": time.time(),
        "lint": lint_body,
        "sheets": sheets_body,
        "findings": findings_body,
    }, headers={"Cache-Control": "no-store"})


# ---- Sheet PNGs ----------------------------------------------------------
@app.get("/api/sheets")
def sheets() -> JSONResponse:
    if not RENDER_DIR.exists():
        body = {"sheets": [], "timestamp": time.time()}
        return JSONResponse(body, headers={"Cache-Control": "no-store"})
    out = []
    for p in sorted(RENDER_DIR.glob(f"*.{RENDER_EXT}")):
        st = p.stat()
        out.append({"name": p.stem, "size": st.st_size, "mtime": st.st_mtime})
    body = {"sheets": out, "timestamp": time.time()}
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/api/png/{name}")
def png(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        raise HTTPException(400, "bad name")
    # Serves the render in the active backend's format (PNG for KiCad, SVG for
    # Altium). Browsers render SVG fine inside the frontend's <img>.
    p = RENDER_DIR / f"{name}.{RENDER_EXT}"
    if not p.exists():
        raise HTTPException(404, "no such sheet")
    # No-cache so the frontend always sees the latest render after a regen.
    return FileResponse(p, media_type=RENDER_MEDIA,
                        headers={"Cache-Control": "no-store"})


# ---- Lint report ---------------------------------------------------------
_LINT_LINE = re.compile(
    r"^\s*\[(?P<sheet>[^\]]+)\]\s+(?P<sev>ERROR|WARNING|INFO)\s+"
    r"(?P<rule>\S+)\s+(?P<msg>.+?)(?:\s+\((?P<refs>[^)]*)\))?\s*$"
)

# Altium build_project format: a per-sheet table row sets the "current sheet",
# then each issue is an indented detail line "- SEVERITY rule msg (refs)".
_LINT_SHEET_ROW = re.compile(
    r"^(?P<sheet>[A-Za-z]\w*)\s+(?:A\d|-)\s+\d+/\d+/\d+\s+\S")
_LINT_DETAIL = re.compile(
    r"^\s*(?:-\s+)?(?P<sev>ERROR|WARNING|INFO)\s+(?P<rule>\S+)\s+"
    r"(?P<msg>.+?)(?:\s+\((?P<refs>[^)]*)\))?\s*$")


def _parse_lint_from_lines(lines: list[str]) -> list[dict]:
    """Pull layout-lint rows out of a gen_schematic.py run.

    The lint printer (gen/layout_lint.py print_report) prefixes each issue
    with the sheet name in brackets. Anything that doesn't match is dropped.
    """
    out = []
    cur_sheet = "?"
    for line in lines:
        # Legacy KiCad gen format: "[sheet] SEVERITY rule msg".
        m = _LINT_LINE.match(line)
        if m:
            out.append({
                "sheet": m.group("sheet"), "severity": m.group("sev"),
                "rule": m.group("rule"), "message": m.group("msg").strip(),
                "refs": [r.strip() for r in (m.group("refs") or "").split(",") if r.strip()],
            })
            continue
        # Altium build_project format: track current sheet from the table row,
        # attach each indented detail line to it.
        if line.strip().lower().startswith("symbol library"):
            cur_sheet = "library"
            continue
        row = _LINT_SHEET_ROW.match(line)
        if row:
            cur_sheet = row.group("sheet")
            continue
        d = _LINT_DETAIL.match(line)
        if d:
            out.append({
                "sheet": cur_sheet, "severity": d.group("sev"),
                "rule": d.group("rule"), "message": d.group("msg").strip(),
                "refs": [r.strip() for r in (d.group("refs") or "").split(",") if r.strip()],
            })
    return out


@app.get("/api/lint")
def lint(run_id: str | None = None) -> JSONResponse:
    """Return the lint report for the MOST RECENT build.

    Altium backend: `build_project` writes `out/lint.json` (every issue, all
    severities, attributed per sheet) on each build. We serve that file so the
    checklist reflects the current on-disk build and survives a backend restart
    — independent of whether a generate run is still in this process's memory.
    Falls back to parsing the last generate run's console output (and, for the
    legacy KiCad backend, that is the only source).

    Also returns the static rule registry so the frontend can render the full
    checklist (pass/fail per rule) even when nothing fired.

    Response includes cache-busting headers and timestamp so every fetch is fresh.
    """
    try:
        from test1.altium.layout_lint import RULES as _RULES
        rules = [dict(r) for r in _RULES]
    except Exception:
        rules = [
            {"id": "diagonal_wire", "severity": "ERROR", "scope": "sheet",
             "summary": "Wire is not strictly H or V"},
            {"id": "wire_through_body", "severity": "WARNING", "scope": "sheet",
             "summary": "Wire crosses a part body"},
        ]

    # Preferred source: the structured report from the most recent build.
    report_path = ALTIUM_OUT / "lint.json"
    if BACKEND == "altium" and report_path.exists():
        try:
            data = json.loads(report_path.read_text())
            issues = data.get("issues", [])
            counts = data.get("counts") or {
                s: sum(1 for i in issues if i["severity"] == s)
                for s in ("ERROR", "WARNING", "INFO")
            }
            body = {
                "run_id": None,
                "status": data.get("status", "unknown"),
                "generated_at": data.get("generated_at"),
                "issues": issues,
                "rules": rules,
                "counts": counts,
                "timestamp": time.time(),
            }
            return JSONResponse(body, headers={"Cache-Control": "no-store"})
        except (ValueError, OSError):
            pass  # fall through to the console-parse path

    target: Run | None = None
    if run_id and run_id in _RUNS:
        target = _RUNS[run_id]
    else:
        for r in reversed(list(_RUNS.values())):
            if r.kind == "generate":
                target = r
                break
    issues = _parse_lint_from_lines(list(target.lines)) if target else []
    body = {
        "run_id": target.run_id if target else None,
        "status": target.status if target else "unknown",
        "issues": issues,
        "rules": rules,
        "counts": {
            "ERROR": sum(1 for i in issues if i["severity"] == "ERROR"),
            "WARNING": sum(1 for i in issues if i["severity"] == "WARNING"),
            "INFO": sum(1 for i in issues if i["severity"] == "INFO"),
        },
        "timestamp": time.time(),
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


# ---- Review findings -----------------------------------------------------
@app.get("/api/findings")
def findings() -> JSONResponse:
    """Return review findings.

    findings.json may be either (a) a bare list of Finding dicts (legacy
    KiCad run_review.py path) or (b) a dict envelope produced by the
    Voltai-PDF parser `_review_incoming/install_review.py`
    ({ project, findings: [...], semantic: [...], summary: {...}, sources }).
    Both shapes are accepted.

    Response includes cache-busting headers so every fetch is fresh.
    """
    data: list = []
    envelope_summary: dict | None = None
    envelope_semantic: list | None = None
    if FINDINGS_JSON.exists():
        try:
            raw = json.loads(FINDINGS_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = []
        if isinstance(raw, dict):
            data = raw.get("findings") or []
            envelope_semantic = raw.get("semantic")
            envelope_summary = raw.get("summary")
        elif isinstance(raw, list):
            data = raw
    semantic: list = envelope_semantic if envelope_semantic is not None else []
    if not semantic and SEMANTIC_FINDINGS.exists():
        try:
            semantic = json.loads(SEMANTIC_FINDINGS.read_text())
        except json.JSONDecodeError:
            semantic = []
    if envelope_summary is not None:
        summary = {"ERROR": int(envelope_summary.get("ERROR", 0)),
                   "WARNING": int(envelope_summary.get("WARNING", 0)),
                   "INFO": int(envelope_summary.get("INFO", 0))}
    else:
        summary = {"ERROR": 0, "WARNING": 0, "INFO": 0}
        for f in data:
            sev = (f.get("severity") or "").upper()
            if sev in summary:
                summary[sev] += 1
    body = {
        "findings": data,
        "semantic": semantic,
        "summary": summary,
        "error_log_exists": ERROR_LOG.exists(),
        "timestamp": time.time(),
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


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
    """Return the set of MPNs (directory names) that have a native Altium
    symbol library `<MPN>/<MPN>.SchLib`."""
    if not LIBRARY_DIR.exists():
        return set()
    out: set[str] = set()
    for d in LIBRARY_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if symlib.has_symbol(d.name):
            out.add(d.name)
    return out


def _primary_symbol_for(mpn: str) -> tuple[Path, str] | None:
    """Return (schlib_file, symbol_name) for an MPN, or None. Symbols are
    authored as `<MPN>` inside `<MPN>/<MPN>.SchLib`, but fall back to the first
    symbol present so a hand-built library still resolves."""
    name = symlib.symbol_name(mpn)
    if name is None:
        return None
    return symlib.schlib_path(mpn), name


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


# --- Symbol parser + renderer (native Altium .SchLib) ----------------------
SYM_CACHE = HERE.parent / "state" / "symbol-cache"


def _parse_symbol(mpn: str) -> dict | None:
    """GUI-shaped symbol info read straight from the committed `<MPN>.SchLib`
    via altium_monkey. Returns {name, mpn, properties, pins[], pin_count,
    unit_names[]} or None when the part has no symbol library yet."""
    summary = symlib.symbol_summary(mpn)
    if not summary:
        return None
    # Strip the per-pin `unit` helper field the frontend doesn't model. Surface
    # the symbol's own parameters (Value/Footprint/Datasheet/MPN/...), falling
    # back to a local PDF for Datasheet when the symbol carries none.
    pins = [{k: v for k, v in p.items() if k != "unit"} for p in summary["pins"]]
    props: dict[str, str] = dict(summary.get("properties") or {})
    if "Datasheet" not in props:
        pdfs = sorted((LIBRARY_DIR / mpn).glob("*.pdf"))
        if pdfs:
            props["Datasheet"] = pdfs[0].name
    return {
        "name": summary["name"],
        "mpn": mpn,
        "properties": props,
        "pins": pins,
        "pin_count": summary["pin_count"],
        "unit_names": summary["unit_names"],
    }


def _render_symbol_svg(mpn: str) -> tuple[Path, str]:
    """Render the MPN's symbol to SVG (one file per unit) via altium_monkey,
    cached on disk and invalidated when the source `<MPN>.SchLib` mtime grows.

    Returns (cache_dir, symbol_name); SVGs are named <symbol_name>_unit<N>.svg.
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

    # Clear any stale unit SVGs so a re-render after an edit can't leave behind
    # units that no longer exist.
    for old in cache_dir.glob(f"{actual_name}_unit*.svg"):
        old.unlink()

    try:
        from altium_monkey import AltiumSchLib
        lib = AltiumSchLib(sym_file)
        units = sorted({u for *_, u in symlib.read_pins(mpn).values()}) or [1]
        multipart = len(units) > 1
        for part_id in units:
            svg = lib.symbol_to_svg(actual_name,
                                    part_id=part_id if multipart else None)
            (cache_dir / f"{actual_name}_unit{part_id}.svg").write_text(
                svg, encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"symbol render failed: {e}")
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


class SymbolUpload(BaseModel):
    filename: str
    content_b64: str


@app.post("/api/library/{mpn}/symbol")
def library_symbol_upload(mpn: str, body: SymbolUpload) -> dict:
    """Replace an MPN's symbol with a user-supplied Altium `.SchLib`.

    The file is validated (it must parse via altium_monkey and contain at least
    one symbol) before it overwrites `Parts Library/<MPN>/<MPN>.SchLib`. Any
    previous symbol is kept as `<MPN>.SchLib.bak` (the repo is not under git).
    Caches invalidate automatically: symlib's summary is keyed on file mtime and
    the SVG cache re-renders when the source mtime grows.
    """
    from altium_monkey import AltiumSchLib

    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", mpn):
        raise HTTPException(400, "bad mpn")
    d = LIBRARY_DIR / mpn
    if not d.exists() or not d.is_dir():
        raise HTTPException(404, "no such part")
    _safe_upload_name(body.filename, ("schlib",))
    raw = _decode_upload(body.content_b64)

    dest = symlib.schlib_path(mpn)            # Parts Library/<MPN>/<MPN>.SchLib
    tmp = dest.with_suffix(".SchLib.upload-tmp")
    tmp.write_bytes(raw)
    try:
        names = AltiumSchLib.get_symbol_names(str(tmp))
    except Exception as e:                    # noqa: BLE001 — surface parse error
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"not a readable Altium .SchLib: {e}")
    if not names:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "no symbols found in the .SchLib")

    if dest.exists():
        bak = dest.with_suffix(".SchLib.bak")
        bak.unlink(missing_ok=True)
        dest.replace(bak)
    tmp.replace(dest)
    return {"ok": True, "mpn": mpn, "symbols": names, "size": len(raw)}


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
    if BACKEND == "altium":
        # Build every sheet + the project via the Altium backend. Run as a
        # module from the repo root so `test1.altium...` imports resolve, using
        # this server's interpreter (the venv that has altium_monkey + pyyaml).
        cmd = [sys.executable, "-m", "test1.altium.build_project"]
        return {"run_id": await _start_run("generate", cmd, cwd=str(REPO_ROOT))}
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
        # If the run has already finished, send the final status immediately
        # (handles the race where subscriber joins after process completes).
        if r.status != "running":
            yield (f"event: done\ndata: "
                   f"{json.dumps({'status': r.status, 'rc': r.returncode})}"
                   f"\n\n").encode()
            return
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


# ---- Design Resources: datasheets · requirement docs · skills --------------
MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # 30 MB cap for base64 JSON uploads


def _decode_upload(content_b64: str) -> bytes:
    """Decode a base64 (or data: URL) payload, enforcing a size cap.

    Uploads come in as JSON base64 rather than multipart so the backend needs
    no extra dependency (python-multipart isn't installed)."""
    s = content_b64.strip()
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    try:
        raw = base64.b64decode(s, validate=False)
    except (ValueError, TypeError):
        raise HTTPException(400, "bad base64 content")
    if not raw:
        raise HTTPException(400, "empty file")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large (30 MB max)")
    return raw


def _safe_upload_name(name: str, exts: tuple[str, ...]) -> str:
    base = Path(name).name
    if not base or base.startswith("."):
        raise HTTPException(400, "bad filename")
    if not re.fullmatch(r"[A-Za-z0-9 _.\-()]+", base):
        raise HTTPException(400, "filename has unsupported characters")
    ext = base.lower().rsplit(".", 1)[-1] if "." in base else ""
    if exts and ext not in exts:
        raise HTTPException(400, f"extension must be one of: {', '.join(exts)}")
    return base


class DatasheetUpload(BaseModel):
    mpn: str
    filename: str
    content_b64: str


class RequirementUpload(BaseModel):
    filename: str
    content_b64: str


class SkillSave(BaseModel):
    title: str
    content: str
    slug: str | None = None


@app.get("/api/resources/datasheets")
def resources_datasheets() -> dict:
    """Every datasheet PDF already in the parts library, grouped by MPN."""
    out: list[dict] = []
    if LIBRARY_DIR.exists():
        for d in sorted(LIBRARY_DIR.iterdir(), key=lambda p: p.name.lower()):
            if not d.is_dir():
                continue
            for pdf in sorted(d.glob("*.pdf")):
                out.append({"mpn": d.name, "file": pdf.name, "size": pdf.stat().st_size})
    return {"datasheets": out}


@app.post("/api/resources/datasheets")
def resources_datasheet_upload(body: DatasheetUpload) -> dict:
    """Upload a datasheet into Parts Library/<MPN>/ so it ports into the rest
    of the app (Library + Simulation see it via the existing endpoints)."""
    mpn = body.mpn.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", mpn):
        raise HTTPException(400, "bad mpn (letters, digits, _ - . only)")
    fname = _safe_upload_name(body.filename, ("pdf",))
    raw = _decode_upload(body.content_b64)
    dest = LIBRARY_DIR / mpn
    dest.mkdir(parents=True, exist_ok=True)
    (dest / fname).write_bytes(raw)
    return {"ok": True, "mpn": mpn, "file": fname, "size": len(raw)}


@app.get("/api/resources/requirements")
def resources_requirements() -> dict:
    docs: list[dict] = []
    if REQ_DOCS_DIR.exists():
        for f in sorted(REQ_DOCS_DIR.iterdir(), key=lambda p: p.name.lower()):
            if f.is_file():
                docs.append({"name": f.name, "size": f.stat().st_size})
    return {"active_md_exists": DESIGN_REQS.exists(), "docs": docs}


@app.post("/api/resources/requirements")
def resources_requirement_upload(body: RequirementUpload) -> dict:
    fname = _safe_upload_name(
        body.filename, ("pdf", "docx", "doc", "pptx", "ppt", "md", "txt")
    )
    raw = _decode_upload(body.content_b64)
    REQ_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (REQ_DOCS_DIR / fname).write_bytes(raw)
    return {"ok": True, "file": fname, "size": len(raw)}


@app.get("/api/resources/requirements/file")
def resources_requirement_file(name: str = Query(...)):
    fname = Path(name).name
    target = REQ_DOCS_DIR / fname
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "no such file")
    media = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(target, media_type=media, filename=fname)


def _skill_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_\-]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise HTTPException(400, "bad skill name")
    return slug[:64]


def _skill_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            t = line.lstrip("#").strip()
            if t:
                return t
        if line.strip():
            break
    return fallback


@app.get("/api/resources/skills")
def resources_skills() -> dict:
    skills: list[dict] = []
    if SKILLS_DIR.exists():
        for f in sorted(SKILLS_DIR.glob("*.md"), key=lambda p: p.name.lower()):
            text = f.read_text(errors="replace")
            st = f.stat()
            skills.append({
                "slug": f.stem,
                "title": _skill_title(text, f.stem),
                "size": st.st_size,
                "updated": st.st_mtime,
            })
    return {"skills": skills}


@app.get("/api/resources/skills/{slug}")
def resources_skill_get(slug: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", slug):
        raise HTTPException(400, "bad slug")
    f = SKILLS_DIR / f"{slug}.md"
    if not f.exists():
        raise HTTPException(404, "no such skill")
    return {"slug": slug, "content": f.read_text(errors="replace")}


@app.post("/api/resources/skills")
def resources_skill_save(body: SkillSave) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "empty title")
    slug = body.slug or _skill_slug(body.title)
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", slug):
        raise HTTPException(400, "bad slug")
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_DIR / f"{slug}.md").write_text(body.content)
    return {"ok": True, "slug": slug}


@app.delete("/api/resources/skills/{slug}")
def resources_skill_delete(slug: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", slug):
        raise HTTPException(400, "bad slug")
    f = SKILLS_DIR / f"{slug}.md"
    if not f.exists():
        raise HTTPException(404, "no such skill")
    f.unlink()
    return {"ok": True}


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
    session_id: str | None = None


class SessionCreate(BaseModel):
    title: str | None = None


class SessionRename(BaseModel):
    title: str


class ChangelogAdd(BaseModel):
    summary: str
    # Origin. Defaults to a manual user add. The Simulation tab passes
    # source="sim" + the block/sim_type so the post-apply chain can re-run ONLY
    # the originating sim (a user/manual item never triggers a simulation).
    source: str = "user"
    sim_block: str | None = None
    sim_type: str | None = None


@app.get("/api/chat/sessions")
def chat_sessions() -> dict:
    """List chat sessions (metadata only) and which one is the default."""
    return agent_mod.list_sessions()


@app.post("/api/chat/sessions")
def chat_session_create(body: SessionCreate = SessionCreate()) -> dict:
    return agent_mod.create_session(body.title)


@app.get("/api/chat/sessions/{sid}")
def chat_session_get(sid: str) -> dict:
    s = agent_mod.get_session(sid)
    if not s:
        raise HTTPException(404, "no such session")
    return s


@app.post("/api/chat/sessions/{sid}/rename")
def chat_session_rename(sid: str, body: SessionRename) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "empty title")
    if not agent_mod.rename_session(sid, body.title):
        raise HTTPException(404, "no such session")
    return {"ok": True}


@app.post("/api/chat/sessions/{sid}/default")
def chat_session_default(sid: str) -> dict:
    if not agent_mod.set_default_session(sid):
        raise HTTPException(404, "no such session")
    return {"ok": True}


@app.post("/api/chat/sessions/{sid}/clear")
def chat_session_clear(sid: str) -> dict:
    if not agent_mod.clear_session(sid):
        raise HTTPException(404, "no such session")
    return {"ok": True}


@app.delete("/api/chat/sessions/{sid}")
def chat_session_delete(sid: str) -> dict:
    if not agent_mod.delete_session(sid):
        raise HTTPException(404, "no such session")
    return {"ok": True}


@app.post("/api/chat/sessions/{sid}/compact")
async def chat_session_compact(sid: str) -> dict:
    """Summarize the session and collapse its transcript. Returns an agent
    run_id to stream via /api/agent/{run_id}/stream; on completion the
    session's summary is updated and its messages are cleared."""
    run = await agent_mod.start_compact(sid)
    if not run:
        raise HTTPException(404, "no such session")
    return {"run_id": run.run_id, "kind": run.kind}


@app.post("/api/chat")
async def chat_send(msg: ChatMessage) -> dict:
    """Send a user turn in a session. The agent runs as a subprocess and may
    append bullets to the changelog when explicitly asked. Frontend subscribes
    to /api/agent/{run_id}/stream to watch the response stream in."""
    content = msg.content.strip()
    if not content:
        raise HTTPException(400, "empty message")
    sid = msg.session_id or agent_mod.list_sessions()["default_id"]
    run = await agent_mod.start_chat_turn(sid, content)
    return {"run_id": run.run_id, "kind": run.kind, "session_id": sid}


# NOTE: static "/api/agent/runs" + "/decisions" must precede the dynamic
# "/api/agent/{run_id}" route — FastAPI matches in declaration order.
@app.get("/api/agent/runs")
def agent_runs() -> dict:
    """List persisted run-reasoning logs (newest first) so the GUI can show an
    auditable history of what each apply/fix run reasoned and decided."""
    runs_dir = agent_mod.STATE_DIR / "runs"
    out = []
    if runs_dir.is_dir():
        for f in sorted(runs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                head = f.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
            except OSError:
                head = []
            out.append({"run_id": f.stem, "header": head[0] if head else "",
                        "mtime": f.stat().st_mtime})
    return {"runs": out[:50]}


@app.get("/api/agent/decisions")
def agent_decisions() -> dict:
    """The most recent apply/fix run's per-item outcomes (APPLIED/STOPPED/CLARIFY)
    so the GUI can show each changelog item's fate at a glance."""
    return agent_mod._load(agent_mod.DECISIONS_FILE, {}) or {}


@app.get("/api/agent/runs/{run_id}/log")
def agent_run_log(run_id: str) -> dict:
    """Full reasoning log (thinking + assistant + tools + final) for one run."""
    if not re.fullmatch(r"[0-9a-f]{6,32}", run_id):
        raise HTTPException(400, "bad run_id")
    f = agent_mod.STATE_DIR / "runs" / f"{run_id}.log"
    if not f.exists():
        raise HTTPException(404, "no such run log")
    return {"run_id": run_id, "body": f.read_text(encoding="utf-8", errors="replace")}


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


@app.post("/api/agent/{run_id}/cancel")
def agent_cancel(run_id: str) -> dict:
    """Cancel a running agent (terminates its claude -p process). Used by the
    Simulation tab's Cancel button to abort a long setup/interpret pass. The
    SSE stream then closes with status 'cancelled'. Idempotent: returns
    cancelled=False if the run is unknown or already finished."""
    return {"run_id": run_id, "cancelled": agent_mod.cancel_run(run_id)}


@app.get("/api/changelog")
def changelog_get() -> dict:
    return {"items": agent_mod.load_changelog()}


@app.post("/api/changelog")
def changelog_add(item: ChangelogAdd) -> dict:
    if not item.summary.strip():
        raise HTTPException(400, "empty summary")
    # Only honor sim origin when source is explicitly "sim"; otherwise treat as
    # a manual/user item with no sim linkage (so it can't trigger a re-sim).
    src = item.source if item.source in ("sim", "user", "agent", "closed_loop") else "user"
    return agent_mod.append_changelog(
        item.summary,
        source=src,
        sim_block=item.sim_block if src == "sim" else None,
        sim_type=item.sim_type if src == "sim" else None,
    )


@app.delete("/api/changelog/{item_id}")
def changelog_delete(item_id: str) -> dict:
    if not agent_mod.remove_changelog(item_id):
        raise HTTPException(404, "no such item")
    return {"ok": True}


@app.post("/api/changelog/clear")
def changelog_clear() -> dict:
    agent_mod.clear_changelog()
    return {"ok": True}


# ---- Simulation (ngspice-backed) -----------------------------------------
class SimRunReq(BaseModel):
    block: str
    sim_type: str
    # None → the service uses the agent-determined operating point (sim_config),
    # falling back to 1.8V only if no scenario has been determined yet.
    vout_set: float | None = None


class SimChatEditReq(BaseModel):
    block: str
    instruction: str                 # natural-language edit request


class AgentModelReq(BaseModel):
    kind: str                        # agent kind (sim_setup, sim_generate, …)
    model: str | None = None         # one of MODEL_CHOICES, or None to clear override


# Functional grouping for the Simulation tab + sidebar. The `group` id on each
# block (blocks.yaml) keys into this ordered list — it gives the section its
# display label, a one-line blurb, and (by position) its order. A block whose
# group isn't listed here falls into the trailing "other" bucket. Order = how an
# engineer reads the signal chain: make a rail → distribute it → condition analog
# → integrate → (gaps). To add a group: append it here and tag the blocks.
SIM_GROUPS = [
    {"id": "power_generation", "label": "Power generation",
     "blurb": "How a rail is made — regulator + load switch."},
    {"id": "power_distribution", "label": "Power distribution (PDN)",
     "blurb": "How a rail is delivered to the chip — decoupling / PDN banks."},
    {"id": "analog_bias", "label": "Analog & bias",
     "blurb": "Precision analog signal-conditioning."},
    {"id": "system_integration", "label": "System integration",
     "blurb": "Multi-block / whole-board composition tests."},
    {"id": "not_simulatable", "label": "Not simulatable",
     "blurb": "Documented gaps — connectors, digital-only, EEPROM."},
    {"id": "other", "label": "Other", "blurb": ""},
]


@app.get("/api/sim/blocks")
def sim_blocks() -> dict:
    """Block catalog + the functional-group taxonomy (ordered labels/blurbs) the
    GUI uses to organize the Simulation tab and sidebar into named sections."""
    return {"blocks": sim_service.list_blocks(), "groups": SIM_GROUPS}


# ---- Edit per-sim requirements (pass criteria + boundary params) -----------
class SimReqEdit(BaseModel):
    block: str
    # exactly one of these edit shapes:
    sim_type: str | None = None       # for field edits
    field: str | None = None          # "pass" | "rationale"
    value: str | None = None
    net: str | None = None            # for boundary-param edits
    key: str | None = None
    param_value: str | None = None


@app.get("/api/sim/requirements")
def sim_requirements(block: str) -> dict:
    """The editable requirements for a block: each sim_type's pass/rationale +
    the block's boundary params (the operating-point/load values)."""
    from test1.sim import catalog_edit
    try:
        return catalog_edit.requirements(block)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/sim/requirements")
def sim_requirements_edit(req: SimReqEdit) -> dict:
    """Surgically edit blocks.yaml (comment-preserving, validated): set a
    sim_type's pass/rationale, or set/add a boundary net's param."""
    from test1.sim import catalog_edit
    try:
        if req.field is not None and req.sim_type is not None and req.value is not None:
            catalog_edit.set_sim_field(req.block, req.sim_type, req.field, req.value)
        elif req.net is not None and req.key is not None and req.param_value is not None:
            catalog_edit.set_boundary_param(req.block, req.net, req.key, req.param_value)
        else:
            raise HTTPException(400, "specify (sim_type, field, value) or (net, key, param_value)")
        return {"ok": True, "requirements": catalog_edit.requirements(req.block)}
    except catalog_edit.CatalogEditError as e:
        raise HTTPException(400, f"edit rejected: {e}")
    except KeyError as e:
        raise HTTPException(404, str(e))


# ---- Clear a block's sim cache --------------------------------------------
class SimCacheClear(BaseModel):
    block: str
    scope: str = "all"                # "scenario" | "params" | "all"


@app.post("/api/sim/cache/clear")
def sim_cache_clear(req: SimCacheClear) -> dict:
    """Clear a block's cached sim state so the next Run re-derives it.
      scenario → drop the operating-point scenario (sim_config) + iter counters
      params   → drop the block's datasheet device params
      all      → both."""
    from test1.sim import simconfig as sc
    blocks = {b["id"]: b for b in sim_service.list_blocks()}
    blk = blocks.get(req.block)
    if not blk:
        raise HTTPException(404, f"no block {req.block!r}")
    out: dict = {"block": req.block, "scope": req.scope}
    if req.scope in ("scenario", "all"):
        out["scenario_cleared"] = sc.clear_scenario(req.block)
        out["counters_cleared"] = sc.clear_iter_counters(req.block)
    if req.scope in ("params", "all"):
        mpns = [d.get("mpn") for d in blk.get("datasheets", []) if d.get("mpn")]
        out["params_cleared"] = sc.clear_params(mpns)
    return out


@app.post("/api/sim/run")
def sim_run(req: SimRunReq) -> dict:
    """Run one (block, sim_type). Synchronous — sims finish in ~1s and
    FastAPI runs sync endpoints in a threadpool, so the ngspice subprocess
    blocks its worker thread, not the event loop."""
    try:
        return sim_service.run_block_sim(req.block, req.sim_type, vout_set=req.vout_set)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/sim/circuit")
def sim_circuit(block: str, sim_type: str) -> dict:
    """Parsed node-graph of the deck for (block, sim_type) WITHOUT running it —
    powers the Simulation tab's "SPICE model" view (what's being simulated).
    Builds the deck and parses it; no ngspice needed, so it works even when the
    simulator is absent. `circuit` is null when the combo has no deck (a
    code-built analysis, or a planned sim)."""
    try:
        return {"block": block, "sim_type": sim_type,
                "circuit": sim_service.circuit_for(block, sim_type)}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/sim/simulated-region")
def sim_simulated_region(block: str) -> dict:
    """Which parts of the real schematic this sim block covers, and WHERE they
    are — ACROSS ALL SHEETS (a block's parts can span sheets, e.g. an LDO whose
    VDDIO decaps live on the bobcat sheet). The block's real refdes come from the
    deck's circuit (deck element → netlist refdes); each is then located on every
    rendered sheet. Returns a per-sheet map so the GUI can highlight on the right
    sheet and flag which sheet tabs contain a simulated part. Altium backend
    only (needs the rendered SVGs)."""
    empty = {"sheets": {}, "sheets_with_parts": [], "refdes": [], "primary": None}
    if BACKEND != "altium":
        return empty
    blocks = {b["id"]: b for b in sim_service.list_blocks()}
    blk = blocks.get(block)
    if not blk:
        raise HTTPException(404, f"no block {block!r}")

    # the block's REAL schematic refdes, from the deck (a representative
    # implemented sim type — topology/parts are shared across a block's sims).
    st = next((s["type"] for s in blk.get("sim_types", [])
               if s.get("status") == "implemented"), None)
    circ = sim_service.circuit_for(block, st) if st else None
    sim_refs = sorted({e["refdes"] for e in (circ or {}).get("elements", [])
                       if e.get("refdes")})
    if not sim_refs:
        return empty

    from test1.altium import refdes_locations
    from test1.sim import design_extract
    sim_set = set(sim_refs)
    # Locate the sim refs on each rendered sheet. Refdes are NOT globally unique
    # (each sheet has its own C20/C24 series), and the rendered SVG can contain
    # off-sheet/cross-ref labels — so a refdes only counts on a sheet if that
    # sheet's NETLIST actually declares it. (netlist = authority for which sheet
    # a part lives on; SVG = where it sits.)
    sheets: dict[str, dict] = {}
    for svg in sorted(RENDER_DIR.glob("*.svg")):
        stem = svg.stem
        if stem in ("root", "test1"):
            continue
        on_sheet = set(design_extract.sheet_refdes(stem))   # netlist parts here
        placed = refdes_locations.extract(svg)
        located = {r: xy for r, xy in placed["refdes"].items()
                   if r in sim_set and r in on_sheet}
        if located:
            sheets[stem] = {"viewBox": placed["viewBox"], "refdes": located}

    with_parts = sorted(sheets.keys())
    # primary = the block's declared sheet if it has parts, else the sheet with
    # the most simulated parts (a sensible default to switch to).
    decl = (blk.get("sheet") or "").strip()
    decl = decl[:-5] if decl.endswith(".yaml") else decl
    primary = decl if decl in sheets else (
        max(sheets, key=lambda s: len(sheets[s]["refdes"])) if sheets else None)
    return {
        "sheets": sheets,                       # {stem: {viewBox, refdes:{x,y}}}
        "sheets_with_parts": with_parts,        # tab-highlight list
        "refdes": sim_refs,                     # all real refdes the block sims
        "primary": primary,                     # sheet to switch to first
    }


@app.post("/api/sim/setup")
async def sim_setup(req: SimRunReq) -> dict:
    """Context-first stage: if the block's scenario is stale or missing, spawn
    the agent to read datasheets + requirements + the current design and write
    the device params + operating-point scenario. If fresh, skip — the sim can
    run immediately on the cached scenario (cache-gated)."""
    blocks = {b["id"]: b for b in sim_service.list_blocks()}
    block = blocks.get(req.block)
    if not block:
        raise HTTPException(404, f"no block {req.block!r}")
    if block.get("status") != "implemented":
        return {"fresh": True, "skipped": "block not runnable"}
    if sim_config.is_fresh(block):
        return {"fresh": True}
    run = await agent_mod.start_sim_setup(
        block_id=req.block,
        datasheets=block.get("datasheets", []),
        sheet=block.get("sheet", ""),
    )
    return {"fresh": False, "run_id": run.run_id}


@app.post("/api/sim/interpret")
async def sim_interpret(req: SimRunReq) -> dict:
    """Run the sim, then spawn the agent to read the block's datasheets +
    requirements, cache the extracted device parameters, and interpret the
    result against spec. Returns an agent run_id to stream via
    /api/agent/{run_id}/stream."""
    res = sim_service.run_block_sim(req.block, req.sim_type, vout_set=req.vout_set)
    if res.get("status") not in ("ran",):
        raise HTTPException(400, f"sim not runnable ({res.get('status')}): {res.get('message','')}")

    blocks = {b["id"]: b for b in sim_service.list_blocks()}
    block = blocks.get(req.block, {})
    compact = {
        "block": req.block, "sim_type": req.sim_type,
        "ok": res.get("ok"), "analysis": res.get("analysis"),
        "op_point": res.get("op_point"),
    }
    run = await agent_mod.start_sim_interpret(
        block_id=req.block,
        sim_type=req.sim_type,
        pass_criterion=res.get("pass_criterion") or "",
        datasheets=block.get("datasheets", []),
        result_json=json.dumps(compact, indent=2),
    )
    return {"run_id": run.run_id, "sim_ok": res.get("ok")}


# ---- SPICE-model lifecycle (generate / update / chat-edit) ----------------
@app.post("/api/sim/generate-model")
async def sim_generate_model(req: SimRunReq) -> dict:
    """Spawn the generator agent to AUTHOR a SPICE model for a block that has
    none (writes sim/decks/<block>.py + dispatch + catalog entry). Stream the run
    via /api/agent/{run_id}/stream. 409 if the block already has a model."""
    blocks = {b["id"]: b for b in sim_service.list_blocks()}
    block = blocks.get(req.block)
    if not block:
        raise HTTPException(404, f"no block {req.block!r}")
    if block.get("has_model"):
        raise HTTPException(409, f"block {req.block!r} already has a SPICE model — use update instead")
    run = await agent_mod.start_sim_generate_model(
        block_id=req.block,
        title=block.get("title", req.block),
        sheet=block.get("sheet", ""),
        datasheets=block.get("datasheets", []),
        description=block.get("description", ""),
        group=block.get("group", ""),
    )
    return {"run_id": run.run_id}


@app.post("/api/sim/update-model")
async def sim_update_model(req: SimRunReq) -> dict:
    """Spawn the schematic-sync agent to bring a block's EXISTING model + catalog
    entry back in line with the current netlist. 409 if the block has no model
    (generate first)."""
    blocks = {b["id"]: b for b in sim_service.list_blocks()}
    block = blocks.get(req.block)
    if not block:
        raise HTTPException(404, f"no block {req.block!r}")
    if not block.get("has_model"):
        raise HTTPException(409, f"block {req.block!r} has no SPICE model — generate one first")
    run = await agent_mod.start_sim_update_model(
        block_id=req.block,
        title=block.get("title", req.block),
        sheet=block.get("sheet", ""),
        datasheets=block.get("datasheets", []),
        status_reason=f"model_status={block.get('model_status')}",
    )
    return {"run_id": run.run_id}


@app.post("/api/sim/chat-edit")
async def sim_chat_edit(req: SimChatEditReq) -> dict:
    """Apply a natural-language edit to a block's sim (pass criteria / params /
    model / functions). Foundation for the interactive chat editor — the live
    chat UI is gated on the forthcoming chat API; this endpoint + agent are the
    ready wire-up."""
    blocks = {b["id"]: b for b in sim_service.list_blocks()}
    block = blocks.get(req.block)
    if not block:
        raise HTTPException(404, f"no block {req.block!r}")
    if not (req.instruction or "").strip():
        raise HTTPException(400, "instruction is empty")
    run = await agent_mod.start_sim_chat_edit(
        block_id=req.block,
        instruction=req.instruction.strip(),
        sheet=block.get("sheet", ""),
    )
    return {"run_id": run.run_id}


# ---- Per-agent model selection --------------------------------------------
@app.get("/api/sim/agent-models")
def sim_agent_models() -> dict:
    """Which Claude model each sim agent runs on (current + default + choices),
    for the GUI's per-agent model picker."""
    return agent_mod.agent_model_config()


@app.post("/api/sim/agent-models")
def sim_set_agent_model(req: AgentModelReq) -> dict:
    """Set (or clear, model=null) the model override for one agent kind."""
    ok = agent_mod.set_agent_model(req.kind, req.model)
    if not ok:
        raise HTTPException(400, f"unknown agent kind {req.kind!r} or invalid model {req.model!r}")
    return agent_mod.agent_model_config()


# ---- Generate with changelog-apply ----------------------------------------
class ApplyAndGenOpts(BaseModel):
    no_reopen: bool = True
    # Closed-loop review: after the apply pass, build + read the gates
    # (validator + layout lint); if the build fails, spawn a bounded fix pass
    # with the actual failures and rebuild — up to LOOP_MAX_ROUNDS — so Generate
    # lands a gate-clean change instead of shipping a broken build. Opt-in.
    loop_review: bool = False


# Hard cap on apply->build->fix rounds when loop_review is on (mirrors the sim
# iterate cap: bounded so a stubborn failure can't spin forever).
LOOP_MAX_ROUNDS = 3


def _read_lint_failures() -> dict:
    """Read out/lint.json + the latest generate run's output tail into the
    failure payload the fix pass consumes. Called after a build to decide
    whether the gates passed."""
    out: dict = {"status": "unknown", "counts": {}, "issues": [], "tail": [], "exit": None}
    try:
        data = json.loads((ALTIUM_OUT / "lint.json").read_text())
        out["status"] = data.get("status", "unknown")
        out["counts"] = data.get("counts", {})
        out["issues"] = data.get("issues", [])
    except (OSError, json.JSONDecodeError):
        pass
    # latest generate run's exit code + output tail
    gen = next((r for r in reversed(list(_RUNS.values())) if r.kind == "generate"), None)
    if gen is not None:
        out["exit"] = gen.returncode
        out["tail"] = list(gen.lines)[-30:]
    return out


def _gates_passed(failures: dict) -> bool:
    """The build is clean iff it exited 0 AND lint reports no ERRORs. (WARN/INFO
    are advisory and don't fail the build — matching build_project's gate.)"""
    if failures.get("exit") not in (0, None):
        return False
    if failures.get("status") == "fail":
        return False
    return int(failures.get("counts", {}).get("ERROR", 0)) == 0


def _sim_targets_from_items(items: list[dict]) -> list[tuple[str, str | None]]:
    """From a changelog snapshot, return the DISTINCT (block, sim_type) pairs of
    SIM-ORIGINATED items only. This is the hard gate for the post-apply re-sim:
    ONLY items with source=="sim" (set by the Simulation tab when the user adds a
    suggestion to the changelog) contribute here. A user/manual/agent-originated
    item NEVER triggers a re-sim, regardless of any other fields it may carry.

    Backward-compatible fallback: an older item lacking source=="sim" but whose
    summary starts with the historical "[sim block/sim_type]" prefix (the Simulation
    tab used this format before source/sim_block were first-class fields) is also
    recognized as sim-originated. Every other item is skipped immediately on the
    source check — the source check is the FIRST gate, not an afterthought."""
    targets: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for it in items:
        if it.get("source") == "sim":
            # Primary path: the Simulation tab sets source="sim" and the structured
            # sim_block/sim_type fields when adding a suggestion to the changelog.
            block = it.get("sim_block")
            stype = it.get("sim_type")
        else:
            # Legacy fallback ONLY: parse the old "[sim <block>/<sim_type>]" prefix.
            # Any item without this prefix is NOT sim-originated → skip immediately.
            m = re.match(r"\s*\[sim\s+([^/\]\s]+)(?:/([^\]\s]+))?\]",
                         it.get("summary", ""))
            if not m:
                continue  # user/agent/manual item — never re-sim
            block = m.group(1)
            stype = m.group(2)
        if not block:
            continue
        key = (block, stype)
        if key not in seen:
            seen.add(key)
            targets.append(key)
    return targets


async def _resim_blocks(targets: list[tuple[str, str | None]]) -> list[dict]:
    """Re-run each sim-originated (block, sim_type) after the apply landed, so the
    loop is closed back to the sim that asked for the change. Best-effort and
    non-fatal: a sim error is recorded, never raised (it must not break the build
    chain). Returns a list of {block, sim_type, status, ...} verdicts that the GUI
    can surface as before/after. Runs in a thread since run_block_sim is sync."""
    results: list[dict] = []
    for block, stype in targets:
        # Resolve a concrete sim_type if the item didn't carry one.
        st = stype
        if not st:
            try:
                blk = next((b for b in sim_service.list_blocks() if b["id"] == block), None)
                sts = (blk or {}).get("sim_types", [])
                st = sts[0]["type"] if sts else None
            except Exception:
                st = None
        if not st:
            results.append({"block": block, "sim_type": None, "status": "skipped",
                            "reason": "no sim_type resolvable"})
            continue
        try:
            res = await asyncio.to_thread(sim_service.run_block_sim, block, st)
            results.append({"block": block, "sim_type": st,
                            "status": res.get("status", "ran"),
                            "verdict": res.get("verdict")})
            print(f"[apply-and-generate] re-sim {block}/{st} -> {res.get('status')}", flush=True)
        except Exception as e:
            results.append({"block": block, "sim_type": st, "status": "error", "reason": str(e)})
            print(f"[apply-and-generate] re-sim {block}/{st} FAILED: {e}", flush=True)
    return results


@app.post("/api/run/apply-and-generate")
async def run_apply_and_generate(opts: ApplyAndGenOpts = ApplyAndGenOpts()) -> dict:
    """Three-stage pipeline:

      1. Spawn the agent in apply mode to implement queued changelog items.
      2. Wait for it to finish in the background.
      3. Spawn gen_schematic.py via the existing run-registry path.

    The frontend tracks stage 1 via /api/agent/{run_id}/stream and stage 3
    via /api/run/{run_id}/stream. Both ids are returned up front (generate
    may still be pending if apply is still running).
    """
    # KiCad backend needs gen_schematic.py; the Altium backend builds a module.
    if BACKEND != "altium" and not GEN_SCRIPT.exists():
        raise HTTPException(500, "gen_schematic.py missing")

    # --- helpers shared by both paths ---------------------------------------
    def _generate_cmd() -> tuple[list[str], str | None]:
        if BACKEND == "altium":
            return [sys.executable, "-m", "test1.altium.build_project"], str(REPO_ROOT)
        cmd = [sys.executable, str(GEN_SCRIPT)]
        if opts.no_reopen:
            cmd.append("--no-reopen")
        return cmd, None

    async def _await_run(run_id: str) -> None:
        r = _RUNS.get(run_id)
        while r is not None and r.status == "running":
            await asyncio.sleep(0.25)

    async def _await_agent(run_id: str) -> None:
        ar = agent_mod.get_run(run_id)
        while ar is not None and ar.status == "running":
            await asyncio.sleep(0.25)

    async def _build_once() -> str:
        cmd, cwd = _generate_cmd()
        gid = await _start_run("generate", cmd, cwd=cwd)
        await _await_run(gid)
        return gid

    def _spawn_chain(coro, label: str) -> None:
        """Schedule a background chain task whose exceptions are NEVER swallowed.
        A bare asyncio.create_task drops any exception silently — which is exactly
        why a failed apply->generate chain vanished with no trace. Wrap it so any
        failure prints a full traceback to the backend log (visible) AND is
        recorded as a failed 'generate' run so the GUI shows an error instead of
        hanging forever waiting for a build that never starts."""
        async def _guarded() -> None:
            try:
                await coro
            except Exception:
                import traceback
                tb = traceback.format_exc()
                print(f"[apply-and-generate] {label} FAILED:\n{tb}", flush=True)
                # Surface to the GUI: a failed generate run carries the error so
                # the frontend's poll/stream resolves instead of spinning.
                rid = uuid.uuid4().hex[:12]
                r = Run(run_id=rid, kind="generate", cmd=["<chain>"], cwd=None)
                r.status = "fail"
                r.returncode = -1
                for ln in (f"[chain-error] {label} failed:", *tb.splitlines()):
                    r.lines.append(ln)
                _RUNS[rid] = r
        asyncio.create_task(_guarded())

    items = agent_mod.load_changelog()
    # Snapshot the SIM-ORIGINATED targets NOW, before the apply pass clears the
    # changelog. Only these (block, sim_type) pairs get re-simulated after a
    # clean build — user/manual items contribute nothing here, so they never
    # trigger a sim (the specific requirement).
    sim_targets = _sim_targets_from_items(items)
    apply_run_id: str | None = None
    if items:
        apply_run = await agent_mod.start_apply_pass()
        apply_run_id = apply_run.run_id

    # ---- CLOSED-LOOP REVIEW path -------------------------------------------
    # apply -> build -> read the gates -> if failed, bounded fix pass -> rebuild,
    # up to LOOP_MAX_ROUNDS, so Generate lands a gate-clean change. All phases run
    # in the background and surface via the run registry / SSE, exactly like the
    # plain path; the frontend streams "generate"/"apply"/"lint-fix" runs as they
    # appear. (Altium backend only — the loop reads the validator+lint gate.)
    if opts.loop_review and BACKEND == "altium":
        async def chain_with_loop_review() -> None:
            if apply_run_id:
                await _await_agent(apply_run_id)
            await _build_once()
            failures = _read_lint_failures()
            rnd = 0
            while not _gates_passed(failures) and rnd < LOOP_MAX_ROUNDS:
                rnd += 1
                fix = await agent_mod.start_lint_fix_pass(failures, rnd, LOOP_MAX_ROUNDS)
                await _await_agent(fix.run_id)
                await _build_once()
                failures = _read_lint_failures()
            # Close the loop back to the sim: ONLY for sim-originated items, and
            # ONLY once the build is gate-clean (no point re-simming a broken design).
            if sim_targets and _gates_passed(failures):
                await _resim_blocks(sim_targets)
            # final state is whatever the last build left in lint.json / run registry
        _spawn_chain(chain_with_loop_review(), "loop-review chain")
        return {
            "apply_run_id": apply_run_id,
            "generate_run_id": None,    # phases appear in the run registry as they start
            "queued_items": len(items),
            "loop_review": True,
            "max_rounds": LOOP_MAX_ROUNDS,
        }

    # ---- PLAIN path (unchanged behavior) -----------------------------------
    if not apply_run_id:
        # No apply pass needed: start generate directly and return its id.
        cmd, cwd = _generate_cmd()
        generate_run_id = await _start_run("generate", cmd, cwd=cwd)
        return {
            "apply_run_id": None,
            "generate_run_id": generate_run_id,
            "queued_items": 0,
        }

    async def chain_to_generate() -> None:
        """Wait for apply to complete, then start generate."""
        await _await_agent(apply_run_id)
        cmd, cwd = _generate_cmd()
        gid = await _start_run("generate", cmd, cwd=cwd)
        await _await_run(gid)
        # Close the loop back to the sim for sim-originated items only, once the
        # build is gate-clean. (Plain path has no fix loop; re-sim if it passed.)
        if sim_targets and _gates_passed(_read_lint_failures()):
            await _resim_blocks(sim_targets)

    _spawn_chain(chain_to_generate(), "apply->generate chain")
    return {
        "apply_run_id": apply_run_id,
        "generate_run_id": None,  # Will be available via /api/run stream once apply finishes
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


# ---- Apply-fix queue ----------------------------------------------------
#
# Per-row Apply -> POST /api/findings/{id}/apply, body
#   { action_index, action_kind, action_text }. Backend writes a request
#   into test1/review/fix_queue.json. The Claude agent reads that queue
#   in chat ("apply pending fixes"), verifies each, applies, and updates
#   the queue status. UI polls GET /api/fix-queue.
#
# Why a queue instead of synchronous LLM call: applying a review fix is
# semantically complex (schematic topology + symbol + YAML edits + rebuild
# verification) and needs the agent in the loop, not a one-shot prompt.


def _read_queue() -> list:
    if not FIX_QUEUE_JSON.exists():
        return []
    try:
        return json.loads(FIX_QUEUE_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _write_queue(q: list) -> None:
    FIX_QUEUE_JSON.parent.mkdir(parents=True, exist_ok=True)
    FIX_QUEUE_JSON.write_text(json.dumps(q, indent=2), encoding="utf-8")


class ApplyFindingBody(BaseModel):
    action_index: int = 0   # which Fix/Alt/Verify in the action list
    action_kind: str = ""   # "fix" | "alt" | "verify" (informational)
    action_text: str = ""   # the chosen action body (informational, for queue
                            # readability)


@app.post("/api/findings/{finding_id}/apply")
def apply_finding(finding_id: str, body: ApplyFindingBody) -> dict:
    """Queue a finding's chosen fix for the chat agent to pick up. Idempotent
    on (finding_id + action_index): re-queueing replaces the previous request.

    Does NOT touch the design directly — the agent owns that step so it can
    sanity-check the suggestion before editing."""
    if not re.fullmatch(r"[A-Fa-f0-9]{4,32}", finding_id):
        raise HTTPException(400, "bad finding id")
    # Cross-check: the finding must exist in the current findings.json.
    snap = findings()
    f = next((x for x in snap["findings"] if x.get("id") == finding_id), None)
    if f is None:
        raise HTTPException(404, "finding not found in current findings.json")
    actions = f.get("actions") or []
    if not (0 <= body.action_index < len(actions)):
        raise HTTPException(400, f"action_index out of range (0..{len(actions) - 1})")
    chosen = actions[body.action_index]
    q = _read_queue()
    # Replace any existing entry for this (id, action_index).
    q = [e for e in q if not (e.get("finding_id") == finding_id
                              and e.get("action_index") == body.action_index)]
    q.append({
        "finding_id": finding_id,
        "action_index": body.action_index,
        "action_kind": chosen.get("kind", body.action_kind),
        "action_text": chosen.get("text", body.action_text),
        "component": f.get("component"),
        "category": f.get("category"),
        "rule": f.get("rule"),
        "refs": f.get("refs"),
        "status": "queued",
        "queued_at": time.time(),
    })
    _write_queue(q)
    return {"ok": True, "queued": len(q), "finding_id": finding_id}


@app.get("/api/fix-queue")
def fix_queue() -> dict:
    """Surface the apply-fix queue so the GUI can show per-row status badges
    and the chat agent can list what's pending."""
    q = _read_queue()
    return {"queue": q, "counts": {
        "queued": sum(1 for e in q if e.get("status") == "queued"),
        "applied": sum(1 for e in q if e.get("status") == "applied"),
        "failed": sum(1 for e in q if e.get("status") == "failed"),
        "dismissed": sum(1 for e in q if e.get("status") == "dismissed"),
    }}


@app.delete("/api/fix-queue/{finding_id}")
def dismiss_fix(finding_id: str) -> dict:
    """Remove all queue entries for a finding (cancel / dismiss)."""
    if not re.fullmatch(r"[A-Fa-f0-9]{4,32}", finding_id):
        raise HTTPException(400, "bad finding id")
    q = _read_queue()
    before = len(q)
    q = [e for e in q if e.get("finding_id") != finding_id]
    _write_queue(q)
    return {"ok": True, "removed": before - len(q)}


# ===========================================================================
# Closed-loop design review — Rules endpoints
# ===========================================================================

@app.get("/api/review/rules")
def review_rules_list() -> dict:
    """Return the current rules.yaml contents + staleness state."""
    from test1.review.rule_eval import load_rules
    rf = load_rules()
    # Staleness: any source on disk newer than the recorded mtime?
    stale_sources: list[dict] = []
    for s in rf.sources_seen:
        p = REPO_ROOT / s.path
        if p.exists() and p.stat().st_mtime > s.mtime + 1.0:
            stale_sources.append({"path": s.path,
                                  "current_mtime": p.stat().st_mtime,
                                  "recorded_mtime": s.mtime})
    return {
        "version": rf.version,
        "generated_at": rf.generated_at,
        "rules": [r.model_dump(exclude_none=True) for r in rf.rules],
        "sources_seen": [s.model_dump() for s in rf.sources_seen],
        "stale_sources": stale_sources,
        "by_family": {
            fam: sum(1 for r in rf.rules if r.family == fam)
            for fam in ("schematic", "simulation", "design")
        },
        "by_origin": {
            ori: sum(1 for r in rf.rules if r.origin == ori)
            for ori in ("generated", "user", "imported")
        },
    }


@app.post("/api/review/rules/generate")
async def review_rules_generate() -> dict:
    """Kick off rule generation in the BACKGROUND. Returns the job_id
    immediately; the GUI subscribes to ``/api/review/rules/generate/{job_id}
    /stream`` for phase events (bundle/dispatch/validate/merge/write/done) and,
    once the dispatch event fires, to ``/api/agent/{agent_run_id}/stream`` for
    the agent's live console.

    The final rules.yaml is written when the job finishes; poll
    ``/api/review/rules`` to fetch the new rule set."""
    from test1.review import rule_gen
    job_id = rule_gen.start_generate_job()
    return {"job_id": job_id}


# NOTE: static routes (``.../latest``) must be registered BEFORE the dynamic
# ``/{job_id}`` route — FastAPI matches in declaration order.
@app.get("/api/review/rules/generate/latest")
def review_rules_generate_latest() -> dict:
    """Return the latest job summary, or ``{job_id: null}`` if none exists."""
    from test1.review import rule_gen
    jid = rule_gen.latest_job_id()
    if not jid:
        return {"job_id": None}
    J = rule_gen.get_job(jid)
    if not J:
        return {"job_id": None}
    return rule_gen.job_summary(J)


@app.get("/api/review/rules/generate/{job_id}")
def review_rules_generate_get(job_id: str) -> dict:
    from test1.review import rule_gen
    J = rule_gen.get_job(job_id)
    if not J:
        raise HTTPException(404, "no such job")
    return rule_gen.job_summary(J)


@app.get("/api/review/rules/generate/{job_id}/stream")
async def review_rules_generate_stream(job_id: str) -> StreamingResponse:
    """SSE stream of phase events. Mirrors ``/api/loop/{loop_id}/stream``:
    if the job already finished, emit a synthetic ``done`` (or ``error``)
    frame immediately so late subscribers don't hang."""
    from test1.review import rule_gen
    J = rule_gen.get_job(job_id)
    if not J:
        raise HTTPException(404, "no such job")

    async def gen() -> AsyncIterator[bytes]:
        if J.status != "running":
            # Late-subscriber synthetic frame -- the agent_run_id is preserved
            # so the UI can still pin the console to the finished agent.
            ev = "done" if J.status == "ok" else "error"
            data = {
                "phase": J.phase,
                "status": J.status,
                "agent_run_id": J.agent_run_id,
                "result": J.result,
                "error": J.error,
            }
            yield f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode()
            return
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        J.subscribers.append(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    return
                evname = item.get("event", "message")
                data = json.dumps(item.get("data", {}))
                yield f"event: {evname}\ndata: {data}\n\n".encode()
        finally:
            try:
                J.subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


class RuleEditBody(BaseModel):
    rule_id: str
    enabled: bool | None = None
    title: str | None = None
    severity: str | None = None
    fix_hint: str | None = None
    prompt: str | None = None     # only valid for semantic rules


@app.post("/api/review/rules/edit")
def review_rules_edit(body: RuleEditBody) -> dict:
    """Edit a single rule by id. Marks origin='user' so the edit survives
    regenerate."""
    from test1.review.rule_eval import load_rules, save_rules
    rf = load_rules()
    target = next((r for r in rf.rules if r.id == body.rule_id), None)
    if not target:
        raise HTTPException(404, f"rule not found: {body.rule_id}")
    if body.enabled is not None:    target.enabled = body.enabled
    if body.title is not None:      target.title = body.title
    if body.severity is not None:   target.severity = body.severity  # type: ignore[assignment]
    if body.fix_hint is not None:   target.fix_hint = body.fix_hint
    if body.prompt is not None and hasattr(target, "prompt"):
        target.prompt = body.prompt
    target.origin = "user"
    save_rules(rf)
    return {"ok": True, "rule": target.model_dump(exclude_none=True)}


@app.delete("/api/review/rules/{rule_id}")
def review_rules_delete(rule_id: str) -> dict:
    """Soft-delete: sets enabled=false. Hard-delete: pass ?hard=true."""
    from test1.review.rule_eval import load_rules, save_rules
    rf = load_rules()
    target = next((r for r in rf.rules if r.id == rule_id), None)
    if not target:
        raise HTTPException(404, f"rule not found: {rule_id}")
    target.enabled = False
    target.origin = "user"
    save_rules(rf)
    return {"ok": True, "rule_id": rule_id, "enabled": False}


@app.get("/api/review/providers")
def review_providers() -> dict:
    """Diagnostic: which backend implementation is bound to each provider
    slot (parts / knowledge / rulegen / chat). Surfaced in the Resources
    tab so the user can confirm a Custom*APIProvider swap took effect."""
    from test1.review.providers import configured_providers
    return configured_providers()


# ===========================================================================
# Closed-loop design review -- Loop endpoints
# ===========================================================================

from test1.review import closed_loop as _loop_mod


@app.post("/api/loop/start")
async def loop_start() -> dict:
    # Reject if another loop is currently running.
    for L in _loop_mod._LOOPS.values():
        if L.status == "running":
            raise HTTPException(409, f"loop {L.loop_id} already running")
    loop_id = _loop_mod.start_loop()
    return {"loop_id": loop_id}


@app.get("/api/loop/latest")
def loop_latest() -> dict:
    lid = _loop_mod.latest_loop_id()
    if not lid:
        return {"loop_id": None}
    L = _loop_mod.get_loop(lid)
    if L:
        return _loop_mod.loop_summary(L)
    # Fallback: read from disk
    audit = _loop_mod.LOOPS_STATE_DIR / f"{lid}.json"
    if audit.exists():
        return json.loads(audit.read_text(encoding="utf-8"))
    return {"loop_id": None}


@app.get("/api/loop/{loop_id}")
def loop_get(loop_id: str) -> dict:
    L = _loop_mod.get_loop(loop_id)
    if L:
        return _loop_mod.loop_summary(L)
    audit = _loop_mod.LOOPS_STATE_DIR / f"{loop_id}.json"
    if audit.exists():
        return json.loads(audit.read_text(encoding="utf-8"))
    raise HTTPException(404, "no such loop")


@app.get("/api/loop/{loop_id}/stream")
async def loop_stream(loop_id: str) -> StreamingResponse:
    L = _loop_mod.get_loop(loop_id)
    if not L:
        raise HTTPException(404, "no such loop")

    async def gen() -> AsyncIterator[bytes]:
        # Replay buffered events: we don't keep a buffer (subscribers attach
        # for live events only). If the loop is already done, send a single
        # 'done' frame from the audit so late subscribers don't hang.
        if L.status != "running":
            yield (f"event: done\ndata: "
                   f"{json.dumps({'status': L.status, 'rounds': len(L.rounds), 'remaining': len(L.findings_current)})}"
                   f"\n\n").encode()
            return
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        L.subscribers.append(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    return
                ev = item.get("event", "message")
                data = json.dumps(item.get("data", {}))
                yield f"event: {ev}\ndata: {data}\n\n".encode()
        finally:
            try:
                L.subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/loop/{loop_id}/cancel")
def loop_cancel(loop_id: str) -> dict:
    ok = _loop_mod.cancel_loop(loop_id)
    if not ok:
        raise HTTPException(404, "no such loop")
    return {"ok": True}


@app.post("/api/loop/{loop_id}/accept")
def loop_accept(loop_id: str) -> dict:
    L = _loop_mod.get_loop(loop_id)
    if not L:
        raise HTTPException(404, "no such loop")
    _loop_mod.archive_snapshot(L)
    return {"ok": True}


class LoopRejectBody(BaseModel):
    revert: list[str] | None = None    # refdes list for selective revert


@app.post("/api/loop/{loop_id}/reject")
async def loop_reject(loop_id: str, body: LoopRejectBody = LoopRejectBody()) -> dict:
    L = _loop_mod.get_loop(loop_id)
    if not L:
        raise HTTPException(404, "no such loop")
    _loop_mod.restore_from_snapshot(L, refdes_revert=body.revert)
    # Rebuild once to refresh out/render
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "test1.altium.build_project",
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return {"ok": True, "rebuild_status": proc.returncode == 0,
            "rebuild_log_tail": out.decode("utf-8", errors="replace")[-2000:]}


@app.get("/api/loop/{loop_id}/diff")
def loop_diff(loop_id: str) -> dict:
    from test1.review.diff import compute_loop_diff
    return {"loop_id": loop_id, "sheets": compute_loop_diff(loop_id)}


@app.get("/api/png_snapshot/{loop_id}/{name}")
def png_snapshot(loop_id: str, name: str):
    """Serve a pre-loop snapshot render for the Diff & Accept side-by-side
    view. name is the sheet stem (no extension)."""
    safe = re.sub(r"[^A-Za-z0-9_]", "", name)
    snap = _loop_mod.SNAPSHOT_ROOT / loop_id / "render" / f"{safe}.svg"
    if not snap.exists():
        raise HTTPException(404, f"snapshot render not found: {snap}")
    return FileResponse(snap, media_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})


def main() -> None:
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
