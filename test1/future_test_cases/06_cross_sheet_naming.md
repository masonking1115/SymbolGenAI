# 06 — Cross-sheet and naming errors

Global/hier label drift, FMC pin re-routing, port-direction inconsistency.
These break the implicit "name = same net" contract that joins sheets together.
They tend to slip past per-sheet validators (each sheet is internally
consistent) and only surface at root-stitch time or at semantic eval.

**Index**
- XS-01 LDO_SET_* names off-by-one for TPS7A8401A (the F-2 finding)
- XS-02 RESET_N typo (`RESETN`)
- XS-03 CS_L mixed naming (`CSL` on one sheet, `CS_L` on another)
- XS-04 Case-sensitivity on BIAS0/Bias0
- XS-05 SCL/SDA crossed on one sheet only
- XS-06 +VDDIO vs VDDIO (power-net vs hier-label) inconsistency
- XS-07 Hier-label direction wrong (BIAS0 output on Bobcat but input on Bias)
- XS-08 FMC LA P↔N pin swap regression
- XS-09 Missing root-sheet entry for an existing hier label
- XS-10 Duplicate global label with conflicting direction

---

### XS-01 — LDO_SET_* names off-by-one for TPS7A8401A

**Description.** Audit finding F-2 (current state). Pins 5/6/7/9/10/11 of the
8401A carry weights 25/50/100/200/400/800 mV (base 500 mV, 25 mV resolution).
The schematic labels them LDO_SET_50mV/100mV/200mV/400mV/800mV/1V6 — the
TPS7A8400A weights. Wiring is electrically correct; firmware that reads net
names will set wrong VOUT.

**Plant.** No plant — this is the gold-checkout state. The test is "audit
that the existing pipeline detects it." If no detector exists, the test
surfaces a coverage gap (must add a `SEM_LDO_SETPOINT_NAMES_MATCH_PART` rule
or equivalent).

**Detect.**
- Tool: semantic (planned)
- Rule/ID: `SEM_LDO_SETPOINT_NAMES_MATCH_PART`
- Severity: ERROR
- Expected: rule cross-references `parts.U10.lib_id` (which says 8401A)
  against the global-net names of the LDO setpoint pins and flags the
  mismatch.

**Fix.** Rename in 4 places:
- `test1/netlist/power.yaml` — net keys `LDO_SET_*`
- `test1/netlist/fmc.yaml` — net keys + R122–R127 notes
- `test1/altium/build_fmc.py` — `LA_ROUTING` tuple list
- `test1/design_requirements.md` — FMC LA table
And rename to: `LDO_SET_25mV/50mV/100mV/200mV/400mV/800mV`.

**Pass criteria.**
- The audit (clean checkout) fires this rule.
- After rename, rule passes AND build still validates.

**Notes.** Highest-priority "naming" test because it's a real live bug.

---

### XS-02 — RESET_N renamed to RESETN on one sheet

**Description.** Drop the underscore on RESET_N in `bobcat.yaml`, leaving it
as RESET_N in `fmc.yaml`. The two sheets now don't connect — Bobcat's RESET
floats, FMC's RESET drives nothing.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Key: `nets.RESET_N` → `nets.RESETN`. Update the global-label reference to
  match.

**Detect.**
- Tool: semantic / root-stitch
- Rule/ID: `ROUTE_RESET_N` (member must exist on both sheets)
- Severity: ERROR

Also:
- Tool: validator
- Rule/ID: orphan-net (one global label with one member only).
- Severity: WARNING

**Fix.** Restore the underscore.

---

### XS-03 — CS_L renamed CSL on one sheet only

**Description.** Same family as XS-02 but tests a different underscore
position. Distinct test because the lint rule might catch underscore-prefix
but not underscore-suffix variants.

**Plant.**
- File: `test1/netlist/fmc.yaml`
- Key: `nets.CS_L` → `nets.CSL`. Update `R109` reference.

**Detect.**
- Tool: semantic
- Rule/ID: `ROUTE_CS_L`
- Severity: ERROR

**Fix.** Restore underscore.

---

### XS-04 — Case-sensitivity: BIAS0 vs Bias0

**Description.** Hier-label `BIAS0` in `bobcat.yaml` lowercased to `Bias0` on
the bias sheet. Altium labels are case-sensitive; this breaks the join.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Key: `nets.BIAS0` → `nets.Bias0`.

**Detect.**
- Tool: semantic / root-stitch
- Rule/ID: hier-label coherence between parent and child.
- Severity: ERROR

**Fix.** Restore caps.

---

### XS-05 — SCL/SDA crossed on EEPROM sheet only

**Description.** Swap which EEPROM pin gets SCL vs SDA. Easy to miss because
the bus has both signals and any single sheet's swap "looks consistent."

**Plant.**
- File: `test1/netlist/eeprom.yaml`
- Edits:
  - `nets.SCL.members`: `U30.6, R60.2` → `U30.5, R60.2`
  - `nets.SDA.members`: `U30.5, R61.2` → `U30.6, R61.2`

**Detect.**
- Tool: semantic
- Rule/ID: `RAIL_EEPROM_VCC` is unrelated; need a `ROUTE_EEPROM_SCL` /
  `ROUTE_EEPROM_SDA` cross-check rule (planned).
- Severity: ERROR

Also:
- Tool: sim
- Block: `eeprom`
- Rule/ID: I²C transactional test fails to ACK.
- Severity: ERROR

**Fix.** Swap back.

---

### XS-06 — +VDDIO vs VDDIO inconsistency

**Description.** Power nets are prefixed `+` (`+VDDIO`, `+3V3`); hier-labels
are not. A typo drops the `+` on one sheet, fragmenting the rail into two
nets.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Key: `nets.+VDDIO` → `nets.VDDIO`. Also update member references.

**Detect.**
- Tool: validator
- Rule/ID: orphan power net + un-sourced power net.
- Severity: ERROR
- Expected: two findings — `+VDDIO` has only the load-switch source, `VDDIO`
  has only the Bobcat pins.

Also:
- Tool: linter
- Rule/ID: `_check_power_orientation` won't fire, but a name-coherence rule
  should (planned `_check_power_name_convention`).
- Severity: WARNING

**Fix.** Restore `+VDDIO`.

---

### XS-07 — Hier-label direction wrong

**Description.** BIAS0 declared `output` from Bobcat (input to chip) but
`output` from Bias (delivers current) — Bobcat side should be `input`.
Reverse the parent-side direction.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Key: `nets.BIAS0.direction`
- Before: `input`
- After:  `output`

**Detect.**
- Tool: semantic / root-stitch
- Rule/ID: hier-label direction coherence (parent input ↔ child output).
- Severity: WARNING (Altium ERC will also complain).

**Fix.** Restore direction.

---

### XS-08 — FMC LA P↔N pin swap regression

**Description.** Memory `fmc-pinout-correction` documents the 2026-05-27 fix
that swapped rows C↔D / G↔H to correct VITA 57.1. Plant: swap a single
LA-pair P/N pin (e.g. LA00_P @ G6 → LA00_N @ G7) and verify the semantic eval
flags it.

**Plant.**
- File: `test1/netlist/fmc.yaml`
- Key: `internal_LA00_stub.members`
- Before: `[J3:u3.G6, R100.2]`
- After:  `[J3:u3.G7, R100.2]`

**Detect.**
- Tool: semantic
- Rule/ID: per-FMC-pin assignment (e.g. `ROUTE_SAMPLE_OUTV` cites G6).
- Severity: ERROR

Also:
- Tool: validator (no SAMPLE_OUTV source on G6).
- Severity: ERROR

**Fix.** Restore G6.

**Pass criteria.**
- Rule fires.
- Plan recognizes the swap as a P/N regression, not a generic mis-route.

---

### XS-09 — Missing root-sheet entry for an existing hier label

**Description.** Drop `BIAS0` from `build_root.ENTRIES["bobcat"]`. The two
child sheets (`bobcat`, `bias`) both declare BIAS0 hier-labels, but the root
has no sheet-symbol entry to stitch them.

**Plant.**
- File: `test1/altium/build_root.py`
- Key: `ENTRIES["bobcat"]`
- Action: delete the `("BIAS0", "input", "left", 200)` tuple.

**Detect.**
- Tool: root-stitch / semantic
- Rule/ID: `SEM_ROOT_ENTRY_COMPLETENESS` (planned)
- Severity: ERROR
- Expected: warns that a hier-label exists on both children with no root
  bridge.

**Fix.** Restore the entry.

**Anti-test.** Globally-routed nets (SCL, SDA, SAMPLE_OUT*) have NO root
entries by design — the rule must NOT fire on them. Memory: power and global
ports skip root entries.

---

### XS-10 — Duplicate global label with conflicting direction

**Description.** Declare MOSI as `direction: output` on `bobcat.yaml`
(currently `input`) while keeping `direction: output` on `fmc.yaml`. Two
drivers on one global net.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Key: `nets.MOSI.direction`
- Before: `input`
- After:  `output`

**Detect.**
- Tool: semantic / Altium ERC
- Rule/ID: multi-driver on global net.
- Severity: WARNING (could be ERROR depending on policy).

**Fix.** Restore `input` on bobcat side (Bobcat receives MOSI; FPGA drives).

**Notes.** Direction errors are a common LLM-edit failure; this is a useful
regression guard.
