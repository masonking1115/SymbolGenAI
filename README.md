# Symbol Library AI

AI-assisted EDA tooling. Inputs: part datasheets + freeform design requirements. Outputs: validated KiCad symbol libraries (`.kicad_sym`) and complete application schematics (`.kicad_sch`) that open in eeschema.

Long-term direction: a chunked design pipeline (`spec → part fingerprints → nets → BOM → schematic`) with a Python/ngspice simulation feedback loop, and integration into the user's existing platform with its own chat front end.

See [PROJECT_MEMORY.md](PROJECT_MEMORY.md) for the full handoff doc (architecture, skills, running eeschema, current state).

## Repo layout

```
.claude/
  skills/           per-stage skill docs (symbol gen, circuit gen, KiCad launch)
  datasheets/       source PDFs
*.kicad_sym         generated symbol libraries
<project>/         each demo project — *.kicad_pro + *.kicad_sch + generate.py
PROJECT_MEMORY.md   project memory + handoff
SymbolGenAI.md      original spec
```

## Running a generated schematic in eeschema

This machine uses a partial KiCad dev build at `~/Downloads/kicad/`. See [`.claude/skills/kicad-launch-dev-build.md`](.claude/skills/kicad-launch-dev-build.md) for the working binary paths and the kiface/resource symlinks.

On a fresh machine, `brew install kicad` and then:

```sh
open -a KiCad LDO_LNA_Demo/LDO_LNA_Demo.kicad_pro
```

The demo schematics embed their `lib_symbols` self-contained, so they render without registering the `.kicad_sym` files in the user-level `sym-lib-table`.

## Skills

- [`kicad-symbol-from-datasheet`](.claude/skills/kicad-symbol-from-datasheet.md) — generate a `.kicad_sym` from a PDF datasheet.
- [`kicad-circuit-from-topology`](.claude/skills/kicad-circuit-from-topology.md) — build a full schematic from a parts list + net topology, with layout rules to avoid text overlap and floating nets.
- [`kicad-launch-dev-build`](.claude/skills/kicad-launch-dev-build.md) — open schematics in eeschema and run `kicad-cli` on this machine's specific dev build.

## Current demo projects

| Project | What it is |
|---|---|
| `TPS7E72_demo/` | TI TPS7E72 LDO at 3.3V out, datasheet design example p. 27. |
| `LNA_LDO_chain/` | First LNA+LDO chain (pre-layout-rules — has known overlap issues). |
| `LDO_LNA_Demo/` | Regenerated LNA+LDO chain with the layout rules applied. |
