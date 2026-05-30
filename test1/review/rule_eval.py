"""Rule evaluator — dispatches each Rule against the current design.

Structural rules → predicate dispatch table (this module).
Semantic rules → claude -p invocation per rule, with cited source excerpts
                 from knowledge_provider() (Phase 2+).

Emits Finding objects compatible with test1/review/findings.py — the same
schema run_review.py + the GUI already consume.

Spec §3 + §4.plan_actions mapping.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from .findings import AutofixCategory, Finding, Severity
from .netlist_view import load_all, NetlistView
from .rule_schema import (
    Rule, RulesFile, StructuralRule, SemanticRule,
    DecouplingCount, PullupPulldown, NoConnect, NetRouting,
    ConnectorPin, PowerRailMembership, ValueInRange, Present,
    SimPass, SimMetric,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
RULES_YAML = PROJECT_DIR / "review" / "rules.yaml"


# ---- Loader -------------------------------------------------------------

def load_rules(path: Path = RULES_YAML) -> RulesFile:
    if not path.exists():
        return RulesFile()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RulesFile.model_validate(data)


def save_rules(rf: RulesFile, path: Path = RULES_YAML) -> None:
    path.write_text(
        yaml.safe_dump(rf.model_dump(exclude_none=True), sort_keys=False),
        encoding="utf-8",
    )


# ---- Helpers used by multiple predicates --------------------------------

def _value_regex_match(part_value: str, regex: str | None) -> bool:
    if not regex:
        return True
    return bool(re.search(regex, part_value, re.IGNORECASE))


def _is_cap_value(v: str) -> bool:
    return bool(re.search(r"\d+\.?\d*\s*[µu]?[FfNn]F?", v))


def _other_pins_on_refdes(view: NetlistView, refdes: str, exclude_pin: str) -> list[str]:
    """All pins of `refdes` (across every net) except `exclude_pin`.

    The Part dataclass doesn't carry a pin list, so we discover pins by
    scanning the reverse netlist index.
    """
    seen: set[str] = set()
    for member in view.nets_with_member(refdes):
        if member.pin != exclude_pin:
            seen.add(member.pin)
    return sorted(seen)


# ---- Structural predicate evaluators ------------------------------------

def eval_decoupling_count(p: DecouplingCount, view: NetlistView) -> bool:
    """Returns True if rule PASSES (≥min caps), False if it FIRES."""
    nets: set[str] = set()
    for pin in p.pins:
        for nm in view.nets_with_member(p.refdes, pin):
            nets.add(nm.net)
    if not nets:
        return True  # pin not wired — different problem; validator handles it
    caps: set[str] = set()
    for net in nets:
        for m in view.members(net):
            if m.refdes.startswith("C"):
                hit = view.part(m.refdes)
                if hit and _value_regex_match(hit[1].value, p.value_match):
                    caps.add(m.refdes)
    return len(caps) >= p.min


def eval_pullup_pulldown(p: PullupPulldown, view: NetlistView) -> bool:
    rail = "GND" if p.direction == "down" else p.rail
    net_resistors = {m.refdes for m in view.members(p.net) if m.refdes.startswith("R")}
    rail_resistors = {m.refdes for m in view.members(rail) if m.refdes.startswith("R")}
    candidates = net_resistors & rail_resistors
    for rd in candidates:
        hit = view.part(rd)
        if hit and re.search(p.value_match, hit[1].value, re.IGNORECASE):
            return True
    return False


def eval_no_connect(p: NoConnect, view: NetlistView) -> bool:
    """PASSES if pin is unwired (proper NC); FIRES if pin is wired."""
    return not view.nets_with_member(p.refdes, p.pin)


def eval_net_routing(p: NetRouting, view: NetlistView) -> bool:
    """Very basic shape check: requires (refdes, pin) endpoints share a net,
    and for via=series_R, exactly one resistor sits on that path."""
    f_ref, f_pin = p.from_pin.split(".")
    t_ref, t_pin = p.to_pin.split(".")
    f_nets = {n.net for n in view.nets_with_member(f_ref, f_pin)}
    t_nets = {n.net for n in view.nets_with_member(t_ref, t_pin)}
    if p.via == "direct":
        return bool(f_nets & t_nets)
    # series_R / jumper — share a 2-pin intermediate part
    for fn in f_nets:
        for m in view.members(fn):
            if not m.refdes.startswith(("R", "J")):
                continue
            other_pins = _other_pins_on_refdes(view, m.refdes, m.pin)
            for op in other_pins:
                op_nets = {n.net for n in view.nets_with_member(m.refdes, op)}
                if op_nets & t_nets:
                    # right shape? series_R wants refdes starting R; jumper J
                    if p.via == "series_R" and m.refdes.startswith("R"):
                        return True
                    if p.via == "jumper" and m.refdes.startswith("J"):
                        return True
    return False


def eval_connector_pin(p: ConnectorPin, view: NetlistView) -> bool:
    return any(n.net == p.net for n in view.nets_with_member(p.refdes, p.pin))


def eval_power_rail_membership(p: PowerRailMembership, view: NetlistView) -> bool:
    return any(n.net == p.rail for n in view.nets_with_member(p.refdes, p.pin))


def eval_value_in_range(p: ValueInRange, view: NetlistView) -> bool:
    hit = view.part(p.refdes)
    if not hit:
        return True  # part not present is a different rule's problem
    value = hit[1].value
    if p.value_regex and not re.search(p.value_regex, value, re.IGNORECASE):
        return False
    # Numeric range — parse leading number with k/M/µ multipliers if min/max set
    if p.min is not None or p.max is not None:
        m = re.match(r"\s*([\d.]+)\s*([kMµunpf]?)", value)
        if not m:
            return False
        num = float(m.group(1))
        mult = {"k": 1e3, "M": 1e6, "µ": 1e-6, "u": 1e-6,
                "n": 1e-9, "p": 1e-12, "f": 1e-15}.get(m.group(2), 1.0)
        val = num * mult
        if p.min is not None and val < p.min:
            return False
        if p.max is not None and val > p.max:
            return False
    return True


def eval_present(p: Present, view: NetlistView) -> bool:
    if p.mpn:
        # Part dataclass has no .mpn field — the `value` field is overloaded
        # to carry either a discrete value ("10k") or an MPN ("TPS7A8401A"),
        # and lib_id often holds the symbol name (close to MPN). Match on
        # both for robustness.
        for sheet_name, nl in view.by_sheet.items():
            for refdes, part in nl.parts.items():
                if part.value == p.mpn or part.lib_id == p.mpn:
                    return True
        return False
    # role_spec → cannot be auto-evaluated; missing-part flow handles it
    # by inspecting the rule directly. Return False so the finding fires.
    return False


def eval_sim_pass(p: SimPass, sim_results: dict) -> bool:
    """sim_results = { (block, sim_type): {ok: bool, ...} }"""
    res = sim_results.get((p.sim_block, p.sim_type))
    if not res:
        return True  # sim hasn't run yet — separate signal
    return bool(res.get("ok"))


def eval_sim_metric(p: SimMetric, sim_results: dict) -> bool:
    res = sim_results.get((p.sim_block, p.sim_type))
    if not res:
        return True  # sim hasn't run yet — separate signal
    metric = (res.get("analysis") or {}).get(p.metric)
    if metric is None:
        return True
    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
           "==": lambda a, b: a == b, ">": lambda a, b: a > b,
           "<": lambda a, b: a < b}
    return ops[p.op](metric, p.value)


_DISPATCH = {
    "decoupling_count":       lambda p, view, sim: eval_decoupling_count(p, view),
    "pullup_pulldown":        lambda p, view, sim: eval_pullup_pulldown(p, view),
    "no_connect":             lambda p, view, sim: eval_no_connect(p, view),
    "net_routing":            lambda p, view, sim: eval_net_routing(p, view),
    "connector_pin":          lambda p, view, sim: eval_connector_pin(p, view),
    "power_rail_membership":  lambda p, view, sim: eval_power_rail_membership(p, view),
    "value_in_range":         lambda p, view, sim: eval_value_in_range(p, view),
    "present":                lambda p, view, sim: eval_present(p, view),
    "sim_pass":               lambda p, view, sim: eval_sim_pass(p, sim),
    "sim_metric":             lambda p, view, sim: eval_sim_metric(p, sim),
}


# ---- Finding factory ----------------------------------------------------

def _rule_to_finding(rule: Rule, observed: str = "rule fired") -> Finding:
    af: AutofixCategory = "manual"
    af_data: dict = {}
    if isinstance(rule, StructuralRule):
        if rule.predicate.kind == "pullup_pulldown":
            af = "pullup_pulldown"
            p = rule.predicate
            af_data = {"net": p.net, "rail": p.rail, "kind": p.direction,
                       "value": p.value_match}
        elif rule.predicate.kind == "decoupling_count":
            af = "decoupling"
            p = rule.predicate
            af_data = {"refdes": p.refdes, "pins": p.pins,
                       "min": p.min, "value": p.value_match or "0.1uF"}
        elif rule.predicate.kind == "no_connect":
            af = "nc_marker"
    return Finding(
        rule_id=rule.id,
        severity=Severity(rule.severity),
        title=rule.title,
        subject=(rule.applies_to.refdes or rule.applies_to.net
                 or rule.applies_to.sim_block or rule.id),
        sheet=(rule.applies_to.sheet or "?"),
        component_refs=[rule.applies_to.refdes] if rule.applies_to.refdes else [],
        requirement_ref=rule.source[0].doc + ":" + rule.source[0].loc,
        observed=observed,
        impact="",
        fix=rule.fix_hint,
        autofix=af,
        autofix_data=af_data,
    )


# ---- Top-level runner ---------------------------------------------------

def run_all(rules: list[Rule] | None = None,
            sim_results: dict | None = None) -> list[Finding]:
    """Evaluate every enabled rule against the current netlist + sim cache.

    sim_results: { (block, sim_type): result_dict } as produced by the
    Phase 4 orchestrator. None means "no sim data" — sim_pass/sim_metric
    rules return PASS (silent) when their data is absent."""
    if rules is None:
        rf = load_rules()
        rules = rf.rules
    view = load_all()
    sim = sim_results or {}
    out: list[Finding] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if isinstance(rule, StructuralRule):
            ok = _DISPATCH[rule.predicate.kind](rule.predicate, view, sim)
            if not ok:
                out.append(_rule_to_finding(rule))
        else:
            # SemanticRule — Phase 2+ wires the claude -p invocation here.
            # For Phase 1 we treat semantic rules as deferred (no finding).
            pass
    return out
