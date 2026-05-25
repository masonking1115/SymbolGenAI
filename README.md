# Symbol Library AI

AI-assisted EDA tooling. Inputs: part datasheets + freeform design requirements. Outputs: validated KiCad symbol libraries (`.kicad_sym`) and complete application schematics (`.kicad_sch`) that open in eeschema.

Long-term direction: a chunked design pipeline (`spec → part fingerprints → nets → BOM → schematic`) with a Python/ngspice simulation feedback loop, and integration into the user's existing platform with its own chat front end.

See [PROJECT_MEMORY.md](PROJECT_MEMORY.md) for the full handoff doc (architecture, skills, running eeschema, current state).

## Repo layout

```
.claude/skills/        per-stage skill docs (symbol gen, circuit gen, KiCad launch)
test1/                 active project — Bobcat carrier-board parts library
PROJECT_MEMORY.md      project memory + handoff
README.md
```

## Per-project convention — strict isolation

Every design is its own self-contained folder. Two projects that use the same MPN each carry their own copy of the symbol and datasheet — no cross-contamination of data between projects.

```
<project>/
   design_requirements.md               REQUIRED — application, specs, parts list, notes
   <project>.kicad_pro
   <project>.kicad_sch                  schematic — embeds lib_symbols self-contained
   datasheets/<MPN>/
      <MPN>.kicad_sym                   parts used in this project only
      <MPN>.pdf                         source datasheet (optional)
   generate.py                          Python generator (optional)
```

`design_requirements.md` is the source of truth for what is being designed and why; read it first when entering a project. See PROJECT_MEMORY.md for the suggested section structure. Add more files (e.g. `nets.yaml`, `bom.yaml`, `sim/`) as a project evolves — always inside the per-project folder.

Do not create a shared `datasheets/` at the repo root. The duplication is intentional: each project folder is a complete, transportable unit, and editing one project's symbols cannot silently affect another.

## Running a generated schematic in eeschema

This machine uses a partial KiCad dev build at `~/Downloads/kicad/`. See [`.claude/skills/kicad-launch-dev-build.md`](.claude/skills/kicad-launch-dev-build.md) for the working binary paths and the kiface/resource symlinks.

On a fresh machine, `brew install kicad` and open the schematic directly:

```sh
open -a KiCad <project>/<project>.kicad_pro
```

Schematics generated through the skills embed their `lib_symbols` self-contained, so they render without registering the `.kicad_sym` files in the user-level `sym-lib-table`.

## Editing in eeschema

Two workflow rules to make edits durable and avoid the "false save" trap. Full rationale in [PROJECT_MEMORY.md](PROJECT_MEMORY.md).

1. **Symbol-shape edits only go through the Symbol Editor on the canonical `<project>/datasheets/<MPN>/<MPN>.kicad_sym`.** Never use right-click → Edit Symbol on a placed instance — that writes only to the schematic's embedded copy and is overwritten by the next `generate.py` run. After editing the canonical file, run **Tools → Update Symbols from Library** in eeschema to refresh.
2. **End every editing session with `git add && git commit && git push`.** Cmd+S writes to disk; only a commit reaches GitHub. Schematic placement, wires, refdes, and values can be edited freely in eeschema — just commit when done.

## Skills

- [`kicad-symbol-from-datasheet`](.claude/skills/kicad-symbol-from-datasheet.md) — generate a `.kicad_sym` from a PDF datasheet.
- [`kicad-circuit-from-topology`](.claude/skills/kicad-circuit-from-topology.md) — build a full schematic from a parts list + net topology, with layout rules to avoid text overlap and floating nets.
- [`kicad-launch-dev-build`](.claude/skills/kicad-launch-dev-build.md) — open schematics in eeschema and run `kicad-cli` on this machine's specific dev build.

## Schematic generation pipeline (test1 reference)

The active reference project, [`test1/`](test1/), implements the end-to-end pipeline below. Read each stage's named module for the actual contract.

```
                        ┌─────────────────────────────────────┐
  design_requirements   │ test1/design_requirements.md        │
  ─────────────────────►│   (manual: application, specs, BOM) │
                        └─────────────────────────────────────┘
                                         │
                                         ▼
  parts (per-MPN)       ┌─────────────────────────────────────┐
  ─────────────────────►│ test1/Parts Library/<MPN>/          │
   kicad-symbol-        │   <MPN>.kicad_sym + .pdf            │
   from-datasheet skill │   (one folder per MPN — strict)     │
                        └─────────────────────────────────────┘
                                         │
                                         ▼
  netlist (per-sheet)   ┌─────────────────────────────────────┐
  ─────────────────────►│ test1/netlist/<sheet>.yaml          │
   (manual: nets +      │   parts: {refdes: {lib_id, value}}  │
    members per net)    │   nets:  {name: [Rx.1, Uy.5, ...]}  │
                        └─────────────────────────────────────┘
                                         │
                                         ▼
  layout (per-sheet)    ┌─────────────────────────────────────┐
  ─────────────────────►│ test1/gen/build_<sheet>.py          │
   (Python, relative    │   place(U1, x, y) → returns pin map │
    to chip pins)       │   wire(...) / junction(...) /       │
                        │   power_at(...) / hier_label(...)   │
                        │  + gen/shared.py (Sheet, primitives)│
                        └─────────────────────────────────────┘
                                         │
                                         ▼
  generator             ┌─────────────────────────────────────┐
  ─────────────────────►│ test1/gen_schematic.py              │
   (orchestrator)       │   per sheet:                        │
                        │     • emit .kicad_sch               │
                        │     • strict net validator          │
                        │     • layout lint                   │
                        │     • kicad-cli sch export png      │
                        │   → kicad/<sheet>.kicad_sch         │
                        │   → kicad/render/<sheet>.png        │
                        └─────────────────────────────────────┘
                                         │
                       ┌─────────────────┴────────────────┐
                       ▼                                  ▼
              ┌─────────────────┐               ┌──────────────────┐
              │ visual review   │               │ open in eeschema │
              │ (Read PNG —     │               │ for final user   │
              │  catches what   │               │ sign-off         │
              │  lint misses)   │               └──────────────────┘
              └─────────────────┘
```

### Gate semantics

The orchestrator runs three gates per sheet, in order:

1. **Strict net validator** ([`test1/gen/validator.py`](test1/gen/validator.py)) — every YAML-declared net member must be in a connected component named that net. Raises `ValidationError` on failure. This is the hard correctness gate; build fails if any sheet doesn't pass.
2. **Layout linter** ([`test1/gen/layout_lint.py`](test1/gen/layout_lint.py)) — advisory geometric checks for visual issues the validator can't catch (silent shorts via parallel-range wire overlap, label-on-wire-interior, label crowding components, wires crossing label text, …). Severity is `ERROR / WARNING / INFO`; reported but does not fail the build. The current full check set:
   - `diagonal_wires`, `bbox_overlap_and_spacing`, `wire_through_body`, `wire_into_body`, `bridged_drop_column`, `wire_overlap`, `label_on_body`, `refval_on_body`, `vertical_label`, `wire_through_label`, `wire_crosses_label_text`, `label_overlap_part`, `dense_gnd_cluster`, `duplicate_wires`, `redundant_junctions`.
3. **Parse + render** (`kicad-cli sch export png`) — emits `kicad/render/<sheet>.png` and surfaces any s-expr parse failure as exit-code-3 `"Failed to load schematic"`.

### Coordinate convention

All coordinates inside a build module are **chip-pin-relative**, not absolute. The only true anchor is each IC's `place_from_netlist(x, y)` call. Every downstream rail / column / label anchor is expressed as `U1["<pin>"][offset_axis] ± delta`. This keeps origin snaps cascade-free: shifting U1 by 0.46 mm to land it on grid requires zero downstream edits.

The 50-grid (1.27 mm) is the coordinate floor. Standard `Device:R/C/L` pins are at local ±3.81 mm (50-grid), so wire endpoints touching those pins are inherently on 50-grid; trying to force everything to 100-grid is impossible without redrawing the symbol library. Pre-emission coords are rounded to 3 decimals so float arithmetic (`R10_X - 6.35 - 5.08`) doesn't pollute the `.kicad_sch` git diff.

### Lint-first iteration

When the visual review surfaces an issue (yours or via screenshot), the first move is to **convert the rule into a new `_check_*` in `layout_lint.py`** before fixing the offending case. Every check that exists is one less round-trip on future iterations. See the skill doc's Process section for the full loop.
