# Symbol Library AI

AI-assisted EDA tooling. Inputs: part datasheets + freeform design requirements. Outputs: validated KiCad symbol libraries (`.kicad_sym`) and complete application schematics (`.kicad_sch`) that open in eeschema.

Long-term direction: a chunked design pipeline (`spec → part fingerprints → nets → BOM → schematic`) with a Python/ngspice simulation feedback loop, and integration into the user's existing platform with its own chat front end.

See [PROJECT_MEMORY.md](PROJECT_MEMORY.md) for the full handoff doc (architecture, skills, running eeschema, current state).

## Repo layout

```
.claude/skills/        per-stage skill docs (symbol gen, circuit gen, KiCad launch)
PROJECT_MEMORY.md      project memory + handoff
SymbolGenAI.md         original spec
```

**Convention for new work** (no parts or projects exist yet — the repo was reset to a clean slate on 2026-05-24):

- `datasheets/<MPN>/` — one folder per part, containing the `.kicad_sym` and (if available) the source `.pdf`.
- `<project>/` — one folder per design, containing `<project>.kicad_pro` + `<project>.kicad_sch` (+ optional `generate.py`).

## Running a generated schematic in eeschema

This machine uses a partial KiCad dev build at `~/Downloads/kicad/`. See [`.claude/skills/kicad-launch-dev-build.md`](.claude/skills/kicad-launch-dev-build.md) for the working binary paths and the kiface/resource symlinks.

On a fresh machine, `brew install kicad` and open the schematic directly:

```sh
open -a KiCad <project>/<project>.kicad_pro
```

Schematics generated through the skills embed their `lib_symbols` self-contained, so they render without registering the `.kicad_sym` files in the user-level `sym-lib-table`.

## Skills

- [`kicad-symbol-from-datasheet`](.claude/skills/kicad-symbol-from-datasheet.md) — generate a `.kicad_sym` from a PDF datasheet.
- [`kicad-circuit-from-topology`](.claude/skills/kicad-circuit-from-topology.md) — build a full schematic from a parts list + net topology, with layout rules to avoid text overlap and floating nets.
- [`kicad-launch-dev-build`](.claude/skills/kicad-launch-dev-build.md) — open schematics in eeschema and run `kicad-cli` on this machine's specific dev build.
