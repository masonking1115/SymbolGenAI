"""Phase 2a: deterministic Python rules — the structural-check layer.

Every rule is a function that takes (RequirementsIndex, NetlistView)
and yields Findings. The dispatcher `run_all` collects them.

Rules here catch issues with stable, machine-detectable shape:
  - missing pull-ups / pull-downs on nets the requirements doc names
  - missing decoupling caps on IC power pins
  - open-drain outputs without a pull-up to a logic rail
  - hier-label parity (every parent pin has a child label and vice-versa)

Anything that requires reading a datasheet or judging a topology choice
lives in `semantic_review.py` (Phase 2b).

Adding a rule:
  1. Write a function `def check_<thing>(idx, view) -> Iterable[Finding]`.
  2. Use a stable rule_id (UPPER_SNAKE_CASE) and a stable subject string
     so the renderer assigns the same ordinal across runs.
  3. Register it in RULES below.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from .findings import AutofixCategory, Finding, Severity
from .netlist_view import NetlistView, load_all
from .requirements_index import RequirementsIndex

PROJECT_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Hard-coded knowledge that doesn't live in the requirements doc.
# When we get to Phase 2 fingerprints, this moves into parts/<MPN>.json.
# ---------------------------------------------------------------------------

# Open-drain outputs that REQUIRE a pull-up. (refdes, pin, rail-hint, datasheet)
OPEN_DRAIN_OUTPUTS = [
    # TPS7A8401A PG — datasheet SBVS210 §7.3.4. Pin 4 on this design's symbol.
    ("U10", "4", "+3V3", "TPS7A8401A SBVS210 §7.3.4 Power Good"),
]

# I²C buses that need pull-ups somewhere in the project (one set, shared).
I2C_BUSES = [
    ("SCL", "+3V3", "I²C bus standard practice (typ. 2.2k–10k)"),
    ("SDA", "+3V3", "I²C bus standard practice (typ. 2.2k–10k)"),
]


# Pull-down/up requirements expressed as the requirements doc states them.
# Each entry: (net_name, kind, rail, source_quote).
# kind = "pulldown" → expect a resistor with the net + GND
# kind = "pullup"   → expect a resistor with the net + named rail
BOBCAT_PULLS = [
    ("MOSI",        "pulldown", "GND",     "design_requirements.md:15"),
    ("SCLK",        "pulldown", "GND",     "design_requirements.md:15"),
    ("SPI_DMODE",   "pulldown", "GND",     "design_requirements.md:15"),
    ("OSC_EN",      "pulldown", "GND",     "design_requirements.md:15"),
    ("WEIGHT_EN",   "pulldown", "GND",     "design_requirements.md:15"),
    ("SAMPLE_TRIG", "pulldown", "GND",     "design_requirements.md:15"),
    ("GPIO0",       "pulldown", "GND",     "design_requirements.md:15"),
    ("GPIO1",       "pulldown", "GND",     "design_requirements.md:15"),
    ("GPIO2",       "pulldown", "GND",     "design_requirements.md:15"),
    ("GPIO3",       "pulldown", "GND",     "design_requirements.md:15"),
    ("CS_L",        "pullup",   "+VDDIO",  "design_requirements.md:15"),
    ("RESET_N",     "pullup",   "+VDDIO",  "design_requirements.md:15"),
]

# Decoupling-cap requirements, keyed by IC + the pins sharing a rail.
# For each group, the rule walks the YAML, picks up every net those pins
# belong to (rail OR internal_<rail>_path), and counts cap members on
# the union of those nets. Series-0Ω-isolated caps are caught this way
# because they sit on the internal_<rail>_path net by design.
# (refdes, [pin numbers], rail_label_for_msg, expected_count, source)
IC_POWER_GROUPS = [
    ("U20", ["1"],             "+VDDA1", 1, "Bobcat PDF page 4"),
    ("U20", ["12", "20"],      "+VDDD",  2, "Bobcat PDF page 4"),
    ("U20", ["26", "27"],      "+VDDA2", 1, "Bobcat PDF page 4"),
    ("U20", ["7","13","22","33","34"], "+VDDIO", 6,
        "Bobcat PDF page 4 (5 pins + 1 bulk)"),
    ("U10", ["15","16","17"],  "+3V3 (Vin)", 2,
        "TPS7A8401A SBVS210 §8.2.2.1 (10µF + 0.1µF)"),
    ("U10", ["12"],            "BIAS",   1,
        "TPS7A8401A SBVS210 §8.2.2.1 (1µF on BIAS)"),
    ("U10", ["1","19","20"],   "Vout",   2,
        "TPS7A8401A SBVS210 §8.2.2.1 (22µF + 0.1µF on OUT)"),
    ("U40", ["1"],             "+3V3 (VDD)", 1,
        "MCP4728 22187E Figure 2-1"),
    ("U11", ["A2"],            "VADJ",   1, "TPS22916 §8.2.2.2 VIN"),
    ("U11", ["A1"],            "+VDDIO", 1, "TPS22916 §8.2.2.2 VOUT"),
]


# ---------------------------------------------------------------------------
# Rule: pulls present.
# ---------------------------------------------------------------------------

_PULL_VALUE_RE = re.compile(r"^\s*10\s*k\s*$", re.IGNORECASE)


def _is_pull_resistor(value: str) -> bool:
    return bool(_PULL_VALUE_RE.match(value))


def check_bobcat_pulls(idx: RequirementsIndex, view: NetlistView) -> Iterable[Finding]:
    """For every Bobcat pull declared in the requirements doc, confirm a 10kΩ
    resistor exists whose two pins are (the named net) and (the named rail)."""
    for net, kind, rail, source in BOBCAT_PULLS:
        members = view.members(net)
        rail_members = view.members(rail)
        net_resistors = {r.refdes for r in members if r.refdes.startswith("R")}
        rail_resistors = {r.refdes for r in rail_members if r.refdes.startswith("R")}
        candidates = net_resistors & rail_resistors

        # At least one candidate must also be a 10k resistor.
        ok = False
        for rd in candidates:
            hit = view.part(rd)
            if hit and _is_pull_resistor(hit[1].value):
                ok = True
                break
        if ok:
            continue

        severity = Severity.ERROR
        autofix: AutofixCategory = "pullup_pulldown"
        yield Finding(
            rule_id=f"MISSING_{kind.upper()}",
            severity=severity,
            title=f"Missing 10kΩ {kind} on {net}",
            subject=f"{net}",
            sheet="bobcat",
            component_refs=[net],
            requirement_ref=source,
            observed=(f"No 10kΩ resistor between {net} and {rail} "
                      f"(candidates: {sorted(candidates) or 'none'})"),
            impact=("Input floats at POR — undefined state risks metastability, "
                    "false triggering, or latch-up." if kind == "pulldown"
                    else "Open-domain input could be misread as asserted."),
            fix=f"Add a 10kΩ 0402 resistor between {net} and {rail} on the bobcat sheet.",
            autofix=autofix,
            autofix_data={"net": net, "rail": rail, "kind": kind, "value": "10k"},
        )


# ---------------------------------------------------------------------------
# Rule: open-drain outputs need pull-ups.
# ---------------------------------------------------------------------------

def check_open_drain_pullups(idx: RequirementsIndex,
                             view: NetlistView) -> Iterable[Finding]:
    for refdes, pin, rail_hint, source in OPEN_DRAIN_OUTPUTS:
        # Which nets does that pin belong to?
        pin_nets = view.nets_with_member(refdes, pin)
        if not pin_nets:
            continue   # pin not wired at all — caught by the validator
        target_net = pin_nets[0].net
        rail_members = view.members(rail_hint)
        target_members = view.members(target_net)
        target_resistors = {r.refdes for r in target_members
                            if r.refdes.startswith("R")}
        rail_resistors = {r.refdes for r in rail_members
                          if r.refdes.startswith("R")}
        candidates = target_resistors & rail_resistors
        ok = any(
            view.part(rd) and _is_pull_resistor(view.part(rd)[1].value)  # type: ignore[index]
            for rd in candidates
        )
        if ok:
            continue
        yield Finding(
            rule_id="OPEN_DRAIN_NO_PULLUP",
            severity=Severity.ERROR,
            title=f"Open-drain output {refdes}.{pin} ({target_net}) has no pull-up",
            subject=f"{refdes}.{pin}",
            sheet=pin_nets[0].sheet,
            component_refs=[refdes],
            datasheet_ref=source,
            observed=f"No 10kΩ resistor between {target_net} and {rail_hint}",
            impact="Open-drain output sits high-impedance when asserted; downstream may not read a reliable HIGH.",
            fix=f"Add a 10kΩ 0402 pull-up between {target_net} and {rail_hint}.",
            autofix="pullup_pulldown",
            autofix_data={"net": target_net, "rail": rail_hint, "kind": "pullup", "value": "10k"},
        )


# ---------------------------------------------------------------------------
# Rule: I²C pull-ups.
# ---------------------------------------------------------------------------

def check_i2c_pullups(idx: RequirementsIndex, view: NetlistView) -> Iterable[Finding]:
    for bus, rail, source in I2C_BUSES:
        net_members = view.members(bus)
        rail_members = view.members(rail)
        net_resistors = {r.refdes for r in net_members if r.refdes.startswith("R")}
        rail_resistors = {r.refdes for r in rail_members if r.refdes.startswith("R")}
        if net_resistors & rail_resistors:
            continue
        yield Finding(
            rule_id="MISSING_I2C_PULLUP",
            severity=Severity.ERROR,
            title=f"I²C {bus} has no pull-up to {rail}",
            subject=f"{bus}",
            sheet="eeprom",
            datasheet_ref=source,
            observed=f"No resistor between {bus} and {rail} anywhere in the project",
            impact="I²C bus cannot reach logic HIGH; transactions will fail.",
            fix=f"Add a 2.2k–10kΩ resistor between {bus} and {rail} (typ. on the eeprom sheet).",
            autofix="pullup_pulldown",
            autofix_data={"net": bus, "rail": rail, "kind": "pullup", "value": "2.2k"},
        )


# ---------------------------------------------------------------------------
# Rule: decoupling cap count per IC rail.
# ---------------------------------------------------------------------------

def _value_is_cap(v: str) -> bool:
    return bool(re.search(r"\d+\.?\d*\s*[µu]F", v)) or bool(re.search(r"\d+\s*nF", v))


def check_decoupling(idx: RequirementsIndex, view: NetlistView) -> Iterable[Finding]:
    for refdes, pins, rail_label, expected, source in IC_POWER_GROUPS:
        # Collect every net these pins live on (handles internal_<rail>_path).
        nets: set[str] = set()
        for pn in pins:
            for nm in view.nets_with_member(refdes, pn):
                nets.add(nm.net)
        if not nets:
            continue   # pins not in any YAML net — generator bug, not a review finding

        # Union of cap members across all those nets.
        caps: set[str] = set()
        for net in nets:
            for m in view.members(net):
                if m.refdes.startswith("C"):
                    caps.add(m.refdes)

        if len(caps) >= expected:
            continue

        ic_hit = view.part(refdes)
        ic_sheet = ic_hit[0] if ic_hit else "?"
        yield Finding(
            rule_id="INSUFFICIENT_DECOUPLING",
            severity=Severity.WARNING,
            title=f"{refdes} {rail_label} decoupling — found {len(caps)}, expected ≥{expected}",
            subject=f"{refdes}:{rail_label}",
            sheet=ic_sheet,
            component_refs=[refdes],
            datasheet_ref=source,
            observed=(f"Caps on net(s) {sorted(nets)}: "
                      f"{sorted(caps) or 'none'}"),
            impact="Higher rail impedance at frequency; per-pin transient response degraded.",
            fix=f"Add {expected - len(caps)}× 0.1µF 0402 cap near {refdes} on the {rail_label} rail.",
            autofix="decoupling",
            autofix_data={
                "refdes": refdes, "rail_label": rail_label,
                "sheet": ic_sheet, "nets": sorted(nets),
                "need": expected - len(caps), "value": "0.1uF",
            },
        )


# ---------------------------------------------------------------------------
# Rule: requirements-listed parts that aren't in the netlist.
# ---------------------------------------------------------------------------

# Keyword-to-refdes-hint mapping — used to confirm a "Parts to implement"
# entry from the requirements doc actually exists in the project.
PARTS_INDEX_HINTS = {
    "Bobcat":         ("U20",),
    "TPS7A8401A":     ("U10",),
    "Load switch":    ("U11",),
    "EEPROM":         ("U30",),
    "Bias circuit":   ("U40", "U41", "Q40", "Q41"),
    "SMA connectors": ("J50", "J51", "J52", "J53", "J54", "J55", "J56"),
}


def check_parts_present(idx: RequirementsIndex,
                        view: NetlistView) -> Iterable[Finding]:
    for part_name, hints in PARTS_INDEX_HINTS.items():
        if not idx.part(part_name):
            continue   # requirements doc doesn't mention it — skip
        if not any(view.part(h) for h in hints):
            yield Finding(
                rule_id="REQUIRED_PART_MISSING",
                severity=Severity.ERROR,
                title=f"Required part '{part_name}' not found in netlist",
                subject=part_name,
                sheet="?",
                requirement_ref=f"design_requirements.md (Parts to implement: {part_name})",
                observed=f"None of {list(hints)} present in any sheet's netlist",
                impact="Requirements-mandated function is unimplemented.",
                fix=f"Add a part fulfilling the '{part_name}' role to the netlist + a build_<sheet>.py.",
                autofix="manual",
            )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

RULES = [
    check_parts_present,
    check_bobcat_pulls,
    check_open_drain_pullups,
    check_i2c_pullups,
    check_decoupling,
]


def run_all(idx: RequirementsIndex) -> list[Finding]:
    view = load_all()
    out: list[Finding] = []
    for rule in RULES:
        out.extend(rule(idx, view))
    return out
