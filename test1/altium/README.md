# test1/altium — Altium backend (Gate 0)

Migration of the KiCad generator's backend to **Altium**, via
[`altium_monkey`](https://github.com/wavenumber-eng/altium_monkey) (pure-Python
read/write of Altium binary files — no Altium install or scripting API needed).

**Strategy:** `netlist/*.yaml` stays the canonical source of truth; only the
backend swaps. This package mirrors `gen/` module-for-module.

## Seam mapping (KiCad → Altium)

| KiCad (`gen/`) | Altium (`altium/`) | altium_monkey API |
|---|---|---|
| `Sheet` (s-expr text) | `AltiumSheet` | `AltiumSchDoc` + `add_object` |
| `wire/junction/label` | same verbs | `make_sch_wire/_junction/_net_label` |
| `hier_label`/`global_label` | `port` | `make_sch_port` |
| `power_at` | `power_at` | `make_sch_power_port` (+ glyph style) |
| `no_connect` | `no_connect` | `make_sch_no_erc` |
| `text` | `text` | `make_sch_text_string` |
| `place` → pin world coords | `place` | `add_component_from_library` → `pin.get_hot_spot()` |
| `parse_pins`/`pin_world` (`symbols.py`) | **collapses** | pins come back live from the placed component |
| `.kicad_sym` authoring | `symbols.author_passive_lib` | `AltiumSchLib` + `make_sch_pin` |
| `.pretty` footprints | `footprints.author_footprint_lib` | `AltiumPcbLib` + `add_pad` |
| `kicad-cli sch export svg` (parse gate) | `AltiumSheet.render_svg` | `AltiumSchDoc.to_svg()` |
| coords in mm, 50-grid | mils, 100-mil grid | `units.py` (`mm_to_mil`, `snap`, `flip_y`) |

## Files
- `units.py` — mm↔mil, grid snap, Y-axis flip (KiCad Y-down → Altium Y-up).
- `config.py` — paths, fonts, rail→power-glyph map.
- `symbols.py` — author `.SchLib` (passives + 24AA08); lib_id→symbol map; read placed pin hot-spots.
- `footprints.py` — author `.PcbLib` footprints.
- `shared.py` — `AltiumSheet`: primitives + `gnd_bus` + validator-facing records (`_wires`/`_junctions`/`_placed`/`_labels`).
- `build_eeprom.py` — first real sheet port (24AA08 I²C EEPROM).
- `smoke_test.py` — Gate 0 driver.
- `verify/` — Tier 1 real-Altium oracle (`run_altium_verify.py`) + junction repro + FINDINGS.md.

## Reuse, not reimplementation
The Altium backend **imports the KiCad** `gen/netlist.py` (YAML loader) and
`gen/validator.py` (strict connectivity check) unchanged. The validator is
coordinate-based and backend-agnostic — `AltiumSheet` exposes the same
duck-typed records (`_wires`, `_junctions`, `_placed`, `_labels`), so the
*identical* validator gates both backends == true functional parity. (Needs
`pip install pyyaml` in the spike venv.)

## Full design port

The entire test1 design is ported. Build everything + emit the project:

```powershell
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe -m test1.altium.build_project
```

This validates all 6 child sheets (reused `gen.validator`), builds the root,
and writes `out/test1.PrjPcb` referencing root + children.

### Symbol library — native Altium `.SchLib`
The source of truth is per-MPN `Parts Library/<MPN>/<MPN>.SchLib` (committed,
the symbol named after the MPN), either downloaded from Ultra Librarian or
authored from a JSON pin-spec via `author_symbol.py` (`python -m
test1.altium.author_symbol <MPN>`). `build_symbols.py` MERGES the per-MPN
`.SchLib` (+ stock R/C passives) into `out/lib/parts.SchLib` via
`AltiumSchLib.merge`, rebuilding only when a source `.SchLib` is newer than the
merged file; it resolves each symbol's real internal name via `symlib.symbol_name`
(UL names parts after the orderable variant, not the MPN) and `verify_coverage()`
checks every netlist part + net-member pin. Pins come back live from the placed
component's hot-spots, so exact symbol coords don't matter — builders route from
hot-spots. (The original KiCad `.kicad_sym` → SchLib `translate.py` and the
`_archive_kicad/` source were removed once the library went Altium-native.)

### Per-sheet builders (`build_<sheet>.py`)
Each reuses the netlist loader + validator, and
routes from pin hot-spots. `build_all.py` builds them all; `build_root.py`
emits the hierarchical root; `build_project.py` ties it together.

| Sheet | Parts | Nets | Paper | Validator | Altium oracle |
|---|---|---|---|---|---|
| eeprom | 4 | 4 | A4 | ✓ | ✓ |
| connectors | 14 | 12 | A2 | ✓ | — |
| power | 17 | 19 | A3 | ✓ | — |
| bias | 16 | 16 | A2 | ✓ | — |
| fmc | 32 | 62 | A0 | ✓ | ✓ (all counts match) |
| bobcat | 25 | 35 | A3 | ✓ | ✓ (all counts match) |

Verified three ways: (1) reused `gen.validator` connectivity check; (2)
`to_netlist()` pin groupings match the YAML; (3) real-Altium oracle opens the
file uncorrupted with matching object counts.

### Sheet template (A4-preferred auto-fit)
`AltiumSheet` defaults to **A4** and auto-upgrades to the smallest A-series size
that contains the layout (`_fit_paper`), so simple sheets stay A4 and dense ones
grow. A real carrier board with a 160-pin FMC connector can't all fit A4 (KiCad
used A3 per sheet too); nothing overflows its frame.

### Known limitations
- Signal **Port** names don't propagate as net names in altium_monkey's
  single-sheet `to_netlist` (power ports do); real Altium resolves them on
  project compile. Cross-sheet net connectivity rides the root sheet entries.
- Junctions are cosmetic (Altium drops altium_monkey junction records — see
  FINDINGS.md); connectivity rides T-intersections.
- Sheet sizes are larger than minimal because the per-sheet auto-layouts place
  content off-origin; component pins don't move with a component, so post-hoc
  origin-normalization isn't safe. Tightening is a per-sheet layout follow-up.

## Running

Needs Python 3.11–3.12 and `altium-monkey`. Isolated spike venv lives at
`C:\Users\mking\Downloads\altium_spike\.venv` (outside this repo).

```powershell
# from the repo root (SymbolGenAI/)
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe -m test1.altium.smoke_test
```

## Gate 0 status

In-process steps **PASS**: authors `.SchLib`+`.PcbLib`, builds `out/smoke.SchDoc`
exercising every primitive, round-trips it (2 components / 5 wires / 1 net
label / 2 power ports / 1 port survive reopen), renders `out/render/smoke.svg`
(non-empty geometry).

**Remaining manual gate:** open `out/smoke.SchDoc` in **real Altium** on this
Windows machine and confirm it is uncorrupted. That is the one fidelity check
the library cannot self-verify (binary format is reverse-engineered).

`out/` is generated — safe to delete and regenerate; should be gitignored.
