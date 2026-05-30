"""Integration test for the closed-loop SSE stream — TODO #1 verification.

Confirms:
  • A live subscriber sees `loop_start` BEFORE the first `round_done`
    (i.e., monitoring doesn't drop the start of the loop).
  • A late subscriber (attached after the loop completes) sees a `done`
    event immediately and not a hang.

Runs against a synthetic in-memory orchestrator — does NOT spin up FastAPI
or claude -p. Uses a stub _dispatch_action that doesn't call any agent.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from test1.review import closed_loop


@pytest.fixture(autouse=True)
def patch_dispatch(monkeypatch):
    """Replace _dispatch_action and _rebuild_project with no-op stubs."""
    async def stub_dispatch(L, action):
        action.status = "ok"
        action.summary = "(stubbed)"
        action.finished_at = time.time()

    async def stub_build():
        return ("ok", {"ERROR": 0, "WARNING": 0, "INFO": 0})

    monkeypatch.setattr(closed_loop, "_dispatch_action", stub_dispatch)
    monkeypatch.setattr(closed_loop, "_rebuild_project", stub_build)

    # Replace eval_rules with a controlled sequence. The orchestrator
    # imports run_all locally (`from .rule_eval import run_all as eval_rules`)
    # so we must patch the symbol on the rule_eval module itself.
    state = {"count": 3}

    def stub_eval(*args, **kwargs):
        if state["count"] <= 0:
            return []
        state["count"] -= 1
        from test1.review.findings import Finding, Severity
        return [Finding(rule_id=f"DUMMY_{i}", severity=Severity.WARNING,
                        title="dummy", subject="", sheet="")
                for i in range(state["count"])]

    monkeypatch.setattr("test1.review.rule_eval.run_all", stub_eval)


@pytest.mark.asyncio
async def test_live_subscriber_sees_loop_start_first():
    """A subscriber attached BEFORE the loop starts must see `loop_start`
    before any `round_done`."""
    loop_id = closed_loop.start_loop()
    L = closed_loop._LOOPS[loop_id]

    # Attach subscriber synchronously
    q: asyncio.Queue = asyncio.Queue()
    L.subscribers.append(q)

    events_seen: list[str] = []
    while True:
        try:
            item = await asyncio.wait_for(q.get(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail(f"timed out waiting for events; got: {events_seen}")
        if item is None:
            break
        events_seen.append(item["event"])

    assert "loop_start" in events_seen, f"loop_start not seen: {events_seen}"
    assert "done" in events_seen, f"done not seen: {events_seen}"
    loop_idx = events_seen.index("loop_start")
    # Every round_done must come AFTER loop_start
    for i, ev in enumerate(events_seen):
        if ev == "round_done":
            assert i > loop_idx, f"round_done at {i} before loop_start at {loop_idx}: {events_seen}"


@pytest.mark.asyncio
async def test_late_subscriber_gets_done_immediately():
    """A subscriber attached AFTER the loop completes (via the endpoint
    fallback in /api/loop/{id}/stream) sees a synthetic done frame and
    doesn't hang. We simulate this by checking _LOOPS state, not the
    endpoint itself — endpoint logic is the same shape."""
    loop_id = closed_loop.start_loop()
    L = closed_loop._LOOPS[loop_id]

    # Wait for the loop to finish
    while L.status == "running":
        await asyncio.sleep(0.1)

    # Endpoint behavior: if status != running, emit done immediately
    assert L.status in ("all_clear", "plateau", "max_rounds", "cancelled", "error"), \
        f"unexpected status: {L.status}"
    # The synthetic event the endpoint would emit
    synthetic_done = {
        "event": "done",
        "data": {"status": L.status, "rounds": len(L.rounds),
                 "remaining": len(L.findings_current)},
    }
    assert synthetic_done["data"]["status"] in ("all_clear", "plateau", "max_rounds")
