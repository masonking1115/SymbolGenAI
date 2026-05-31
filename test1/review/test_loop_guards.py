"""A6: regression tests for the loop SAFETY NETS — the mechanisms that keep a
misbehaving agent from (a) shipping a build regression or (b) hanging the loop
forever. These are the two failure modes that cost us a whole debugging session;
lock their logic in so they can't silently rot.

Fast + deterministic: we test the guard LOGIC (build-quality ordering, snapshot/
restore, the watchdog) with fakes — NOT by spawning real `claude -p` agents
(slow, non-deterministic, network-bound). A live end-to-end "agent finishes with
an edit in N s" check is valuable but belongs in a manual/opt-in run, not CI.

Run: python -m pytest test1/review/test_loop_guards.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# app.py lives in gui/backend; make it importable as `app`.
_BACKEND = Path(__file__).resolve().parent.parent / "gui" / "backend"
sys.path.insert(0, str(_BACKEND))

import agent  # noqa: E402
import app    # noqa: E402


# ---- propose-verify-commit: the loop may only IMPROVE or HOLD -------------
def _F(exit=0, status="pass", E=0, W=0, issues=None):
    return {"exit": exit, "status": status,
            "counts": {"ERROR": E, "WARNING": W}, "issues": issues or []}


def test_quality_rejects_trading_a_warning_for_a_short():
    """The exact regression from the session: clearing warnings while introducing
    a SHORT must score strictly WORSE (so the loop reverts it)."""
    clean = app._build_quality(_F(W=10))
    short = app._build_quality(_F(E=2, issues=[{"rule": "build_failed",
                                                "message": "SHORT: nets GND,SCLK"}]))
    assert short > clean, "a short must be worse than 10 warnings"


def test_quality_accepts_clearing_warnings():
    assert app._build_quality(_F(W=5)) < app._build_quality(_F(W=10))


def test_quality_broken_build_is_worst():
    assert app._build_quality(_F(exit=1, status="fail")) > app._build_quality(_F(W=99))


def test_snapshot_restore_round_trips(tmp_path, monkeypatch):
    """A restored snapshot puts edited files back exactly; created files are left."""
    d = tmp_path / "netlist"
    d.mkdir()
    f = d / "bias.yaml"
    f.write_text("orig\n", encoding="utf-8")
    monkeypatch.setattr(app, "_EDITABLE_DESIGN_DIRS", [d])
    snap = app._design_snapshot()
    f.write_text("TAMPERED\n", encoding="utf-8")            # agent edits it
    (d / "new.yaml").write_text("added\n", encoding="utf-8")  # agent adds a file
    restored = app._restore_snapshot(snap)
    assert f.read_text(encoding="utf-8") == "orig\n"          # edit undone
    assert "bias.yaml" in restored
    assert (d / "new.yaml").exists()                          # additive file kept


# ---- watchdog: a stuck agent can't hang the loop forever ------------------
class _FakeRun:
    def __init__(self, run_id="r"):
        self.run_id = run_id
        self.status = "running"
        self.proc = None


def test_watchdog_times_out_a_hung_agent():
    async def go():
        r = _FakeRun("hung")
        agent._RUNS[r.run_id] = r
        return await agent.await_run_bounded(r, timeout_s=0.2)
    assert asyncio.run(go()) == "timeout"


def test_watchdog_honors_cancel():
    async def go():
        r = _FakeRun("cancelme")
        agent._RUNS[r.run_id] = r
        return await agent.await_run_bounded(r, timeout_s=5, should_cancel=lambda: True)
    assert asyncio.run(go()) == "cancelled"


def test_watchdog_returns_ok_when_agent_finishes():
    async def go():
        r = _FakeRun("finisher")
        agent._RUNS[r.run_id] = r

        async def finish():
            await asyncio.sleep(0.2)
            r.status = "ok"
        t = asyncio.create_task(finish())
        disp = await agent.await_run_bounded(r, timeout_s=5)
        await t
        return disp
    assert asyncio.run(go()) == "ok"
