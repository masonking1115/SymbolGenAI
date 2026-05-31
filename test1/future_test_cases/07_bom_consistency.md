# 07 — BOM consistency errors

Tests for the bidirectional reconciliation between `test1/test1_bom.xlsx`,
the YAML netlists, and the symbol library. There is currently no automated
`bom_check` runner; each test here is a specification for that runner. Mark
every test `Status: tool not implemented` until the runner exists, and grade
it as "spec valid, run pending."

**Index**
- BC-01 BOM R40 stale at 5.11 k (the F-4 finding)
- BC-02 BOM MPN doesn't match parts.SchLib's lib_id
- BC-03 BOM has a refdes not present in any sheet
- BC-04 Netlist refdes not in BOM
- BC-05 BOM footprint disagrees with yaml footprint
- BC-06 BOM Per-Refdes vs Summary count mismatch
- BC-07 BOM lists DNP but YAML doesn't mark `dnp: true`
- BC-08 BOM duplicates a refdes

---

### BC-01 — BOM stale: R40/R41 listed as 5.11 k 0.1 % / TNPW06035K11BEEA

**Description.** The audit's F-4 finding. The Per-Refdes sheet shows
`R40 = 5.11k 0.1% / TNPW06035K11BEEA`, while bias.yaml + parts.SchLib both
have `3.65k 0.1% / TNPW06033K65BEEA`. The BOM is the stale party.

**Plant.** No plant — this is the gold-checkout state. The test is an audit.

**Detect.**
- Tool: bom_check (planned)
- Rule/ID: `BOM_VALUE_MATCH(yaml.bias.R40, bom.R40)`
- Severity: ERROR
- Expected: mismatch on both `value` and `MPN`.

**Fix.** Regenerate the BOM Per-Refdes sheet from the YAML netlists (the
designated source of truth).

**Pass criteria.**
- bom_check fires on a clean checkout (audit succeeds).
- After BOM regen, audit passes.

**Notes.** Holds the system honest about which document is authoritative.
The convention (per `design_intent.md`): YAML wins, BOM is derived.

---

### BC-02 — BOM MPN doesn't match parts.SchLib's lib_id

**Description.** Plant: the BOM lists `MCP4728` (no variant suffix), but
parts.SchLib uses `MCP4728T-EUN` (MSOP-10 variant). The Per-Refdes row may
look fine but procurement would order the wrong variant.

**Plant.**
- File: `test1_bom.xlsx`, Per-Refdes sheet, U40 row.
- Change: `MPN` column from `MCP4728` → `MCP4728-E/UN` (legitimate but wrong
  variant: VQFN-10).

**Detect.**
- Tool: bom_check
- Rule/ID: `BOM_MPN_MATCHES_LIBRARY(u40.lib_id, bom.u40.mpn)`
- Severity: ERROR

**Fix.** Restore `MCP4728T-EUN`.

---

### BC-03 — BOM has refdes not present in any netlist

**Description.** Add a phantom row to the BOM (e.g. R200) that doesn't exist
in any sheet's `parts:`. Catches the case where a BOM is hand-edited and
drifts from the schematic.

**Plant.**
- File: `test1_bom.xlsx`, Per-Refdes sheet.
- Add row: `R200 | 10k | CR0402-FX-1002GLF | ... | bobcat`.

**Detect.**
- Tool: bom_check
- Rule/ID: `BOM_ORPHAN_REFDES`
- Severity: ERROR

**Fix.** Remove R200 from BOM.

---

### BC-04 — Netlist refdes not in BOM

**Description.** Inverse of BC-03. Delete the R44 row from the BOM (BIAS_ISO0
pull-down). Schematic has it but BOM doesn't.

**Plant.**
- File: `test1_bom.xlsx`, Per-Refdes sheet.
- Delete row for R44.

**Detect.**
- Tool: bom_check
- Rule/ID: `BOM_MISSING_REFDES`
- Severity: ERROR

**Fix.** Re-add R44.

---

### BC-05 — BOM footprint disagrees with YAML footprint

**Description.** Per audit F-6: yaml lists `footprint:
Package_DFN_QFN:VQFN-10-1EP_3x3mm` for MCP4728. If the BOM column says
`MSOP-10`, the two disagree. Fixing one alone is insufficient; the rule must
distinguish "yaml wrong" from "bom wrong" from "both wrong."

**Plant.** No plant for the canonical case — the gold checkout already has
this mismatch. (For test isolation, can also plant: change `bias.yaml.U40
.footprint` to `Package_SO:SOIC-8` and verify the BOM check still fires.)

**Detect.**
- Tool: bom_check
- Rule/ID: `BOM_FOOTPRINT_MATCH(yaml.footprint, bom.package)`
- Severity: WARNING (the rule should also report the MPN to disambiguate
  which side is wrong).

**Fix.** Update yaml `footprint:` to match the orderable MPN's actual package.

**Pass criteria.**
- All three known cases (MCP4728, OPA2388, PMZ1200UPEYL) fire on the audit.

---

### BC-06 — BOM Per-Refdes count differs from Summary count

**Description.** The main BOM sheet has a `Qty` column for each line item;
the Per-Refdes sheet enumerates instances. Plant a discrepancy: BOM main
sheet says "C_bulk×4" but Per-Refdes only enumerates 3.

**Plant.**
- File: `test1_bom.xlsx`, Per-Refdes sheet.
- Delete one of the bulk-cap rows (e.g. C13).

**Detect.**
- Tool: bom_check
- Rule/ID: `BOM_QTY_CONSISTENCY`
- Severity: ERROR

**Fix.** Re-add.

---

### BC-07 — DNP marker mismatch

**Description.** YAML `bias.yaml.R42` is `dnp: true`. If the BOM doesn't show
DNP, procurement will order it; if YAML doesn't have it but BOM does,
assembly will skip it. Plant either direction.

**Plant A (BOM has DNP, YAML doesn't):**
- File: `test1_bom.xlsx`, Per-Refdes sheet.
- Set R20 (bobcat VDDA1 0 Ω) Notes column to "DNP".

**Plant B (YAML has DNP, BOM doesn't):**
- File: `test1/netlist/bias.yaml`
- Key: `parts.R42.dnp` → remove the line (defaults to false).

**Detect.**
- Tool: bom_check
- Rule/ID: `BOM_DNP_CONSISTENCY`
- Severity: ERROR

**Fix.** Align both sides.

---

### BC-08 — BOM duplicates a refdes

**Description.** Add a second row for R40 with a different MPN. Procurement
sees the conflict.

**Plant.**
- File: `test1_bom.xlsx`, Per-Refdes sheet.
- Add another `R40` row with a wrong MPN.

**Detect.**
- Tool: bom_check
- Rule/ID: `BOM_DUPLICATE_REFDES`
- Severity: ERROR

**Fix.** Remove the duplicate.

---

## Notes on tool implementation

A minimal `bom_check` runner needs only:
1. Read `test1_bom.xlsx` (openpyxl) into a flat dict keyed by refdes.
2. Walk every `netlist/*.yaml` to build the canonical refdes table from the
   YAML side.
3. Compare: `{value, mpn, footprint, dnp}` per refdes.
4. Emit findings with ID, severity, message.

Estimated implementation cost: 1 day. High ROI because the BOM ↔ schematic
drift is currently caught only by hand audits (which is how F-4 was found).
