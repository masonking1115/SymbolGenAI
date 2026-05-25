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
3. **Generate** the `.kicad_pro` (minimal JSON) and `.kicad_sch` (full sexpr). For hierarchical designs, emit one `.kicad_sch` per page plus a root sheet that embeds them — see [Hierarchical (multi-page) designs](#hierarchical-multi-page-designs). A Python script is cleaner than hand-writing s-expressions for anything beyond ~5 components.
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
- **No net passes through a component body.** When you route a wire that visually passes under a passive's footprint without connecting to its pin, move the passive or reroute. Even though KiCad's connectivity is fine, a reader cannot tell whether the cap is in-path or merely behind the wire.

### 6. Components are in-path or removed — never orphaned
- **Every placed component must connect to something on both sides.** If a component is "DNP" (do not populate) but lives in a series path, keep it wired in the schematic and just mark `(dnp yes)` plus a `(DNP)` value tag. The reader sees the intent.
- **Do not** leave a placed component with `no_connect` on all of its pins as a "for later" placeholder — either wire it now or delete it. A floating component with NCs on every pin reads as a bug.
- **Bypass / decoupling caps belong directly under the pin they decouple**, with one short wire stub to the pin and one short wire stub to a local GND symbol. Don't place a cap so that an unrelated net has to detour around it.

### 7. Ground symbol clustering
- **One GND symbol per local pin cluster**, not one per pin. When a chip has several adjacent GND pins (e.g., a connector's GND row or an IC's GND + thermal pad), tie them together with a single short wire and drop ONE `power:GND` symbol at the junction.
- Place the GND triangle at the **end of the wire it terminates**, not on top of a chip body or input pin. Keep ≥ 2.54 mm clearance between the triangle apex and any IC body or signal pin.
- For connectors with many GND pins (e.g., FMC's "all unlabeled pins are GND"), bus them along a short common rail and drop one GND symbol on that rail. Don't emit dozens of independent `power:GND` symbols.

### 8. Decoupling-cap cluster pattern (read this if doing more than one rail)
Per the LTC3114 / LD39050 reference style, the canonical IC + decoupling cluster looks like:

```
          [chip pin Vxx] ───┬──── [pin]
                            │
                            ├── C_bulk (e.g. 1 µF, 0805)
                            │
                            ├── C_HF   (e.g. 100 nF, 0402)
                            │
                          [GND]
```

- Bulk and HF cap **share a single GND symbol** directly below the cluster.
- The supply rail label (e.g. `5V`, `+3V3`) lives at the **top** of the cluster, above the pin.
- For multi-cap decoupling (e.g. 10 µF + 1 µF + 100 nF), place them in a tight horizontal row sharing one rail above and one GND below — not in a single vertical column where each has its own GND.
- Stay **off the path** of unrelated nets. A cap on the chip's left side shouldn't sit where the chip's right-side signal needs to route.

## File templates

### `.kicad_pro` (minimal, single-sheet)
```json
{
  "meta": { "filename": "<name>.kicad_pro", "version": 3 },
  "schematic": { "legacy_lib_dir": "", "legacy_lib_list": [] },
  "sheets": [["<schematic_uuid>", ""]],
  "text_variables": {}
}
```
For multi-page designs the `sheets` array gets one entry per page — see [Hierarchical (multi-page) designs](#hierarchical-multi-page-designs).

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
For symbols on a child sheet, the path is the full hierarchy: `"/<root_uuid>/<child_sheet_uuid>"` — see [Hierarchical (multi-page) designs](#hierarchical-multi-page-designs).

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

## Hierarchical (multi-page) designs

**When to split into pages:** >25–30 components, distinct functional blocks (Power, Analog, Digital, RF, Connectors), or when a block will be reused. One `.kicad_sch` per page; the root sheet contains `(sheet …)` blocks that embed each child file.

**File layout:**
- `<project>.kicad_pro` — `sheets` array lists every page (root first, then children in display order)
- `<project>.kicad_sch` — root sheet, mostly `(sheet …)` blocks with little or no component placement
- `<block>.kicad_sch` — one child file per functional block (e.g. `power.kicad_sch`, `digital.kicad_sch`)

**Crossing signals — name + direction must match exactly:**
- Parent declares `(pin "NAME" <dir>)` on the child sheet's box edge.
- Child places `(hierarchical_label "NAME" (shape <dir>))` where the signal enters/exits its sheet.
- `<dir>` ∈ `input` (into child), `output` (out of child), `bidirectional`, `tri_state`, `passive`. Mismatch → ERC error and validator failure.
- For nets touching ≥3 sheets (global RESET, common buses, supply rails), use `(global_label …)` on every sheet instead — no per-sheet pin declarations needed. **Power symbols (`power:GND`, `power:+5V`) are already global**; do not re-export them as hierarchical pins.

### `.kicad_pro` (multi-sheet)
```json
{
  "meta": { "filename": "<name>.kicad_pro", "version": 3 },
  "schematic": { "legacy_lib_dir": "", "legacy_lib_list": [] },
  "sheets": [
    ["<root_uuid>",    ""],
    ["<power_uuid>",   "Power"],
    ["<digital_uuid>", "Digital"]
  ],
  "text_variables": {}
}
```

### Parent: `(sheet …)` block embedding a child page
```
(sheet
  (at <X> <Y>) (size <W> <H>)
  (stroke (width 0.1524) (type solid))
  (fill (color 0 0 0 0.0000))
  (uuid <child_sheet_uuid>)
  (property "Sheetname" "Power"            (at <X> <Y_top>    0) (effects (font (size 1.27 1.27)) (justify left bottom)))
  (property "Sheetfile" "power.kicad_sch"  (at <X> <Y_bottom> 0) (effects (font (size 1.27 1.27)) (justify left top)))
  (pin "+5V" output (at <Xp> <Yp> 0)   (effects (font (size 1.27 1.27))) (uuid …))
  (pin "VIN" input  (at <Xp> <Yp> 180) (effects (font (size 1.27 1.27))) (uuid …))
  (instances (project "<project>" (path "/<root_uuid>" (page "2")))))
```
`<child_sheet_uuid>` is reused in three places: this block's `(uuid …)`, the `.kicad_pro` `sheets` entry, and the child's symbol-instance paths (next).

### Child sheet: hierarchical labels and symbol instances
```
(hierarchical_label "+5V" (shape output) (at <x> <y> 0)
  (effects (font (size 1.27 1.27)) (justify left)) (uuid …))
```
Symbol instances on a child sheet use the full hierarchy in their path:
```
(instances (project "<project>"
  (path "/<root_uuid>/<child_sheet_uuid>" (reference "U3") (unit 1))))
```
Path order is always root → child → grandchild. Refdes namespace is project-wide, so do not reuse `R1` across sheets.

### Root `sheet_instances` — one entry per page
```
(sheet_instances
  (path "/"                (page "1"))
  (path "/<power_uuid>"    (page "2"))
  (path "/<digital_uuid>"  (page "3")))
```
Each child `.kicad_sch` carries its own `(sheet_instances (path "/" (page "<n>")))` where `<n>` matches the parent's page number.

### Validation flow
Run `kicad-cli sch export svg --output <dir> <root>.kicad_sch` from the root — KiCad follows `Sheetfile` references and renders every page (one SVG per page). Common failures:
- Parent pin name ≠ child hierarchical-label name (typo, case).
- Direction mismatch — parent `input` vs child `output` of same name.
- `Sheetfile` path wrong or relative-path broken → "cannot open file".
- Child symbol instance path missing the `<child_sheet_uuid>` segment → symbol appears unannotated.
- Same refdes (`R1`) reused on two sheets → ERC duplicate-reference.

### Page breakdown — test1 (Bobcat carrier) reference

> **Project-specific.** This is the chosen split for the test1 Bobcat carrier board. The rules-of-thumb below are candidate generalizations — promote to a project-agnostic rubric once a second design has been broken up the same way.

| Page | File | Block | Notable nets exported |
|---|---|---|---|
| 1 (root) | `bobcat_carrier.kicad_sch` | Sheet blocks + title block; no parts | — |
| 2 | `fmc.kicad_sch` | VITA 57.1 LPC connector (160-pin), PRSNT/GA strapping, PG_C2M tie | `+3P3V` (global), `VADJ` (out), `SCL`/`SDA` (bidir), LA-bank signals |
| 3 | `power.kicad_sch` | TPS7A8401A LDO + ANY-OUT strap, VADJ load switch, EN pulldowns, output jumpers | `+VDDD`/`+VDDA1`/`+VDDA2`/`+VDDIO` (globals), `LDO_EN`/`LDO_PG`/`LSW_EN` (bidir) |
| 4 | `bobcat.kicad_sch` | Bobcat 40-QFN DUT, decoupling, VDDA1/VDDA2 series 0Ω, pull-up/down network, series 0Ω signal isolators | SPI bus, `RESET_N`, `GPIO0–3`, `SAMPLE_OUT*`, `CLK_OUT0–3`, `BIAS0/BIAS1`, `OSC_EN`/`WEIGHT_EN`/`SAMPLE_TRIG` |
| 5 | `eeprom.kicad_sch` | 8-Kbit I²C EEPROM, address straps, SCL/SDA pull-ups (shared with bias) | I²C bus only |
| 6 | `bias.kicad_sch` | MCP4728 DAC + OPA2388 + PMZ1200UPEYL PMOS + 5.11 kΩ sense, ×2 channels, optional DNP NMOS isolators | `BIAS0`/`BIAS1` (out) |
| 7 | `connectors.kicad_sch` | CLK_OUT0–3 SMAs, OSC_EN/WEIGHT_EN/SAMPLE_TRIG SMAs + 0Ω routing, GPIO0–3 header, GND clips | `CLK_OUT*` (in), `OSC_EN`/`WEIGHT_EN`/`SAMPLE_TRIG` (bidir), `GPIO0–3` (in) |

**Rules driving the split (candidate generalizations):**
- **One supply domain per page** when feasible — keeps decoupling-cap clusters local to the rail they serve. Power *generation* gets its own page.
- **The DUT gets its own page.** Never split a chip's decoupling, pull, or series-isolation network across pages.
- **Connector banks** (FMC, SMA arrays, breakout headers) get dedicated pages — many nets, few parts, would bloat any page they share.
- **Independent functional sub-blocks** (EEPROM, Bias) each get their own page even if small — they have a clean I²C-only (or other narrow) interface and are independently editable / removable.
- **Target 5–15 placed components per page.** Bobcat is the upper edge (~30 with passives); the root sits at 0.

**Globals stay global.** Power symbols (`+3P3V`, `+VDDIO`, `GND`, …) are inherently shared across all sheets by name — drop them where needed and do **not** export them as `(hierarchical_label …)`. Only non-supply nets crossing sheets need hierarchical pin/label pairs.

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
- `<project>.kicad_sch` (root schematic) plus one `<block>.kicad_sch` per child page for hierarchical designs
- SVG exports at `<project>/render/<page>.svg` — one per page — for visual sanity check before the user opens eeschema
- A brief summary of what's in the schematic (page breakdown, parts list, net topology, any non-obvious decisions)
