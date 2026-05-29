#!/usr/bin/env python3
"""Bounded re-sim CLI for the interpret agent's iterate loop.

The interpreter may decide that a clarification is resolvable by an instant
re-sim with a corrected scenario param (e.g. the operating point was wrong).
It updates sim_config.json and calls this CLI to re-run. To prevent token
leakage from runaway iteration, the number of re-sims per (block, sim_type) is
HARD-capped here — not just instructed — via a per-pair counter file. Past the
cap the CLI refuses to sim and returns limit_reached, so the agent must stop.

Usage (agent cwd is test1/):
    python sim/iterate_sim.py --block ldo_rail --sim-type dc_op_point
    python sim/iterate_sim.py --block ldo_rail --sim-type dc_op_point --reset
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]                      # repo root (SymbolGenAI/)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test1.sim import service                # noqa: E402

MAX_ITERS = 3
CACHE_DIR = HERE.parent / "cache"


def _counter(block: str, sim_type: str) -> Path:
    safe = f"{block}_{sim_type}".replace("/", "_")
    return CACHE_DIR / f".iter_{safe}.json"


def _read(path: Path) -> int:
    try:
        return int(json.loads(path.read_text()).get("count", 0))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0


def _write(path: Path, count: int) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"count": count}))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--block", required=True)
    p.add_argument("--sim-type", required=True)
    p.add_argument("--reset", action="store_true",
                   help="reset the iteration counter (backend calls this before interpret)")
    args = p.parse_args()

    cpath = _counter(args.block, args.sim_type)
    if args.reset:
        _write(cpath, 0)
        print(json.dumps({"reset": True}))
        return 0

    count = _read(cpath)
    if count >= MAX_ITERS:
        print(json.dumps({
            "limit_reached": True, "count": count, "max": MAX_ITERS,
            "message": f"re-sim limit ({MAX_ITERS}) reached — stop iterating and emit the verdict.",
        }))
        return 0

    count += 1
    _write(cpath, count)

    res = service.run_block_sim(args.block, args.sim_type)
    compact = {
        "iteration": count, "max": MAX_ITERS,
        "ok": res.get("ok"), "status": res.get("status"),
        "analysis": res.get("analysis"), "op_point": res.get("op_point"),
    }
    print(json.dumps(compact, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
