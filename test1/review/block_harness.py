#!/usr/bin/env python3
"""Block-boundary stress-test harness.

Drives the `block` rule family (rule_schema.Family == "block") — the
boundary-validation rules that check each functional block against datasheet
specs, component tolerances, and EE first principles. Unlike the schematic
pull-up/decoupling rules (existence checks) or the simulation sim_pass rules
(does the deck's own OK flag pass), block rules ask the harder question:

    "Does the block hold up at its OPERATING LIMITS?"

Examples it is built to catch:
  • The OPA2388 is single-supply; near full-scale (V_DAC→0) it cannot drive the
    PMOS gate below ground, so the bias loop SATURATES below the 646 µA ideal.
    A nominal-midscale sim looks fine; the ceiling rule judges i_max_regulated
    against the 0–640 µA spec.  (user bias concern #1)
  • R40/R41 are 5.11k 0.1%; stacked with the OPA2388 input offset (Vos≈15 µV)
    and DAC INL, the worst-case full-scale current error must still fit the
    ~1 µA-step / FS-accuracy budget.  (user bias concern #4)

This is a HARNESS, not a new evaluator: every rule runs through the same
rule_eval path the closed loop uses (sim_review → real ngspice + a judge agent;
semantic → datasheet/netlist judge), so there is exactly one evaluation code
path and the harness can never drift from the live review. The harness adds:
  • a `block`-family filter + optional per-block (`--block opa_bias`) slice,
  • per-rule timing + structured logging (so a flaky/slow rule is visible),
  • a boundary stress report grouped by block,
  • exit code 1 if any ERROR-severity block rule fires (CI-friendly).

Usage:
    python -m test1.review.block_harness                # all block rules
    python -m test1.review.block_harness --block opa_bias
    python -m test1.review.block_harness --no-sim       # semantic rules only (fast)
    python -m test1.review.block_harness --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

from .findings import Finding, Severity
from .rule_eval import load_rules, run_all
from .rule_schema import Rule, StructuralRule, SemanticRule


# ---- Per-rule observation record ---------------------------------------

@dataclass
class RuleResult:
    rule_id: str
    block: str                 # the block this rule validates (sim_block or sheet)
    title: str
    severity: str
    mode: str                  # "sim_review" | "semantic" | other predicate kind
    fired: bool                # True == the boundary check FAILED
    observed: str = ""         # what the judge/agent reported
    seconds: float = 0.0       # wall time for this rule
    criterion: str = ""        # the spec the rule judged against


@dataclass
class HarnessReport:
    results: list[RuleResult] = field(default_factory=list)
    started_at: float = 0.0
    elapsed_s: float = 0.0

    @property
    def fired(self) -> list[RuleResult]:
        return [r for r in self.results if r.fired]

    @property
    def errors(self) -> list[RuleResult]:
        return [r for r in self.fired if r.severity == "ERROR"]

    def by_block(self) -> dict[str, list[RuleResult]]:
        out: dict[str, list[RuleResult]] = {}
        for r in self.results:
            out.setdefault(r.block, []).append(r)
        return out


# ---- Rule introspection -------------------------------------------------

def _rule_block(rule: Rule) -> str:
    """The block a rule validates: its sim_block if it names one, else the sheet,
    else the applies_to refdes/net — best-effort label for grouping."""
    at = rule.applies_to
    # Prefer the explicit block tag (the stable grouping key the UI + generator
    # use); fall back to sim_block / sheet for older rules without it.
    if getattr(at, "block", None):
        return at.block
    if at.sim_block:
        return at.sim_block
    if at.sheet:
        return at.sheet
    if isinstance(rule, StructuralRule) and getattr(rule.predicate, "sim_block", None):
        return rule.predicate.sim_block  # type: ignore[attr-defined]
    return at.refdes or at.net or "?"


def _rule_mode(rule: Rule) -> str:
    if isinstance(rule, SemanticRule):
        return "semantic"
    if isinstance(rule, StructuralRule):
        return rule.predicate.kind
    return "?"


def _rule_criterion(rule: Rule) -> str:
    if isinstance(rule, SemanticRule):
        return (rule.prompt or "").strip()
    if isinstance(rule, StructuralRule) and getattr(rule.predicate, "criterion", None):
        return rule.predicate.criterion  # type: ignore[attr-defined]
    return ""


def block_rules(rules: list[Rule] | None = None,
                only_block: str | None = None) -> list[Rule]:
    """Every enabled `block`-family rule, optionally sliced to one block."""
    if rules is None:
        rules = load_rules().rules
    out = [r for r in rules if r.family == "block" and r.enabled]
    if only_block:
        out = [r for r in out if _rule_block(r) == only_block]
    return out


# ---- Harness run --------------------------------------------------------

def run_harness(only_block: str | None = None,
                run_sim: bool = True,
                log=print) -> HarnessReport:
    """Evaluate the block-family rules through the real rule_eval path and
    collect a structured report. `run_sim=False` skips the slow rules (sim_review
    + semantic) so a quick structural-only pass is possible — but block rules are
    almost all sim_review/semantic, so the default is the full (slow) run.

    `log` is the line sink (default print); the GUI/closed loop can pass a
    different sink. Every rule's start/finish + result is logged so a hung or
    flaky rule is visible in the process log."""
    report = HarnessReport(started_at=time.time())
    rules = block_rules(only_block=only_block)
    if not rules:
        log(f"[harness] no block-family rules found"
            + (f" for block {only_block!r}" if only_block else ""))
        report.elapsed_s = 0.0
        return report

    log(f"[harness] {len(rules)} block-family rule(s)"
        + (f" for block {only_block!r}" if only_block else "")
        + f"; run_sim={run_sim}")

    # Per-rule timing: rule_eval's progress callback fires once per rule with a
    # pass/fail result, but not start/stop timing. We wrap each rule by running
    # the evaluator with that single rule's list and timing the call — this keeps
    # ONE eval path (run_all) while giving per-rule observability. The sim cache
    # is shared across calls so a block's ngspice run is reused by sibling rules.
    shared_sim: dict = {}
    fired_ids: set[str] = set()
    observed_by_id: dict[str, str] = {}

    def _progress(kind: str, payload: dict) -> None:
        if kind == "rule":
            rid = payload.get("id", "?")
            res = payload.get("result", "?")
            i, n = payload.get("i"), payload.get("total")
            log(f"[harness]   rule {i}/{n} {rid}: {res}")

    for idx, rule in enumerate(rules, 1):
        block = _rule_block(rule)
        mode = _rule_mode(rule)
        log(f"[harness] ({idx}/{len(rules)}) {rule.id} "
            f"[block={block} mode={mode} sev={rule.severity}] — start")
        t0 = time.time()
        # run_all wants the FULL machinery; pass just this one rule so timing is
        # per-rule. semantic=run_sim gates the slow path (sim_review + semantic).
        findings: list[Finding] = run_all(
            rules=[rule], sim_results=shared_sim,
            semantic=run_sim, progress=_progress,
        )
        dt = time.time() - t0
        fired = bool(findings)
        observed = findings[0].observed if findings else ""
        if fired:
            fired_ids.add(rule.id)
            observed_by_id[rule.id] = observed
        report.results.append(RuleResult(
            rule_id=rule.id, block=block, title=rule.title,
            severity=str(rule.severity), mode=mode, fired=fired,
            observed=observed, seconds=round(dt, 2),
            criterion=_rule_criterion(rule)[:200],
        ))
        verdict = "FIRED ✗" if fired else "ok ✓"
        log(f"[harness] ({idx}/{len(rules)}) {rule.id} — {verdict} ({dt:.1f}s)"
            + (f"  observed: {observed}" if observed else ""))

    report.elapsed_s = time.time() - report.started_at
    return report


# ---- Report rendering ---------------------------------------------------

def render_report(report: HarnessReport, log=print) -> None:
    log("")
    log("===== Block-boundary stress report =====")
    by_block = report.by_block()
    for block in sorted(by_block):
        rows = by_block[block]
        n_fired = sum(1 for r in rows if r.fired)
        log(f"\n  ● {block}  ({len(rows) - n_fired}/{len(rows)} within bounds)")
        for r in rows:
            mark = "✗" if r.fired else "✓"
            log(f"      {mark} [{r.severity:<7}] {r.rule_id}  ({r.mode}, {r.seconds:.1f}s)")
            if r.criterion:
                log(f"          spec: {r.criterion[:110]}")
            if r.fired and r.observed:
                log(f"          → {r.observed}")
    log("")
    log(f"  total: {len(report.results)} rule(s), {len(report.fired)} fired "
        f"({len(report.errors)} ERROR), {report.elapsed_s:.1f}s")


def report_to_json(report: HarnessReport) -> dict:
    return {
        "elapsed_s": round(report.elapsed_s, 2),
        "total": len(report.results),
        "fired": len(report.fired),
        "errors": len(report.errors),
        "results": [
            {
                "rule_id": r.rule_id, "block": r.block, "title": r.title,
                "severity": r.severity, "mode": r.mode, "fired": r.fired,
                "observed": r.observed, "seconds": r.seconds,
                "criterion": r.criterion,
            }
            for r in report.results
        ],
    }


# ---- CLI ----------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--block", default=None,
                   help="only validate this block (e.g. opa_bias, ldo_rail)")
    p.add_argument("--no-sim", action="store_true",
                   help="skip slow rules (sim_review + semantic); structural only")
    p.add_argument("--json", type=Path, default=None,
                   help="also write the report as JSON to this path")
    args = p.parse_args()

    report = run_harness(only_block=args.block, run_sim=not args.no_sim)
    render_report(report)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report_to_json(report), indent=2),
                             encoding="utf-8")
        print(f"  wrote {args.json}")

    # CI signal: nonzero if any ERROR-severity boundary rule fired.
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
