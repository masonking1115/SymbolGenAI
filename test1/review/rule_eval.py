"""Rule evaluator — dispatches each Rule against the current design.

Structural rules → predicate dispatch table (this module).
Semantic rules → claude -p invocation per rule, with cited source excerpts
                 from knowledge_provider() (Phase 2+).

Emits Finding objects compatible with test1/review/findings.py — the same
schema run_review.py + the GUI already consume.

Spec §3 + §4.plan_actions mapping.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from pydantic import BaseModel

from . import mpn_value
from .findings import AutofixCategory, Finding, Severity
from .netlist_view import load_all, NetlistView
from .rule_schema import (
    Rule, RulesFile, StructuralRule, SemanticRule,
    DecouplingCount, PullupPulldown, NoConnect, NetRouting,
    ConnectorPin, PowerRailMembership, ValueInRange, Present,
    SimPass, SimMetric, SimReview,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
RULES_YAML = PROJECT_DIR / "review" / "rules.yaml"

# claude CLI used for semantic-rule verdicts (matches gui/backend/agent.py).
_CLAUDE = "claude"
_SEMANTIC_MODEL = os.environ.get("TEST1_AGENT_MODEL", "sonnet")
_SEMANTIC_TIMEOUT_S = 120


# ---- Loader -------------------------------------------------------------

# A single malformed rule (bad family/severity, missing source, etc.) used to
# fail RulesFile.model_validate() for the WHOLE file → load_rules raised →
# /api/review/rules returned HTTP 500 and the entire Rules UI + every review
# went dark. Now we validate each rule INDIVIDUALLY: valid rules load, invalid
# ones are collected and surfaced (see load_rules_safe + the API) instead of
# bricking everything. The file-level shape (version/sources_seen) is still
# parsed leniently.

class RejectedRule(BaseModel):
    """A rules.yaml entry that failed schema validation — kept out of the active
    set but reported so the user can see + fix it (vs a silent/opaque 500)."""
    id: str
    error: str
    raw: dict = {}


def load_rules_safe(path: Path = RULES_YAML) -> tuple[RulesFile, list["RejectedRule"]]:
    """Lenient loader: returns (RulesFile of the VALID rules, [RejectedRule,...]).

    Never raises on a malformed individual rule or a non-fatal file issue. A
    truly unparseable YAML file (syntax error) still surfaces as one rejected
    entry rather than crashing the caller."""
    if not path.exists():
        return RulesFile(), []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        # Whole file unparseable — surface as a single rejected pseudo-rule.
        return RulesFile(), [RejectedRule(id="<rules.yaml>",
                                          error=f"YAML parse error: {e}")]
    if not isinstance(data, dict):
        return RulesFile(), [RejectedRule(id="<rules.yaml>",
                                          error="top-level YAML is not a mapping")]

    raw_rules = data.get("rules") or []
    valid: list = []
    rejected: list[RejectedRule] = []
    from pydantic import TypeAdapter, ValidationError
    rule_adapter = TypeAdapter(Rule)
    for i, raw in enumerate(raw_rules):
        rid = raw.get("id", f"<index {i}>") if isinstance(raw, dict) else f"<index {i}>"
        try:
            valid.append(rule_adapter.validate_python(raw))
        except ValidationError as e:
            # Compact one-line reason(s).
            msgs = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in e.errors()[:4]
            )
            rejected.append(RejectedRule(
                id=str(rid), error=msgs,
                raw=raw if isinstance(raw, dict) else {"value": raw}))

    # Build the RulesFile from the file-level fields + only the valid rules.
    rf = RulesFile(
        version=int(data.get("version", 1) or 1),
        generated_at=str(data.get("generated_at", "") or ""),
        sources_seen=data.get("sources_seen", []) or [],
        rules=valid,
    )
    return rf, rejected


def load_rules(path: Path = RULES_YAML) -> RulesFile:
    """Back-compat strict-ish loader used across the codebase. No longer raises
    on a single bad rule — it drops invalid rules (use load_rules_safe to see
    which). An empty/missing file returns an empty RulesFile."""
    rf, _ = load_rules_safe(path)
    return rf


def save_rules(rf: RulesFile, path: Path = RULES_YAML) -> None:
    path.write_text(
        yaml.safe_dump(rf.model_dump(exclude_none=True), sort_keys=False),
        encoding="utf-8",
    )


# ---- Scoped re-evaluation (impacted-area only) --------------------------
# After a fix the closed loop re-checks only the rules whose subject lives on a
# CHANGED sheet (+ rules whose subject refdes/net touches a changed component),
# trusting the rest as unchanged. This is the "scope re-check to impacted area"
# optimization — typically 1 sheet of ~6, so ~5-6x fewer (slow) semantic/sim
# calls per round. Safe because edits are localized to a sheet; a fix that
# reaches across sheets still re-checks every sheet it touched.

def rule_sheets(rule: Rule, view: NetlistView) -> set[str]:
    """Every sheet a rule's subject could live on. Uses applies_to.sheet when
    set; otherwise resolves the subject refdes/net to its sheet(s) via the view.
    Empty set ⇒ couldn't localize ⇒ treat as global (always re-check)."""
    at = rule.applies_to
    if at.sheet:
        return {at.sheet}
    sheets: set[str] = set()
    # refdes on applies_to or in the structural predicate
    refs: set[str] = set()
    if at.refdes:
        refs.add(at.refdes)
    if isinstance(rule, StructuralRule):
        p = rule.predicate
        for attr in ("refdes",):
            v = getattr(p, attr, None)
            if v:
                refs.add(v)
        for attr in ("from_pin", "to_pin"):
            v = getattr(p, attr, None)
            if isinstance(v, str) and "." in v:
                refs.add(v.split(".", 1)[0])
    for r in refs:
        hit = view.part(r)
        if hit:
            sheets.add(hit[0])
    # net membership
    if at.net:
        for m in view.members(at.net):
            sheets.add(m.sheet)
    return sheets


def scope_rules(all_rules: list[Rule], changed_sheets: set[str],
                changed_refdes: set[str], view: NetlistView
                ) -> tuple[list[Rule], list[Rule]]:
    """Split rules into (impacted, carried_forward) given the changed sheets +
    refdes. Impacted = subject on a changed sheet, OR subject refdes is changed,
    OR couldn't be localized (global → re-check to be safe). carried_forward =
    everything else (verdict reused from the prior round)."""
    impacted: list[Rule] = []
    carried: list[Rule] = []
    for r in all_rules:
        sheets = rule_sheets(r, view)
        ref = r.applies_to.refdes
        if (not sheets) or (sheets & changed_sheets) or (ref and ref in changed_refdes):
            impacted.append(r)
        else:
            carried.append(r)
    return impacted, carried


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
    # Part-agnostic refdes match (preferred): the listed designators must all
    # exist AND be populated (not DNP). Survives a part swap (2N7002 -> BSS138)
    # because it keys on the reference, not a hardcoded MPN.
    if p.refdes:
        for ref in p.refdes:
            hit = view.part(ref)
            if not hit:
                return False
            _sheet, part = hit
            if getattr(part, "dnp", False):
                return False  # present in BOM but DNP => not populated
        return True
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


def eval_sim_review(p: "SimReview", sim_results: dict) -> bool:
    """Agent-judged sim check. RUN the real block (deriving the scenario via the
    sim-setup pass if stale), then hand the result + analysis to claude -p to
    judge against the rule's criterion. Returns True (pass) on any infra failure
    — fail-safe, never fabricates a finding. sim_results may pre-seed a result
    (so the loop runs each block once and reuses it across rules)."""
    res = sim_results.get((p.sim_block, p.sim_type))
    if res is None:
        res = _run_block_for_review(p.sim_block, p.sim_type)
        if res is not None:
            sim_results[(p.sim_block, p.sim_type)] = res  # cache for sibling rules
    if not res or res.get("status") not in ("ran", None):
        return True  # couldn't run the sim → defer (no false finding)
    verdict = _judge_sim_result(p, res)
    return verdict != "FAIL"


def _run_block_for_review(block: str, sim_type: str) -> dict | None:
    """Run a real sim block for review. Best-effort: ensures the operating-point
    scenario exists (the sim-setup agent derives it from requirements/datasheets
    when stale), then runs ngspice via the service. Returns the result dict or
    None on failure."""
    try:
        from test1.sim import service as sim_service
        from test1.sim import simconfig
    except Exception:
        return None
    # Derive params dynamically if the scenario is stale (agent reads reqs +
    # datasheets and writes sim_config). Best-effort + bounded; if the agent
    # path isn't available (headless), run_block_sim still uses cached/defaults.
    try:
        entry = simconfig.entry(block) if hasattr(simconfig, "entry") else {}
        if not entry:
            _ensure_scenario_via_agent(block)
    except Exception:
        pass
    try:
        return sim_service.run_block_sim(block, sim_type)
    except Exception:
        return None


def _ensure_scenario_via_agent(block: str) -> None:
    """Spawn the sim-setup agent (reads requirements + datasheets, derives the
    operating point, writes sim_config) and wait briefly. Synchronous + bounded;
    failures are swallowed (run_block_sim falls back to defaults)."""
    try:
        import sys
        sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
        # Use the bounded CLI rather than the async agent so this stays callable
        # from the sync evaluator thread. iterate_sim runs the block; setup is a
        # heavier path we only trigger when there is genuinely no scenario.
        subprocess.run(
            [sys.executable, str(PROJECT_DIR / "sim" / "iterate_sim.py"),
             "--block", block, "--sim-type", "dc_op_point", "--reset"],
            cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=60,
        )
    except Exception:
        pass


def _humanize_units(analysis: dict) -> dict:
    """Annotate SI-suffixed metrics with engineering-unit readings so the judge
    never has to convert (amps↔µA was a reproducible false-FAIL source: the value
    arrives as 0.000669 A while the criterion is written in µA, and the model
    compared 0.000669 to 640). For any numeric key ending in a known unit suffix,
    add a sibling "<key>_human" string with a scaled, readable value. Pure Python —
    deterministic, not agent guesswork. Leaves everything else untouched."""
    def eng(v: float, unit: str) -> str:
        a = abs(v)
        if unit == "A":
            if a < 1e-3: return f"{v*1e6:.3g} µA"
            if a < 1:    return f"{v*1e3:.3g} mA"
            return f"{v:.3g} A"
        if unit == "V":
            if a < 1:    return f"{v*1e3:.3g} mV"
            return f"{v:.4g} V"
        if unit == "s":
            if a < 1e-6: return f"{v*1e9:.3g} ns"
            if a < 1e-3: return f"{v*1e6:.3g} µs"
            if a < 1:    return f"{v*1e3:.3g} ms"
            return f"{v:.3g} s"
        if unit == "Hz":
            if a >= 1e6: return f"{v/1e6:.3g} MHz"
            if a >= 1e3: return f"{v/1e3:.3g} kHz"
            return f"{v:.3g} Hz"
        return f"{v:g} {unit}"
    SUFFIX = {"_A": "A", "_V": "V", "_s": "s", "_Hz": "Hz", "_ohm": "Ω", "_dB": "dB"}
    out = dict(analysis)
    for k, v in list(analysis.items()):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        for suf, unit in SUFFIX.items():
            if k.endswith(suf):
                out[f"{k}_human"] = eng(float(v), unit) if unit not in ("Ω", "dB") else f"{v:g} {unit}"
                break
    return out


def _judge_sim_result(p: "SimReview", res: dict) -> str:
    """claude -p verdict: does the sim result satisfy the criterion? Returns
    'PASS' | 'FAIL' (fail-safe 'PASS' on any error)."""
    analysis = _humanize_units(res.get("analysis") or {})
    op = res.get("op_point") or {}
    prompt = (
        f"You are reviewing a SPICE simulation result against a design requirement.\n\n"
        f"BLOCK: {p.sim_block} / {p.sim_type}\n"
        f"REQUIREMENT: {p.criterion}\n\n"
        f"SIM RESULT:\n"
        f"  ok (deck's own check): {res.get('ok')}\n"
        f"  analysis: {json.dumps(analysis, default=str)[:1800]}\n"
        f"  op_point: {json.dumps(op, default=str)[:600]}\n\n"
        f"Each numeric metric ending in a unit suffix (e.g. _A, _V, _s, _Hz) has a "
        f"matching <key>_human field giving its value in engineering units — read the "
        f"value from THAT to avoid unit-scale mistakes (e.g. i_max_regulated_A = "
        f"0.000669 → i_max_regulated_A_human = '669 µA'; that is 669 µA, NOT 0.000669 µA).\n\n"
        f"Decide carefully:\n"
        f"  1. Identify the measured value(s) (in engineering units) and the "
        f"required threshold from the requirement.\n"
        f"  2. State the comparison explicitly, e.g. '669 µA >= 640 µA' and whether "
        f"it is satisfied.\n"
        f"  3. The verdict MUST follow that comparison: satisfied ⇒ PASS, not "
        f"satisfied ⇒ FAIL. Do NOT contradict your own comparison.\n\n"
        f"Respond with ONLY one JSON object, no prose:\n"
        f'{{"comparison": "<measured> <op> <threshold> -> satisfied|not satisfied", '
        f'"verdict": "PASS" | "FAIL", "observed": "<one sentence: the measured '
        f'value(s) in engineering units vs the requirement>"}}\n'
        f"If you cannot tell from the result, answer PASS (do not guess a violation)."
    )
    try:
        proc = subprocess.run(
            [_CLAUDE, "-p", prompt, "--model", _SEMANTIC_MODEL,
             "--permission-mode", "plan"],
            cwd=str(PROJECT_DIR), capture_output=True, text=True,
            encoding="utf-8", timeout=_SEMANTIC_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "PASS"
    parsed = _parse_verdict(proc.stdout or "")
    if not parsed:
        return "PASS"
    verdict, observed = parsed
    # stash the observation so _rule_to_finding can use it
    res["_review_observed"] = observed
    return verdict


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
    "sim_review":             lambda p, view, sim: eval_sim_review(p, sim),
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


# ---- Semantic-rule evaluation (claude -p verdict) -----------------------
# A SemanticRule asks a question that can't be reduced to a netlist predicate
# (e.g. "is this op-amp's feedback network appropriate for the stated gain?").
# We hand claude -p the rule's prompt + its cited source excerpts + the relevant
# slice of the as-built netlist, and ask for a strict PASS/FAIL verdict. FAIL
# emits a Finding; PASS — or ANY error/timeout/parse failure — emits nothing
# (fail-safe: a flaky agent must never fabricate a finding or block the loop).

def _part_label(view: NetlistView, refdes: str) -> str:
    """'R12 (10k)' / 'C30 (0.1uF) DNP' — value + DNP for a refdes, best-effort."""
    p = view.part(refdes)
    if not p:
        return refdes
    _, part = p
    dnp = " DNP" if getattr(part, "dnp", False) else ""
    return f"{refdes} ({part.value}){dnp}"


def _mpn_decode_lines(parts: list[tuple[str, object]]) -> list[str]:
    """Deterministic value↔MPN comparison lines for R/C parts whose MPN encodes a
    machine-readable value (Murata EIA pF codes, Vishay RKM / EIA-4 codes, …).

    The semantic value↔MPN judge can't reliably decode opaque manufacturer codes
    from memory (an E2E test caught it passing a 5.11k value behind a `3K65`
    MPN), so we decode them HERE and surface a pre-computed MATCH/MISMATCH the
    judge can just read. Conservative: parts whose MPN isn't decodable are
    omitted (no line == 'use your own judgement'), never asserted as a match."""
    out: list[str] = []
    for ref, part in parts:
        try:
            line = mpn_value.describe(ref, str(part.value),
                                      str(getattr(part, "lib_id", "")))
        except Exception:
            line = None  # decoder is best-effort; never break evaluation
        if line:
            out.append("  " + line)
    return out


def _part_datasheet_facts(rule: "SemanticRule", view: NetlistView) -> list[str]:
    """FAIL-SAFE for part-specific semantic rules: surface the ACTUALLY-populated
    subject part + its datasheet, and warn if the rule's own text names a DIFFERENT
    part (stale citation after a part swap).

    Background: BLK_BIAS_ISO_GATE_DRIVE was authored citing 2n7002.pdf with the
    2N7002's Vth baked into the prompt. After Q42/Q43 were swapped to BSS138 the
    judge kept reusing the 2N7002 number (a stale-citation false verdict). This
    block makes the rule re-ground on the populated part automatically and flags
    the drift so it can't pass silently on the wrong part's spec."""
    out: list[str] = []
    at = rule.applies_to
    if not at.refdes:
        return out
    p = view.part(at.refdes)
    if not p:
        return out
    _sheet, part = p
    lib_id = str(getattr(part, "lib_id", "") or "")
    mpn = lib_id.split(":", 1)[1].strip() if ":" in lib_id else lib_id.strip()
    if not mpn:
        return out
    # Locate the populated part's datasheet under Parts Library/<MPN>/.
    ds_dir = PROJECT_DIR / "Parts Library" / mpn
    pdfs = sorted(ds_dir.glob("*.pdf")) if ds_dir.exists() else []
    ds_hint = (f"Parts Library/{mpn}/{pdfs[0].name}" if pdfs
               else f"(no local datasheet found under Parts Library/{mpn}/)")
    out.append(
        f"\nPOPULATED-PART DATASHEET FACTS (FAIL-SAFE — judge the ACTUAL part, not "
        f"any part named in the rule text):\n"
        f"  {at.refdes} is populated as MPN '{mpn}'. Read its spec from its OWN "
        f"datasheet: {ds_hint}. If the rule's prose or citations quote a threshold "
        f"for a DIFFERENT part, that value does NOT apply unless it matches '{mpn}'."
        f" Use '{mpn}'’s own datasheet values.")
    return out


def _netlist_context_for(rule: SemanticRule, view: NetlistView) -> str:
    """Build a focused but COMPLETE netlist excerpt for the rule's applies_to so
    the agent judges against the ACTUAL design.

    Crucially, for every net the subject touches we expand the FULL membership of
    that net (with each member's value). This is what lets the evaluator see a
    pull-up/pull-down wired through a series resistor on the same node — without
    it, the evaluator only saw the subject's own pins and produced false
    positives (e.g. 'LDO PG has no pull-up' when R12 sits on that very net)."""
    at = rule.applies_to
    lines: list[str] = []
    nets_to_expand: list[str] = []

    if at.refdes:
        p = view.part(at.refdes)
        if p:
            sheet, part = p
            lines.append(f"SUBJECT {at.refdes} ({sheet}): value={part.value} "
                         f"lib_id={part.lib_id} footprint={getattr(part, 'footprint', '') or '(none)'} "
                         f"dnp={getattr(part, 'dnp', False)}")
        lines.append(f"{at.refdes} pin -> net:")
        for m in view.nets_with_member(at.refdes):
            lines.append(f"  {at.refdes}.{m.pin} -> '{m.net}'")
            nets_to_expand.append(m.net)
    if at.net:
        nets_to_expand.append(at.net)

    # Expand each touched net to its FULL membership (dedup, cap for prompt size).
    seen: set[str] = set()
    for net in nets_to_expand:
        if net in seen:
            continue
        seen.add(net)
        members = view.members(net)
        if not members:
            continue
        body = ", ".join(
            f"{m.refdes}.{m.pin} [{_part_label(view, m.refdes)}]" for m in members[:30]
        )
        lines.append(f"\nnet '{net}' — every member (so pull-ups/downs/series-R "
                     f"on this node are visible):\n  {body}")

    # When the rule names a sheet (most semantic rules do), include that whole
    # sheet's parts so the agent judges against the real components.
    if at.sheet and at.sheet in view.by_sheet:
        nl = view.by_sheet[at.sheet]
        lines.append(f"\nAll parts on sheet '{at.sheet}':")
        for ref, part in nl.parts.items():
            dnp = " DNP" if getattr(part, "dnp", False) else ""
            fp = getattr(part, "footprint", "") or ""
            fp_s = f" footprint={fp}" if fp else ""
            lines.append(f"  {ref}: {part.value} ({part.lib_id}){fp_s}{dnp}")

    # Deterministic value↔MPN decode (Murata/Vishay codes the judge can't read
    # from memory). Scope it to the parts in view: the named sheet, else — for a
    # board-wide rule with no specific subject (e.g. CHK_VALUE_MATCHES_MPN, whose
    # applies_to is empty) — EVERY R/C part across all sheets, since that rule has
    # nothing else to anchor on and would otherwise see no parts at all.
    decode_scope: list[tuple[str, object]] = []
    if at.sheet and at.sheet in view.by_sheet:
        decode_scope = list(view.by_sheet[at.sheet].parts.items())
    elif not (at.refdes or at.net or at.sheet):
        for nl in view.by_sheet.values():
            decode_scope.extend(nl.parts.items())
    elif at.refdes:
        p = view.part(at.refdes)
        if p:
            decode_scope = [(at.refdes, p[1])]
    decoded = _mpn_decode_lines(decode_scope)
    if decoded:
        lines.append(
            "\nDECODED PART VALUE vs MPN (computed deterministically from the "
            "manufacturer part number — trust these over your own code-reading; "
            "MISMATCH = the displayed value contradicts the part number):")
        lines.extend(decoded)

    # FAIL-SAFE: for a part-specific rule, re-ground on the POPULATED part's
    # datasheet + warn on stale part-name citations (prevents a rule authored
    # against an old part from judging a swapped-in part by the wrong spec).
    lines.extend(_part_datasheet_facts(rule, view))

    return "\n".join(lines) if lines else "(no specific netlist subject; judge against the cited source + design intent)"


def _build_semantic_prompt(rule: SemanticRule, view: NetlistView) -> str:
    quotes = "\n".join(
        f"  - [{c.doc}:{c.loc}] {c.quote}" for c in rule.source if c.quote
    ) or "  (no verbatim quote on this rule's citation)"
    ctx = _netlist_context_for(rule, view)
    return (
        f"You are a hardware design-review checker. Evaluate ONE rule against the "
        f"as-built design and return a strict JSON verdict.\n\n"
        f"RULE: {rule.title}\n"
        f"QUESTION: {rule.prompt}\n\n"
        f"CITED REQUIREMENT / DATASHEET SOURCE:\n{quotes}\n\n"
        f"RELEVANT AS-BUILT NETLIST:\n{ctx}\n\n"
        f"Decide whether the design SATISFIES the rule. Respond with ONLY a single "
        f"JSON object, no prose, no code fence:\n"
        f'{{"verdict": "PASS" | "FAIL", "observed": "<one concise sentence of what '
        f'you found that justifies the verdict>"}}\n'
        f"PASS = the design meets the rule. FAIL = it violates it. If you cannot "
        f'tell from the given source + netlist, answer PASS (do not guess a violation).'
    )


def _parse_verdict(text: str) -> tuple[str, str] | None:
    """Extract {"verdict","observed"} from the agent's output. Tolerant of a
    surrounding code fence or stray prose. Returns (verdict, observed) or None.

    Consistency guard: sim_review emits an extra "comparison" field ending in
    "satisfied" / "not satisfied". The sonnet judge sometimes reads the value
    right but still emits a verdict that contradicts its own comparison ("…below
    640 µA — wait, 669 ≥ 640" then FAIL). When a comparison is present, the
    verdict is forced to follow it (satisfied ⇒ PASS), since the explicit
    comparison is more reliable than the free-form verdict. Semantic rules don't
    emit "comparison", so they're unaffected."""
    if not text:
        return None
    # Take the LAST verdict object, not the first: the judge sometimes emits a
    # wrong object, then self-corrects with a second ("…-> not satisfied", FAIL —
    # then "wait, 669 > 640" → a corrected "…-> satisfied", PASS object). Its final
    # answer is the one that counts, so scan all and keep the last parseable one.
    objs = re.findall(r"\{[^{}]*\"verdict\"[^{}]*\}", text, re.DOTALL)
    obj = None
    for cand in reversed(objs):
        try:
            obj = json.loads(cand)
            break
        except (json.JSONDecodeError, ValueError):
            continue
    if obj is None:
        return None
    v = str(obj.get("verdict", "")).strip().upper()
    if v not in ("PASS", "FAIL"):
        return None
    observed = str(obj.get("observed", "")).strip()
    comp = str(obj.get("comparison", "")).strip().lower()
    if comp:
        # "not satisfied" → FAIL; a clear "satisfied" (not preceded by "not") → PASS.
        if "not satisfied" in comp or "unsatisfied" in comp:
            v = "FAIL"
        elif "satisfied" in comp:
            v = "PASS"
    return v, observed


def _eval_semantic_rule(rule: SemanticRule, view: NetlistView) -> Finding | None:
    """Run one semantic rule via claude -p. Returns a Finding on FAIL, else None
    (PASS or any failure — fail-safe, never fabricates a finding)."""
    prompt = _build_semantic_prompt(rule, view)
    try:
        proc = subprocess.run(
            [_CLAUDE, "-p", prompt, "--model", _SEMANTIC_MODEL,
             "--permission-mode", "plan"],   # read-only: the checker must not edit
            cwd=str(PROJECT_DIR),
            capture_output=True, text=True, encoding="utf-8",
            timeout=_SEMANTIC_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None  # fail-safe: no verdict -> no finding
    parsed = _parse_verdict(proc.stdout or "")
    if not parsed:
        return None
    verdict, observed = parsed
    if verdict == "FAIL":
        return _rule_to_finding(rule, observed=observed or "semantic rule violated")
    return None


# ---- Top-level runner ---------------------------------------------------

def run_all(rules: list[Rule] | None = None,
            sim_results: dict | None = None,
            semantic: bool = False,
            progress=None) -> list[Finding]:
    """Evaluate every enabled rule against the current netlist + sim cache.

    sim_results: { (block, sim_type): result_dict } as produced by the
    Phase 4 orchestrator. None means "no sim data" — sim_pass/sim_metric
    rules return PASS (silent) when their data is absent.

    semantic: when True, SemanticRules are evaluated via claude -p (one verdict
    per rule — slower, N agent calls). Default False keeps the structural path
    instant (the GUI's quick lint/refresh uses it); the closed-loop + an explicit
    full review opt in. Semantic eval is fail-safe: a timeout/parse error yields
    no finding rather than a false positive.

    progress: optional callback(kind, payload) for live progress (the closed loop
    bridges this to SSE so the review console streams activity like the sim tab).
    Called as progress("rule", {i, total, id, evaluation, result})."""
    if rules is None:
        rf = load_rules()
        rules = rf.rules
    view = load_all()
    sim = sim_results or {}
    # What we'll actually evaluate. Structural predicates are instant EXCEPT
    # sim_review (runs ngspice + a judge agent) — gate those behind `semantic`
    # alongside the LLM semantic rules, so the fast path stays instant.
    def _is_slow(r) -> bool:
        return (not isinstance(r, StructuralRule)) or \
               (isinstance(r, StructuralRule) and r.predicate.kind == "sim_review")
    active = [r for r in rules if r.enabled and (semantic or not _is_slow(r))]
    total = len(active)
    # Stable index per rule so progress + ordering are deterministic regardless
    # of completion order under concurrency.
    idx_of = {id(r): i for i, r in enumerate(active, 1)}
    findings_by_idx: dict[int, Finding] = {}

    def _emit(rule, result: str) -> None:
        if progress is None:
            return
        try:
            progress("rule", {"i": idx_of[id(rule)], "total": total, "id": rule.id,
                              "evaluation": getattr(rule, "evaluation", "structural"),
                              "result": result})
        except Exception:
            pass  # best-effort; never break evaluation

    def _eval_one(rule) -> None:
        """Evaluate one rule; record a finding (by stable index) on fail + emit
        progress. Safe to call from worker threads."""
        result = "pass"
        if isinstance(rule, StructuralRule):
            ok = _DISPATCH[rule.predicate.kind](rule.predicate, view, sim)
            if not ok:
                observed = "rule fired"
                if rule.predicate.kind == "sim_review":
                    r = sim.get((rule.predicate.sim_block, rule.predicate.sim_type)) or {}
                    observed = r.get("_review_observed") or "sim result did not meet the requirement"
                findings_by_idx[idx_of[id(rule)]] = _rule_to_finding(rule, observed=observed)
                result = "fail"
        else:  # SemanticRule
            f = _eval_semantic_rule(rule, view)
            if f is not None:
                findings_by_idx[idx_of[id(rule)]] = f
                result = "fail"
        _emit(rule, result)

    # Split fast (instant Python predicates) vs slow (agent/ngspice). Fast run
    # inline; slow run in a bounded thread pool so 16 agent calls finish in
    # ~max(call) instead of sum(calls) — the responsiveness fix.
    fast = [r for r in active if not _is_slow(r)]
    slow = [r for r in active if _is_slow(r)]
    for rule in fast:
        _eval_one(rule)

    if slow:
        # Pre-run the DISTINCT sim blocks ONCE (concurrently) so multiple
        # sim_review rules sharing a block don't each spawn a duplicate ngspice
        # run / race the shared cache. The judge agents then read cached results.
        distinct_blocks = []
        seen_blk = set()
        for r in slow:
            if isinstance(r, StructuralRule) and r.predicate.kind == "sim_review":
                key = (r.predicate.sim_block, r.predicate.sim_type)
                if key not in seen_blk and key not in sim:
                    seen_blk.add(key)
                    distinct_blocks.append(key)
        if distinct_blocks:
            with ThreadPoolExecutor(max_workers=min(4, len(distinct_blocks))) as ex:
                futs = {ex.submit(_run_block_for_review, b, st): (b, st)
                        for (b, st) in distinct_blocks}
                for fut in as_completed(futs):
                    b, st = futs[fut]
                    try:
                        res = fut.result()
                        if res is not None:
                            sim[(b, st)] = res
                    except Exception:
                        pass

        # Now judge/eval all slow rules concurrently (sims are cached; judges +
        # semantic agents are independent claude -p calls).
        with ThreadPoolExecutor(max_workers=min(8, len(slow))) as ex:
            list(ex.map(_eval_one, slow))

    # Assemble findings in stable rule order.
    return [findings_by_idx[i] for i in sorted(findings_by_idx)]
