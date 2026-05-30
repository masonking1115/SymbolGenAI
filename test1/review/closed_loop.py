"""Closed-loop design-review orchestrator.

The outer loop is Python-driven (this module); each round's work is
dispatched to existing sub-AgentRuns (apply / lint_fix / symbol_gen / sim_*
/ missing_part / topology_adapt) via test1/gui/backend/agent.py.

Lifecycle per loop:
  1. Snapshot pre-loop state to out/render_snapshots/<loop_id>/.
  2. Loop over rounds (max 10) until all-clear / plateau / cancel / error.
  3. Each round: evaluate rules -> plan_actions -> dispatch -> rebuild ->
     re-evaluate -> compute delta -> check plateau.
  4. On halt: persist audit, post plateau changelog (if plateau), wait
     for /accept or /reject.

State stores:
  - _LOOPS: dict[loop_id, Loop]  -- in-process, lost on backend restart
  - test1/gui/state/loops/<loop_id>.json  -- on-disk audit, survives restart

Spec section 4.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import AsyncIterator

from .findings import Finding, Severity


PROJECT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_DIR.parent
OUT_DIR = PROJECT_DIR / "altium" / "out"
RENDER_DIR = OUT_DIR / "render"
NETLIST_DIR = PROJECT_DIR / "netlist"
SNAPSHOT_ROOT = OUT_DIR / "render_snapshots"
LOOPS_STATE_DIR = PROJECT_DIR / "gui" / "state" / "loops"

MAX_ROUNDS = 10
PLATEAU_STREAK = 2
WEB_CALL_BUDGET = 50         # parts + knowledge fetches across one loop


# ---- Dataclasses --------------------------------------------------------

@dataclass
class Action:
    kind: str                 # "apply" | "lint_fix" | "symbol_gen" |
                              #   "missing_part" | "sim" | "topology_adapt"
    agent_run_id: str | None = None
    targets: list[str] = field(default_factory=list)   # rule IDs or refdes
    status: str = "running"   # "running" | "ok" | "fail" | "cancelled"
    summary: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


@dataclass
class Round:
    n: int
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    findings_before: int = 0
    findings_after: int = 0
    findings_cleared: list[str] = field(default_factory=list)
    findings_new: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    build_status: str = ""           # "ok" | "fail" | "skipped"
    lint_summary: dict | None = None
    sim_results: list[dict] = field(default_factory=list)


@dataclass
class Loop:
    loop_id: str
    started_at: float
    status: str = "running"      # "running" | "all_clear" | "plateau" |
                                 #   "max_rounds" | "cancelled" | "error"
    round: int = 0
    rounds: list[Round] = field(default_factory=list)
    findings_initial: list[Finding] = field(default_factory=list)
    findings_current: list[Finding] = field(default_factory=list)
    snapshot_dir: Path | None = None
    sub_runs: list[str] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    cancelled: bool = False
    last_delta: int | None = None
    plateau_streak: int = 0
    finished_at: float | None = None
    error: str = ""
    web_call_count: int = 0       # missing-part flow increments this


_LOOPS: dict[str, Loop] = {}


# ---- Public lookups -----------------------------------------------------

def get_loop(loop_id: str) -> Loop | None:
    return _LOOPS.get(loop_id)


def latest_loop_id() -> str | None:
    """Most recent loop_id (running or completed)."""
    if not _LOOPS:
        # Try disk
        if LOOPS_STATE_DIR.exists():
            audits = sorted(LOOPS_STATE_DIR.glob("*.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
            if audits:
                return audits[0].stem
        return None
    return max(_LOOPS.keys(),
               key=lambda lid: _LOOPS[lid].started_at)


def loop_summary(L: Loop) -> dict:
    """Wire-format snapshot for /api/loop/{id}."""
    return {
        "loop_id": L.loop_id,
        "status": L.status,
        "round": L.round,
        "started_at": L.started_at,
        "finished_at": L.finished_at,
        "rounds": [_round_to_wire(r) for r in L.rounds],
        "findings_initial": len(L.findings_initial),
        "findings_current": len(L.findings_current),
        "last_delta": L.last_delta,
        "plateau_streak": L.plateau_streak,
        "error": L.error,
    }


def _round_to_wire(r: Round) -> dict:
    return {
        "n": r.n,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "findings_before": r.findings_before,
        "findings_after": r.findings_after,
        "findings_cleared": r.findings_cleared,
        "findings_new": r.findings_new,
        "actions": [asdict(a) for a in r.actions],
        "build_status": r.build_status,
        "lint_summary": r.lint_summary,
        "sim_results": r.sim_results,
    }
