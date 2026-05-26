#!/usr/bin/env python3
"""CLI entry for the AI-assisted sim PoC.

Usage:
    python -m test1.sim.run_sim                     # all three modes
    python -m test1.sim.run_sim --mode load_step    # one mode
    python -m test1.sim.run_sim --vout-set 1.2      # override LDO setpoint
    python -m test1.sim.run_sim --keep-decks /tmp   # dump SPICE decks for debugging

Outputs:
    test1/sim/results/<mode>.json   structured summary the agent can read
    test1/sim/results/<mode>.deck   the SPICE deck that was run
    test1/sim/results/<mode>.log    raw ngspice stdout
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python test1/sim/run_sim.py` from the repo root by anchoring imports.
HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test1.sim.decks import ldo_rail
from test1.sim.runner import run_deck


RESULTS_DIR = HERE.parent / "results"


def _run_one(mode: str, vout_set: float) -> dict:
    deck, traces = ldo_rail.build_deck(mode=mode, vout_set=vout_set)
    res = run_deck(deck, trace_specs=traces)

    # Persist artifacts so the agent / reviewer can inspect after the fact.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{mode}.deck").write_text(deck)
    (RESULTS_DIR / f"{mode}.log").write_text(res.stdout)

    summary = res.summary()

    if mode == "op":
        summary["analysis"] = ldo_rail.analyze_op_point(res.op_point, vout_set=vout_set)
    elif mode == "load_step" and "load_step" in res.traces:
        summary["analysis"] = ldo_rail.analyze_load_step(
            res.traces["load_step"], vout_set=vout_set,
        )
    elif mode == "powerup" and "powerup" in res.traces:
        summary["analysis"] = ldo_rail.analyze_powerup(
            res.traces["powerup"], vout_set=vout_set,
        )

    (RESULTS_DIR / f"{mode}.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["op", "powerup", "load_step", "all"],
                   default="all")
    p.add_argument("--vout-set", type=float, default=1.8,
                   help="LDO output setpoint in volts (default 1.8)")
    args = p.parse_args()

    modes = ["op", "powerup", "load_step"] if args.mode == "all" else [args.mode]
    overall_ok = True

    print(f"sim: VOUT_SET={args.vout_set}V, modes={modes}")
    for mode in modes:
        print(f"\n=== {mode} ===")
        summary = _run_one(mode, args.vout_set)
        ok = summary.get("ok") and summary.get("analysis", {}).get("overall", "OK") == "OK"
        overall_ok = overall_ok and ok

        if not summary.get("ok"):
            print(f"  ngspice failed (rc={summary.get('returncode')})")
            print(f"  see test1/sim/results/{mode}.log for details")
        a = summary.get("analysis", {})
        if a:
            print(f"  check:   {a.get('check')}")
            print(f"  overall: {a.get('overall')}")
            for k, v in a.items():
                if k in ("check", "overall", "rails"):
                    continue
                print(f"    {k}: {v}")
            if "rails" in a:
                for r in a["rails"]:
                    print(f"    {r['rail']:<12} expected={r.get('expected_V')}V "
                          f"measured={r.get('measured_V')}V → {r.get('status')}")

    print(f"\nresults written to {RESULTS_DIR.relative_to(ROOT)}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
