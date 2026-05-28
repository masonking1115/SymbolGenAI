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
# Drop folder for incoming review PDFs (parsed by install_review.py).
REVIEW_INCOMING = PROJECT_DIR.parent / "_review_incoming"
REVIEW_INSTALL_SCRIPT = REVIEW_INCOMING / "install_review.py"
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
def state() -> dict:
    sheets = sorted(p.stem for p in RENDER_DIR.glob(f"*.{RENDER_EXT}")) if RENDER_DIR.exists() else []
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

    Inputs:  netlist/*.yaml, gen/*.py, Parts Library/**/*.SchLib
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


# ---- Sheet PNGs ----------------------------------------------------------
@app.get("/api/sheets")
def sheets() -> dict:
    if not RENDER_DIR.exists():
        return {"sheets": []}
    out = []
    for p in sorted(RENDER_DIR.glob(f"*.{RENDER_EXT}")):
        st = p.stat()
        out.append({"name": p.stem, "size": st.st_size, "mtime": st.st_mtime})
    return {"sheets": out}


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
def lint(run_id: str | None = None) -> dict:
    """Return the lint report for the MOST RECENT build.

    Altium backend: `build_project` writes `out/lint.json` (every issue, all
    severities, attributed per sheet) on each build. We serve that file so the
    checklist reflects the current on-disk build and survives a backend restart
    — independent of whether a generate run is still in this process's memory.
    Falls back to parsing the last generate run's console output (and, for the
    legacy KiCad backend, that is the only source).

    Also returns the static rule registry so the frontend can render the full
    checklist (pass/fail per rule) even when nothing fired.
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
            return {
                "run_id": None,
                "status": data.get("status", "unknown"),
                "generated_at": data.get("generated_at"),
                "issues": issues,
                "rules": rules,
                "counts": counts,
            }
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
    """Return review findings.

    findings.json may be either (a) a bare list of Finding dicts (legacy
    KiCad run_review.py path) or (b) a dict envelope produced by the
    Voltai-PDF parser `_review_incoming/install_review.py`
    ({ project, findings: [...], semantic: [...], summary: {...}, sources }).
    Both shapes are accepted."""
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


# ---- Simulation (ngspice-backed) -----------------------------------------
class SimRunReq(BaseModel):
    block: str
    sim_type: str
    # None → the service uses the agent-determined operating point (sim_config),
    # falling back to 1.8V only if no scenario has been determined yet.
    vout_set: float | None = None


@app.get("/api/sim/blocks")
def sim_blocks() -> dict:
    return {"blocks": sim_service.list_blocks()}


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
    # KiCad backend needs gen_schematic.py; the Altium backend builds a module.
    if BACKEND != "altium" and not GEN_SCRIPT.exists():
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
        # Now start the generate subprocess — mirror run_generate's backend
        # selection so this machine drives the Altium pipeline (build_project),
        # not the KiCad gen_schematic.py which reads .kicad_sym files.
        if BACKEND == "altium":
            cmd = [sys.executable, "-m", "test1.altium.build_project"]
            return await _start_run("generate", cmd, cwd=str(REPO_ROOT))
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


# ---- Voltai PDF review ingest + Apply-fix queue --------------------------
#
# Two parts:
#   1. Upload a PDF -> POST /api/review/upload, body { filename, content_b64 }.
#      Backend writes the PDF into _review_incoming/ and runs install_review.py
#      (in the same Python env this backend runs in — the spike venv that has
#      fitz). After the script returns, GET /api/findings sees the new rows.
#
#   2. Per-row Apply -> POST /api/findings/{id}/apply, body
#      { action_index, action_kind, action_text }. Backend writes a request
#      into test1/review/fix_queue.json. The Claude agent reads that queue
#      in chat ("apply pending fixes"), verifies each, applies, and updates
#      the queue status. UI polls GET /api/fix-queue.
#
# Why a queue instead of synchronous LLM call: applying a review fix is
# semantically complex (schematic topology + symbol + YAML edits + rebuild
# verification) and needs the agent in the loop, not a one-shot prompt.

class ReviewUploadBody(BaseModel):
    filename: str
    content_b64: str


@app.post("/api/review/upload")
async def review_upload(body: ReviewUploadBody) -> dict:
    """Accept a review PDF from the GUI dropzone, write it into
    _review_incoming/, then invoke install_review.py to parse it into
    findings.json. Returns the new summary so the UI can refresh.
    """
    name = _safe_upload_name(body.filename, (".pdf",))
    raw = _decode_upload(body.content_b64)
    REVIEW_INCOMING.mkdir(parents=True, exist_ok=True)
    dest = REVIEW_INCOMING / name
    dest.write_bytes(raw)
    # Run the parser in the SAME interpreter as this backend (so it picks up
    # fitz from the spike venv automatically). The parser scans the folder
    # for new PDFs and moves them to _processed/ on success.
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(REVIEW_INSTALL_SCRIPT),
        cwd=str(REVIEW_INCOMING),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out_b, _ = await proc.communicate()
    parse_log = out_b.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise HTTPException(500, f"install_review.py failed:\n{parse_log[-1000:]}")
    return {
        "ok": True,
        "file": name,
        "size": len(raw),
        "parse_log": parse_log,
        "findings_after": findings(),
    }


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


def main() -> None:
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
