# 04 — Symbol library issues and inconsistencies

Pin name / number / position / electrical-type / footprint drift in
`test1/altium/out/lib/parts.SchLib` and the per-part `.SchLib` files under
`test1/Parts Library/`. These are the highest-leverage faults: a bad symbol
silently propagates into every sheet that places it, and the strict validator
only catches the subset that breaks net-membership.

Plants here are edits to a `.SchLib` (binary OLE Altium format, edited via
`altium_monkey`) or to the symbol metadata referenced from `bias.yaml` etc.

**Index**
- SL-01 Pin name renamed (SDA → DATA)
- SL-02 Pin number drift from UL re-import
- SL-03 Missing pin (V- on OPA2388)
- SL-04 Extra phantom pin (VREF on MCP4728)
- SL-05 Wrong electrical type on FMC GND pins
- SL-06 Pin font scramble after `merge` (regression test)
- SL-07 Multi-unit PartCount drift (FMC 4 → 3)
- SL-08 Pin position drift breaks routing
- SL-09 Symbol MPN vs orderable-part variant mismatch
- SL-10 Pin orientation flipped (right-facing → left-facing)
- SL-11 lib_id reference mismatch between netlist and library
- SL-12 Duplicate symbol UniqueID

---

### SL-01 — Pin name renamed (SDA → DATA) on MCP4728 symbol

**Description.** Rename the SDA pin (pin 3) in the MCP4728 symbol to "DATA".
This breaks intent across every sheet that ties SDA to the part, but the
designator (3) stays the same so net-membership-by-designator still resolves.
Exposes any rule that pivots on pin NAME rather than pin DESIGNATOR.

**Plant.**
- File: `test1/altium/out/lib/parts.SchLib` (or per-part `parts.SchLib`)
- Symbol: `MCP4728T-EUN`
- Pin designator 3: rename `Name` from `SDA` to `DATA`.

**Detect.**
- Tool: validator
- Rule/ID: per-pin name vs net coherence (if implemented; otherwise gap)
- Severity: WARNING

Also (planned):
- Tool: semantic
- Rule/ID: `SEM_MCP4728_PIN_NAMES`
- Severity: WARNING

**Fix.** Rename back to SDA in the symbol.

**Pass criteria.**
- A name-vs-net mismatch finding fires (or the test surfaces a coverage gap).

**Anti-test.** Renaming the pin to a synonym already in the lib (e.g. SDIO)
should still fire — semantic equivalence is not a defense.

---

### SL-02 — Pin number drift from UL re-import

**Description.** Per memory `ul-symbol-import`: builders are pin-position
sensitive. Simulate a UL re-import that shuffles MCP4728 pin 6 (VOUTA) and pin
7 (VOUTB). The schematic still validates against the YAML (which references
pins by designator), but the placed routing now wires VOUTA from the wrong
package pin.

**Plant.**
- File: `parts.SchLib`
- Symbol: `MCP4728T-EUN`
- Swap pin designators 6 ↔ 7. (Or swap their X positions, depending on what
  the builder reads.)

**Detect.**
- Tool: build
- Rule/ID: builder pin-position mismatch — `place_from_netlist` returns wrong
  coordinates for `U40["6"]`.
- Severity: ERROR (build fails OR places wires that fail validator).

Also:
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_FS_CEILING` (because the wrong DAC channel feeds the
  loop) — depends on whether the deck reads from netlist or library.
- Severity: ERROR

**Fix.** Restore original pin numbering.

**Pass criteria.**
- Build or validator emits a "pin not where expected" error.
- The harness verifies the placed wire actually connects to pin 6's spatial
  location, not pin 7.

**Notes.** Memory: "2N7002 UL is a diode (reverted), OPA2388 UL is
single-unit." Both are evidence that UL imports drift; this test guards the
guard.

---

### SL-03 — Missing pin: drop V- (pin 4) from OPA2388

**Description.** Remove pin 4 (V-) from the OPA2388 symbol. The bias.yaml
lists `U41.4` in the `GND` net; the validator should fire on the missing
member.

**Plant.**
- File: `parts.SchLib`
- Symbol: `OPA2388IDGKR`
- Delete pin with `Designator: 4`.

**Detect.**
- Tool: validator
- Rule/ID: member-not-found
- Severity: ERROR
- Expected: `"net GND member U41.4 not present in symbol"`.

**Fix.** Restore pin 4.

**Pass criteria.**
- Validator fires immediately at build time.
- Build aborts before reaching the layout linter.

---

### SL-04 — Extra phantom pin: add VREF to MCP4728

**Description.** Per `design_intent.md`: "MCP4728 has NO VREF pin … Do not
add a VREF net/pin to 'tie VREF to 3.3V'." This test plants exactly that
mistake to verify the system can catch a phantom pin even when the netlist
doesn't reference it.

**Plant.**
- File: `parts.SchLib`
- Symbol: `MCP4728T-EUN`
- Add an extra pin: `Designator: VREF`, `Name: VREF`, placed on the symbol
  body somewhere.

**Detect.**
- Tool: validator OR semantic
- Rule/ID: `BLK_BIAS_DAC_VREF_EXTERNAL` should NOT be satisfied by the
  presence of a VREF pin (it's a config bit, not wireable).
- Severity: ERROR

Also:
- Tool: build/linter — extra unconnected pin generates an unconnected-pin
  warning.
- Severity: WARNING

**Fix.** Delete the phantom pin.

**Pass criteria.**
- Phantom pin is detected (not silently accepted).
- Closed-loop does NOT propose "wire VREF to +3V3" as a fix; instead, it
  proposes deleting the pin and adjusting the firmware config.

**Notes.** This is a high-priority semantic test: agents have historically
proposed adding "missing" pins to satisfy electrical-intent rules.

---

### SL-05 — FMC connector GND pins set to wrong electrical type

**Description.** This is the inverse of the F-1 finding in the audit:
`ASP-134606-01.SchLib` currently marks ALL pins as `Electrical=Passive`, which
is why GND pins don't auto-merge. Test: change a single FMC pin (say C2) to
`Electrical=Power` with `Name=GND` and verify the auto-merge behavior. Then
verify that LEAVING it `Passive` is correctly flagged as a defect.

**Plant A (positive test of the fix).**
- File: `Parts Library/ASP-134606-01/ASP-134606-01.SchLib`
- Pin: C2
- Change: `Electrical: 4` (Passive) → `Electrical: 7` (Power), `Name: C2` →
  `Name: GND`.
- Expected: pin C2 auto-merges into the GND net even though `fmc.yaml` doesn't
  list it explicitly.

**Plant B (negative test — the current state).**
- No plant; just run the audit.
- Expected: a NEW rule `FMC_GND_PIN_COVERAGE` (to be added) reports that the
  GND pins of the FMC connector are not enumerated AND the symbol's pins are
  not power-typed.

**Detect.**
- Tool: validator (new rule)
- Rule/ID: `FMC_GND_PIN_COVERAGE`
- Severity: ERROR
- Expected: lists every FMC pin not in any wired net AND with Electrical ≠
  Power.

**Fix.** Either enumerate every GND pin in `fmc.yaml`'s `GND` net, or update
the FMC symbol to mark all GND pins as `Electrical=Power, Name=GND`.

**Pass criteria.**
- The rule fires on a clean checkout (the F-1 finding).
- After either of the two fix paths is applied, the rule passes.

**Notes.** Critical test. The audit report's F-1 is the canonical positive
example. See `Parts Library/ASP-134606-01/ASP-134606-01.pdf` for the manufactured
pin list.

---

### SL-06 — Pin font scramble after AltiumSchLib.merge

**Description.** Memory `merge-font-scramble-bug`: "AltiumSchLib.merge
scrambles CUSTOM pin font_ids; author symbols in DEFAULT font mode (no
name_font) so names stay readable post-merge." This test plants a CUSTOM
pin font on one symbol and runs the merge to confirm the regression.

**Plant.**
- File: `Parts Library/MCP4728/MCP4728.SchLib` (source)
- Change: set `name_font` on any pin to a custom font ID.

**Detect.**
- Tool: post-merge symbol inspection
- Rule/ID: `_check_pin_font_default` (planned linter rule on the merged
  output)
- Severity: ERROR

**Fix.** Author with default font mode.

**Pass criteria.**
- After `python -m test1.altium.build_project`, the merged
  `out/lib/parts.SchLib` shows MCP4728 pins with scrambled font IDs.
- A future rule should flag this BEFORE merge.

**Notes.** This is also a regression test — guards against the bug
re-emerging after `altium_monkey` updates.

---

### SL-07 — Multi-unit PartCount drift: FMC 4 → 3

**Description.** FMC LPC symbol has 4 parts (one per row C/D/G/H). Drop
PartCount to 3 (lose row H). Build should fail when `J4` is placed.

**Plant.**
- File: `Parts Library/ASP-134606-01/ASP-134606-01.SchLib`
- Change: `PartCount: 4` → `PartCount: 3`.

**Detect.**
- Tool: build
- Rule/ID: `place_from_netlist` for `J4` with `unit=4` raises (no such unit).
- Severity: ERROR
- Expected: build error citing missing part unit.

**Fix.** Restore PartCount = 4.

---

### SL-08 — Pin position drift breaks routing

**Description.** Per memory `ul-symbol-import`: builders are pin-position
sensitive. Move pin 2 (source) of PMZ1200UPEYL by 100 mil.

**Plant.**
- File: `Parts Library/PMZ1200UPEYL/PMZ1200UPEYL.SchLib`
- Change: shift pin 2's X coordinate +100.

**Detect.**
- Tool: build / linter
- Rule/ID: the wire from R40 to PMOS source now no longer terminates at the
  pin → `_check_pin_wire_crosses_body` or similar, OR validator finds no
  electrical connection.
- Severity: ERROR

**Fix.** Restore pin position.

**Pass criteria.**
- Build emits a routing error.
- The harness verifies the placed wire ends at the new pin coordinate (proves
  the diagnosis).

---

### SL-09 — Symbol-MPN vs orderable-part variant mismatch

**Description.** Audit finding F-6: yaml lists `footprint:
Package_DFN_QFN:VQFN-10-1EP_3x3mm` for MCP4728, but the actual symbol library
uses `MCP4728T-EUN` (MSOP-10, no EP). Same for OPA2388 (yaml SOIC-8, symbol
VSSOP-8) and PMZ1200UPEYL (yaml DFN-3 with EP, datasheet SOT883 no EP).

**Plant.** No plant — this is the current state. The test is "audit the gold
checkout."

**Detect.**
- Tool: bom_check (planned)
- Rule/ID: `MPN_FOOTPRINT_COHERENCE`
- Severity: ERROR
- Expected: yaml `footprint` field disagrees with the orderable MPN's actual
  package per datasheet.

**Fix.** Update yaml `footprint:` to the correct land pattern for the
orderable part, OR change the MPN to one that matches the footprint.

**Pass criteria.**
- The audit catches all three (MCP4728, OPA2388, PMZ1200UPEYL) on the gold
  checkout — proving the rule actually runs and finds existing bugs.

**Notes.** This test exists explicitly to keep the F-6 finding from being
silently ignored.

---

### SL-10 — Pin orientation flipped

**Description.** A pin's exit direction is part of the symbol; the builder
assumes specific orientations to compute exit coordinates. Flip one pin's
orientation by 180°.

**Plant.**
- File: `parts.SchLib`
- Symbol: any chip
- Change: pin 1 `Orientation: 2` (left-facing) → `Orientation: 0`
  (right-facing).

**Detect.**
- Tool: build / linter
- Rule/ID: wire exits from the wrong side; `_check_wire_through_body` likely
  fires because the wire goes through the chip body to reach the pin's new
  position.
- Severity: ERROR

**Fix.** Restore orientation.

**Pass criteria.**
- Linter fires on `_check_wire_through_body` or similar.
- Closed-loop should propose a SYMBOL fix, not a placement workaround.

---

### SL-11 — lib_id reference in YAML diverges from library

**Description.** YAML references `Lib:TNPW06035K11BEEA` but parts.SchLib only
has `TNPW06033K65BEEA` (or vice versa). The build can either fail outright or
substitute a placeholder symbol — both should be detected.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Key: `parts.R40.lib_id`
- Before: `Lib:TNPW06033K65BEEA`
- After:  `Lib:TNPW06035K11BEEA`  (an MPN NOT present in the library)

**Detect.**
- Tool: build
- Rule/ID: symbol-not-found
- Severity: ERROR
- Expected: `"lib_id Lib:TNPW06035K11BEEA not found"`.

**Fix.** Either restore the lib_id OR add the symbol to the library (deeper
fix). The closed-loop should distinguish these two cases and pick the right
one (memory `loop-symbol-clone-remediation` describes the clone-from
workflow for the latter).

**Pass criteria.**
- Build fails with the symbol-not-found error.
- Plan correctly identifies the fix path (revert vs clone).

---

### SL-12 — Duplicate symbol UniqueID

**Description.** Altium uses `UniqueID` per object for incremental updates. If
two symbols share a UniqueID, downstream PCB sync gets confused.

**Plant.**
- File: `parts.SchLib`
- Change: set MCP4728's UniqueID equal to OPA2388's.

**Detect.**
- Tool: build / linter (planned)
- Rule/ID: `_check_unique_ids`
- Severity: WARNING

**Fix.** Regenerate UniqueIDs.

**Pass criteria.**
- The duplicate is detected before the symbol is placed twice.

**Notes.** If this rule doesn't exist, it's a coverage gap to add.
