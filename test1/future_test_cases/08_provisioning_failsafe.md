# 08 — Provisioning and POR / fail-safe tests

Tests for behaviors that only manifest at power-up, during hot-plug, or before
firmware has finished provisioning the I²C devices. These cross multiple
layers: schematic (POR pull-down presence), semantic (`SEM_*`), simulation
(`system_sequencing` block), and firmware assumptions.

These tests are often the highest-stakes — they protect a $X custom test chip
from a virgin MCP4728 dumping full-scale bias at first power-on. They're also
the ones agents historically get wrong (an agent will helpfully "improve"
something and accidentally remove the failsafe).

**Index**
- PF-01 Q42 changed to DNP (NMOS not populated) — bias path open
- PF-02 R42/R43 populated — POR fail-safe defeated
- PF-03 BIAS_ISO pull-down removed
- PF-04 LDO EN pull-down missing
- PF-05 LSW EN pull-down missing
- PF-06 MCP4728 EEPROM config not enforced (firmware-side assertion)
- PF-07 2N7002 V_GS at low VADJ — the F-3 audit finding
- PF-08 Hot-plug — board powered without FMC seated
- PF-09 VADJ ramp slower than 3.3 V — sequencing
- PF-10 SCL/SDA driven before slave VDD ramp — I²C latch-up risk

---

### PF-01 — Q42 changed to DNP (NMOS not populated)

**Description.** Set Q42 to DNP while leaving R42 (the parallel 0 Ω jumper)
also DNP. The bias path is fully open — bias current can never reach Bobcat,
even when the FPGA asserts BIAS_ISO HIGH.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Key: `parts.Q42.dnp` → add `dnp: true`. Leave R42 dnp: true.

**Detect.**
- Tool: semantic
- Rule/ID: `SEM_BIAS_PATH_PRESENT` (planned) — exactly one of {Q42, R42}
  must be POPULATED for the bias path to exist.
- Severity: ERROR

**Fix.** Either un-DNP Q42 (preferred — keeps POR failsafe) or un-DNP R42
(loses failsafe; only acceptable for benchtop debug).

**Pass criteria.**
- The rule fires.
- Plan picks the preferred fix (Q42), not R42.

---

### PF-02 — R42/R43 populated — POR fail-safe defeated

**Description.** Inverse of PF-01: leave Q42 populated but ALSO populate R42
(remove its `dnp: true`). The 0 Ω jumper shorts D-S, so the NMOS is always
"on" — virgin MCP4728 → V_DAC=0 → PMOS full-scale on → uncontrolled bias
into Bobcat at POR.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Key: `parts.R42.dnp`
- Before: `true`
- After:  `false` (or remove the line).

**Detect.**
- Tool: semantic
- Rule/ID: `SEM_BIAS_OVERRIDE_DNP` and `SEM_BIAS_DEFAULT_OFF`
- Severity: ERROR

Also:
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_POR_FAILSAFE` (virgin DAC scenario)
- Severity: ERROR
- Expected: simulated bias at POR ~900 µA (uncontrolled).

**Fix.** Restore R42 DNP.

**Pass criteria.**
- Both rules fire.
- Plan does NOT propose "remove R42" — the part should stay on the BOM with
  DNP so it can be hand-populated for benchtop use.

**Notes.** `design_requirements.md` "Assembly / provisioning notes" pins
this. The fix must keep the override available, not delete the part.

---

### PF-03 — BIAS_ISO pull-down removed

**Description.** R44 or R45 deleted from `bias.yaml`. BIAS_ISO0/1 floats at
POR; NMOS gate is undefined → behavior depends on FPGA pin reset state.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Action: delete the `R44:` part block AND its membership in `GND` and
  `BIAS_ISO0` nets.

**Detect.**
- Tool: semantic
- Rule/ID: `PULLDOWN_BIAS_ISO0` and `BLK_BIAS_ISO_PULLDOWN`
- Severity: ERROR

Also:
- Tool: sim
- Block: `system_sequencing` (POR I/O state)
- Severity: ERROR if floating gate is modeled

**Fix.** Restore R44.

---

### PF-04 — LDO EN pull-down missing

**Description.** R10 (10 k pull-down on LDO_EN) deleted. LDO_EN floats at POR
until FPGA drives.

**Plant.**
- File: `test1/netlist/power.yaml`
- Action: delete `R10` part block + memberships.

**Detect.**
- Tool: semantic
- Rule/ID: `PULLDOWN_LDO_EN` and `BLK_LDO_EN_PULLDOWN`
- Severity: ERROR

**Fix.** Restore R10.

**Pass criteria.**
- Both rules fire.
- Plan proposes restoring with the canonical MPN.

---

### PF-05 — LSW EN pull-down missing

**Description.** Mirror of PF-04 for the load switch. TPS22916 has an
internal 750 kΩ smart pull-down (effective only when EN is low), but the
external 10 k is the spec's defense-in-depth.

**Plant.**
- File: `test1/netlist/power.yaml`
- Action: delete `R11`.

**Detect.**
- Tool: semantic
- Rule/ID: `PULLDOWN_LSW_EN` and `BLK_LOADSW_DEFAULT_OFF`
- Severity: ERROR

**Fix.** Restore R11.

**Anti-test.** Halving R11 to 5 k should NOT fire (still within "10 k ±50 %"
band). Halving to 100 Ω should fire (too low — wastes FPGA drive current).

---

### PF-06 — MCP4728 EEPROM config not enforced

**Description.** The schematic is fine, but the FPGA bring-up firmware does
not enforce the MCP4728 EEPROM config (VREF=VDD, code=0xFFF) before
asserting BIAS_ISO. This is a system-level test — not a schematic plant.

**Plant.** N/A in schematic. The harness should run the closed-loop and
verify it flags the firmware contract as a documented dependency
(`design_requirements.md` Assembly/provisioning W8).

**Detect.**
- Tool: semantic
- Rule/ID: `SEM_MCP4728_POR_CODE` and `BLK_BIAS_DAC_VREF_EXTERNAL`
- Severity: WARNING
- Expected: the rules cite the firmware contract, NOT a schematic-side fix.

**Fix.** No schematic change. Plan must surface the firmware dependency.

**Pass criteria.**
- Rules fire on the clean checkout (as informational reminders).
- Plan does NOT propose any schematic edit — proposes documenting / verifying
  firmware-side enforcement.

**Notes.** This test guards against agents that "fix" a non-bug by changing
the schematic.

---

### PF-07 — 2N7002 V_GS at low VADJ (audit finding F-3)

**Description.** BIAS_ISO is driven by FPGA from the FMC LA bank, whose
VCCO = VADJ. At VADJ < ~2.5 V, V_GS < 2N7002 Vth_max (2.5 V) and the
isolator can't reliably turn on. Bias current cannot reach Bobcat when
VDDIO < ~2.5 V, even with R42/R43 still DNP.

**Plant.** No schematic plant — exercise the existing design.
- Sim scenario: set VADJ = 1.2 V (low end of spec).

**Detect.**
- Tool: sim
- Block: `opa_bias` (cross-domain with `vddio_pdn` for the gate-drive level)
- Rule/ID: `BLK_BIAS_ISO_PULLDOWN` should ALSO check V_GS adequacy at
  the operating VADJ.
- Severity: ERROR if "bias active required at VDDIO < 2.5 V"; otherwise
  WARNING / acceptable-constraint.

**Fix.** Two reasonable fixes:
- Document the constraint in `design_requirements.md` (cheapest).
- Replace 2N7002 with a low-Vth NMOS (e.g. Si2302, IRLML6244) and update
  bias.yaml + lib. (Harder, schematic change.)

**Pass criteria.**
- Sim reports V_GS < Vth at VADJ = 1.2 V.
- Plan proposes ONE of the two fixes, not both (the choice depends on the
  test plan).

**Notes.** Audit finding F-3 is the canonical motivation. This test exists
to make sure the harness can connect "low VADJ" → "bias path broken" without
human intervention.

---

### PF-08 — Hot-plug: board powered without FMC seated

**Description.** Some test setups apply +3V3 to the mezzanine through a
separate clip lead before seating into the carrier. With no carrier, VADJ
floats and FMC signals are undriven — but +3V3 reaches the bias block.

**Plant.** Sim scenario: VADJ = 0 V; +3V3 = 3.3 V; all FMC signals high-Z.

**Detect.**
- Tool: sim
- Block: `system_sequencing`
- Rule/ID: `BLK_LOADSW_DEFAULT_OFF` (VDDIO must stay 0)
- Severity: WARNING (acceptable if intentional dev workflow)

Also:
- Tool: semantic
- Rule/ID: `SEM_BIAS_DEFAULT_OFF` (still must hold)
- Severity: ERROR if violated

**Fix.** No change. This test verifies the design degrades safely under
partial power.

**Pass criteria.**
- Sim shows VDDIO = 0, BIAS0/1 = 0, no current into Bobcat.

---

### PF-09 — VADJ ramp slower than 3.3 V

**Description.** Carrier sequencing: +3V3 ramps in < 1 ms but VADJ takes 10
ms. Bobcat sees VDDD = 0.8 V before VDDIO = 1.8 V — verify no latch-up
between IO and core supplies.

**Plant.** Sim scenario in `system_sequencing`:
- +3V3: 0 → 3.3 V in 1 ms
- VADJ: 0 → 1.8 V in 10 ms
- LDO_EN asserts at t = 5 ms (after both rails are nominally up).

**Detect.**
- Tool: sim
- Block: `system_sequencing`
- Rule/ID: rail-ramp ordering pass criterion
- Severity: WARNING

**Fix.** May require ordering at LDO_EN assertion time. Not a schematic
change.

**Pass criteria.**
- Sim reports the ramp order. Plan recommends a firmware sequencing rule.

---

### PF-10 — SCL/SDA driven before slave VDD ramp

**Description.** Genesys 2 carrier may start driving SCL/SDA before VADJ
ramps fully. With the EEPROM and DAC at VDD = 0, driven inputs can latch
parasitic substrate diodes. Bus pull-ups (R60/R61) help; verify.

**Plant.** Sim scenario:
- SCL/SDA: driven at t = 0 ms with VDD = 0.
- +3V3: 0 → 3.3 V at t = 1 ms.

**Detect.**
- Tool: sim
- Block: `eeprom`
- Rule/ID: input-voltage-during-power-down pass criterion
- Severity: WARNING

**Fix.** Verify spec; possibly add series Rs on SCL/SDA. Not necessarily a
schematic change.

**Pass criteria.**
- Sim reports the off-state input voltage on EEPROM/DAC inputs.

---

## Cross-cutting note

PF tests are the only category where "the schematic is fine" can be the
correct answer. The harness must NOT grade a closed-loop fail-state if the
fix is "document the constraint" or "this is a firmware contract." Plan
should escalate to firmware/sequencing/operator-documentation when a
schematic edit would be the wrong remedy.

This is the place where agents are most likely to over-correct. Build the
test grading around that failure mode.
