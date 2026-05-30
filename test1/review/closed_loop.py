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


# ---- Event emission to subscribers --------------------------------------

async def emit(L: Loop, event: str, **data) -> None:
    """Fan-out an SSE event to every subscriber queue. Drops on slow consumers."""
    payload = {"event": event, "data": data}
    for q in list(L.subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


# ---- Sub-agent dispatch wrappers (call into agent.py) -------------------

async def _dispatch_action(L: Loop, action: Action) -> None:
    """Run one Action to completion. Updates action.status + summary in place."""
    import sys
    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod

    if action.kind == "apply":
        # Look up findings for the targeted rule IDs to build a context blob.
        # Reuse existing start_apply_pass -- it reads the changelog. We
        # bypass the changelog by setting up a synthetic one-shot context.
        # For Phase 4, we use the existing apply agent + emit the targets
        # in its prompt by pushing them to changelog first.
        for rid in action.targets:
            agent_mod.append_changelog(
                f"closed-loop: address rule {rid}",
                source="closed_loop",
            )
        run = await agent_mod.start_apply_pass()
        action.agent_run_id = run.run_id
        L.sub_runs.append(run.run_id)
        while run.status == "running":
            if L.cancelled:
                agent_mod.cancel_run(run.run_id)
                action.status = "cancelled"
                action.finished_at = time.time()
                return
            await asyncio.sleep(0.5)
        action.status = "ok" if run.status == "ok" else "fail"
        action.summary = f"apply pass: {run.status} ({len(action.targets)} targets)"

    elif action.kind == "lint_fix":
        # Read current lint failures + dispatch lint_fix agent
        from .closed_loop_helpers import _read_lint_failures
        failures = _read_lint_failures()
        run = await agent_mod.start_lint_fix_pass(failures, round_no=L.round,
                                                  max_rounds=MAX_ROUNDS)
        action.agent_run_id = run.run_id
        L.sub_runs.append(run.run_id)
        while run.status == "running":
            if L.cancelled:
                agent_mod.cancel_run(run.run_id)
                action.status = "cancelled"
                action.finished_at = time.time()
                return
            await asyncio.sleep(0.5)
        action.status = "ok" if run.status == "ok" else "fail"
        action.summary = f"lint_fix: {run.status}"

    elif action.kind == "sim":
        # Run the named (block, sim_type) sims via sim_service
        from test1.sim import service as sim_service
        from .rule_eval import load_rules
        rules_by_id = {r.id: r for r in load_rules().rules}
        results = []
        for rid in action.targets:
            rule = rules_by_id.get(rid)
            if not rule or not getattr(rule.applies_to, "sim_block", None):
                continue
            block = rule.applies_to.sim_block
            stype = rule.applies_to.sim_type
            if not stype:
                continue
            try:
                res = sim_service.run_block_sim(block, stype)
                results.append({"block": block, "sim_type": stype,
                                "ok": bool(res.get("ok"))})
            except Exception as e:
                results.append({"block": block, "sim_type": stype,
                                "ok": False, "error": str(e)})
        action.status = "ok" if results and all(r.get("ok") for r in results) else "fail"
        action.summary = f"sim: {sum(1 for r in results if r.get('ok'))}/{len(results)} ok"
        # store results on the action for round.sim_results aggregation
        if L.rounds:
            L.rounds[-1].sim_results.extend(results)

    elif action.kind == "missing_part":
        from .missing_part import run_missing_part_action
        audit = await run_missing_part_action(L, action)
        # Stash the per-action audit on the round for the UI to surface
        if L.rounds:
            L.rounds[-1].sim_results.extend([
                {"audit_kind": "missing_part",
                 "rule_id": audit.rule_id,
                 "status": audit.status,
                 "candidates": [asdict(c) for c in audit.candidates_considered],
                 "topology": audit.topology_adaptations}
            ])

    else:
        action.status = "fail"
        action.summary = f"unknown action kind: {action.kind}"

    action.finished_at = time.time()


_VENV_PY = Path(r"C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe")


async def _rebuild_project() -> tuple[str, dict | None]:
    """Run python -m test1.altium.build_project as a subprocess. Returns
    (status, lint_summary)."""
    proc = await asyncio.create_subprocess_exec(
        str(_VENV_PY), "-m", "test1.altium.build_project",
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    status = "ok" if proc.returncode == 0 else "fail"
    lint_summary = None
    lint_json = OUT_DIR / "lint.json"
    if lint_json.exists():
        try:
            data = json.loads(lint_json.read_text(encoding="utf-8"))
            lint_summary = {
                "ERROR":   sum(1 for f in data if f.get("severity") == "ERROR"),
                "WARNING": sum(1 for f in data if f.get("severity") == "WARNING"),
                "INFO":    sum(1 for f in data if f.get("severity") == "INFO"),
            }
        except Exception:
            pass
    return status, lint_summary


# ---- The main loop ------------------------------------------------------

async def run_loop(loop_id: str) -> None:
    """Top-level orchestrator. Runs in a background task started by
    POST /api/loop/start."""
    L = _LOOPS[loop_id]
    try:
        snapshot_pre_loop(L)
        _clear_sim_cache_for_review()

        from .rule_eval import run_all as eval_rules
        # Bridge run_all's per-rule progress (called from the worker thread) back
        # to the loop's SSE via the running event loop, so the review console
        # streams "evaluating rule i/N …" activity even before any apply agent
        # spawns (the eval phase was previously invisible — empty console).
        _ev_loop = asyncio.get_running_loop()

        def _progress(kind: str, data: dict) -> None:
            try:
                asyncio.run_coroutine_threadsafe(
                    emit(L, "eval_progress", **data), _ev_loop)
            except Exception:
                pass

        # semantic=True exercises the LLM-judged rules too; run off the event
        # loop thread since each is a blocking claude -p call (keeps SSE + cancel
        # responsive). Fail-safe inside run_all: a flaky agent yields no finding.
        await emit(L, "eval_start", phase="initial")
        L.findings_initial = await asyncio.to_thread(
            eval_rules, None, None, True, _progress)
        L.findings_current = list(L.findings_initial)
        await emit(L, "eval_done", findings=len(L.findings_initial))
        await emit(L, "loop_start", findings=len(L.findings_initial))

        for r in range(1, MAX_ROUNDS + 1):
            if L.cancelled:
                break
            if not L.findings_current:
                break  # all-clear

            R = Round(n=r, findings_before=len(L.findings_current))
            L.round = r
            L.rounds.append(R)
            await emit(L, "round_start", round=r,
                       findings=R.findings_before)

            for action in plan_actions(L.findings_current):
                if L.cancelled:
                    break
                R.actions.append(action)
                await emit(L, "action_start",
                           round=r, kind=action.kind,
                           targets=action.targets)
                await _dispatch_action(L, action)
                await emit(L, "action_end",
                           round=r, kind=action.kind,
                           agent_run_id=action.agent_run_id,
                           status=action.status,
                           summary=action.summary)

            if not L.cancelled:
                await emit(L, "build_start", round=r)
                R.build_status, R.lint_summary = await _rebuild_project()
                await emit(L, "build_end", round=r,
                           status=R.build_status, lint=R.lint_summary)

            # Re-evaluate (semantic too, off-thread — see loop_start note)
            await emit(L, "eval_start", phase=f"re-eval round {r}")
            new_findings = await asyncio.to_thread(
                eval_rules, None, None, True, _progress)
            await emit(L, "eval_done", findings=len(new_findings))
            R.findings_after = len(new_findings)
            old_ids = {f.rule_id for f in L.findings_current}
            new_ids = {f.rule_id for f in new_findings}
            cleared = sorted(old_ids - new_ids)
            added = sorted(new_ids - old_ids)
            R.findings_cleared = cleared
            R.findings_new = added
            delta = len(cleared) - len(added)
            L.findings_current = new_findings
            L.last_delta = delta
            L.plateau_streak = (L.plateau_streak + 1) if delta <= 0 else 0
            R.finished_at = time.time()
            await emit(L, "round_done", round=r,
                       delta=delta, cleared=cleared, new=added,
                       remaining=R.findings_after)

            if L.plateau_streak >= PLATEAU_STREAK:
                L.status = "plateau"
                break

        if not L.cancelled and L.status == "running":
            L.status = "all_clear" if not L.findings_current else "max_rounds"
        if L.cancelled:
            L.status = "cancelled"

    except Exception as e:
        L.status = "error"
        L.error = str(e)
        import traceback
        await emit(L, "error", message=str(e),
                   traceback=traceback.format_exc())

    L.finished_at = time.time()
    persist_audit(L)
    # NOTE: we deliberately do NOT write a plateau report into the changelog.
    # The changelog is the ACTIONABLE queue (items an apply pass implements); a
    # plateau is a status, not an action, so it would linger forever unconsumed.
    # The plateau + unresolved count is already surfaced via the loop summary,
    # the 'done' event, and the Iteration panel banner.
    await emit(L, "done", status=L.status,
               rounds=len(L.rounds),
               remaining=len(L.findings_current))

    # Send sentinel to all subscribers
    for q in list(L.subscribers):
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass


def _clear_sim_cache_for_review() -> None:
    """Start the review's simulations from scratch: drop the cached scenario +
    re-sim counters for every block referenced by a sim_review rule, so the
    sim-setup pass re-derives params and the sim re-runs fresh (no stale result
    reused across reviews). Best-effort; failures are non-fatal."""
    try:
        from .rule_eval import load_rules
        from .rule_schema import StructuralRule
        from test1.sim import simconfig
        blocks = {r.predicate.sim_block for r in load_rules().rules
                  if isinstance(r, StructuralRule)
                  and r.predicate.kind == "sim_review"}
        for b in blocks:
            try:
                simconfig.clear_scenario(b)
                simconfig.clear_iter_counters(b)
            except Exception:
                pass
    except Exception:
        pass


def persist_audit(L: Loop) -> None:
    """Write the loop's audit JSON to disk for survives-restart Diff & Accept."""
    LOOPS_STATE_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = LOOPS_STATE_DIR / f"{L.loop_id}.json"
    audit_path.write_text(json.dumps(loop_summary(L), indent=2,
                                     default=str), encoding="utf-8")




def start_loop() -> str:
    """Allocate a new Loop, register it, kick off the run task."""
    loop_id = uuid.uuid4().hex[:8]
    L = Loop(loop_id=loop_id, started_at=time.time())
    _LOOPS[loop_id] = L
    asyncio.create_task(run_loop(loop_id))
    return loop_id


def cancel_loop(loop_id: str) -> bool:
    L = _LOOPS.get(loop_id)
    if not L:
        return False
    L.cancelled = True
    return True
