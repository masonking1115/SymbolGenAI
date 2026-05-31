# 03 — Linter rule coverage

One test per `_check_*` rule in `test1/altium/layout_lint.py` (31 rules as of
2026-05-31). Each test plants a minimal geometric defect that should fire
exactly that rule. The harness must also verify no UNRELATED rules fire
(false-positive pressure).

Plants in this file are placement-level — they live in `build_<sheet>.py`,
not in the netlist YAMLs. Most are 1–3 line edits to a coordinate.

**Coverage goal:** every rule in `RULES` (top of `layout_lint.py`) has at least
one positive test (fires when planted) AND at least one negative test (does
NOT fire on the gold checkout). The gold negative is implicit: every test in
this file expects ZERO findings on the clean checkout's `lint.json`.

**Index**
- LR-01 off_grid
- LR-02 diagonal
- LR-03 out_of_bounds
- LR-04 component_overlap
- LR-05 duplicate_wire
- LR-06 wire_overlap
- LR-07 bridged_drop
- LR-08 passive_on_corner
- LR-09 visible_param_glob
- LR-10 power_orientation
- LR-11 wire_through_label
- LR-12 power_straddles_net
- LR-13 ground_on_top
- LR-14 power_stub_side (auto-fixable)
- LR-15 power_borders_component
- LR-16 power_clearance_all_sides
- LR-17 wire_through_body
- LR-18 body_wire_clearance
- LR-19 pin_wire_crosses_body
- LR-20 off_center
- LR-21 cramped_spacing
- LR-22 cramped_cluster
- LR-23 decap_grouping
- LR-24 passive_declutter
- LR-25 label_overlap (with port-port exemption)
- LR-26 label_over_symbol
- LR-27 label_symbol_clearance
- LR-28 wire_through_port
- LR-29 offpage_text
- LR-30 redundant_junction
- LR-31 stub_t_short

---

### LR-01 — off_grid

**Description.** Wires must land on the 100-mil grid. Plant a vertex at a
50-mil offset.

**Plant.**
- File: `test1/altium/build_eeprom.py`
- Change: pick any `s.wire(x0, y0, x1, y1)` call and modify one coordinate by
  +50 mil.

**Detect.**
- Tool: linter
- Rule/ID: `_check_off_grid`
- Severity: ERROR
- Expected: lint report cites the modified wire vertex.

**Fix.** Snap to grid.

**Anti-test.** Don't accept this as warning-only; off-grid wires break
Altium's auto-junction inference.

---

### LR-02 — diagonal

**Description.** Wires must be horizontal or vertical. Plant a diagonal.

**Plant.**
- File: any `build_*.py`
- Change: alter a `s.wire(x0, y0, x1, y1)` so that x0≠x1 AND y0≠y1.

**Detect.**
- Tool: linter
- Rule/ID: `_check_diagonal`
- Severity: ERROR

**Fix.** Make it a single L-bend (two orthogonal segments).

---

### LR-03 — out_of_bounds

**Description.** A component placed outside the declared paper frame (memory
`altium-paper-sizes` documents the correct usable rectangle).

**Plant.**
- File: `test1/altium/build_connectors.py`
- Change: place TP52 at (50, 50) — outside the A3 usable area.

**Detect.**
- Tool: linter
- Rule/ID: `_check_out_of_bounds`
- Severity: ERROR
- Expected: cites refdes + position vs declared frame.

**Fix.** Move inside frame.

**Anti-test.** Placement at exactly the frame edge (touching but not crossing)
should NOT fire — paper margin is exclusive (memory `altium-paper-sizes`).

---

### LR-04 — component_overlap

**Description.** Two component bodies sharing the same bounding box.

**Plant.**
- File: `test1/altium/build_bias.py`
- Change: place C42 at the same (x, y) as U41.

**Detect.**
- Tool: linter
- Rule/ID: `_check_component_overlap`
- Severity: ERROR

**Fix.** Separate.

---

### LR-05 — duplicate_wire

**Description.** Two identical wires (same endpoints, same direction) — the
schematic builder occasionally emits these on retry.

**Plant.**
- File: any `build_*.py`
- Change: call `s.wire(x0, y0, x1, y1)` twice with identical args.

**Detect.**
- Tool: linter
- Rule/ID: `_check_duplicate_wire`
- Severity: WARNING

**Fix.** Drop one.

---

### LR-06 — wire_overlap

**Description.** Two wires sharing a colinear segment (not identical, but
overlapping in a region).

**Plant.**
- File: any `build_*.py`
- Change: two wires from (1000, 5000)→(2000, 5000) and (1500, 5000)→(2500,
  5000).

**Detect.**
- Tool: linter
- Rule/ID: `_check_wire_overlap`
- Severity: WARNING

**Fix.** Merge into one (1000, 5000)→(2500, 5000).

---

### LR-07 — bridged_drop

**Description.** A power "drop" symbol terminus lands on a non-terminating
wire crossing (bridges two unrelated nets).

**Plant.**
- File: `test1/altium/build_eeprom.py`
- Change: place a `+3V3` power symbol over the midpoint of an SDA wire.

**Detect.**
- Tool: linter
- Rule/ID: `_check_bridged_drop`
- Severity: ERROR

**Fix.** Move the power symbol to a wire endpoint.

---

### LR-08 — passive_on_corner

**Description.** A passive component placed exactly on an L-bend corner of a
wire — its body covers the corner, creating implicit T-junctions that don't
correspond to the schematic intent.

**Plant.**
- File: `test1/altium/build_bobcat.py`
- Change: shift R22 so its center sits on the corner of the MOSI exit wire.

**Detect.**
- Tool: linter
- Rule/ID: `_check_passive_on_corner`
- Severity: WARNING

**Fix.** Move 100 mil off the corner.

---

### LR-09 — visible_param_glob

**Description.** A component with all parameters set "visible" (Value,
Designator, Description, Comment, MPN, Footprint, …) — clutters the sheet.

**Plant.**
- File: any `build_*.py`
- Change: set `show_all_params=True` on a placed component (or equivalent
  symbol parameter visibility flag).

**Detect.**
- Tool: linter
- Rule/ID: `_check_visible_param_glob`
- Severity: WARNING

**Fix.** Hide all but Designator + Value.

---

### LR-10 — power_orientation

**Description.** `+3V3` symbol facing downward (arrow points down) or `GND`
symbol facing upward. Convention is +rails up, GND down.

**Plant.**
- File: any `build_*.py`
- Change: place a `+3V3` power symbol with rotation = 180°.

**Detect.**
- Tool: linter
- Rule/ID: `_check_power_orientation`
- Severity: ERROR

**Fix.** Rotate to standard orientation.

---

### LR-11 — wire_through_label

**Description.** A wire passing through (under) a net label's bounding box —
the label appears to attach to the wrong wire.

**Plant.**
- File: `test1/altium/build_fmc.py`
- Change: route a stub wire across a global-label rectangle from a different
  net.

**Detect.**
- Tool: linter
- Rule/ID: `_check_wire_through_label`
- Severity: ERROR

**Fix.** Reroute around the label.

---

### LR-12 — power_straddles_net

**Description.** A power port placed in such a way that it attaches to a
locally-different net name (e.g. `+3V3` symbol on a wire labeled `SDA`).

**Plant.**
- File: `test1/altium/build_eeprom.py`
- Change: place a `+3V3` power symbol on the SDA exit wire.

**Detect.**
- Tool: linter
- Rule/ID: `_check_power_straddles_net`
- Severity: ERROR

**Fix.** Move/relabel.

---

### LR-13 — ground_on_top

**Description.** GND symbol placed above the wire it grounds (with the
"prong" pointing UP rather than DOWN). Inverse of LR-10 but for GND specifically.

**Plant.**
- File: any `build_*.py`
- Change: rotate a `GND` symbol 180°.

**Detect.**
- Tool: linter
- Rule/ID: `_check_ground_on_top`
- Severity: WARNING

**Fix.** Rotate.

---

### LR-14 — power_stub_side (auto-fixable)

**Description.** Power stub (drop wire from rail to component) exits on the
wrong side of the component. Memory `cosmetic-linter-rules` documents this
rule + `auto_fix_power_stub_side`.

**Plant.**
- File: `test1/altium/build_bobcat.py`
- Change: place R22 (MOSI pull-down) so its `+VDDIO` side wire exits from
  the bottom instead of the top of the body.

**Detect.**
- Tool: linter
- Rule/ID: `_check_power_stub_side`
- Severity: WARNING (auto-fix)

**Fix.** Autofixer rewrites the placement. Closed-loop should NOT escalate
this to a manual edit.

**Pass criteria.**
- Linter fires once.
- Build re-runs autofix and reports the same sheet clean after one iteration.

---

### LR-15 — power_borders_component

**Description.** Power symbol body touches (without proper gap to) an
adjacent component body.

**Plant.**
- File: any `build_*.py`
- Change: place a `+3V3` symbol 0 mil from C20's bounding box.

**Detect.**
- Tool: linter
- Rule/ID: `_check_power_borders_component`
- Severity: WARNING

**Fix.** Insert a 100-mil clearance.

---

### LR-16 — power_clearance_all_sides

**Description.** Power symbol surrounded too tightly by other symbols on
multiple sides (cluttered).

**Plant.**
- File: any `build_*.py`
- Change: surround a `+3V3` symbol with 4 capacitors at <50 mil clearance on
  all sides.

**Detect.**
- Tool: linter
- Rule/ID: `_check_power_clearance_all_sides`
- Severity: WARNING

**Fix.** Spread out.

---

### LR-17 — wire_through_body

**Description.** A wire that routes straight through a component body
(crosses the body rectangle).

**Plant.**
- File: any `build_*.py`
- Change: route a wire from one side of U10 to the other passing through the
  middle of the chip body.

**Detect.**
- Tool: linter
- Rule/ID: `_check_wire_through_body`
- Severity: ERROR

**Fix.** Route around the body.

---

### LR-18 — body_wire_clearance

**Description.** A wire too close (but not crossing) to a body. Weaker form
of LR-17.

**Plant.**
- File: any `build_*.py`
- Change: route a wire 25 mil from a body edge.

**Detect.**
- Tool: linter
- Rule/ID: `_check_body_wire_clearance`
- Severity: WARNING

**Fix.** Move ≥ 100 mil clear.

---

### LR-19 — pin_wire_crosses_body

**Description.** Wire from a pin crosses another component's body. Memory
`cosmetic-linter-rules` introduces this.

**Plant.**
- File: `test1/altium/build_bias.py`
- Change: route U40.6 (VOUTA) → U41.3 (+IN A) via a path that crosses Q40's
  body.

**Detect.**
- Tool: linter
- Rule/ID: `_check_pin_wire_crosses_body`
- Severity: WARNING

**Fix.** Reroute.

---

### LR-20 — off_center

**Description.** Value/Designator text drifted more than the threshold from
the component body center.

**Plant.**
- File: any `build_*.py`
- Change: place a capacitor with `value_offset_x = 500`.

**Detect.**
- Tool: linter
- Rule/ID: `_check_off_center`
- Severity: INFO

**Fix.** Recenter.

---

### LR-21 — cramped_spacing

**Description.** Two components < 100 mil apart (edge-to-edge).

**Plant.**
- File: `test1/altium/build_bobcat.py`
- Change: place C20 50 mil from C21.

**Detect.**
- Tool: linter
- Rule/ID: `_check_cramped_spacing`
- Severity: WARNING

**Fix.** Increase to 200 mil.

---

### LR-22 — cramped_cluster

**Description.** Many components inside a small region (density check). Plant
a 5×5 grid of decaps in a 1000-mil square.

**Plant.**
- File: any `build_*.py`
- Change: place 25 decaps in a 1000×1000 mil region.

**Detect.**
- Tool: linter
- Rule/ID: `_check_cramped_cluster`
- Severity: WARNING

**Fix.** Spread.

---

### LR-23 — decap_grouping

**Description.** A decoupling cap placed far from the pin it decouples.
Memory `cosmetic-linter-rules`.

**Plant.**
- File: `test1/altium/build_bobcat.py`
- Change: move C20 (VDDD pin-12 decap) 1000 mil away from U20.

**Detect.**
- Tool: linter
- Rule/ID: `_check_decap_grouping`
- Severity: WARNING

**Fix.** Move ≤ 200 mil from the pin.

**Anti-test.** Bulk caps (10 µF) farther from the chip should NOT fire — only
per-pin HF/MF decaps trigger this.

---

### LR-24 — passive_declutter

**Description.** Too many value labels stacked in a small adjacency.

**Plant.**
- File: any `build_*.py`
- Change: show value labels on ≥ 6 passives in a 500-mil-tall column.

**Detect.**
- Tool: linter
- Rule/ID: `_check_passive_declutter`
- Severity: WARNING

**Fix.** Hide some / stagger.

---

### LR-25 — label_overlap (with port-port exemption)

**Description.** Two text labels with overlapping bounding boxes. Memory
`port-label-overlap-exemption` notes that port-to-port overlaps are exempt
(SCL/SDA side-by-side is fine).

**Plant.**
- File: any `build_*.py`
- Change: place a hier-label `BIAS0` directly under a net-label `BIAS1` so
  bounding boxes overlap.

**Detect.**
- Tool: linter
- Rule/ID: `_check_label_overlap`
- Severity: ERROR

**Fix.** Stagger.

**Anti-test.** Two adjacent FMC PORTS (e.g. SCL and SDA ports on top of each
other but vertically separated) should NOT fire — confirm the exemption.

---

### LR-26 — label_over_symbol

**Description.** Net label drawn on top of a symbol body.

**Plant.**
- File: any `build_*.py`
- Change: place a `SCL` global label centered on U30 body.

**Detect.**
- Tool: linter
- Rule/ID: `_check_label_over_symbol`
- Severity: ERROR

**Fix.** Move off the body.

---

### LR-27 — label_symbol_clearance

**Description.** Label close to but not on a symbol body (clearance violation).
Memory `label-symbol-clearance-rule` documents the boundary computation using
`graphic_box from full_bounds_mils`.

**Plant.**
- File: any `build_*.py`
- Change: place a hier-label 25 mil from a symbol body edge.

**Detect.**
- Tool: linter
- Rule/ID: `_check_label_symbol_clearance`
- Severity: WARNING

**Fix.** Move ≥ 100 mil.

**Anti-test.** Passive value labels right above/below their own body are
exempt (per memory).

---

### LR-28 — wire_through_port

**Description.** Wire passing through a port's bounding rectangle.

**Plant.**
- File: any `build_*.py`
- Change: route a wire across the body of a `VADJ` port.

**Detect.**
- Tool: linter
- Rule/ID: `_check_wire_through_port`
- Severity: ERROR

**Fix.** Reroute.

---

### LR-29 — offpage_text

**Description.** Text or port body extends past the usable paper area. Memory
`offpage-text-linter-fix` documents the rule against declared paper size.

**Plant.**
- File: any `build_*.py`
- Change: place a port at x = paper_width - 50 (port body overhangs).

**Detect.**
- Tool: linter
- Rule/ID: `_check_offpage_text`
- Severity: ERROR

**Fix.** Move inward.

---

### LR-30 — redundant_junction

**Description.** A junction dot placed where the schematic doesn't actually
need it (only 2 wires meet, not 3+).

**Plant.**
- File: any `build_*.py`
- Change: call `s.junction(x, y)` at a corner where exactly 2 wires meet.

**Detect.**
- Tool: linter
- Rule/ID: `_check_redundant_junction`
- Severity: INFO

**Fix.** Remove.

---

### LR-31 — stub_t_short

**Description.** Orphan T-junction stub — a tiny wire stub branches off a
main wire and ends in midair.

**Plant.**
- File: any `build_*.py`
- Change: add a 50-mil orthogonal stub from a wire midpoint, terminating in
  open space.

**Detect.**
- Tool: linter
- Rule/ID: `_check_stub_t_short`
- Severity: WARNING

**Fix.** Remove or extend to a real endpoint.

---

## Cross-rule false-positive matrix (planned)

A future runner should also assemble a matrix: for each plant (LR-XX), record
every rule that fires. The gold-master expectation is "exactly one rule fires
per plant." Cross-rule false positives (e.g. LR-08 plant also tripping LR-21)
should either be documented as expected co-fires or filed as linter bugs.
