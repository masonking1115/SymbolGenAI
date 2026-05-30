#!/usr/bin/env python3
"""Close the rule-set audit gaps + apply the new general checklist.

Two batches, merged idempotently into rules.yaml (re-run safe on these ids):

1. SIGNAL ROUTING (structural, family=schematic): the spec lists 14 Bobcat→FMC
   signals routed through series 0Ω; the pull-up/down ones were covered but
   SAMPLE_OUTV/0-7 + MISO had NO rule asserting they reach the FMC. Add a
   net_routing(via=series_R) per signal, matching the existing SERIESR_VDDA*
   pattern (Bobcat pin → its series-R far side). Also drop the shared-LDO
   duplicate (SEM_SHARED_LDO_INTENT — BLK_LDO_SHARED_RAIL_INTENT covers it).

2. GENERAL CHECKLIST (semantic, family=schematic): items from the user's general
   checklist that aren't already covered by existing rules or the layout linter.
   Authored as semantic rules (claude -p judge) because the available structural
   predicates can't express them and we are NOT changing the evaluator/linter.
   Items already covered are intentionally skipped (see SKIPPED below).

SKIPPED (already covered, do not duplicate):
  • No shorted components            → validator._check_shorted_components + layout_lint.shorted_component
  • Power nets need a decoupling cap  → DECOUPLE_* rules
  • IC power/gnd pins connected       → RAIL_* rules
  • I2C names match / pull-ups / range→ BLK_EEPROM_I2C_PULLUPS + VAL_I2C_PULLUP_R60/R61
  • Open-drain needs pull-up          → BLK_LDO_PG_PULLUP
  • Designator/pin-number uniqueness, pin-names-match-datasheet, diff-pair _P/_N,
    diff polarity                     → structural/library checks (layout_lint + validator), not design-review
"""

from __future__ import annotations

from .rule_eval import load_rules, save_rules
from .rule_schema import (
    AppliesTo, RulesFile, SemanticRule, SourceCitation, StructuralRule, NetRouting,
)

REQ = "design_requirements.md"

# signal -> (Bobcat U20 pin, series-R refdes), from the netlist.
_SIGNALS = {
    "SAMPLE_OUTV": ("2", "R100"), "SAMPLE_OUT0": ("3", "R101"),
    "SAMPLE_OUT1": ("4", "R102"), "SAMPLE_OUT2": ("5", "R103"),
    "SAMPLE_OUT3": ("6", "R104"), "SAMPLE_OUT4": ("8", "R105"),
    "SAMPLE_OUT5": ("9", "R106"), "SAMPLE_OUT6": ("10", "R107"),
    "SAMPLE_OUT7": ("11", "R108"), "MISO": ("15", "R112"),
}


def _routing_rules():
    out = []
    for sig, (upin, rref) in _SIGNALS.items():
        out.append(StructuralRule(
            id=f"ROUTE_{sig}", family="schematic", severity="ERROR",
            title=f"{sig} must route to the FMC through its series 0Ω ({rref})",
            applies_to=AppliesTo(net=sig, refdes="U20", sheet="bobcat"),
            source=[SourceCitation(
                doc=REQ, loc="FMC LPC pinout / LA bank",
                quote="Bobcat → FMC LA bank (via 0Ω): SAMPLE_OUTV, SAMPLE_OUT0–7, "
                      "CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N")],
            fix_hint=f"Route U20.{upin} ({sig}) to the FMC LA pin through {rref} (series 0Ω).",
            origin="generated",
            predicate=NetRouting(from_pin=f"U20.{upin}", to_pin=f"{rref}.2", via="series_R"),
        ))
    return out


def _sem(rid, *, sev, title, sheet, prompt, loc, quote, fix, refdes=None, net=None):
    return SemanticRule(
        id=rid, family="schematic", severity=sev, title=title,
        applies_to=AppliesTo(sheet=sheet, refdes=refdes, net=net),
        source=[SourceCitation(doc=REQ, loc=loc, quote=quote)],
        fix_hint=fix, origin="generated", prompt=prompt,
    )


def _checklist_rules():
    """Applicable general-checklist items as board-wide semantic checks (sheet=None
    means the judge looks across the design). These are advisory hygiene checks."""
    R = []
    R.append(_sem(
        "CHK_PARTS_HAVE_MPN", sev="WARNING",
        title="Every component should have a Manufacturer Part Number / library part",
        sheet=None, loc="Parts to implement",
        quote="Parts to implement: Bobcat, TPS7A8401A, Load switch, EEPROM, Bias circuit, SMAs, header.",
        prompt=("Check that every placed component carries a real Manufacturer Part Number (the lib_id / value "
                "is an MPN or a defined library part, not a placeholder). Connectors (J*), SMAs, and headers count. "
                "PASS if all parts are MPN-associated; FAIL listing any with a missing/placeholder MPN."),
        fix="Assign an MPN / library part to every component (esp. connectors J50–J56, headers)."))
    R.append(_sem(
        "CHK_PASSIVES_HAVE_VALUE", sev="WARNING",
        title="Every R/C/L/crystal/fuse must have a value",
        sheet=None, loc="Parts to implement",
        quote="Decoupling caps … 10kΩ pull-downs … 5.11 kΩ … series 0Ω …",
        prompt=("Check that every resistor, capacitor, inductor, crystal, and fuse has a defined value (e.g. '10k', "
                "'0.1uF', '0'); a 0Ω jumper counts as a value. PASS if all passives are valued; FAIL listing any "
                "with an empty/missing value."),
        fix="Give every passive a value (a 0Ω jumper is '0', not blank)."))
    R.append(_sem(
        "CHK_SIGNAL_NET_MIN_TWO_PINS", sev="WARNING",
        title="Every signal net should connect to at least two pins (no single-pin/floating nets)",
        sheet=None, loc="Topology / block diagram",
        quote="Bobcat SPI, RESET_N, and SAMPLE_OUT signals route to the FMC through series 0Ω resistors",
        prompt=("Check that each non-power signal net connects to at least two pins (a source and a destination). "
                "A net with only ONE pin is floating/unterminated — e.g. a SAMPLE_OUT that reaches its series-R but "
                "whose far side never reaches the FMC. Ignore intentional single-pin test points / NC. PASS if all "
                "signal nets have >=2 pins; FAIL listing any single-pin signal net."),
        fix="Terminate every signal net at >=2 pins (route the output to its destination)."))
    R.append(_sem(
        "CHK_NO_MULTI_DRIVER", sev="ERROR",
        title="No signal net may have multiple output drivers (contention)",
        sheet=None, loc="Interfaces",
        quote="SPI (CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N), I²C (EEPROM + Bias), GPIO0–3",
        prompt=("Check that no signal net is driven by two or more push-pull OUTPUT pins simultaneously (driver "
                "contention). Open-drain/I²C buses with multiple devices + a pull-up are fine. PASS if no net has "
                "≥2 conflicting push-pull drivers; FAIL listing the contended net(s)."),
        fix="Ensure each signal net has a single push-pull driver (or open-drain + pull-up for shared buses)."))
    R.append(_sem(
        "CHK_POWER_NOT_SHORTED_GND", sev="ERROR",
        title="Power rails must not be shorted to GND",
        sheet=None, loc="Specs",
        quote="Power in (from FMC): 3P3V; VADJ 1.2–3.3V; Bobcat rails VDDD/VDDA1/VDDA2 = 0.6–1.0V; VDDIO = VADJ",
        prompt=("Check that no power rail (+3V3, VADJ, +VDDIO, +VDDD, +VDDA1, +VDDA2, LDO output) is directly "
                "connected to GND (a dead short). A decoupling cap from rail to GND is expected and fine; a direct "
                "wire/0Ω from rail to GND is not. PASS if no rail is shorted to GND; FAIL listing the shorted rail."),
        fix="Remove any direct rail-to-GND connection (decoupling caps are fine; a 0Ω/wire short is not)."))
    R.append(_sem(
        "CHK_VALUE_MATCHES_MPN", sev="INFO",
        title="Component schematic value should match the manufacturer part value",
        sheet=None, loc="Parts to implement",
        quote="5.11 kΩ 0.1% thin-film sense resistor … 10kΩ pull-downs … 2.2 kΩ I²C pull-ups",
        prompt=("Spot-check that each component's displayed schematic value is consistent with its MPN (e.g. a part "
                "labeled '10k' uses a 10k-MPN resistor; the 3.65k sense R uses a 3.65k part — NOTE: R40/R41 were "
                "changed to 3.65k but may still reference the 5.11k MPN lib_id TNPW06035K11BEEA, which is a real "
                "mismatch to flag). PASS if values match their MPNs; FAIL listing mismatches."),
        fix="Reconcile each schematic value with its MPN (notably R40/R41: 3.65k value vs the 5.11k MPN lib_id)."))
    R.append(_sem(
        "CHK_CAP_VOLTAGE_DERATING", sev="INFO",
        title="Capacitors on power rails must have adequate voltage derating",
        sheet=None, loc="Specs",
        quote="Power in (from FMC): 3P3V … VADJ 1.2–3.3V",
        prompt=("Check that capacitors on power rails are rated comfortably above the rail voltage (a common rule is "
                "≥2× derating, e.g. a 3.3 V rail wants ≥6.3 V caps; MLCC capacitance also derates with DC bias). The "
                "netlist may not carry voltage ratings — if absent, PASS with a note that ratings should be confirmed "
                "at BOM. FAIL only if a cap's rating is present and clearly too low for its rail."),
        fix="Confirm rail-cap voltage ratings give ≥2× margin over the rail (check at BOM if not in the netlist)."))
    R.append(_sem(
        "CHK_CLOCK_PINS_CLOCK_NETS", sev="INFO",
        title="Clock pins should connect to clock-named nets",
        sheet="connectors", loc="Signal outputs",
        quote="Signal outputs: CLK_OUT0–3, SAMPLE_OUTV, SAMPLE_OUT0–7, OSC_EN, WEIGHT_EN, SAMPLE_TRIG",
        prompt=("Check that clock pins connect to clock-named nets — the CLK_OUT0–3 outputs should land on nets named "
                "CLK_OUT* (and reach their SMAs). PASS if clock pins are on clock-named nets; FAIL if a clock pin is "
                "on a mis-named or non-clock net."),
        fix="Name clock nets CLK_OUT* and route the clock pins to them."))
    return R


def main() -> int:
    routing = _routing_rules()
    checklist = _checklist_rules()
    new = routing + checklist
    new_ids = {r.id for r in new}
    drop_ids = {"SEM_SHARED_LDO_INTENT"}   # duplicate of BLK_LDO_SHARED_RAIL_INTENT

    rf = load_rules()
    kept = [r for r in rf.rules if r.id not in new_ids and r.id not in drop_ids]
    dropped = [r.id for r in rf.rules if r.id in drop_ids]
    merged = RulesFile(version=rf.version, generated_at=rf.generated_at,
                       sources_seen=rf.sources_seen, rules=kept + new)
    save_rules(merged)
    print(f"+ {len(routing)} signal-routing rules (ROUTE_*)")
    print(f"+ {len(checklist)} general-checklist rules (CHK_*)")
    print(f"- dropped duplicate: {dropped}")
    print(f"total rules: {len(rf.rules)} -> {len(merged.rules)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
