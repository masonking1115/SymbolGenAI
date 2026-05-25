#!/usr/bin/env python3
"""Design review entry point — runs every pass, writes error_log.md.

Phases:
  1. Load requirements (review/requirements_index.py).
  2. Run deterministic rules (review/rules.py).
  3. Run semantic per-IC review (review/semantic_review.py) — opt-in.
  4. Render error_log.md + review_history/<ts>.md.

CLI flags:
  --no-semantic  Skip Phase 2b (the LLM driver). Default for now while
                 we iterate on the deterministic side.
  --json <path>  Also emit findings.json for the autofix dispatcher.
  --autofix      After rendering, run review/autofix.py on the trivial
                 bucket (NC marker / decoupling / pull-up/down) and
                 ask before applying anything else.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from review import render, requirements_index
from review.findings import Finding  # noqa: F401 — exported for downstream

PROJECT_DIR = Path(__file__).resolve().parent


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-semantic", action="store_true",
                   help="skip the LLM per-IC review pass")
    p.add_argument("--json", type=Path, default=None,
                   help="also write findings JSON to this path")
    p.add_argument("--autofix", action="store_true",
                   help="run trivial-bucket autofixer after rendering")
    args = p.parse_args()

    print("===== Design Review =====")
    print("Phase 1: loading requirements …")
    idx = requirements_index.load()
    print(f"  application: {idx.application[:60]}…")
    print(f"  parts in spec: {len(idx.parts)}")
    print(f"  FMC power rows: {len(idx.fmc_power)} · "
          f"control rows: {len(idx.fmc_control)} · "
          f"LA pairs: {len(idx.fmc_la_pairs)}")

    findings: list[Finding] = []

    print()
    print("Phase 2a: deterministic rules …")
    try:
        from review import rules
        findings.extend(rules.run_all(idx))
        print(f"  {len(findings)} findings so far")
    except ImportError:
        print("  (rules.py not yet implemented — skipping)")

    if not args.no_semantic:
        print()
        print("Phase 2b: semantic per-IC review …")
        try:
            from review import semantic_review
            findings.extend(semantic_review.run(idx))
            print(f"  total findings: {len(findings)}")
        except ImportError:
            print("  (semantic_review.py not yet implemented — skipping)")

    print()
    print("Phase 3: rendering …")
    reviewed_against = [
        "test1/design_requirements.md",
        "test1/[External] Bobcat Board Design.pdf",
        "test1/Parts Library/<per-IC datasheets>",
    ]
    log_path, hist_path = render.write(findings, reviewed_against)
    print(f"  wrote {log_path.relative_to(PROJECT_DIR.parent)}")
    print(f"  wrote {hist_path.relative_to(PROJECT_DIR.parent)}")

    if args.json:
        render.write_json(findings, args.json)
        print(f"  wrote {args.json}")

    if args.autofix:
        print()
        print("Phase 4: autofix dispatch …")
        try:
            from review import autofix
            autofix.run(findings)
        except ImportError:
            print("  (autofix.py not yet implemented — skipping)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
