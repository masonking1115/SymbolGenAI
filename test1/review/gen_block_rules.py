#!/usr/bin/env python3
"""One-shot generator for the `block` rule family — a STRICT, per-block rule set.

Each functional block in the simulation catalog (blocks.yaml) gets its own group
of rules that pin down the block's boundaries against the design requirements, the
Bobcat board-design PPT, and the part datasheets. The rules are deliberately
strict: they assert the specific numbers (full-scale current, dropout, setpoint
coverage, decoupling, default-off interlocks, supply ranges) rather than vague
"looks right" checks.

Every rule carries `applies_to.block` = the block id, so the GUI groups them
under a Blocks dropdown (block → its rules) and the harness reports per block.

Authoring as code (not hand-edited YAML) guarantees schema-validity + correct
escaping, and the merge is idempotent on the BLK_* ids (re-run to update).

Grounding (extracted from the datasheets in Parts Library/ + the PPT + reqs):
  • Bobcat PPT: BIAS0/1 = 0–640 µA, 1 µA step, nominally 320 µA @ 0.5 V; decoupling
    on VDDD/VDDIO/VDDA1/VDDA2; series 0Ω on VDDA1/VDDA2; rails 0.6–1.0 V via ANY-OUT.
  • OPA2388: zero-drift RRIO, Vos = ±0.25 µV, GBW = 10 MHz, single supply 2.5–5.5 V.
  • TPS7A8401A: 3 A, 0.75% accuracy, 180 mV max dropout @ 3 A (with BIAS), Vin 1.1–6.5 V
    (with BIAS), ANY-OUT 0.5–2.075 V @ 25 mV, 4.4 µVrms noise, open-drain PG.
  • MCP4728: 12-bit quad DAC, external VREF=VDD for rail-to-rail, EEPROM default,
    ±0.2 LSB DNL, I2C.
  • TPS22916: 1–5.5 V, 2 A load switch, RON 60 mΩ@5V / 100 mΩ@1.8V, active-high EN, QOD.
  • 24AA08: 8-Kbit I2C EEPROM, Vcc 1.7–5.5 V.
  • R40/R41: 5.11k→3.65k 0.1% thin-film sense R (see the bias headroom analysis).
"""

from __future__ import annotations

from .rule_eval import load_rules, save_rules
from .rule_schema import (
    AppliesTo, RulesFile, SemanticRule, SourceCitation, StructuralRule, SimReview,
)

REQ = "design_requirements.md"
PPT = "[External] Bobcat Board Design.pdf"


def _sim(rid, *, block, sim_block, sim_type, sev, title, sheet, criterion,
         source, quote, fix, source_doc=REQ, refdes=None, net=None, datasheet=None):
    cites = [SourceCitation(doc=source_doc, loc=source, quote=quote)]
    if datasheet:
        cites.append(SourceCitation(doc=datasheet[0], loc=datasheet[1], quote=datasheet[2]))
    return StructuralRule(
        id=rid, family="block", severity=sev, title=title,
        applies_to=AppliesTo(block=block, sim_block=sim_block, sim_type=sim_type,
                             sheet=sheet, refdes=refdes, net=net),
        source=cites, fix_hint=fix, origin="generated",
        predicate=SimReview(sim_block=sim_block, sim_type=sim_type, criterion=criterion),
    )


def _sem(rid, *, block, sev, title, sheet, prompt, source, quote, fix,
         source_doc=REQ, refdes=None, net=None, rail=None, datasheet=None):
    cites = [SourceCitation(doc=source_doc, loc=source, quote=quote)]
    if datasheet:
        cites.append(SourceCitation(doc=datasheet[0], loc=datasheet[1], quote=datasheet[2]))
    return SemanticRule(
        id=rid, family="block", severity=sev, title=title,
        applies_to=AppliesTo(block=block, sheet=sheet, refdes=refdes, net=net, rail=rail),
        source=cites, fix_hint=fix, origin="generated", prompt=prompt,
    )


def build_block_rules():
    R = []

    # ========================================================================
    # BLOCK: opa_bias — the V-to-I precision bias loop (the headline block)
    # ========================================================================
    B = "opa_bias"
    R += [
        _sim("BLK_BIAS_FS_CEILING", block=B, sim_block="opa_bias", sim_type="dc_sweep",
             sev="ERROR", sheet="bias",
             title="Bias reaches the full 0–640 µA spec in regulation (op-amp/headroom ceiling)",
             source="Specs / Bias outputs",
             quote="BIAS0, BIAS1 — independent programmable current sources, 0–640 µA, ~1 µA step",
             datasheet=(PPT, "Bias", "Programmable range of 0-640uA with a step size of 1uA"),
             criterion=(
                 "The regulated full-scale current (i_max_regulated_A) MUST reach at least "
                 "640 µA. The OPA2388 is single-supply and the sense-R drop I·R must fit "
                 "within 3.3 V minus the 0.5 V DUT compliance, so an over-large R_sense caps "
                 "the loop below 640 µA. PASS only if i_max_regulated_A >= 640 µA; FAIL with "
                 "the observed ceiling otherwise."),
             fix="Lower R_sense (R40/R41) so 640 µA fits the 3V3-0.5V headroom (≈3.65k); do not raise it."),
        _sim("BLK_BIAS_COMPLIANCE_0V5", block=B, sim_block="opa_bias", sim_type="dc_compliance",
             sev="ERROR", sheet="bias",
             title="Bias delivers 320 µA nominal with BIASx held at the 0.5 V compliance point",
             source="Specs / Bias outputs", quote="nominal 320 µA @ 0.5 V",
             datasheet=(PPT, "Bias", "nominally 320uA at 0.5V"),
             criterion=(
                 "With BIAS0 pinned at the 0.5 V DUT compliance point, the loop must source "
                 "the ideal current within 1% over the regulated range AND hit ~320 µA at the "
                 "nominal code (within ~1%), with the PMOS drain staying >= 0.5 V. PASS if "
                 "i_at_nominal_uA ≈ 320 (±1%) and pmos_drain_min_V >= 0.5; FAIL otherwise."),
             fix="Ensure R_sense + pass-FET/isolator headroom let 320 µA flow with the output at 0.5 V."),
        _sem("BLK_BIAS_ACCURACY_BUDGET", block=B, sev="WARNING", sheet="bias", refdes="R40",
             title="Bias accuracy budget closes: 0.1% sense-R + OPA2388 0.25 µV Vos + 12-bit DAC",
             source="Specs / Bias outputs", quote="0–640 µA, ~1 µA step (nominal 320 µA @ 0.5 V)",
             datasheet=("opa2388.pdf", "Offset", "Ultra-low offset voltage: ±0.25 µV; zero drift ±0.005 µV/°C"),
             prompt=(
                 "Judge whether the bias-current accuracy budget closes against the spec (0–640 µA, "
                 "~1 µA step ⇒ ~12-bit, ~0.16 µA LSB, ≤1% V-to-I accuracy). I = (3.3−V_DAC)/R_sense. "
                 "Stack the dominant error terms and report each as a % of full scale:\n"
                 " 1. R_sense tolerance — R40/R41 are 0.1% thin-film → ±0.1% current error (dominant).\n"
                 " 2. Op-amp offset — OPA2388 Vos ≈ ±0.25 µV (zero-drift). Error = Vos/(3.3−V_DAC); even "
                 "at 5% FS the sense voltage is ~0.1 V so this is < 0.001% — negligible.\n"
                 " 3. DAC INL/DNL — MCP4728 12-bit, ±0.2 LSB DNL typ → small.\n"
                 "PASS if the RSS stack stays within ~1% across the usable range (it should be "
                 "R-tolerance-dominated at ~0.1%). FAIL only if a term clearly blows the budget."),
             fix="If the budget fails, tighten R40/R41 tolerance; offset/DAC terms are already negligible."),
        _sim("BLK_BIAS_LOOP_STABILITY", block=B, sim_block="opa_bias", sim_type="ac_stability",
             sev="WARNING", sheet="bias",
             title="Bias feedback loop is stable driving the PMOS gate capacitance",
             source="Parts to implement / Bias circuit",
             quote="Op-amp output drives the gate of a small-signal PMOS (PMZ1200UPEYL).",
             datasheet=("opa2388.pdf", "Bandwidth", "Gain bandwidth: 10 MHz"),
             criterion="Closed-loop peaking <= 3 dB (phase margin >= ~45°). PASS if peaking_dB <= 3; FAIL if it peaks higher.",
             fix="If peaking > 3 dB, add a small series gate R or feedback Cff for phase margin."),
        _sim("BLK_BIAS_POR_FAILSAFE", block=B, sim_block="opa_bias", sim_type="por_failsafe",
             sev="ERROR", sheet="bias",
             title="No bias current reaches Bobcat at POR (Q42/Q43 isolation holds)",
             source="Assembly / provisioning notes / MCP4728 EEPROM (W8)",
             quote="the Q42/Q43 isolation NMOSes (populated default, default-OFF) … cannot reach Bobcat",
             criterion="Bias current into the DUT at POR (BIAS_ISO low) must be <= 1 µA. PASS if bias_current_at_por_A <= 1e-6; FAIL otherwise.",
             fix="Verify the isolation NMOS is populated and the BIAS_ISO gate pull-down (R44/R45) is present."),
        _sem("BLK_BIAS_DAC_VREF_EXTERNAL", block=B, sev="WARNING", sheet="bias", refdes="U40",
             title="MCP4728 uses external VREF = VDD (rail-to-rail), not the 2.048 V internal ref",
             source="Parts to implement / Bias circuit",
             quote="MCP4728 quad 12-bit I²C voltage DAC with external V_REF tied to 3.3 V (not internal 2.048 V ref)",
             datasheet=("22187E.pdf", "VREF", "Internal or External Voltage Reference Selection; External VREF (VDD)"),
             prompt=("Confirm the bias design intends the MCP4728 to run with EXTERNAL VREF = VDD (3.3 V) so the DAC "
                     "output spans 0–3.3 V rail-to-rail. The internal 2.048 V ref would cap V_DAC at 2.048 V, "
                     "shrinking the controllable current range. This is a configuration/provisioning intent — PASS "
                     "if the netlist/notes reflect external-VREF (VDD) operation; the MCP4728 has no dedicated VREF "
                     "pin (it is register-selected), so judge from the design notes, not a pin."),
             fix="Document external-VREF=VDD in the MCP4728 provisioning; it is register-selected, not a pin."),
        _sem("BLK_BIAS_ISO_PULLDOWN", block=B, sev="ERROR", sheet="bias", net="BIAS_ISO0",
             title="BIAS_ISO0/1 have 10 kΩ gate pull-downs (default-OFF at POR)",
             source="Parts to implement / Bias circuit",
             quote="gated by BIAS_ISO0/1 from the FPGA with 10 kΩ pull-downs (R44/R45) at the gates",
             prompt=("Verify each isolation-FET gate net (BIAS_ISO0, BIAS_ISO1) has a ~10 kΩ pull-down to GND so the "
                     "2N7002 is OFF at POR until the FPGA drives it HIGH. Examine the full net membership — PASS if a "
                     "10 kΩ resistor to GND is present on each; FAIL if either floats or lacks the pull-down."),
             fix="Add a 10 kΩ pull-down from BIAS_ISO0/1 to GND (R44/R45)."),
    ]

    # ========================================================================
    # BLOCK: ldo_rail — TPS7A8401A ANY-OUT LDO (+ load switch on the VDDIO path)
    # ========================================================================
    B = "ldo_rail"
    R += [
        _sim("BLK_LDO_SETPOINT_COVERAGE", block=B, sim_block="ldo_rail", sim_type="setpoint_coverage",
             sev="ERROR", sheet="power", refdes="U10",
             title="LDO ANY-OUT regulates every 0.6–1.0 V Bobcat rail with dropout headroom",
             source="Parts to implement / TPS7A8401A",
             quote="ANY-OUT pin-programmable output 0.5–2.075 V at 25 mV resolution (covers Bobcat 0.6–1.0 V rails)",
             datasheet=("tps7a84a.pdf", "ANY-OUT", "ANY-OUT operation: 0.5 V to 2.075 V, 25-mV resolution"),
             criterion=("Every selectable Bobcat rail in 0.6–1.0 V must regulate within ~50 mV with dropout "
                        "headroom (Vin=3.3 V). PASS if all tested setpoints regulate; FAIL if any in-range setpoint fails."),
             fix="Check ANY-OUT setpoint-pin strapping / VOUT_SET mapping for the failing rail."),
        _sem("BLK_LDO_DROPOUT_MARGIN", block=B, sev="WARNING", sheet="power", refdes="U10",
             title="LDO dropout (180 mV max @ 3 A) leaves ample headroom from 3.3 V to ≤1.0 V",
             source="Parts to implement / TPS7A8401A", quote="180 mV max dropout … 3 A LDO",
             datasheet=("tps7a84a.pdf", "Dropout", "Low dropout: 180 mV (maximum) at 3 A with BIAS"),
             prompt=("Confirm dropout headroom by first principles: Vin=3.3 V, Vout ≤ 1.0 V, datasheet dropout = "
                     "180 mV max @ 3 A. Headroom = Vin−Vout−dropout ≈ 3.3−1.0−0.18 = 2.1 V, comfortably positive. "
                     "PASS unless the netlist shows Vin is not the 3.3 V rail or Vout is set above ~3.1 V."),
             fix="Only flag if Vin is mis-rooted or Vout set too high; headroom is large by design."),
        _sim("BLK_LDO_LINE_REG", block=B, sim_block="ldo_rail", sim_type="line_regulation",
             sev="WARNING", sheet="power", refdes="U10",
             title="LDO holds 0.75% accuracy across the FMC +3V3 tolerance (3.0–3.6 V)",
             source="Specs", quote="Power in (from FMC): 3P3V",
             datasheet=("tps7a84a.pdf", "Accuracy", "0.75% (maximum) accuracy over line, load, and temperature"),
             criterion=("As +3V3 sweeps 3.0–3.6 V the output must hold regulation: Vout span small (≤ ~10 mV) and "
                        "mean within ~50 mV of setpoint (datasheet line accuracy 0.75%). FAIL if Vout tracks Vin."),
             fix="If Vout tracks Vin the LDO is in dropout or Vin is mis-rooted — re-check."),
        _sim("BLK_LDO_DC_OK", block=B, sim_block="ldo_rail", sim_type="dc_op_point",
             sev="ERROR", sheet="power", refdes="U10",
             title="All LDO/switch rails settle at the expected DC operating point (not in dropout)",
             source="Topology / block diagram",
             quote="The LDO generates 0.6–1.0V for Bobcat VDDD/VDDA1/VDDA2",
             criterion=("Every rail (+3V3, LDO_OUT, VADJ, +VDDIO) must settle within tolerance "
                        "(±50 mV core, ±100 mV +VDDIO for Rdson drop) and the LDO must not be in dropout. "
                        "PASS if all rails are on-target; FAIL with the offending rail."),
             fix="If a rail is off, check the setpoint, the source rail, or load-switch Rdson."),
        _sem("BLK_LDO_VIN_RANGE", block=B, sev="WARNING", sheet="power", refdes="U10",
             title="LDO Vin (3.3 V from FMC) is within the device input range (1.1–6.5 V with BIAS)",
             source="Parts to implement / TPS7A8401A", quote="Vin 1.1–6.5 V (with BIAS) … 3P3V from FMC drives Vin and BIAS",
             datasheet=("tps7a84a.pdf", "Vin", "Input voltage range with BIAS: 1.1 V to 6.5 V"),
             prompt=("Confirm the LDO's IN (and BIAS) pins are driven from the FMC +3V3 rail, which sits inside the "
                     "1.1–6.5 V input range. PASS if IN/BIAS connect to +3V3; FAIL if rooted to a rail outside the range."),
             fix="Route LDO IN + BIAS to +3V3 (FMC)."),
        _sem("BLK_LDO_EN_PULLDOWN", block=B, sev="ERROR", sheet="power", net="LDO_EN",
             title="LDO EN has a 10 kΩ pull-down (off at POR until FPGA enables)",
             source="Parts to implement / TPS7A8401A", quote="EN driven by FPGA with 10kΩ pull-down",
             prompt=("Verify the LDO EN net has a ~10 kΩ pull-down to GND so the LDO is OFF at power-on until the FPGA "
                     "drives EN high. Examine the full EN net — PASS if a 10 kΩ pull-down is present; FAIL if EN floats/tied high."),
             fix="Add a 10 kΩ pull-down from LDO_EN to GND."),
        _sem("BLK_LDO_PG_PULLUP", block=B, sev="WARNING", sheet="power", refdes="U10",
             title="LDO PG (open-drain) has a pull-up before returning to the FPGA",
             source="Parts to implement / TPS7A8401A", quote="Open-drain PG output back to FPGA.",
             datasheet=("tps7a84a.pdf", "PG", "Power-good is an open-drain output"),
             prompt=("The TPS7A8401A PG output is open-drain and needs a pull-up to read high. Examine the full PG-net "
                     "membership — a pull-up counts if ANY resistor on that node reaches a supply (incl. through a series "
                     "R). PASS if such a pull-up exists; FAIL only if none does."),
             fix="Add a pull-up (e.g. 10 kΩ to +3V3) on the LDO PG net."),
        _sem("BLK_LDO_SHARED_RAIL_INTENT", block=B, sev="INFO", sheet="power", refdes="U10",
             title="Single LDO feeds VDDD/VDDA1/VDDA2 via 3× jumpers (rails track together — intended)",
             source="Notes / open questions",
             quote="one TPS7A8401A feeding VDDD, VDDA1, VDDA2 through 3×1×2 jumpers (all three tap the same LDO output bus)",
             prompt=("Confirm the design intentionally uses ONE LDO output bus fanned to VDDD/VDDA1/VDDA2 via three 1×2 "
                     "jumpers (so the three rails track together). PASS if that is the topology; only FAIL if the rails are "
                     "wired to imply independent setpoints from one LDO (which is not achievable)."),
             fix="Keep one LDO → 3 jumpers off the same bus; replicate the LDO block to get independent rails."),
    ]

    # ========================================================================
    # BLOCK: loadsw — TPS22916 load switch (VADJ → VDDIO). Logical block on the
    # power sheet; structural/semantic only (no dedicated sim deck).
    # ========================================================================
    B = "loadsw"
    R += [
        _sem("BLK_LOADSW_DEFAULT_OFF", block=B, sev="ERROR", sheet="power", net="LSW_EN",
             title="Load switch is OFF by default (LSW_EN 10 kΩ pull-down) — no VDDIO before FPGA enables",
             source="Parts to implement / Load switch", quote="EN driven by FPGA with 10kΩ pull-down",
             datasheet=("TPS22916CNYFPR.pdf", "EN", "Active-low/high enable; quick output discharge (QOD)"),
             prompt=("Verify the VADJ→VDDIO load switch EN (LSW_EN) has a ~10 kΩ pull-down to GND so VDDIO is not "
                     "energized until the FPGA drives EN. Examine the full LSW_EN net — PASS if a 10 kΩ pull-down to GND "
                     "is present; FAIL if EN floats or is tied to a supply."),
             fix="Add a 10 kΩ pull-down from LSW_EN to GND."),
        _sem("BLK_LOADSW_VIN_RANGE", block=B, sev="WARNING", sheet="power",
             title="Load switch passes VADJ (1.2–3.3 V) within the device input range (1–5.5 V)",
             source="Specs", quote="VADJ 1.2–3.3V (to Bobcat VDDIO via load switch)",
             datasheet=("TPS22916CNYFPR.pdf", "Vin", "Input operating voltage range (VIN): 1 V–5.5 V"),
             prompt=("Confirm the load switch input is VADJ (1.2–3.3 V), inside the device's 1–5.5 V VIN range, and its "
                     "output feeds Bobcat VDDIO through a 1×2 jumper. PASS if so; FAIL if the input rail is outside range "
                     "or the output is not VDDIO-via-jumper."),
             fix="Route VADJ → load switch VIN → VDDIO via 1×2 jumper."),
        _sem("BLK_LOADSW_VDDIO_PATH", block=B, sev="WARNING", sheet="power", rail="+VDDIO",
             title="Bobcat VDDIO comes from VADJ through the load switch (not directly)",
             source="Specs", quote="VADJ 1.2–3.3V (to Bobcat VDDIO via load switch)",
             prompt=("Verify +VDDIO is fed from VADJ via the load switch (gated by LSW_EN), not directly from VADJ or "
                     "another rail. PASS if the path is VADJ→switch→VDDIO; FAIL otherwise."),
             fix="Insert the load switch between VADJ and +VDDIO."),
    ]

    # ========================================================================
    # BLOCKS: PDN — per-rail decoupling networks (VDDIO/VDDD/VDDA1/VDDA2).
    # Bobcat PPT requires decoupling on all four; analog rails get series 0Ω.
    # ========================================================================
    pdn = [
        ("vddio_pdn", "+VDDIO",  "transient_load_step", "ERROR",  None,
         "Droop <= 30 mV for a 50→250 mA step (100 ns edge).",
         "VDDIO digital-rail decoupling holds under a Bobcat load step"),
        ("vddd_pdn",  "+VDDD",   "transient_load_step", "WARNING", None,
         "Droop <= 50 mV for a 50→250 mA step (100 ns edge).",
         "VDDD decoupling (C20 0.1µF + C21 1µF) holds under a load step"),
        ("vdda1_pdn", "internal_VDDA1_path", "transient_load_step", "WARNING", "R20",
         "Droop <= 50 mV for a 5→25 mA analog step (100 ns edge).",
         "VDDA1 analog decoupling holds; series 0Ω (R20) present"),
        ("vdda2_pdn", "internal_VDDA2_path", "transient_load_step", "WARNING", "R21",
         "Droop <= 50 mV for a 5→25 mA analog step (100 ns edge).",
         "VDDA2 analog decoupling holds; series 0Ω (R21) present"),
    ]
    for blk, net, st, sev, series_r, crit, title in pdn:
        R.append(_sim(f"BLK_PDN_{blk.split('_')[0].upper()}_DROOP",
                      block=blk, sim_block=blk, sim_type=st, sev=sev, sheet="bobcat", net=net,
                      title=title, source="Parts to implement / Bobcat",
                      quote="Decoupling caps on VDDD, VDDIO, VDDA1, VDDA2.",
                      datasheet=(PPT, "Bobcat", "Decoupling capacitors on VDDD, VDDIO, VDDA1, VDDA2"),
                      criterion=(f"The {net} decoupling bank must supply the transient charge without excessive "
                                 f"droop. PASS if {crit} FAIL if droop exceeds the budget (a missing/short decap)."),
                      fix=f"Add/upgrade {net} decoupling near the pin."))
    # Analog-rail series-0Ω presence (PPT: series 0Ω on VDDA1, VDDA2).
    for blk, r_ref, rail in (("vdda1_pdn", "R20", "VDDA1"), ("vdda2_pdn", "R21", "VDDA2")):
        R.append(_sem(f"BLK_PDN_{rail}_SERIES0R", block=blk, sev="WARNING", sheet="bobcat", refdes=r_ref,
                      title=f"{rail} has the series 0Ω isolation resistor ({r_ref})",
                      source="Parts to implement / Bobcat", quote="Series 0Ω on VDDA1, VDDA2.",
                      datasheet=(PPT, "Bobcat", "Series 0Ω on VDDA1, VDDA2"),
                      prompt=(f"Verify the {rail} analog rail has a series 0Ω resistor ({r_ref}) between the LDO bus and "
                              f"the Bobcat {rail} pin (analog/digital isolation). PASS if present on the {rail} path; FAIL if absent."),
                      fix=f"Insert a series 0Ω ({r_ref}) on the {rail} rail between the LDO bus and the pin."))

    # ========================================================================
    # BLOCK: eeprom — 24AA08 I2C EEPROM (not simulatable; structural rules).
    # ========================================================================
    B = "eeprom"
    R += [
        _sem("BLK_EEPROM_SUPPLY", block=B, sev="WARNING", sheet="eeprom",
             title="EEPROM Vcc is +3V3, within the 24AA08 1.7–5.5 V range, with local decoupling",
             source="Parts to implement / EEPROM", quote="8-Kbit, I²C, 3.3V supply (for FMC IPMI / board ID).",
             datasheet=("20001710L.pdf", "Vcc", "VCC Range 1.7V-5.5V"),
             prompt=("Confirm the 24AA08 EEPROM Vcc pin is on +3V3 (inside 1.7–5.5 V) and has a local decoupling cap "
                     "(~0.1µF). PASS if both hold; FAIL if Vcc is mis-rooted or no decap is present on the Vcc net."),
             fix="Route EEPROM Vcc to +3V3 and add a 0.1µF decoupling cap."),
        _sem("BLK_EEPROM_I2C_PULLUPS", block=B, sev="WARNING", sheet="eeprom", net="SCL",
             title="I2C SCL/SDA have pull-ups (shared EEPROM + bias DAC bus)",
             source="Assembly / provisioning notes / I²C pull-ups (W4)",
             quote="R60 and R61 (2.2 kΩ to +3V3 on EEPROM sheet) provide local SCL/SDA pull-ups",
             prompt=("Verify the I2C SCL and SDA nets each have a pull-up to +3V3 (e.g. 2.2 kΩ, R60/R61). The bus is "
                     "shared by the EEPROM and the MCP4728 bias DAC. Examine each net's membership — PASS if a pull-up to "
                     "+3V3 is present on both SCL and SDA; FAIL if either lacks one."),
             fix="Add 2.2 kΩ pull-ups to +3V3 on SCL and SDA (R60/R61)."),
    ]

    return R


def main() -> int:
    new_rules = build_block_rules()
    new_ids = {r.id for r in new_rules}
    if len(new_ids) != len(new_rules):
        # guard against accidental duplicate ids
        from collections import Counter
        dupes = [k for k, v in Counter(r.id for r in new_rules).items() if v > 1]
        raise SystemExit(f"duplicate BLK ids: {dupes}")

    rf = load_rules()
    kept = [r for r in rf.rules if r.id not in new_ids]
    merged = RulesFile(version=rf.version, generated_at=rf.generated_at,
                       sources_seen=rf.sources_seen, rules=kept + new_rules)
    save_rules(merged)

    # Report grouped by block.
    from collections import defaultdict
    by_block = defaultdict(list)
    for r in new_rules:
        by_block[r.applies_to.block or "?"].append(r)
    print(f"merged {len(new_rules)} block-family rules across {len(by_block)} blocks "
          f"into rules.yaml (total now {len(merged.rules)})")
    for blk in sorted(by_block):
        print(f"  {blk}:")
        for r in by_block[blk]:
            mode = "semantic" if isinstance(r, SemanticRule) else r.predicate.kind
            print(f"      {r.id:<28} [{r.severity:<7}] {mode}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
