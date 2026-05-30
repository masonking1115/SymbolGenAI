"""Legacy rule dispatcher — retained only for the `Finding` import shim.

The hardcoded rule tables (BOBCAT_PULLS / IC_POWER_GROUPS / OPEN_DRAIN_OUTPUTS
/ I2C_BUSES / PARTS_INDEX_HINTS) and their check_* functions were retired on
2026-05-29 when rules moved into the generated test1/review/rules.yaml.

Rule evaluation now happens in test1/review/rule_eval.py — see the closed-loop
design spec at docs/superpowers/specs/2026-05-29-closed-loop-design-review-design.md.
"""

from __future__ import annotations

from .findings import Finding  # re-exported for downstream importers

RULES: list = []   # intentionally empty; new evaluator lives in rule_eval.py


def run_all(_idx) -> list[Finding]:
    """Compat shim — returns no findings. Use rule_eval.run_all instead."""
    return []
