# Symbol Library AI

AI-assisted EDA tooling. Inputs: part datasheets + freeform design requirements. Outputs: validated KiCad symbol libraries (`.kicad_sym`) and complete application schematics (`.kicad_sch`) that open in eeschema.

Long-term direction: a chunked design pipeline (`spec → part fingerprints → nets → BOM → schematic`) with a Python/ngspice simulation feedback loop, and integration into the user's existing platform with its own chat front end.

See [PROJECT_MEMORY.md](PROJECT_MEMORY.md) for the full handoff doc (architecture, skills, running eeschema, current state).

## Repo layout

```
.claude/skills/        per-stage skill docs (symbol gen, circuit gen, KiCad launch)
PROJECT_MEMORY.md      project memory + handoff
README.md
```

This is a clean-slate workspace as of 2026-05-24. No parts or designs exist yet.

## Per-project convention — strict isolation

Every design is its own self-contained folder. Two projects that use the same MPN each carry their own copy of the symbol and datasheet — no cross-contamination of data between projects.

```
<project>/
   <project>.kicad_pro
   <project>.kicad_sch                  schematic — embeds lib_symbols self-contained
   datasheets/<MPN>/
      <MPN>.kicad_sym                   parts used in this project only
      <MPN>.pdf                         source datasheet (optional)
   generate.py                          Python generator (optional)
```

Do not create a shared `datasheets/` at the repo root. The duplication is intentional: each project folder is a complete, transportable unit, and editing one project's symbols cannot silently affect another.

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
