---
name: kicad-circuit-from-topology
description: Generate a complete KiCad project (.kicad_pro + .kicad_sch) from a parts list and net topology — schematic instances, wires, junctions, power symbols, and labels — validated with kicad-cli. Use when the user asks for an application/example/typical circuit, a schematic from a BOM, or any chained circuit involving multiple ICs and passives.
---

# Generate a KiCad schematic from a topology specification

Pairs with [[kicad-symbol-from-datasheet]] — that skill makes a single `.kicad_sym`; this one wires multiple symbols together into a working schematic.

## Inputs
- **Symbol library** — one `.kicad_sym` per IC (use the symbol-from-datasheet skill to make these)
- **Parts list** — refdes, lib_id, value, footprint, package (resistor/cap/inductor type)
- **Topology** — which pins / nets / components connect to which
- **Power rails** — explicit names (`+5V`, `+3V3`, `VIN`, `GND`, …)
- **Off-board signals** — names of nets that exit the schematic (`RF_IN`, `ENABLE`, etc.)

## Process
1. **Sketch the topology** as a net list first. Every component pin gets assigned to exactly one net.
2. **Pick positions**: place each symbol so all its pins land on the chosen grid (2.54 mm typical). Symbols whose pins sit on half-grid offsets force the symbol's `at` X or Y to be half-grid; do the arithmetic before placing.
3. **Generate** the `.kicad_pro` (minimal JSON) and `.kicad_sch` (full sexpr). A Python script is cleaner than hand-writing s-expressions for anything beyond ~5 components.
4. **Validate**: `kicad-cli sch export svg --output <dir> <file>.kicad_sch` — must print `"Plotted to … Done."`. Any other output is a parse failure.
5. **Open in eeschema** for visual review. User confirms.

## Coordinate conventions
- All coordinates in **mm**. `y` increases **downward** in the schematic file.
- Symbol **local +y** is **up in the editor view**, which flips to **screen -y** when placed (i.e. pin local y=+2.54 lands at `(symbol_y - 2.54)` in world).
- **Grid: 2.54 mm (100 mil)** for passives and digital. Every pin endpoint must land on a multiple of the grid.
- A symbol's `at` position is the symbol's origin in world coords; pins are then `(at_x + pin_local_x, at_y - pin_local_y)`.

## Layout rules

### 1. Component spacing
- **Adjacent components**: leave at least **2.54–5.08 mm** (1–2 grid units) of empty space between bounding boxes.
- **Component groups** (e.g., input filter cluster, output matching cluster): separate groups by **10–15 mm** so wiring between groups has room to route.
- **ICs**: leave **5–7.5 mm** of clearance around the body so pin labels and external wires don't crowd.
- Don't try to fit everything tight — schematic real estate is cheap. If it feels cluttered, it is.

### 2. Reference / Value label placement — never overlap the symbol body
The single biggest aesthetic problem. Each symbol instance specifies absolute world positions for its `Reference` and `Value` properties — these are NOT relative to the symbol origin and KiCad will not auto-fix overlaps.

Position rules per symbol orientation:

| Symbol orientation | Reference position | Value position |
|---|---|---|
| **Vertical R/C/L** (default, angle 0) | `(X + 2.54, Y - 1.27)` — to the right of body, upper | `(X + 2.54, Y + 1.27)` — to the right of body, lower |
| **Horizontal R/C/L** (angle 90 or 270) | `(X, Y - 3.81)` — above body, centered | `(X, Y + 3.81)` — below body, centered |
| **IC rectangle** | `(X, Y_top - 2.54)` — above body, centered | `(X, Y_bottom + 2.54)` — below body, centered |
| **Power symbol (GND, +5V, …)** | hidden (ref is `#PWR…`, suppressed) | placed adjacent to the triangle/arrow |

**Common mistake**: defaulting to `(X, Y - 1.27)` for a vertical passive — this lands the label directly on the symbol body. The plates of a vertical Device:C span y ∈ [Y−0.762, Y+0.762]; any label at (X, Y±1.27) sits ON the plates.

### 3. Power rails: always use power symbols, not bare net labels
- For `+5V`, `+3V3`, `GND`, `VIN`, `VOUT`, etc., embed and place the matching `power:` symbol (`power:GND`, `power:+5V`, `power:+3V3`, `power:VCC`, …) at every termination of that rail.
- Power symbols auto-group nets by name across the whole schematic — drop one `power:+5V` near every cap and IC supply pin and they're all the same net automatically, no wires needed between them.
- A bare `(label "+5V" …)` works for connectivity but looks like a signal label and clutters the schematic. **Prefer power symbols.**
- For off-board signal nets (`RF_IN`, `ENABLE`, `MOSI`, …) — use `(label …)` or `(global_label …)` instead.

### 4. Floating nets: every wire must terminate
- Every net needs **at least one** of: a pin endpoint, a power symbol, a named label, or a hierarchical/global label naming the off-board destination.
- If a connection is incomplete (waiting on a downstream stage), drop a placeholder label like `"TO_NEXT_STAGE"` or `"FROM_ANTENNA"` — never leave a bare wire end dangling.

### 5. Wire routing
- Strictly **orthogonal** — no diagonal wires.
- Minimize crossings. When unavoidable, KiCad shows crossings as plus-shaped intersections; only ones with an explicit `(junction …)` are connected.
- Add a `(junction)` at any point where 3 or more wires meet AND that point is not a pin endpoint. Skip junctions on pin endpoints — KiCad auto-connects.
- Power symbol pin endpoints count as "pin endpoints" — no junction needed where a wire meets a `power:GND` connection point.

## File templates

### `.kicad_pro` (minimal)
```json
{
  "meta": { "filename": "<name>.kicad_pro", "version": 3 },
  "schematic": { "legacy_lib_dir": "", "legacy_lib_list": [] },
  "sheets": [["<schematic_uuid>", ""]],
  "text_variables": {}
}
```

### `.kicad_sch` shell
```
(kicad_sch
  (version 20240618)
  (generator "eeschema")
  (uuid <schematic_uuid>)
  (paper "A4")          ; or A3 for >20-component circuits
  (title_block (title "…") (date "…") (rev "1"))
  (lib_symbols
    ; embed every (symbol "Lib:Name" …) used in this sheet
  )
  ; wires
  ; junctions
  ; labels / power symbols
  ; symbol instances
  (sheet_instances (path "/" (page "1")))
)
```

### Symbol instance (place a part)
```
(symbol
  (lib_id "Lib:Part")
  (at <X> <Y> <angle>)        ; angle ∈ {0, 90, 180, 270}
  (unit 1) (in_bom yes) (on_board yes) (dnp no)
  (uuid <instance_uuid>)
  (property "Reference" "R1" (at <Xref> <Yref> 0) (effects (font (size 1.27 1.27))))
  (property "Value" "10k"    (at <Xval> <Yval> 0) (effects (font (size 1.27 1.27))))
  (property "Footprint" "…" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
  (property "Datasheet" "~"  (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
  (pin "1" (uuid <pin_uuid>))
  (pin "2" (uuid <pin_uuid>))
  (instances
    (project "<project_name>"
      (path "/<schematic_uuid>" (reference "R1") (unit 1)))))
```

### Wire / junction / label / power symbol
```
(wire (pts (xy x1 y1) (xy x2 y2)) (stroke (width 0) (type default)) (uuid …))
(junction (at x y) (diameter 0) (color 0 0 0 0) (uuid …))
(label "NET_NAME" (at x y 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid …))
; power symbols use the same symbol-instance template with lib_id "power:GND" / "power:+5V" / etc.
```

## Library symbols to embed locally

The schematic must embed every symbol it references in its `lib_symbols` block — there is no runtime library lookup. At minimum:
- Each IC from its `.kicad_sym` file (extract just the `(symbol "Name" …)` block, rename to `"Lib:Name"`)
- `Device:R` — standard rectangle resistor
- `Device:C` — standard two-plate cap
- `Device:L` — standard four-arc inductor
- `power:GND` — triangle
- `power:+5V`, `power:+3V3`, `power:VCC`, `power:VDD` — as needed for the rails in use

Reuse the embedded definitions from a previous generated schematic in the project — they don't change between schematics.

## Validation

```sh
kicad-cli sch export svg --output <dir> <file>.kicad_sch
```

- Success: `Plotted to … Done.`
- Failure: parse error message → check parens balance, justify tokens (see [[kicad-symbol-from-datasheet]]), pin number string vs int, missing mandatory properties.

## Common gotchas

- **`(justify center)` is invalid.** Omit the justify clause for centered text.
- **Pin numbers are strings** in s-expressions: `(number "1" …)`, not `(number 1 …)`.
- **`at_y` flips relative to symbol local y.** If the symbol editor shows IN at the top-left of the body and IN's local pin is at `(-10.16, +2.54)`, the world pin position when placed at `(X, Y)` is `(X − 10.16, Y − 2.54)`, NOT `(X − 10.16, Y + 2.54)`.
- **Half-grid pin offsets**: stock Device:C has pin local y = ±3.81 (= 1.5 × 2.54). Placing the cap at on-grid Y makes pin endpoints land on grid; placing at half-grid Y puts pins on half-grid. Choose to match the rest of your wiring.
- **Mandatory properties** (Reference, Value, Footprint, Datasheet) must exist even if blank: `(property "Datasheet" "" …)`.
- **Symbol rotation rotates pin positions too.** For `Device:C` rotated 90° with `at (X Y 90)`, pin world coords become `(X − 3.81, Y)` and `(X + 3.81, Y)` instead of `(X, Y − 3.81)` and `(X, Y + 3.81)`. Recompute pin coords whenever you rotate.
- **N/C pins on ICs**: use electrical type `no_connect`. KiCad renders a small X over them. If the datasheet says "may be connected to ground," tie them to GND via a wire to a `power:GND` symbol.
- **Property `at` positions in instances are world coordinates**, not relative to the symbol origin. Recompute per instance.
- **Title block lines** that mention the rev/date/comments render at the bottom-right corner of the sheet — keep them concise.

## When to use a Python generator vs hand-writing

| Circuit size | Approach |
|---|---|
| ≤ 3 components | Hand-write the `.kicad_sch` |
| 4–10 components | Python script; one pass |
| > 10 components | Python script with a helper function that takes (lib_id, ref, value, x, y, angle, pin_uuids) and emits a properly-formatted symbol-instance block. UUIDs from `uuid.uuid4()`. |

## Output to deliver
- `<project>.kicad_pro` (minimal JSON)
- `<project>.kicad_sch` (full schematic)
- A SVG export at `<project>/render/<project>.svg` for visual sanity check before the user opens eeschema
- A brief summary of what's in the schematic (parts list, net topology, any non-obvious decisions)
