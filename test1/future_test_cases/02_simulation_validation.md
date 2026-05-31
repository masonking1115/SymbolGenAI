# 02 — Simulation-driven value validation

Tests that ngspice block sims should catch, where the linter/validator/semantic
evaluator alone cannot. These plant subtle electrical errors that pass static
checks but break behavior. Each case names the responsible block in
`test1/sim/blocks.yaml` and the `BLK_*` rule that should fire.

**Block inventory** (per `blocks.yaml` 2026-05-31):
`ldo_rail | opa_bias | vddio_pdn | vddd_pdn | vdda1_pdn | vdda2_pdn |
system_sequencing | eeprom | fmc | connectors`

**Index**
- SV-01 R_sense at 5.11 k caps regulated FS (the canonical FS-ceiling failure)
- SV-02 Bias loop AC stability — swap op-amp for low-GBW model
- SV-03 PMOS Vth shift via datasheet param injection
- SV-04 LDO setpoint pins float (FPGA disconnected)
- SV-05 VDDA1 series 0 Ω promoted to 10 Ω — PDN droop at load step
- SV-06 LDO COUT total below stability minimum
- SV-07 Load switch slow-turn-on inrush violation
- SV-08 I²C SCL rise-time fails at 400 kHz bus capacitance
- SV-09 MCP4728 internal VREF still selected — V_DAC range halved
- SV-10 Opamp→PMOS gate-drive ringing on DAC step
- SV-11 Cap derating not modeled — voltage-coefficient stress test
- SV-12 BIAS compliance — Bobcat raised from 0.5 V to 1.0 V

---

### SV-01 — R_sense at 5.11 kΩ caps regulated FS below 640 µA

**Description.** Headline opa_bias failure mode. With R_sense = 5.11 kΩ and the
Bobcat BIAS pin compliance fixed at 0.5 V, the PMOS only has (3.3 V − 0.5 V) /
5.11 kΩ ≈ 548 µA of headroom, and the op-amp can't fully saturate the gate
before V_source touches V_DAC. Measured regulated FS lands around ~484 µA.

**Plant.** Identical to CV-01. Listed again here because the failure surface
is the sim's, not the static checker's. See `01_component_values.md` for the
exact diff.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_FS_CEILING`
- Severity: ERROR
- Expected: `regulated_FS_uA < 640` and `regulated_FS_uA in [450, 510]`.

**Fix.** Restore 3.65 kΩ + matching MPN.

**Pass criteria.**
- Sim numerically reports FS in the 450–510 µA band.
- Closed-loop reads sim output and proposes 3.65 kΩ (not raising 3V3, not
  dropping compliance, not removing the rule).

**Notes.** `design_intent.md` "Bias" section pins the resolution. Memory
`sim-design-extract` documents the design_extract.sense_resistance() path.

---

### SV-02 — Bias loop AC stability — swap op-amp for low-GBW model

**Description.** The PMOS gate is a capacitive load (~50–200 pF). With OPA2388
(10 MHz GBW, low-Z out) and no gate-stop resistor, the loop is borderline; a
slower op-amp tips it into oscillation under load step. Tests whether the
`opa_bias` sim has a stability sub-test.

**Plant.**
- File: `test1/sim/decks/opa_bias.py`
  (model parameter overlay, not the schematic). Set the op-amp macromodel's
  GBW to 100 kHz instead of 10 MHz.
- Alternatively: change `bias.yaml.parts.U41.lib_id` to a slower opamp MPN
  symbol IF one is added to the library; otherwise stick to the deck overlay.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_LOOP_STABILITY`
- Severity: ERROR
- Expected: phase margin < 30° on small-signal AC sweep, OR transient ringing
  on DAC code step exceeds 5 % overshoot.

**Fix.** Restore OPA2388 GBW. (No change to schematic — this is a sim-model
sanity test.)

**Pass criteria.**
- Sim emits a stability finding.
- Plan does NOT propose changing the schematic (it's a deck issue).

**Notes.** Doubles as a check that `BLK_BIAS_LOOP_STABILITY` actually runs and
isn't silently passing (a regression seen in agent-prompt-tuning churn).

---

### SV-03 — PMOS Vth shift via datasheet-param injection

**Description.** The bias loop assumes a low-Vth PMOS (PMZ1200UPE,
|Vth| ≈ 0.4–1.0 V). Inject a Vth shift in the SPICE model (e.g. shift to
−2.5 V) and watch the loop's low-end accuracy collapse — the PMOS can't enter
strong inversion at 3.3 V supply with V_source ≈ 3.3 V.

**Plant.**
- File: `test1/sim/models.py` (PMOS macromodel parameters)
- Change: `VTO` from −0.6 to −2.5 (or equivalent).

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_ACCURACY_BUDGET` (low-current regime)
- Severity: ERROR

**Fix.** Restore the correct Vth from PMZ1200UPE datasheet.

**Pass criteria.**
- Low-bias accuracy fails at codes near FS (V_DAC near 3.3 V).
- Datasheet → model link is exercised (memory
  `sim-datasheet-params-setup-only`).

---

### SV-04 — LDO setpoint pins float

**Description.** ANY-OUT pins floating = LDO outputs the 500 mV base. The
design intent is that the FPGA drives all six setpoint pins; the sim should
catch the "all pins floating" case as out-of-band low.

**Plant.**
- File: `test1/sim/blocks.yaml`
- Key: `blocks.ldo_rail.boundaries.LDO_SET_*.params.t_on`
- Change: set every setpoint stub to disconnected/floating (`stub: Float` or
  equivalent in the boundary model).

Alternatively, simpler: pass `VOUT_SET = 0.5` in the scenario params.

**Detect.**
- Tool: sim
- Block: `ldo_rail`
- Rule/ID: `BLK_LDO_SETPOINT_COVERAGE`
- Severity: ERROR (operator misuse) OR INFO (this IS the POR state)
- Expected: VOUT = 0.5 V, fails `BLK_LDO_DC_OK` for "should be ≥ 0.6 V at
  normal operation".

**Fix.** The schematic does NOT change. This test exists to verify the sim
correctly distinguishes operating modes — and the harness should grade pass
if Plan correctly identifies "this is the POR state, FPGA must drive these".

**Pass criteria.**
- Sim emits a setpoint-coverage finding.
- Plan classifies as a sequencing/firmware concern, not a parts change.

---

### SV-05 — VDDA1 series 0 Ω promoted to 10 Ω — PDN droop at load step

**Description.** Same plant as CV-09, but the failure of interest is the
dynamic droop on a load step, not the static SERIESR check.

**Plant.** See CV-09 (`R20.value: "0"` → `"10"`).

**Detect.**
- Tool: sim
- Block: `vdda1_pdn`
- Rule/ID: `BLK_PDN_VDDA1_DROOP`
- Severity: ERROR
- Expected: droop on 5 → 25 mA analog step exceeds ~5 mV / spec band.

**Fix.** Restore 0 Ω.

**Pass criteria.**
- Sim reports droop > spec.
- Findings include both SERIESR static AND DROOP dynamic — confirms the two
  paths are wired correctly.

---

### SV-06 — LDO COUT total below stability minimum

**Description.** See CV-03. Beyond the static "missing capacitor" check, the
sim must model the actual instability (phase margin / oscillation).

**Plant.** See CV-03 (`C13.value: 22uF` → `1uF`).

**Detect.**
- Tool: sim
- Block: `ldo_rail`
- Rule/ID: `BLK_LDO_DC_OK` (transient sub-test) OR new `BLK_LDO_STABILITY`
- Severity: ERROR

**Fix.** Restore 22 µF.

**Notes.** If sim only checks DC and not transient/AC, that's a coverage gap.

---

### SV-07 — Load switch slow-turn-on inrush violation

**Description.** TPS22916 has B (fast) and C (slow) variants. The design uses
the C variant for inrush limiting. Swapping to B (or simulating a bad solder
joint on the slew-rate cap) should cause an inrush violation on the +VDDIO rail.

**Plant.**
- File: `test1/sim/blocks.yaml` under `ldo_rail.boundaries.+VDDIO.params`
  (or the load switch deck params).
- Change the slew-rate parameter to the B-version timing (`tON` = 115 µs at
  5 V instead of 1400 µs).

**Detect.**
- Tool: sim
- Block: `ldo_rail` (load-switch sub-scenario)
- Rule/ID: `BLK_LOADSW_VDDIO_PATH` inrush sub-test
- Severity: WARNING

**Fix.** No schematic change. Verifies the sim reports turn-on profile.

---

### SV-08 — I²C SCL rise-time fails at 400 kHz

**Description.** Combine CV-07 (R60/R61 = 22 k) with a bus capacitance model
of ~200 pF (EEPROM + DAC + traces). Rise time τ = R·C = 22 k × 200 p = 4.4 µs,
exceeding the 1000 ns 400 kHz I²C spec.

**Plant.**
- File: `test1/netlist/eeprom.yaml` — `R60/R61.value: 2.2k` → `22k`
- Optional: increase modeled bus C in the `eeprom` block.

**Detect.**
- Tool: sim
- Block: `eeprom`
- Rule/ID: rise-time pass criterion
- Severity: ERROR

**Fix.** Restore 2.2 k.

**Pass criteria.**
- Sim emits explicit rise-time number against the spec.
- The semantic `BLK_EEPROM_I2C_PULLUPS` rule should also fire (static).

---

### SV-09 — MCP4728 internal VREF still selected — V_DAC range halved

**Description.** Memory `sim-datasheet-params-setup-only` documents this:
config-bit drift sets VREF = internal 2.048 V instead of external (= VDD =
3.3 V). V_DAC swings 0–2.048 V instead of 0–3.3 V. At V_DAC max, the PMOS
isn't fully off — leaks ~250 µA into Bobcat at POR (if Q42/Q43 are bypassed).

**Plant.**
- File: `test1/sim/decks/opa_bias.py` (or wherever the MCP4728 config bit is
  parameterized).
- Change: `MCP4728_VREF` from `EXTERNAL` to `INTERNAL_2V048`.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_DAC_VREF_EXTERNAL`
- Severity: ERROR

**Fix.** No schematic change — this is a config-bit issue. Plan should
escalate to firmware-side fix.

**Pass criteria.**
- Sim emits a VREF-mode finding.
- Plan correctly classifies as firmware/provisioning, not a parts change.

**Notes.** `design_intent.md` explicitly warns: "external VREF tied to 3.3V
is an EEPROM config BIT, not a pin." Don't accept any fix that adds a VREF
net.

---

### SV-10 — Opamp→PMOS gate-drive ringing on DAC step

**Description.** OPA2388 (10 MHz GBW) drives PMOS gate (Ciss) with no series
gate-stop. On a DAC code step, the loop can ring 3–5 cycles before settling.
Tests whether the sim characterizes step response, not just DC.

**Plant.**
- File: `test1/sim/decks/opa_bias.py` — add a DAC code-step scenario:
  V_DAC: 3.3 V → 1.0 V in 1 µs.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_LOOP_STABILITY` (transient sub-test)
- Severity: WARNING (if 1–2 cycles), ERROR (if sustained).

**Fix.** Add 100 Ω–1 kΩ gate-stop resistor between U41 output and PMOS gate.
(This is a schematic change — adds R46/R47.)

**Pass criteria.**
- Sim measures overshoot/ring count.
- Plan proposes adding a gate-stop resistor with reasonable value.

**Notes.** This test is also an "improvement-class" recommendation —
the current schematic has no gate-stop. The harness should flag it even on a
clean checkout (gold-master gap).

---

### SV-11 — Cap derating not modeled — voltage-coefficient stress

**Description.** GRM21BR61A226ME44L (22 µF X5R 10 V) derates ~45 % at 3.3 V
applied to the output. If the deck uses nameplate 22 µF, real COUT is ~12 µF.
With the design's 22 µF×2, real COUT ≈ 24 µF — at the stability cliff.

**Plant.**
- File: `test1/sim/decks/ldo_rail.py`
- Change: enable a "derate to nameplate × 0.5" scenario for X5R caps at 3.3 V
  rail.

**Detect.**
- Tool: sim
- Block: `ldo_rail`
- Rule/ID: stability margin under derated COUT
- Severity: WARNING

**Fix.** Either accept derated margin (document) or add a third bulk cap.
Plan should call out the derating explicitly, not silently swap parts.

**Pass criteria.**
- Sim reports derated COUT and margin.

---

### SV-12 — BIAS compliance raised from 0.5 V to 1.0 V

**Description.** Inverse of SV-01. If the DUT spec is updated to allow
V_BIAS = 1.0 V at the chip pin, the 3.65 kΩ sense R should still satisfy FS
((3.3 − 1.0)/3.65k ≈ 630 µA — just under spec). Catches the case where the
design parameter drift is the spec, not the part.

**Plant.**
- File: `test1/sim/blocks.yaml` under `opa_bias.scenarios` (or DUT param).
- Change: `V_BIAS_compliance: 0.5` → `1.0`.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_COMPLIANCE` (with the new compliance number)
- Severity: ERROR (FS just below spec)

**Fix.** Lower R_sense further (e.g. to 3.0 kΩ) OR adjust the spec; harness
grades Plan on which it chooses given the failure mode.

**Pass criteria.**
- Sim reports the new compliance number.
- Plan distinguishes between "part change" and "spec change" cleanly.

**Notes.** Used to test the directional fix logic captured in
`design_intent.md`: "Do NOT raise R40/R41 back toward 5.11k — lower R_sense
satisfies the ceiling."
