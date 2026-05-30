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


# ---- Snapshot mechanics -------------------------------------------------

def snapshot_pre_loop(L: Loop) -> None:
    """Copy out/render/*.svg + netlist/*.yaml + out/lint.json +
    review/findings.json to out/render_snapshots/<loop_id>/."""
    L.snapshot_dir = SNAPSHOT_ROOT / L.loop_id
    L.snapshot_dir.mkdir(parents=True, exist_ok=True)
    (L.snapshot_dir / "render").mkdir(exist_ok=True)
    (L.snapshot_dir / "netlist").mkdir(exist_ok=True)

    if RENDER_DIR.exists():
        for svg in RENDER_DIR.glob("*.svg"):
            shutil.copy2(svg, L.snapshot_dir / "render" / svg.name)
    if NETLIST_DIR.exists():
        for y in NETLIST_DIR.glob("*.yaml"):
            shutil.copy2(y, L.snapshot_dir / "netlist" / y.name)
    lint_json = OUT_DIR / "lint.json"
    if lint_json.exists():
        shutil.copy2(lint_json, L.snapshot_dir / "lint.json")
    findings_json = PROJECT_DIR / "review" / "findings.json"
    if findings_json.exists():
        shutil.copy2(findings_json, L.snapshot_dir / "findings_initial.json")


def restore_from_snapshot(L: Loop, refdes_revert: list[str] | None = None) -> None:
    """Reject path. If refdes_revert is None -> full restore. Otherwise ->
    selective restore: per-refdes YAML surgery (replace one part block
    or one net membership). Full restore overwrites netlist/*.yaml,
    out/render/*.svg, out/lint.json from the snapshot."""
    if not L.snapshot_dir or not L.snapshot_dir.exists():
        raise FileNotFoundError(f"no snapshot for loop {L.loop_id}")

    if refdes_revert is None:
        # Full restore
        snap_netlist = L.snapshot_dir / "netlist"
        if snap_netlist.exists():
            for y in snap_netlist.glob("*.yaml"):
                shutil.copy2(y, NETLIST_DIR / y.name)
        snap_render = L.snapshot_dir / "render"
        if snap_render.exists():
            for svg in snap_render.glob("*.svg"):
                shutil.copy2(svg, RENDER_DIR / svg.name)
        snap_lint = L.snapshot_dir / "lint.json"
        if snap_lint.exists():
            shutil.copy2(snap_lint, OUT_DIR / "lint.json")
        return

    # Selective revert -- YAML-level surgery per refdes
    # For each sheet's netlist, walk parts + nets, restore the entries
    # for the named refdes(s) from the snapshot version.
    import yaml as _yaml
    for current_yaml in NETLIST_DIR.glob("*.yaml"):
        snap_yaml = L.snapshot_dir / "netlist" / current_yaml.name
        if not snap_yaml.exists():
            continue
        cur = _yaml.safe_load(current_yaml.read_text(encoding="utf-8")) or {}
        snap = _yaml.safe_load(snap_yaml.read_text(encoding="utf-8")) or {}
        cur_parts = cur.get("parts", {})
        snap_parts = snap.get("parts", {})
        cur_nets = cur.get("nets", {})
        snap_nets = snap.get("nets", {})

        for rd in refdes_revert:
            if rd in snap_parts:
                cur_parts[rd] = snap_parts[rd]
            elif rd in cur_parts:
                del cur_parts[rd]
            # Net memberships involving this refdes
            for net, members in list(cur_nets.items()):
                if isinstance(members, list):
                    cur_nets[net] = [m for m in members if not
                                     (isinstance(m, dict) and m.get("refdes") == rd
                                      or isinstance(m, str) and m.startswith(f"{rd}."))]
                    snap_members = snap_nets.get(net, [])
                    for sm in snap_members:
                        is_match = (isinstance(sm, dict) and sm.get("refdes") == rd
                                    or isinstance(sm, str) and sm.startswith(f"{rd}."))
                        if is_match and sm not in cur_nets[net]:
                            cur_nets[net].append(sm)
        cur["parts"] = cur_parts
        cur["nets"] = cur_nets
        current_yaml.write_text(_yaml.safe_dump(cur, sort_keys=False),
                                encoding="utf-8")


def archive_snapshot(L: Loop) -> None:
    """Accept path -- tar + remove the snapshot dir."""
    if not L.snapshot_dir or not L.snapshot_dir.exists():
        return
    import tarfile
    tar = SNAPSHOT_ROOT / f"{L.loop_id}.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(L.snapshot_dir, arcname=L.loop_id)
    shutil.rmtree(L.snapshot_dir)
    L.snapshot_dir = None


# ---- Planner -- map findings to round actions ---------------------------

def plan_actions(findings: list[Finding]) -> list[Action]:
    """Bucket findings by required action kind. Returns a list of Actions
    (one per kind per round); the orchestrator dispatches them in order.

    Bucketing rules (Spec section 4 plan_actions table):
      - decoupling_count / pullup_pulldown / no_connect -> 'apply' (trivial,
        grouped into one call)
      - present (role_spec / unknown mpn) -> 'missing_part' (one per finding)
      - present (known mpn, just not placed) -> 'apply'
      - net_routing / connector_pin / power_rail_membership / value_in_range
                                          -> 'apply' (non-trivial structural)
      - sim_pass / sim_metric -> 'sim'
      - semantic (any family) -> 'apply' (semantic mode)
      - ERROR-lint / build-fail finding -> 'lint_fix'
    """
    from .rule_schema import StructuralRule    # local import -- avoids cycle

    apply_bucket: list[str] = []
    sim_bucket: list[str] = []
    missing_part_actions: list[Action] = []
    lint_fix_targets: list[str] = []

    # Load rules to look up predicate.kind per finding's rule_id.
    from .rule_eval import load_rules
    rules_by_id = {r.id: r for r in load_rules().rules}

    for f in findings:
        rule = rules_by_id.get(f.rule_id)
        if rule is None:
            apply_bucket.append(f.rule_id)
            continue

        if rule.evaluation == "semantic":
            apply_bucket.append(f.rule_id)
            continue

        # StructuralRule
        assert isinstance(rule, StructuralRule)
        kind = rule.predicate.kind
        if kind == "present":
            mpn = rule.applies_to.mpn
            role = rule.applies_to.role_spec
            if not mpn or role:
                # by-spec or unknown-mpn -> missing_part flow
                missing_part_actions.append(Action(
                    kind="missing_part", targets=[f.rule_id]))
            else:
                apply_bucket.append(f.rule_id)
        elif kind in ("sim_pass", "sim_metric"):
            sim_bucket.append(f.rule_id)
        elif kind in ("decoupling_count", "pullup_pulldown", "no_connect",
                      "net_routing", "connector_pin",
                      "power_rail_membership", "value_in_range"):
            apply_bucket.append(f.rule_id)
        else:
            apply_bucket.append(f.rule_id)

    out: list[Action] = []
    if apply_bucket:
        out.append(Action(kind="apply", targets=apply_bucket))
    if missing_part_actions:
        out.extend(missing_part_actions)
    if sim_bucket:
        out.append(Action(kind="sim", targets=sim_bucket))
    return out
