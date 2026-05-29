# test1/altium — Altium backend

The generator backend, built on
[`altium_monkey`](https://github.com/wavenumber-eng/altium_monkey) (pure-Python
read/write of Altium binary files — no Altium install or scripting API needed to
build). The full test1 design is ported and builds clean.

**Strategy:** `netlist/*.yaml` is the canonical source of truth; this package is
the Altium backend that consumes it. It reuses the backend-agnostic `gen/`
core (`gen.netlist` loader, `gen.validator` connectivity check) unchanged.

> Historical: this replaced an earlier KiCad backend (now removed). The table
> below maps the old KiCad seam to its Altium equivalent — useful when reading
> old commits or porting another KiCad design, not a description of pending work.

## Seam mapping (former KiCad → current Altium)

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
- `shared.py` — `AltiumSheet`: primitives + `gnd_bus` + validator-facing records (`_wires`/`_junctions`/`_placed`/`_labels`); `_PAPER_MIL` (real Altium frame sizes) + `_PAPER_MARGIN`.
- `build_<sheet>.py` — per-sheet builders (eeprom, connectors, power, bias, fmc, bobcat); `build_root.py` emits the hierarchical root; `build_all.py` / `build_project.py` orchestrate.
- `layout_lint.py` — geometric gate (RULES registry; library-scope `lint_library`).
- `author_symbol.py` / `symlib.py` / `build_symbols.py` — author `.SchLib` from a pin-spec, read pins, merge the library.
- `verify/` — real-Altium oracle (`run_altium_verify.py`) + junction repro + FINDINGS.md.

## Reuse, not reimplementation
The Altium backend **imports the backend-neutral** `gen/netlist.py` (YAML loader)
and `gen/validator.py` (strict connectivity check) unchanged — the part of `gen/`
that survived the KiCad-backend removal. The validator is coordinate-based and
backend-agnostic: `AltiumSheet` exposes the same duck-typed records (`_wires`,
`_junctions`, `_placed`, `_labels`) the validator reads, so the *same* validator
that gated the old KiCad output now gates Altium == true functional parity.
(Needs `pyyaml` in the spike venv.)

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
| fmc | 32 | 62 | A3 | ✓ | ✓ (all counts match) |
| bobcat | 25 | 35 | A2 | ✓ | ✓ (all counts match) |

Verified three ways: (1) reused `gen.validator` connectivity check; (2)
`to_netlist()` pin groupings match the YAML; (3) real-Altium oracle opens the
file uncorrupted with matching object counts.

### Sheet template (A4-preferred auto-fit, real Altium frame sizes)
`AltiumSheet` defaults to **A4** and auto-upgrades to the smallest A-series size
that contains the layout (`_fit_paper`); a sheet may also declare its paper
explicitly when content is known to need it. `_PAPER_MIL` holds Altium's **real
drawable frame sizes** (A3 = 15500×11100, *not* ISO 216's 16535×11690 — Altium
sheet styles run ~1000 mil smaller), and `_PAPER_MARGIN` is the border/
reference-zone band; the linter's `offpage_text` checks the usable area inside
that margin, so content is sized to Altium's frame, not ISO. Nothing overflows
its frame (`out_of_bounds` ERROR).

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
# from the repo root (SymbolGenAI/) — builds + validates + lints all sheets
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe -m test1.altium.build_project
```

To open / preview / fidelity-verify in real Altium AD26 (installed on this
Windows machine), see the `altium-launch-and-verify` skill.

## Verification status

The full design builds clean (all 6 sheets `0/0/0` E/W/I, `FAILURES: none`),
verified three ways: (1) the reused `gen.validator` connectivity gate; (2)
`to_netlist()` pin groupings match the YAML; (3) the **real-Altium oracle**
(`verify/run_altium_verify.py`) opens the files in AD26 and confirms they are
**uncorrupted**, agreeing on every object type except junctions (which Altium
drops by design — see `verify/FINDINGS.md`; connectivity rides T-intersections).

`out/` is generated — safe to delete and regenerate; should be gitignored.
