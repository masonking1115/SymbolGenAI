# Project Memory — SymbolLibraryAI

Handoff doc for resuming work in a new chat. Read this first.

## Project overview

AI-assisted EDA tooling. Inputs: a stack of part datasheets + freeform design requirements. Outputs: validated KiCad symbol libraries (`.kicad_sym`) and complete application schematics (`.kicad_sch`) that open in eeschema. Long-term: integrate a Python simulation feedback loop (ngspice) and graft these capabilities onto the user's existing platform with its own chat front end.

Repo: `git@github.com:masonking1115/SymbolGenAI.git` (main).

## Repo layout

The repo was reset to a clean slate on 2026-05-24 to start a fresh project. Current top-level contents:

```
SymbolLibraryAI/
├── PROJECT_MEMORY.md                ← this file
├── README.md
├── .claude/skills/                  ← per-stage skill docs (see "Skills" below)
└── kicad/                           ← symlink to ~/Downloads/kicad/ (gitignored)
```

**Convention for new work — strict per-project isolation, no cross-contamination of data between projects.** Every project is fully self-contained in its own top-level folder, including the parts it uses:

```
<project>/                           ← one folder per design — self-contained
   design_requirements.md            ← REQUIRED — see "design_requirements.md" below
   <project>.kicad_pro               ← project config JSON
   <project>.kicad_sch               ← schematic — also embeds lib_symbols self-contained
   datasheets/<MPN>/                 ← parts used in THIS project only
      <MPN>.kicad_sym                ← the symbol (canonical source for this project)
      <MPN>.pdf                      ← source datasheet (optional if not available)
   generate.py                       ← Python generator (optional)
   (.history/, render/, *.lck, *.kicad_prl all gitignored)
```

Two projects that happen to use the same MPN each get their own copy of the symbol + datasheet under `<project>/datasheets/<MPN>/`. The duplication is intentional — it means a project folder is a complete, transportable unit, and an edit to one project's `.kicad_sym` cannot silently affect another project.

The user may add more conventional files (e.g. `nets.yaml`, `bom.yaml`, `sim/`) as projects evolve — always inside the per-project folder. When in doubt, add new artifacts under the project, not the repo root.

### `design_requirements.md`

Every project's source of truth for **what is being designed and why**. Read this first when entering a project; everything downstream (symbol selection, BOM, layout decisions) is derived from it.

Suggested sections (extend as needed):

```markdown
# <project> — Design Requirements

## Application
What this circuit is for, one paragraph.

## Specs
- Input range, output range, supply rails
- Signal types and frequency/bandwidth
- Environmental / form factor constraints
- Any other top-level numerical targets

## Parts to implement
- <MPN-1> — role in the design
- <MPN-2> — role in the design
- (passives left abstract: "R1 — feedback divider top")

## Topology / block diagram (optional)
High-level signal flow if not obvious from "Parts".

## Notes / open questions
Anything unresolved that future work should flag back to the user.
```

An earlier Electron+React MVP existed under `src/` and `electron/` but was deleted on 2026-05-24 once the project committed to KiCad-as-platform. If you need to resurrect it, recover from git history (commits `d070e42` through `234cd37`). Three prior demo schematics (`TPS7E72_demo`, `LNA_LDO_chain`, `LDO_LNA_Demo`) and their part libraries were also deleted on the same date; recover via git history if ever needed.

## Running eeschema on this machine

There is a partial KiCad dev build at `/Users/masonking/Downloads/kicad/build/`. Only `eeschema.app` and `kicad-cli` work; `KiCad.app` (project manager) and pcbnew/gerbview/etc. do not. See `.claude/skills/kicad-launch-dev-build.md` for the full table.

**Open a schematic in eeschema (working command):**
```sh
# One-time setup — symlink the icons resource into the bundle:
RES=/Users/masonking/Downloads/kicad/build/eeschema/eeschema.app/Contents/SharedSupport/resources
mkdir -p "$RES"
ln -sf /Users/masonking/Downloads/kicad/build/resources/images.tar.gz "$RES/images.tar.gz"

# Also symlink the kiface so eeschema.app finds its plugin:
ln -sf /Users/masonking/Downloads/kicad/build/kicad/KiCad.app/Contents/PlugIns/_eeschema.kiface \
       /Users/masonking/Downloads/kicad/build/eeschema/eeschema.app/Contents/PlugIns/_eeschema.kiface

# Launch with a schematic:
open -a /Users/masonking/Downloads/kicad/build/eeschema/eeschema.app \
        /path/to/file.kicad_sch
```

Pass the `.kicad_sch` (not `.kicad_pro`) — eeschema opens schematic files directly without the project manager.

**Validate / render without a GUI:**
```sh
KICAD_CLI=/Users/masonking/Downloads/kicad/build/kicad/KiCad.app/Contents/MacOS/kicad-cli

"$KICAD_CLI" sym upgrade --force <file>.kicad_sym       # validates a symbol lib
"$KICAD_CLI" sch export svg --output <dir> <file>.kicad_sch   # parse check + render
"$KICAD_CLI" sch export pdf --output <out.pdf> <file>.kicad_sch
```

Do NOT run `kicad-cli sch erc` — requires `_cvpcb.kiface` which isn't built. Use SVG export as the parse gate.

**On a fresh machine** the dev build won't exist. Either rebuild KiCad at `~/Downloads/kicad/` (Ninja/CMake — see `kicad-launch-dev-build.md` for the cmake flags that worked on macOS) or `brew install kicad` and the schematics will open in the official install.

Symbol library registration is not in the repo — `~/Library/Preferences/kicad/10.99/sym-lib-table` is per-user. Any `.kicad_sym` files added later under `<project>/datasheets/<MPN>/` won't appear in eeschema's symbol browser until added there manually. Schematics generated from those symbols should embed `lib_symbols` self-contained so they open without library registration.

## Skills

Living in `.claude/skills/`. Each one is a contract for a specific stage of work.

| Skill | Use when |
|---|---|
| `kicad-launch-dev-build.md` | User asks to "open in KiCad", "load in eeschema", run a render or validate a schematic. Documents the working binary paths and the broken project manager. |
| `kicad-symbol-from-datasheet.md` | User provides a PDF datasheet and wants a `.kicad_sym`. Covers pin angle convention (angle = direction from outer endpoint toward body), pin electrical types, mandatory properties, validation via `kicad-cli sym upgrade`. |
| `kicad-circuit-from-topology.md` | User asks for an application/example circuit or a schematic from a BOM + topology. Covers component spacing (2.54–5.08 mm adjacent, 10–15 mm between groups), Reference/Value label placement table per orientation (never on the body), `power:` symbols on every rail, no floating nets, orthogonal wires only, and the file templates. |

Critical syntax gotchas captured in both skills:
- `(justify center)` is **invalid** — KiCad needs both axes (`left bottom`) or omit the clause.
- Pin numbers are strings: `(number "1" …)` not `(number 1 …)`.
- Symbol local +y is up in the editor; world y is down — pin world coord is `(at_x + pin_local_x, at_y − pin_local_y)`.
- Property `at` positions in instances are world coordinates, not symbol-local.
- Stock `Device:C` pins are at local y=±3.81 (half-grid offset of 2.54) — placing on-grid puts pins on-grid; placing at half-grid puts pins half-grid.

## User preferences baked into the skills

- Power rails always get a `power:` symbol (`power:GND`, `power:+3V3`, …), not bare net labels.
- Off-board signal nets get `(label …)` or `(global_label …)` with a destination hint (`TO_NEXT_STAGE`, `FROM_ANTENNA`).
- Never leave a bare wire end dangling — every net needs a pin, power symbol, or label.
- No text overlap on a symbol body or another net. Vertical R/C/L: Reference/Value go to the right of the body, not above/below the same X axis. See the table in `kicad-circuit-from-topology.md`.
- Sufficient but not excessive spacing — empty schematic real estate is cheap.
- Symbol fields: hide pin electrical types ("blue text") and hidden lib fields in the editor; show only the Value text by default on placed symbols.

## Proposed design pipeline architecture

For a "datasheets + requirements → finished schematic" project, chunk the work so each stage produces a versioned artifact and validates it before the next stage reads it. Each chunk's prompt only loads its upstream artifact, not the raw datasheets again.

Full 9-stage flow (for larger projects):

| Stage | Output | Validates with | Notes |
|---|---|---|---|
| 1. Requirements digest | `spec.yaml` | user sign-off | normalize: I/O ranges, rails, signal types, env, form factor |
| 2. Part fingerprints (one chunk per PDF) | `parts/<MPN>.json` | sanity check vs datasheet | ~50 lines per part: pinout, electrical limits, recommended app circuit, footprint |
| 3. Architecture | `arch.md` | vs `spec.yaml` | abstract blocks + signal flow, no values |
| 4. Net topology | `nets.yaml` | every pin terminated, no shorts, rails consistent | `name, source_pin, sink_pins, rail_class` per net |
| 5. Symbol generation (one chunk per IC, parallelizable) | `<MPN>.kicad_sym` | `kicad-cli sym upgrade` | uses `kicad-symbol-from-datasheet` skill |
| 6. BOM finalization | `bom.yaml` | values within datasheet recommended ranges | concrete R/C/L per block |
| 7. Schematic layout | `<proj>.kicad_sch` | `kicad-cli sch export svg` | uses `kicad-circuit-from-topology` skill |
| 8. Visual review | user opens in eeschema | user sign-off | |
| 9. (Later) Simulation loop | ngspice deltas | convergence on spec metrics | re-runs stage 6 (BOM) with deltas as input |

**For "generally small" projects**: fold 3+4 (architecture + nets) into one stage and 6+7 (BOM + layout) into another. You end up with five active artifacts (`spec`, `parts/*`, `nets`, `bom`, `sch`) plus the per-IC symbols. That's the sweet spot before the simulation loop attaches at stage 9.

**Why this maps well to Claude Code**: each stage becomes a skill file with a clear input/output contract; per-IC symbol generation parallelizes via subagent dispatch; file-based artifacts persist across sessions so context never needs to reload the full datasheet stack.

## Current state at handoff

- Clean slate as of 2026-05-24 — no parts, no demo schematics. Only the skills, the project docs, and the KiCad dev-build symlink remain.
- **New parts going forward**: always create `<project>/datasheets/<MPN>/` inside the consuming project and place both the `.kicad_sym` and `.pdf` there. Never put a shared `datasheets/` at the repo root — each project owns its own copies.
- **Recovery references** (if previous artifacts are ever needed):
  - Phase 1 Electron MVP: commits `d070e42`–`234cd37`.
  - Earlier demo projects (TPS7E72_demo, LNA_LDO_chain, LDO_LNA_Demo) + their part libraries (TPS7E72, SKY67150-396LF, BFC237076104): up to commit `add3cd6`.

## Things explicitly not in the repo

- The KiCad source tree at `~/Downloads/kicad/` (symlinked as `kicad/`, gitignored — too big and machine-specific).
- KiCad build artifacts (`build/`, install paths).
- The user-level `sym-lib-table` (`~/Library/Preferences/kicad/10.99/`) — must be re-registered per machine if the symbol browser is needed.
- `.env*`, `.claude/settings.local.json`, `.vscode/`, `.idea/`.
- KiCad transient files: `.history/`, `*.kicad_prl`, `~*.lck`, `*/render/`, `fp-info-cache`.

## Open suggestions never acted on

- Add a setup README so a fresh clone is one-shot runnable (covers `brew install kicad` or rebuild path, sym-lib-table registration).
- Scaffold the artifact-template files (`spec.yaml`, `parts/<MPN>.json`, `nets.yaml`, `bom.yaml`) and a per-stage skill file so each pipeline chunk has a clear contract.
- Integrate the symbol/schematic generation pipeline into the user's internal platform with its own chat front end (waiting on the user to share that platform).
