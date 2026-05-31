# 01 — Component value errors

Wrong R / C / L values planted into the netlist YAMLs. These tests exercise the
schematic-builder, the strict validator, the semantic evaluator
(`VAL_*` rules), and — for values that change behavior more than they change
text — the simulation. Some plants are over-determined (will fire at multiple
layers); record every finding.

**Index**
- CV-01 R_sense raised to 5.11 kΩ (regresses 2026-05-30 fix)
- CV-02 R_sense dropped to 1.5 kΩ (accuracy and dissipation impact)
- CV-03 LDO bulk cap shrunk below stability minimum
- CV-04 NR/SS cap two decades too small
- CV-05 LDO EN pull-down value drift (10 k → 100 k)
- CV-06 LDO BIAS bypass cap removed
- CV-07 I²C pull-ups raised (2.2 k → 22 k)
- CV-08 Bobcat VDDD HF cap shrunk (0.1 µF → 100 pF)
- CV-09 VDDA1 series 0 Ω replaced with 10 Ω
- CV-10 Unit typo on a 1 µF cap (1 µF → 1 F)
- CV-11 MPN→value mismatch on a 0 Ω jumper
- CV-12 22 µF MPN labeled as 10 µF

---

### CV-01 — Bias sense R raised back to 5.11 kΩ

**Description.** The 2026-05-30 fix lowered R40/R41 from 5.11 kΩ to 3.65 kΩ
because at 5.11 kΩ the regulated full-scale current capped at ~484 µA — below
the 640 µA spec when the BIAS pin sits at the PDF's 0.5 V compliance point.
Regressing this value should be caught by both the semantic value-vs-MPN rule
and the `opa_bias` sim.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Key: `parts.R40.value` and `parts.R41.value`
- Before: `"3.65k 0.1%"`
- After:  `"5.11k 0.1%"`

(Optionally also flip `lib_id` from `Lib:TNPW06033K65BEEA` back to
`Lib:TNPW06035K11BEEA`; doing only one of the two also reveals the
CHK_VALUE_MATCHES_MPN rule independently.)

**Detect.**
- Tool: sim
- Rule/ID: `BLK_BIAS_FS_CEILING`
- Severity: ERROR
- Expected: regulated FS current at 0.5 V compliance ≤ ~484 µA, fails the
  640 µA pass criterion.

Also:
- Tool: semantic
- Rule/ID: `CHK_VALUE_MATCHES_MPN` (if only the value is changed)
- Severity: ERROR

**Fix.** Closed-loop should restore both `value` AND `lib_id` to the 3.65 kΩ /
`TNPW06033K65BEEA` pair. (See `design_intent.md` "Bias" section.)

**Pass criteria.**
- `opa_bias` block reports FS_failure with regulated_FS_uA in [450, 510].
- Closed-loop's Plan phase proposes restoring 3.65 kΩ.
- After Apply, build is clean and sim passes (FS ≥ 640 µA).

**Notes.** Anchored to `design_intent.md` §Bias and memory
`sim-bias-compliance-vdda-pdn`. Don't accept a fix that lowers DUT compliance
or raises 3V3 to satisfy FS.

---

### CV-02 — Bias sense R dropped to 1.5 kΩ

**Description.** Going the other direction: too small a sense R inflates FS
current capability (~1.87 mA), wastes power, and degrades LSB accuracy at low
bias because the DAC step size in current grows. Linter and validator pass;
only sim + accuracy rule catches it.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Key: `parts.R40.value`, `parts.R41.value`
- Before: `"3.65k 0.1%"`
- After:  `"1.5k 0.1%"`

**Detect.**
- Tool: sim
- Rule/ID: `BLK_BIAS_ACCURACY_BUDGET`
- Severity: WARNING (FS still satisfied; LSB error grows)
- Expected: LSB current step ≥ ~0.5 µA, exceeding the "~1 µA step" target only
  loosely; the real failure is the accuracy budget at low codes.

Also:
- Tool: semantic
- Rule/ID: `CHK_VALUE_MATCHES_MPN` (no 1.5 kΩ MPN in lib).

**Fix.** Restore 3.65 kΩ.

**Pass criteria.**
- Sim reports accuracy budget breach OR FS too high warning.
- Plan proposes 3.65 kΩ, NOT 5.11 kΩ.

---

### CV-03 — LDO bulk cap below stability minimum

**Description.** TPS7A8401A specifies COUT_min ≈ 25 µF for ANY-OUT stability.
The current design uses C13 + C18 = 22 µF + 22 µF (44 µF nominal, ~25 µF
derated). Halving one of them breaks the stability floor.

**Plant.**
- File: `test1/netlist/power.yaml`
- Key: `parts.C13.value`
- Before: `22uF`
- After:  `1uF`

(Keep the MPN the same to avoid layering CHK_VALUE_MATCHES_MPN over this.)

**Detect.**
- Tool: sim
- Rule/ID: `BLK_LDO_DC_OK` (transient/AC sub-test)
- Severity: ERROR
- Expected: regulator ring or fail-to-settle on load step; phase margin < 30°.

Also possibly:
- Tool: semantic
- Rule/ID: `BLK_LDO_DROPOUT_MARGIN` (indirect)
- Severity: WARNING

**Fix.** Restore 22 µF.

**Pass criteria.**
- Sim transient shows oscillation OR settling-time-violation.
- Plan proposes restoring C13 = 22 µF.

**Anti-test.** Do NOT plant the same change on C14 (0.1 µF HF cap) — that's a
different role and should not trip the COUT minimum.

---

### CV-04 — NR/SS cap two decades too small

**Description.** Datasheet recommends C12 ≥ 10 nF on NR/SS to suppress
reference noise and set soft-start. 100 pF makes soft-start essentially
instant and re-couples reference noise to the output.

**Plant.**
- File: `test1/netlist/power.yaml`
- Key: `parts.C12.value`
- Before: `10nF`
- After:  `100pF`

**Detect.**
- Tool: semantic
- Rule/ID: `VAL_LDO_NRSS_RANGE` (new; if absent, this test surfaces a gap)
- Severity: WARNING

Also:
- Tool: sim
- Rule/ID: `BLK_LDO_DC_OK` (noise sub-test if modeled)
- Severity: WARNING

**Fix.** Restore 10 nF.

**Pass criteria.**
- Either the semantic evaluator flags the value, OR this test exposes a
  missing rule and the harness logs it as a coverage gap.

**Notes.** If `VAL_LDO_NRSS_RANGE` doesn't exist, that itself is a finding —
add it to the harness's "rules coverage" report.

---

### CV-05 — LDO EN pull-down drifted 10 k → 100 k

**Description.** EN pull-down strength matters for hot-plug / glitch immunity
on the FMC EN line. 100 k is within typical pull-down range but 10× weaker
than the spec calls for, and inconsistent with the 10 k convention across the
design.

**Plant.**
- File: `test1/netlist/power.yaml`
- Key: `parts.R10.value`
- Before: `10k`
- After:  `100k`

**Detect.**
- Tool: semantic
- Rule/ID: `BLK_LDO_EN_PULLDOWN`
- Severity: WARNING

**Fix.** Restore 10 k (also fix MPN if changed: `CR0402-FX-1002GLF`).

**Pass criteria.**
- Semantic flag fires.
- Plan proposes 10 k.

**Anti-test.** Same change on R11 (LSW_EN) should trip `BLK_LOADSW_DEFAULT_OFF`
in the same family — confirm both rules exist symmetrically.

---

### CV-06 — LDO BIAS bypass cap removed

**Description.** C17 (1 µF) is the bypass on the LDO BIAS pin. Datasheet
§8.2.2.1 requires ≥ 0.47 µF effective (1 µF nominal X5R derates). Removing it
risks instability with BIAS-pin enabled.

**Plant.**
- File: `test1/netlist/power.yaml`
- Action: delete the `C17:` block AND its membership in `+3V3` and `GND` nets.

**Detect.**
- Tool: semantic
- Rule/ID: `DECOUPLE_LDO_BIAS` (or fold into `RAIL_LDO_BIAS12`)
- Severity: ERROR

Also:
- Tool: validator
- Rule/ID: net-membership consistency
- Severity: ERROR

**Fix.** Restore C17 (1 µF, X5R, MPN `GRM155R70J105KA12D`), wire to U10.12 and
GND.

**Pass criteria.**
- Validator/semantic both fire.
- Plan proposes adding back the cap with the correct MPN/footprint.

---

### CV-07 — I²C pull-ups raised 2.2 k → 22 k

**Description.** Raising R60/R61 by 10× increases SCL/SDA rise time on a
loaded I²C bus and may violate the I²C spec at 100/400 kHz.

**Plant.**
- File: `test1/netlist/eeprom.yaml`
- Key: `parts.R60.value`, `parts.R61.value`
- Before: `2.2k`
- After:  `22k`

**Detect.**
- Tool: semantic
- Rule/ID: `BLK_EEPROM_I2C_PULLUPS`
- Severity: WARNING

Also:
- Tool: sim (if I²C bus capacitance model is enabled in `eeprom` block)
- Rule/ID: rise-time pass criterion
- Severity: ERROR if 400 kHz; WARNING if 100 kHz

**Fix.** Restore 2.2 k.

**Anti-test.** Setting R60/R61 to 4.7 k should be in-spec (warning OFF) — use
to confirm threshold.

---

### CV-08 — Bobcat VDDD HF cap shrunk to 100 pF

**Description.** Replacing a 0.1 µF HF decap with 100 pF moves the cap's
self-resonance into a region that doesn't help digital switching transients.
DECOUPLE_VDDD checks the per-pin cap presence; this exercises a value-band check.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Key: `parts.C20.value`
- Before: `0.1uF`
- After:  `100pF`

**Detect.**
- Tool: semantic
- Rule/ID: `DECOUPLE_VDDD` (value-band sub-check)
- Severity: ERROR

**Fix.** Restore 0.1 µF.

**Pass criteria.**
- Semantic flags VDDD decap value out of band.
- Plan proposes 0.1 µF.

**Notes.** If the current rule only checks for cap presence (not value), this
test surfaces a coverage gap. Document it.

---

### CV-09 — VDDA1 series 0 Ω replaced with 10 Ω

**Description.** The series resistor on Bobcat VDDA1 (R20) is supposed to be
0 Ω (a stuff option for noise isolation). 10 Ω introduces a ~6.4 mV/640 µA
drop AND a 10 Ω PDN impedance that shows up in `BLK_PDN_VDDA1_DROOP`.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Key: `parts.R20.value`
- Before: `"0"`
- After:  `"10"`

**Detect.**
- Tool: semantic
- Rule/ID: `SERIESR_VDDA1` (value-band: must be 0 Ω)
- Severity: ERROR

Also:
- Tool: sim
- Rule/ID: `BLK_PDN_VDDA1_SERIES0R` (and `BLK_PDN_VDDA1_DROOP` indirectly)
- Severity: ERROR

**Fix.** Restore 0 Ω.

---

### CV-10 — Unit typo `1uF` → `1F`

**Description.** A common LLM/agent typo — dropping the SI prefix. Tests
whether the YAML parser + value-band rules catch implausible magnitudes.

**Plant.**
- File: `test1/netlist/power.yaml`
- Key: `parts.C15.value`
- Before: `1uF`
- After:  `1F`

**Detect.**
- Tool: semantic
- Rule/ID: any per-component value-range guard (if absent, this is a gap)
- Severity: ERROR

Also:
- Tool: bom_check
- Rule/ID: MPN voltage/capacitance plausibility
- Severity: ERROR

**Fix.** Restore `1uF`.

**Notes.** If no rule catches "1 F on a 0402", the harness must log the gap.
This is a high-priority gap: any LLM-driven edit can introduce it.

---

### CV-11 — 0 Ω jumper with mismatched MPN

**Description.** Tests the value↔MPN coherence pathway in isolation: keep the
value `"0"` but swap to a non-zero MPN.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Key: `parts.R20.lib_id`
- Before: `Lib:CRCW04020000Z0ED`
- After:  `Lib:CR0402-FX-1002GLF`  (a 10 k MPN)

**Detect.**
- Tool: semantic
- Rule/ID: `CHK_VALUE_MATCHES_MPN`
- Severity: ERROR

**Fix.** Restore `Lib:CRCW04020000Z0ED`.

**Anti-test.** Swapping between two 10 k MPNs (e.g. CR0402 ↔ TNPW0402 if such
existed) is a packaging-only edit, NOT a value mismatch.

---

### CV-12 — 22 µF MPN labeled as 10 µF

**Description.** Reverse of CV-11: keep the MPN, drift the value.

**Plant.**
- File: `test1/netlist/power.yaml`
- Key: `parts.C13.value` (MPN stays `GRM21BR61A226ME44L`)
- Before: `22uF`
- After:  `10uF`

**Detect.**
- Tool: semantic
- Rule/ID: `CHK_VALUE_MATCHES_MPN`
- Severity: ERROR

**Fix.** Restore `22uF`.

**Pass criteria.**
- Rule fires before any sim runs (cheap check first).
- Plan proposes restoring the value, not changing the MPN.
