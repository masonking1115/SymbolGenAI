---
name: altium-circuit-from-topology
description: Generate a complete Altium project (.PrjPcb + per-sheet .SchDoc) from a parts list and net topology — component placement, wires, ports, power ports, net labels — built with the test1/altium builder API (altium_monkey) and gated by the shared connectivity validator + layout linter. Use when the user asks for an application/example/typical circuit, a schematic from a BOM, or any chained circuit involving multiple ICs and passives.
---

# Generate an Altium schematic from a topology specification

Pairs with [[altium-symbol-from-datasheet]] — that skill makes a single `<MPN>.SchLib`; this one wires multiple symbols together into a working hierarchical project. The backend is pure-Python [`altium_monkey`](https://github.com/wavenumber-eng/altium_monkey) — no Altium install or scripting API is needed to *build*; Altium is only needed to *open* the result (see [[altium-launch-dev-build]]).

## Where this lives
The generator is `test1/altium/`. The canonical source of truth is `test1/netlist/*.yaml` (one per sheet); the builders consume it via the backend-neutral `gen/` core (`gen.netlist.load_netlist`, `gen.validator.validate`). Build everything from the repo root:

```powershell
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe -m test1.altium.build_project
```

This builds all child sheets, runs the validator + layout linter on each, builds the hierarchical root, and writes `test1/altium/out/test1.PrjPcb` + one `.SchDoc` per sheet. `out/` is generated — safe to delete and regenerate (gitignored).

## Inputs
- **Symbol library** — one `Parts Library/<MPN>/<MPN>.SchLib` per part (use [[altium-symbol-from-datasheet]] to make/import these). `build_symbols.get_library()` merges them into `out/lib/parts.SchLib`.
- **Netlist YAML** — `netlist/<sheet>.yaml`: parts (refdes, lib_id, value, units) and nets (named member-pin lists). This is the connectivity contract the validator enforces.
- **Power rails** — explicit names (`+3V3`, `VIN`, `GND`, `AGND`, …); rendered as power ports.
- **Off-sheet signals** — net names that cross sheets, carried by ports + the hierarchical root.

## Process
1. **Define the netlist first** in `netlist/<sheet>.yaml`. Every component pin belongs to exactly one net. The validator (`gen.validator.validate`) checks this geometrically against what you actually wire — a pin you forgot to route is an error, not a warning.
2. **Place from the netlist**, not by hand. In the sheet builder call `s.place_from_netlist(lib, libid_to_symbol, netlist, refdes, x, y, orientation, unit)`. It maps the part's `lib_id` to the authored SchLib symbol name and returns `{pin_designator: (x, y)}` in **logical coords** for that unit. Route wires to those returned coords — never to literals.
3. **Express coords RELATIVELY** off returned pin coords (`rail_y = pins["15"][1] - 550`), not absolute literals. Centering is applied as a build-time global offset (`set_build_offset`), and `place()` strips it back out of returned coords so pin-chaining stays correct — so relative routing cascades automatically when the sheet re-centers.
4. **Wire it**: `s.wire(x1,y1,x2,y2)`, `s.net_label(net,x,y)`, `s.port(name,x,y,io)`, `s.power_at(rail,x,y)`, `s.no_connect(x,y)`, `s.gnd_bus(pins, rail_x)` for a shared ground rail. Cosmetic notes via `s.text(body,x,y)`.
5. **Validate + lint**: `build_project` runs `gen.validator.validate` (connectivity gate — raises on disconnect/split) then `layout_lint.lint(s)` (geometry). A clean build prints `0/0/N` per sheet (E/W/I). ERROR fails the build; the cosmetic-note auto-fixer (`s.auto_fix_text()`) nudges overlapping `text` notes before the gate. See [[lint-autofix-and-generate-fix]].
6. **Lint-first iteration loop**: when a visual issue surfaces, FIRST add a `_check_*` to `layout_lint.py`, THEN fix the offending case. Every check that exists is one less round-trip. The current `RULES` registry (surfaced in the GUI Generator tab): `off_grid`, `diagonal_wire`, `out_of_bounds`, `component_overlap`, `power_orientation`, `visible_param_glob`, `wire_through_label`, `power_straddles_net`, `ground_on_top`, `power_stub_side`, `wire_through_body`, `pin_wire_crosses_body`, `off_center`, `cramped_spacing`, `decap_grouping`, `passive_declutter`, `label_overlap`, `label_over_symbol`, `label_symbol_clearance`, `wire_through_port`, `offpage_text`, `wire_overlap`, `stub_t_short`, `bridged_drop`, `duplicate_wire`, `redundant_junction`, plus the library-scope `pin_name_overlap`. **Do not weaken or fundamentally restructure the linter** — only add checks or refine a threshold with evidence.
7. **View** the result by opening `out/test1.PrjPcb` in real Altium (see [[altium-launch-dev-build]]), or rasterize a sheet with the dev-only `test1/altium/_render.py` (SVG→reportlab PDF→pymupdf PNG; cairo isn't available on this machine).

## Coordinate conventions (Altium)
- All coordinates in **mils**. **Y increases UP** (Altium native) — the opposite of KiCad. `units.py` has `mm_to_mil`, `snap`, `flip_y` if porting KiCad coords.
- **Grid: 100 mil.** Authored symbol pins (`author_symbol.PITCH = 200`, `PIN_LEN = 200`) land on 100-mil; route on 100-mil. `off_grid` is a lint ERROR.
- A placed component's `location_mils` is its origin; pins come back live from `place()` (via `pin.get_hot_spot()`). **Moving a component's location does NOT move its baked pins** — so there is no post-hoc origin normalization; re-center via a build-time offset re-run (`_build_centered`), not by translating placed parts.

## Layout rules (geometry the linter enforces — match these or add a check)
- **Orthogonal wires only.** `diagonal_wire` is a lint ERROR.
- **Wires exit on the side the pin protrudes from**, extending AWAY from the body. `place()` returns the hot-spot (connection point); extend with the sign that points away. Single-edge parts (FMC/SMA/headers) are the easy case to get wrong because the hot-spot x ≠ the body x.
- **No silent shorts.** Two collinear wires sharing an x-range (same y) or y-range (same x) merge into one net — `wire_overlap` flags this. When tapping a rail, end the new wire ON the rail's interior; don't redraw the rail segment. Give each pin in a parallel pull/fanout its OWN drop column. The connectivity validator does NOT catch geometric merges — the linter does.
- **No net through a component body.** `wire_through_body` flags a wire crossing a part's pin-box without ending on / passing through one of its pins (the pin-pass exclusion permits decoupling-cap-on-rail).
- **No wire reaching a pin THROUGH its own symbol body.** `pin_wire_crosses_body` flags a wire that terminates on a part's own pin but gets there by crossing the part's drawn body (e.g. a gate-drive wire cutting across a MOSFET glyph to a gate pin on the far side). `wire_through_body` deliberately allows a wire ending on the part's pin; this catches the narrower "connected through the symbol" case. Approach a pin from OUTSIDE the body — re-orient the part so the pin faces its driver, or route up/over and drop onto the pin from the side it protrudes. Measured against `graphic_box` inset by `_BODY_CROSS_INSET` (a wire grazing the outline to reach an edge pin is fine).
- **Ports/power terminate wires, don't ride mid-wire.** `wire_through_label` flags a port/power symbol sitting in a wire's interior (net labels are exempt — they legitimately ride a wire).
- **Power-port orientation is rail-driven.** `power_at` defaults GND-family (name contains "GND") to point DOWN (270°), supply rails UP (90°). `_check_power_orientation` enforces it. NOTE: altium_monkey's SVG renderer ignores power-port orientation (the GUI preview won't show rotation) but the binary stores it correctly, so real Altium renders it right.
- **Power glyph terminates a stub on the OFF-net side.** `ground_on_top` flags a GND whose wires all drop downward (it sits above its net); `power_stub_side` is the rail mirror — a supply-rail up-arrow whose net continues ABOVE the glyph (it points up INTO its net instead of capping it from the top). Both are auto-corrected post-build by `shared.auto_fix_power_stub_side` (relocates the glyph to a clear stub that points off the net) and by `auto_fix_power` (the both-sides straddle, `power_straddles_net`). In the builder, route a rail's stub so the arrow sits at the TOP (net below) and a GND so the bar sits at the BOTTOM (net above).
- **Stay centered + in-bounds.** `off_center` (content-bbox center >18% off page center) and `out_of_bounds` (content outside the page frame). Centering is the build-time offset, not per-part moves.
- **Spacing.** `cramped_spacing` flags two non-power parts <200 mil apart (not overlapping); `component_overlap` flags actual overlaps.
- **Group + space decoupling banks.** `decap_grouping` flags same-rail decoupling cells (a 2-pin passive whose BOTH ends land on power symbols — e.g. cap between +3V3 and GND) that cluster in one area but are scattered instead of aligned into a neat row/column; place them in an aligned bank at a uniform pitch (they connect by net name, so they move freely). `passive_declutter` flags two aligned passives packed tighter than a readable pitch (300 mil center-to-center). Bus a cluster of same-net power pins/pull-downs to ONE shared rail + ONE power symbol (`gnd_bus` for GND, or a hand-built collector) rather than giving each its own glyph — four GND glyphs stepped down in a staircase read as messy and adjacent ones collide (`label_overlap`).
- **Labels/ports must not bump symbols.** `label_over_symbol` flags a port/value/text box that OVERLAPS a component body; `label_symbol_clearance` flags a port or text note sitting <50 mil of TRUE clear space from a body (a part's own value and aligned passive value labels — e.g. 0Ω jumper banks — are exempt). Both measure against the **true drawn body** (`PlacedPart.graphic_box` from altium_monkey's `full_bounds_mils()`), NOT the pin column — single-column parts (FMC/SMA/headers) have a body rectangle offset to one side of their pins, so a pin-only box understates the width and misses a port landing on the connector. When placing a port near a single-column connector, leave clearance to the drawn body edge, not the pin x.
- **Text must stay on the page, accounting for the frame.** `offpage_text` flags any label/value/note/body box outside the sheet's USABLE area — the region inside Altium's border + reference-zone margin (`_PAPER_MARGIN`), not the raw page rectangle. A port body whose name text reaches the frame edge is flagged even if it's "within the page."

## Hierarchical (multi-sheet) designs
The design is hierarchical: a root sheet embeds one child `.SchDoc` per functional block. `build_root.py` emits the root via `s.sheet_symbol(child_name, title, x, y, ...)`; `build_all.py` holds the `BUILDERS` list; `build_project.py` ties root + children into `test1.PrjPcb`.

- **Cross-sheet nets ride ports** on each child sheet (`s.port(name, x, y, io)`), resolved into a single net when Altium compiles the `.PrjPcb`. Caveat: altium_monkey's single-sheet `to_netlist` does NOT propagate signal-port names as net names (power ports do) — real Altium names them on project compile, so cross-sheet connectivity is verified by opening the `.PrjPcb`, not by the single-sheet netlister.
- **Power ports are inherently global** — drop them where needed; don't also export them as cross-sheet ports.
- **One block per sheet builder** (`build_<sheet>.py`), each reusing the netlist loader + validator and routing from hot-spots.

### Sheet breakdown — test1 (Bobcat carrier) reference
> Project-specific. Candidate generalizations follow.

| Sheet | File | Block | Paper |
|---|---|---|---|
| eeprom | `build_eeprom.py` | 24AA08 I²C EEPROM | A4 |
| connectors | `build_connectors.py` | CLK/OSC/GPIO SMAs + header | A2 |
| power | `build_power.py` | TPS7A8401A LDO + jumpers + TPS22916 load switch | A3 |
| bias | `build_bias.py` | MCP4728 DAC + OPA2388 + PMOS + sense + NMOS isolation | A2 |
| fmc | `build_fmc.py` | VITA 57.1 LPC 160-pin connector | A3 |
| bobcat | `build_bobcat.py` | Bobcat QFN DUT + decoupling/pulls | A2 |
| root | `build_root.py` | sheet symbols only, no parts | A3 |

**Rules driving the split (candidate generalizations):** one supply domain per page; the DUT gets its own page (never split its decoupling/pull network); connector banks get dedicated pages; independent sub-blocks (EEPROM, Bias) each get a page even if small; target 5–15 placed parts per page.

### Sheet template (A4-preferred auto-fit) + real Altium frame sizes
`AltiumSheet` defaults to **A4** and auto-upgrades to the smallest A-series size that contains the layout (`_fit_paper`). A sheet can also declare its paper explicitly (`paper="A2"`) when content is known to need it. **`_PAPER_MIL` holds Altium's REAL drawable frame sizes** (A3 = 15500×11100, *not* ISO 216's 16535×11690 — Altium sheet styles are ~1000 mil smaller), and `_PAPER_MARGIN` is the border/reference-zone band each side. `out_of_bounds` (content past the frame) is an ERROR; `offpage_text` checks the usable area *inside* the margin. Don't size content against ISO dimensions — a layout that fits ISO A3 can still overflow Altium's A3 frame.

## Builder API quick reference (`test1/altium/shared.py`)
```python
s = AltiumSheet(name="power", paper="A4")          # auto-upgrades paper to fit
pins = s.place_from_netlist(lib, libid_to_symbol, netlist, "U10", x, y, orientation=0, unit=1)
pins = s.place(lib, symbol_name, "R1", "10k", x, y, orientation=0, unit=1)   # direct place
pins = s.pins_of("U10", unit=1)                    # re-fetch an earlier part's pins (logical coords)
s.wire(x1, y1, x2, y2)
s.junction(x, y)                                   # cosmetic only — Altium drops bare junctions; rely on T-intersections
s.net_label("SCL", x, y)
s.port("VADJ", x, y, io=PortIOType.OUTPUT)
s.power_at("+3V3", x, y)                            # orientation auto by rail
s.no_connect(x, y)
s.text("note", x, y)                               # cosmetic; auto_fix_text may nudge it
s.gnd_bus([(x1,y1),(x2,y2)], rail_x)               # tie a GND cluster to one rail + symbol
s.sheet_symbol("power", "Power", x, y, ...)        # root only
s.save(path); s.render_svg(path)
```

## Known limitations
- **Junctions are cosmetic** — altium_monkey can't emit a junction real Altium keeps; connectivity rides T-intersections (Altium auto-junctions). Forbid 4-way crossings. See `test1/altium/verify/FINDINGS.md`.
- **Signal-port net names** don't propagate in single-sheet `to_netlist`; verified on `.PrjPcb` compile.
- **SVG preview ignores power-port orientation** (binary/real-Altium is correct).

## Output to deliver
- `out/test1.PrjPcb` + one `<sheet>.SchDoc` per page + the root `.SchDoc`.
- `out/lib/parts.SchLib` (merged symbol library).
- The per-sheet build table (paper + `E/W/I` lint counts + OK/FAIL).
- A brief summary: sheet breakdown, parts, net topology, any non-obvious decisions.
