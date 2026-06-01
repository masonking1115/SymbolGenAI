"""End-to-end Design-Review loop monitor.

Triggers the SAME pipeline the Design Review tab's "Run review" button does
(POST /api/loop/start) and tails the SSE event stream (/api/loop/{id}/stream),
rendering every event live so a human can watch the full beginning-to-end run:
initial eval (structural + semantic + sim_review, semantic=True) -> rounds
(plan -> apply agents -> rebuild -> lint_fix -> scoped re-eval) -> terminal
state (all_clear / plateau / max_rounds / reverted / error).

Usage:
    python -m test1.review.e2e_monitor [--max-rounds N] [--label TEXT]

Pure stdlib (urllib) so it needs no extra deps; talks to the live :8765 backend.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8765"

# ANSI helpers (terminal is fine with these on Windows Terminal / VS Code).
def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m"

DIM = lambda s: _c("2", s)
BOLD = lambda s: _c("1", s)
CYAN = lambda s: _c("36", s)
GREEN = lambda s: _c("32", s)
YELLOW = lambda s: _c("33", s)
RED = lambda s: _c("31", s)
MAG = lambda s: _c("35", s)


def _post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        BASE + path, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _fmt_event(ev: str, data: dict) -> str | None:
    """Render one SSE event as a single console line (None = skip)."""
    t = DIM(f"[{_ts()}]")
    if ev == "eval_start":
        phase = data.get("phase", "")
        return f"{t} {CYAN('EVAL')}    start ({phase})"
    if ev == "eval_progress":
        # rule_eval emits: {i, total, id, evaluation, result}
        i, n = data.get("i"), data.get("total")
        rid = data.get("id") or ""
        evaln = data.get("evaluation", "")
        result = data.get("result", "")
        rcol = GREEN if result == "pass" else (RED if result == "fail" else YELLOW)
        # de-emphasise the fast structural passes; make sim/semantic + any FAIL pop.
        tag = DIM(evaln) if evaln == "structural" else CYAN(evaln)
        prog = f"{i}/{n}" if i and n else ""
        return f"{t} {CYAN('EVAL')}  {DIM(prog):>7} {rid:<28} {tag:<10} {rcol(result)}"
    if ev == "eval_done":
        return f"{t} {CYAN('EVAL')}    done -> {BOLD(str(data.get('findings')))} finding(s)"
    if ev == "loop_start":
        return f"{t} {MAG('LOOP')}    start, {data.get('findings')} initial finding(s)"
    if ev == "round_start":
        return f"{t} {MAG('ROUND ' + str(data.get('round')))} start ({data.get('findings')} finding(s) to address)"
    if ev == "action_start":
        targets = ", ".join(data.get("targets") or [])
        return f"{t}   {YELLOW('action')} {BOLD(data.get('kind',''))} -> {targets}"
    if ev == "action_end":
        st = data.get("status", "")
        col = GREEN if st == "ok" else (RED if st in ("fail", "error") else YELLOW)
        summ = (data.get("summary") or "").strip().replace("\n", " ")
        if len(summ) > 160:
            summ = summ[:157] + "..."
        rid = data.get("agent_run_id")
        rids = DIM(f" [{rid}]") if rid else ""
        return f"{t}   {YELLOW('action')} {data.get('kind','')} {col(st)}{rids}: {DIM(summ)}"
    if ev == "build_start":
        return f"{t}   {CYAN('build')}  rebuilding project ..."
    if ev == "build_end":
        st = data.get("status", "")
        col = GREEN if st in ("ok", "", "skipped") else RED
        lint = data.get("lint") or {}
        ls = ""
        if lint:
            ls = DIM(f" lint E{lint.get('ERROR',0)}/W{lint.get('WARNING',0)}/N{lint.get('NOTE',0)}")
        return f"{t}   {CYAN('build')}  {col(st or 'ok')}{ls}"
    if ev == "round_reverted":
        return f"{t} {RED('REVERT')}  round {data.get('round')}: {data.get('note','')}"
    if ev == "round_done":
        delta = data.get("delta", 0)
        cleared = data.get("cleared") or []
        added = data.get("new") or []
        rem = data.get("remaining")
        parts = []
        if cleared:
            parts.append(GREEN(f"cleared {len(cleared)}: {', '.join(cleared)}"))
        if added:
            parts.append(RED(f"new {len(added)}: {', '.join(added)}"))
        tail = ("  " + "  ".join(parts)) if parts else ""
        return (f"{t} {MAG('ROUND ' + str(data.get('round')))} done  "
                f"delta={delta}  remaining={BOLD(str(rem))}{tail}")
    if ev == "flapping":
        return f"{t} {RED('FLAP')}    {json.dumps(data.get('rules', {}))}"
    if ev == "error":
        return f"{t} {RED('ERROR')}   {data.get('message','')}"
    if ev == "done":
        st = data.get("status", "")
        col = GREEN if st == "all_clear" else (RED if st in ("error", "reverted") else YELLOW)
        return (f"{t} {BOLD('=== DONE ===')} status={col(BOLD(st))}  "
                f"rounds={data.get('rounds')}  remaining={data.get('remaining')}")
    # Unknown event — show raw so nothing is silently dropped.
    return f"{t} {DIM(ev)}: {DIM(json.dumps(data))}"


def stream_loop(loop_id: str) -> str:
    """Tail the SSE stream until 'done'; return the terminal status."""
    url = f"{BASE}/api/loop/{loop_id}/stream"
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    status = "?"
    ev = "message"
    with urllib.request.urlopen(req, timeout=1800) as r:
        for raw in r:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
                continue
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                try:
                    data = json.loads(payload) if payload else {}
                except Exception:
                    data = {"_raw": payload}
                out = _fmt_event(ev, data)
                if out:
                    print(out, flush=True)
                if ev == "done":
                    status = data.get("status", "?")
                ev = "message"
                continue
            # blank line = event boundary; ignore.
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rounds", type=int, default=None)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    label = f" — {args.label}" if args.label else ""
    print(BOLD(f"\n=== E2E Design-Review run{label} ==="), flush=True)
    print(DIM(f"POST {BASE}/api/loop/start  max_rounds={args.max_rounds}"), flush=True)

    try:
        resp = _post("/api/loop/start",
                     {"max_rounds": args.max_rounds} if args.max_rounds else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(RED(f"start failed: HTTP {e.code} {body}"), flush=True)
        return 2
    loop_id = resp.get("loop_id")
    print(DIM(f"loop_id={loop_id}  max_rounds={resp.get('max_rounds')}"), flush=True)

    t0 = time.time()
    status = stream_loop(loop_id)
    dt = time.time() - t0
    print(BOLD(f"\nfinished in {dt:.0f}s — status={status}  loop_id={loop_id}\n"), flush=True)
    return 0 if status in ("all_clear", "plateau", "max_rounds") else 1


if __name__ == "__main__":
    sys.exit(main())
