---
name: altium-symbol-from-datasheet
description: Create an Altium .SchLib schematic symbol for a part — either by authoring one from a datasheet PDF via a JSON pin-spec (test1.altium.author_symbol), or by downloading the real symbol+footprint from Ultra Librarian. Validates with altium_monkey + the library linter and installs it at Parts Library/<MPN>/<MPN>.SchLib. Use when the user provides a datasheet and asks for a schematic symbol, or asks to import a part into the Altium library.
---

# Create an Altium symbol for a part

The library is per-MPN and self-contained: `Parts Library/<MPN>/<MPN>.SchLib` (the symbol, named after the MPN), plus optionally `<MPN>.PcbLib` (footprint) and `<MPN>.pdf` (datasheet). The generator merges every `<MPN>.SchLib` into `out/lib/parts.SchLib` at build time. No KiCad anywhere in the loop.

There are **two routes**. Prefer Ultra Librarian for catalog parts (real, vendor-accurate geometry + footprint); author from a pin-spec for custom/DUT parts or when UL has no entry.

---

## Route A — Ultra Librarian (catalog parts)

UL has real symbols + footprints for almost every catalog MPN. Provide the user the exact per-MPN search link (UL is auth-gated + JS-driven, so it can't be fetched programmatically — the user downloads the zip):

```
https://app.ultralibrarian.com/search?queryText=<MPN>
```

UL stores ICs under the **orderable variant**, not the bare family name (e.g. `TPS7A8401A` → `TPS7A8401ARGRR`, `MCP4728` → `MCP4728-E/UN`, `OPA2388` → `OPA2388IDR`). The deep-link search resolves these.

**Install flow** (the user drops the UL zip; Claude extracts):
1. User downloads the UL zip and drops it at a scratch folder.
2. Extract: a UL zip contains `<timestamp>.SchLib` + `footprints`/`.PcbLib` + boilerplate (`readme.txt`, `ImportGuides.html`). **No 3D STEP** unless separately selected.
3. Install into `Parts Library/<MPN>/<MPN>.SchLib` (back up any existing → `<MPN>.SchLib.bak`) and `<MPN>.PcbLib`.
4. **Verify it's the right part** — UL serves multiple manufacturer entries for generic MPNs and the symbol can be wrong. Check the internal symbol name resolves plausibly: `AltiumSchLib(path).get_symbol_names()`. (A 2N7002 UL download once turned out to be a SOT-23 *diode*, `Diode-NC_pin`, not the MOSFET — coverage passed only because pin numbers 1/2/3 existed. See [[ul-symbol-import]].)
5. **UL symbols rearrange pins** vs an authored part, and the builders route from live pin coords — so swapping a symbol with a different pin arrangement breaks that sheet's routing. After installing, regenerate and re-route any sheet that places the swapped part.

The UL symbol's internal name is the orderable part, not the MPN — `symlib.symbol_name(mpn)` resolves the actual name and `build_symbols.symbol_name_for` uses it, so the merged library and placement stay correct without renaming (renaming via altium_monkey `to_json`/`from_json` is lossy for pins — resolve names at read time instead).

---

## Route B — Author from a datasheet (custom parts, no UL entry)

An AI (or human) describes the pins in a small reviewable JSON pin-spec; `author_symbol` lays them out on a clean 100-mil grid and writes the committed `.SchLib`.

### Process
1. **Extract from the datasheet** (Read the PDF; use `pages` for >10-page docs): MPN, manufacturer, short description, package + pin count, the pin table (number / name / electrical type / side), datasheet URL.
2. **Write** `Parts Library/<MPN>/<MPN>.pinspec.json` (schema below).
3. **Author**: `python -m test1.altium.author_symbol <MPN>` (with the spike-venv interpreter). It reads the pin-spec and writes `<MPN>.SchLib`.
4. **Validate**: `symlib.read_pins(mpn)` round-trips the geometry; `layout_lint.lint_library(schlib_path(mpn))` checks pin-name fit (`pin_name_overlap`). `build_project` runs `lint_library` as a gate and prints `symbol library: clean`.
5. **Rebuild** the design — `build_symbols` re-merges when any source `.SchLib` mtime is newer than `out/lib/parts.SchLib`.

### Pin-spec schema (`<MPN>.pinspec.json`)
```json
{
  "mpn": "TPS7A8401A",
  "description": "150 mA LDO",
  "reference": "U",
  "properties": {
    "Value": "TPS7A8401ARGRR",
    "Footprint": "RGR0020A",
    "Datasheet": "https://www.ti.com/lit/gpn/tps7a84a",
    "Manufacturer": "Texas Instruments",
    "MPN": "TPS7A8401ARGRR"
  },
  "units": [
    {"unit": 1, "pins": [
      {"number": "1", "name": "IN",  "type": "power_in", "side": "left"},
      {"number": "5", "name": "OUT", "type": "output",   "side": "right"}
    ]}
  ]
}
```
- A single-unit part may omit `units` and give a top-level `pins` list. Multi-unit parts (op-amps, multi-bank connectors) declare one entry per unit.
- `properties` become **hidden** Altium component parameters (metadata lives in the Properties dialog); the value is shown as the component Comment at build time. Don't make params visible — the linter flags a `visible_param_glob`.

### Pin `type` (KiCad-style names → nearest Altium PinElectrical)
`input` · `output` · `bidirectional`/`io` · `passive` · `power_in`/`power_out`/`power` · `tri_state`/`hiz` · `open_collector` · `open_emitter` · `no_connect` (→ passive). Use `power_in` for VCC/VDD/GND on ICs, `power_out` for regulator OUT/reference, `input` for enable/adjust/CS/MOSI, `bidirectional` for GPIO/I²C SDA-SCL, `passive` for R/C/L terminals.

### `side` and body glyph
`side` ∈ `left | right | top | bottom` — which body edge the pin sits on. Conventions: power top, ground bottom, inputs/control left, outputs/feedback right.

`author_symbol` draws a **conventional device glyph** instead of a plain rectangle, inferred by `glyphs.classify(prefix, names, n_pins, n_units)`:
- `C` → capacitor plates · `R` → resistor zig-zag · `L` → inductor arcs · `D` → diode triangle
- 3 pins named G/D/S (or `Q` prefix) → MOSFET
- 2 inputs named +/− → op-amp triangle
- everything else → rectangle (ICs)

Body width auto-sizes to the longest pin name via `units.min_half_x_for_names` (`altium_text_metrics.measure_text_width`) so left+right names don't collide — a narrow IC body overlapping long names (`SER_DATA_I/O` over `VSS`) is the classic cramped symbol.

---

## Installing via the GUI Library tab
The GUI supports uploading a `.SchLib` directly: `POST /api/library/{mpn}/symbol` (validates via `AltiumSchLib.get_symbol_names`, writes `Parts Library/<MPN>/<MPN>.SchLib`, old → `.bak`). The Library tab also surfaces the Ultra Librarian deep-link and renders the symbol SVG (`symlib.symbol_summary` + `AltiumSchLib.symbol_to_svg`, multi-unit aware). See [[gui-altium-backend]].

## Gotchas
- **altium_monkey serializes params/designator/description only on FRESH-authored symbols** — in-place edits to a loaded binary don't round-trip. To change properties, re-author from the pin-spec (or re-read geometry and re-author identically).
- **`to_json`/`from_json` is lossy for pins** (separate OLE streams) — never rename a symbol that way; resolve the real symbol name at read time (`symlib.symbol_name`).
- **Verify the part identity after any UL download** — wrong-manufacturer entries pass a pin-number coverage check while being the wrong device.

## Output to deliver
- `Parts Library/<MPN>/<MPN>.SchLib` (+ `.PcbLib` if from UL, + `.pdf`/`.pinspec.json`).
- Confirmation the symbol validates (`read_pins` round-trip + `lint_library` clean) and that a regenerate picks it up.
