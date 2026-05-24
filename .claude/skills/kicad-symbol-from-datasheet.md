---
name: kicad-symbol-from-datasheet
description: Generate a KiCad .kicad_sym schematic symbol from a PDF datasheet, validate it with kicad-cli, and register it in the user's symbol library. Use when the user provides a datasheet PDF and asks for a schematic symbol, or asks to import a part into their KiCad library.
---

# Generate a KiCad symbol from a datasheet

## Inputs
- **Datasheet PDF** — read with the Read tool (`pages` param for >10-page docs)
- **Target package** — if multiple variants exist, pick the simplest (lowest pin count) unless the user specifies
- **Library path** — existing `.kicad_sym` to append to, or new file in the user's workspace

## Process
1. **Extract** from the datasheet: part number, manufacturer, short description, package + pin count, pin table (number / name / electrical type / description), datasheet URL.
2. **Write** a `.kicad_sym` file using the template below.
3. **Validate**: `kicad-cli sym upgrade --force <file>.kicad_sym`
   - Success: prints `"Saving symbol library in updated format"`
   - Failure: prints `"Unable to load library"` → fix syntax, retry.
4. **Register** in the user's sym-lib-table (see Registration). Quit eeschema first — it overwrites the table on shutdown.
5. **Relaunch** eeschema. The library appears in Symbol Editor → left tree.

## Pin angle convention (non-obvious — get this right)
Angle = direction the pin extends from its **outer** endpoint **toward the body**:
- Left-side pin (wire connects on the left): `angle 0` (pin extends right into body)
- Right-side pin: `angle 180`
- Top-side pin: `angle 270` (extends down into body)
- Bottom-side pin: `angle 90` (extends up into body)

Pin endpoint in `(at x y angle)` is the **wire-connection** point. Length extends inward from there.

## Layout heuristics
- **Passives** (R, C, L), **diodes**, **transistors**: use conventional shapes, not a box.
- **ICs / regulators / converters / op-amps**: rectangular body.
  - Power (VCC, VDD): top edge
  - Ground (GND, VSS): bottom edge
  - Inputs / enable / control: **left** side
  - Outputs / feedback / adjust: **right** side
- **LDOs specifically** (Altium-style): IN top-left, EN bottom-left, OUT top-right, ADJ/NC bottom-right, GND bottom-center.

### Geometry
- Grid: **2.54 mm** (100 mil). All pin endpoints land on multiples.
- Pin length: **2.54 mm**.
- Text size: **1.27 mm** for pin names, pin numbers, Reference, Value.
- Body width must fit the longest pin name + ≥2.54 mm clearance from opposite-side labels.
- Reference label: 1.27 mm above body top, centered horizontally.
- Value label: 1.27 mm below body bottom, centered.

### KiCad pin electrical type strings
Used in `(pin <type> line ...)`:
- `power_in` — VCC, VDD, GND on ICs
- `power_out` — regulator OUT, reference output
- `input` — control signals, enable, adjust, CS, MOSI
- `output` — device-driven signals
- `bidirectional` — GPIO, I²C SDA/SCL
- `passive` — resistor/capacitor/inductor terminals
- `no_connect` — explicit NC pins
- Rare: `open_collector`, `open_emitter`, `tri_state`, `free`, `unspecified`

## File template

```
(kicad_symbol_lib
	(version 20260508)
	(generator "kicad_symbol_editor")
	(generator_version "10.99")
	(symbol "PARTNUM"
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(in_pos_files yes)
		(duplicate_pin_numbers_are_jumpers no)
		(property "Reference" "U"
			(at 0 <body_top + 1.27> 0)
			(effects (font (size 1.27 1.27)))
		)
		(property "Value" "PARTNUM"
			(at 0 <body_bottom - 1.27> 0)
			(effects (font (size 1.27 1.27)))
		)
		(property "Footprint" "Library:Footprint_Name"
			(at 0 0 0) (hide yes)
			(effects (font (size 1.27 1.27)))
		)
		(property "Datasheet" "<url>"
			(at 0 0 0) (hide yes)
			(effects (font (size 1.27 1.27)))
		)
		(property "Description" "<one-line description>"
			(at 0 0 0) (hide yes)
			(effects (font (size 1.27 1.27)))
		)
		(property "Manufacturer" "<manufacturer>"
			(at 0 0 0) (hide yes)
			(effects (font (size 1.27 1.27)))
		)
		(property "ki_keywords" "<space-separated search keywords>"
			(at 0 0 0) (hide yes)
			(effects (font (size 1.27 1.27)))
		)
		(property "ki_fp_filters" "<footprint pattern, e.g. SOT?23*>"
			(at 0 0 0) (hide yes)
			(effects (font (size 1.27 1.27)))
		)
		(symbol "PARTNUM_1_0"
			(rectangle
				(start <x_left> <y_bottom>)
				(end <x_right> <y_top>)
				(stroke (width 0.254) (type solid))
				(fill (type background))
			)
			(pin <electrical_type> line
				(at <x_outer> <y> <angle>)
				(length 2.54)
				(name "PIN_NAME" (effects (font (size 1.27 1.27))))
				(number "1" (effects (font (size 1.27 1.27))))
			)
			... more pins ...
		)
		(embedded_fonts no)
	)
)
```

## Syntax gotchas

- **`(justify center)` is INVALID.** The token requires both axes: `(justify left top)`, `(justify right bottom)`. For centered text, **omit `(justify ...)` entirely** — center is the default.
- Pin numbers are **strings**: `(number "1" ...)`, not `(number 1 ...)`.
- Mandatory properties (Reference, Value, Footprint, Datasheet, Description) must exist even when blank: `(property "Datasheet" "" ...)`.
- `(hide yes)` on a property hides it from placed schematics. Symbol Editor still shows it in grey unless the user's view settings hide it (see below).

## Registration in sym-lib-table

macOS path: `~/Library/Preferences/kicad/<version>/sym-lib-table` (Linux: `~/.config/kicad/<version>/sym-lib-table`; Windows: `%APPDATA%/kicad/<version>/sym-lib-table`).

Append an entry — preserve existing entries:

```
(lib (name "PARTNUM") (type "KiCad") (uri "/absolute/path/to/PARTNUM.kicad_sym") (options "") (descr "<description>"))
```

**Quit eeschema first.** It rewrites the table on shutdown and can clobber the edit.

## Symbol Editor view cleanup (one-time, per user)

If labels look cluttered in the Symbol Editor, these three flags in `~/Library/Preferences/kicad/<version>/symbol_editor.json` control it. None of them affect the symbol when placed on a real schematic — they're editor-time only.

| Setting | Default | Set to `false` to hide |
|---|---|---|
| `show_pin_electrical_type` | true | Blue "Power Input" / "Output" overlay labels |
| `show_hidden_lib_pins` | true | Invisible pins |
| `show_hidden_lib_fields` | true | Grey property labels (Footprint, Datasheet, etc.) inside the body |

## Layout reference for a small IC

Concrete dimensions that worked well for a 5-pin SOT-23-class LDO:
- Body **15.24 mm wide × 8.89 mm tall**, centered roughly at the origin.
- Left-side pins at `angle 0`; right-side pins at `angle 180`; bottom (e.g. GND) at `angle 90`.
- Supply pins → `power_in` / `power_out`; logic-level inputs → `input`; ground → `power_in`.
- Width the body so the **longest pin name** (including any "/"-separated alt names like `NC/ADJ`) has at least ~1 character of clearance from the body edge. A body too narrow forces overlap; better to widen by another 2.54 mm than to truncate.
