"""Live monitor for the Generate flow (the Generator tab's Generate button).

Triggers POST /api/run/apply-and-generate (apply-changelog agent -> build, with
optional closed-loop fix), then tails the apply-agent console (SSE, same {line}
events the GUI consumes) AND the build console live. Pure stdlib.

Usage: python -m test1.review.generate_monitor [--loop-review]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8765"


def _c(code, s): return f"\033[{code}m{s}\033[0m"
DIM = lambda s: _c("2", s); BOLD = lambda s: _c("1", s)
CYAN = lambda s: _c("36", s); GREEN = lambda s: _c("32", s)
YEL = lambda s: _c("33", s); RED = lambda s: _c("31", s); MAG = lambda s: _c("35", s)


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode())


def _post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _ts(): return time.strftime("%H:%M:%S")


def _stream(path, on_line, on_done, idle_timeout=900):
    """Read an SSE stream of {line} events; call on_line(text) per line,
    on_done(status) at the terminal event. Bails after idle_timeout s of silence."""
    req = urllib.request.Request(BASE + path, headers={"Accept": "text/event-stream"})
    ev = "message"
    with urllib.request.urlopen(req, timeout=idle_timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line.startswith("event:"):
                ev = line[6:].strip(); continue
            if line.startswith("data:"):
                payload = line[5:].strip()
                try:
                    d = json.loads(payload) if payload else {}
                except Exception:
                    d = {}
                if ev == "done":
                    on_done(d.get("status", "?")); return
                if "line" in d:
                    on_line(d["line"])
                ev = "message"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop-review", action="store_true")
    args = ap.parse_args()

    cl = _get("/api/changelog").get("items", [])
    print(BOLD(f"\n=== GENERATE (apply-and-generate) — {len(cl)} changelog item(s) ==="))
    for it in cl:
        print(DIM(f"  • {it['summary'][:110]}"))
    body = {"no_reopen": True, "loop_review": args.loop_review, "fix_warnings": False}
    print(DIM(f"POST /api/run/apply-and-generate {json.dumps(body)}"), flush=True)
    resp = _post("/api/run/apply-and-generate", body)
    apply_id = resp.get("apply_run_id")
    gen_id = resp.get("generate_run_id")
    diff_id = resp.get("diff_id")
    print(DIM(f"apply_run_id={apply_id}  generate_run_id={gen_id}  diff_id={diff_id}"),
          flush=True)

    t0 = time.time()

    # ---- Phase 1: apply agent (live SSE) ----
    print(BOLD(f"[{_ts()}] {MAG('APPLY')} — agent implementing the changelog ..."),
          flush=True)
    if apply_id:
        st = {"v": "?"}
        try:
            _stream(f"/api/agent/{apply_id}/stream",
                    on_line=lambda ln: print(f"  {DIM('apply>')} {ln}", flush=True),
                    on_done=lambda s: st.__setitem__("v", s))
        except Exception as e:
            print(f"  {RED('apply stream ended:')} {e}", flush=True)
        # confirm final status
        try:
            fs = _get(f"/api/agent/{apply_id}").get("status", st["v"])
        except Exception:
            fs = st["v"]
        col = GREEN if fs in ("done", "ok") else RED
        print(f"[{_ts()}] {MAG('APPLY')} {col(fs)} ({time.time()-t0:.0f}s)", flush=True)

    # ---- Phase 2: build console ----
    print(BOLD(f"[{_ts()}] {CYAN('BUILD')} — rebuilding ..."), flush=True)
    # gen_id may have been null up front (build scheduled after apply); discover it.
    if not gen_id:
        # poll the run registry for the newest generate run
        for _ in range(40):
            try:
                # build-status surfaces the latest; but we need the run id — poll runs
                runs = _get("/api/run/recent") if False else None
            except Exception:
                runs = None
            time.sleep(1)
            try:
                bs = _get("/api/build-status")
                if bs.get("generate_run_id"):
                    gen_id = bs["generate_run_id"]; break
            except Exception:
                pass
    build_seen = 0
    deadline = time.time() + 1200
    if gen_id:
        try:
            _stream(f"/api/run/{gen_id}/stream",
                    on_line=lambda ln: print(f"  {DIM('build>')} {ln}", flush=True),
                    on_done=lambda s: None)
        except Exception as e:
            print(f"  {DIM('build stream ended:')} {e}", flush=True)
        rs = None
        try:
            rs = _get(f"/api/run/{gen_id}")
        except Exception:
            pass
        if rs:
            status = rs.get("status", "?")
            col = GREEN if status in ("done", "ok", "") else RED
            print(f"[{_ts()}] {CYAN('BUILD')} {col(status or 'ok')} "
                  f"rc={rs.get('returncode')} ({time.time()-t0:.0f}s)", flush=True)

    # ---- Summary ----
    print(BOLD(f"[{_ts()}] === GENERATE COMPLETE ({time.time()-t0:.0f}s) ==="))
    try:
        print("  build-status:", json.dumps(_get('/api/build-status'))[:300])
    except Exception:
        pass
    if diff_id:
        try:
            d = _get(f"/api/loop/{diff_id}/diff")
            print(f"  diff: {len(d.get('sheets', []))} sheet(s) changed (id={diff_id})")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
