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
                   help="skip the LLM per-IC review pass (still writes manifest)")
    p.add_argument("--only-manifest", action="store_true",
                   help="emit the semantic manifest but do not render error_log.md")
    p.add_argument("--json", type=Path, default=None,
                   help="also write findings JSON to this path")
    p.add_argument("--autofix", action="store_true",
                   help="walk findings, propose fixes, prompt for approval")
    p.add_argument("--apply-trivial", action="store_true",
                   help="when used with --autofix, auto-apply trivial "
                        "(pullup_pulldown + decoupling) without prompting")
    p.add_argument("--non-interactive", action="store_true",
                   help="never prompt; print proposals only")
    p.add_argument("--no-altium-compile", action="store_true",
                   help="skip the built-in end-of-review real-Altium compile "
                        "cross-check (default: run it once at the end)")
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
    print("Phase 2a: rule_eval against rules.yaml …")
    try:
        from review import rule_eval
        # --no-semantic now maps to the NEW semantic rules (the old Phase-2b
        # per-IC LLM pass it originally gated was retired 2026-05-29). When
        # semantic is on, each SemanticRule gets a read-only claude -p verdict
        # (slower, fail-safe). Structural rules always run.
        run_semantic = not args.no_semantic
        new_findings = rule_eval.run_all(semantic=run_semantic)
        findings.extend(new_findings)
        rf = rule_eval.load_rules()
        from review.rule_schema import SemanticRule
        n_sem = sum(1 for r in rf.rules if isinstance(r, SemanticRule) and r.enabled)
        n_block = sum(1 for r in rf.rules if r.family == "block" and r.enabled)
        print(f"  {len(new_findings)} findings from "
              f"{sum(1 for r in rf.rules if r.enabled)}/{len(rf.rules)} active rules"
              f" (semantic {'ON' if run_semantic else 'OFF'}: {n_sem} LLM-judged rules;"
              f" {n_block} block-boundary rules)")
    except FileNotFoundError:
        print("  (rules.yaml not yet generated — run /api/review/rules/generate)")
    except Exception as e:
        print(f"  rule_eval error: {e}")

    # Phase 2b retired 2026-05-29 — semantic rules now live in rules.yaml
    # and are evaluated by rule_eval.py alongside structural rules.

    if args.only_manifest:
        print("\n--only-manifest: skipping render.")
        return 0

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
        print("===== Phase 4: autofix dispatch =====")
        from review import autofix
        autofix.run(
            findings,
            non_interactive=args.non_interactive,
            apply_trivial=args.apply_trivial,
        )

    # Phase 5: built-in real-Altium compile cross-check, ONCE at the end of the
    # review (not per loop round — the compile is slow/hang-prone, so it runs once
    # here after all fixes settle). Default-on; advisory (never fails the review).
    # Run as a SUBPROCESS from the repo root: altium_compile reads sys.argv for the
    # project path, so an in-process call would mis-read run_review's own argv
    # (e.g. "--no-semantic") as the project. A clean subprocess avoids that.
    if not args.no_altium_compile:
        print()
        print("===== Phase 5: Altium compile cross-check (built-in) =====")
        import subprocess
        repo_root = PROJECT_DIR.parent
        try:
            subprocess.run(
                [sys.executable, "-m", "test1.altium.verify.altium_compile_check"],
                cwd=str(repo_root), check=False)
        except Exception as e:  # noqa: BLE001
            print(f"  (Altium compile step did not complete: {type(e).__name__}: {e})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
