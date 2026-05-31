"""A5: rules must be SATISFIABLE — a geometric WARNING whose threshold no layout
can hit makes the fix loop churn forever (the body_wire_clearance=100 bug). These
tests lock in (1) the per-rule achievable-bound invariant and (2) a real-design
witness that the as-built design actually passes the gate rules.

Run: python -m pytest test1/altium/test_rule_satisfiability.py
"""
from __future__ import annotations

from test1.altium import layout_lint as L


def test_body_wire_clearance_is_satisfiable():
    """The threshold must be <= the clearance achievable for a passive body in the
    standard pin-drop field. Above that, the rule is unsatisfiable."""
    assert L.BODY_WIRE_CLEAR <= L._MAX_ACHIEVABLE_BODY_WIRE_CLEAR, (
        f"BODY_WIRE_CLEAR={L.BODY_WIRE_CLEAR} > achievable "
        f"{L._MAX_ACHIEVABLE_BODY_WIRE_CLEAR} — would churn the loop"
    )


def test_import_time_satisfiability_guard_runs():
    """The module-level _assert_rules_satisfiable() ran at import (no exception);
    calling it again must also pass for the current constants."""
    L._assert_rules_satisfiable()


def test_clearance_thresholds_are_positive():
    """A clearance threshold of 0 or negative would never fire — a silent no-op
    rule. Every clearance constant should be a positive, sub-pitch value."""
    for name in ("BODY_WIRE_CLEAR", "POWER_BODY_CLEAR", "POWER_SIDE_CLEAR",
                 "LABEL_SYMBOL_CLEAR", "MIN_SYMBOL_GAP", "MIN_CLUSTER_GAP"):
        v = getattr(L, name)
        assert v > 0, f"{name}={v} is not positive (rule would never fire)"


def test_as_built_design_passes_gate_rules():
    """Satisfiability WITNESS: the committed design must actually pass the hard
    gate (no ERROR-level lint) on a real build — proving the gate rules CAN be
    satisfied by a real layout, and that we didn't ship a rule that the design
    can't meet. (Advisory WARNINGs are allowed; this asserts only ERRORs=0.)"""
    from test1.altium.build_all import BUILDERS
    errors: list[str] = []
    for name, fn in BUILDERS.items():
        res = fn()
        s = res[0] if isinstance(res, (tuple, list)) else res
        # Apply the same auto-fixes build_project applies before linting, so the
        # witness matches what the gate actually sees.
        try:
            s.auto_fix_text(); s.auto_fix_power(); s.auto_fix_power_stub_side()
        except Exception:
            pass
        for i in L.lint(s):
            if i.severity == "ERROR":
                errors.append(f"{name}: {i.rule} {i.message[:60]}")
    assert not errors, "as-built design has gate ERRORs:\n  " + "\n  ".join(errors)
