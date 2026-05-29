# HW/SW Codesigner

AI-assisted EDA tooling. Inputs: part datasheets + freeform design requirements.
Outputs: a validated **Altium** schematic project (`.PrjPcb` + per-sheet
`.SchDoc`), a native Altium symbol library (`.SchLib`) and footprints
(`.PcbLib`). A local GUI drives the generate / review / simulate loop.

The backend is pure-Python [`altium_monkey`](https://github.com/wavenumber-eng/altium_monkey)
— it reads/writes Altium's native binary files with **no Altium install or
scripting API needed to build**. Altium Designer is only needed to *open*,
compile, and fidelity-verify the result.

> The project began on a KiCad backend; that backend was removed and Altium is
> now the only one. The declarative netlist and the connectivity validator are
> backend-agnostic and were reused unchanged. See
> [PROJECT_MEMORY.md](PROJECT_MEMORY.md) for the full handoff (environment,
> pipeline, skills, current state) and [docs/pipeline.tex](docs/pipeline.tex) for
> the architecture writeup.

## Repo layout

```
.claude/skills/        per-stage skill contracts (symbol, circuit, launch, review)
docs/pipeline.tex      LaTeX architecture writeup
test1/                 active project — Bobcat carrier board
PROJECT_MEMORY.md      project memory + handoff (read this first)
README.md
```

## Per-project convention — strict isolation

Every design is its own self-contained folder, including the parts it uses. Two
projects that use the same MPN each carry their own copy of the symbol and
datasheet — editing one project's library cannot silently affect another.

```
<project>/
   design_requirements.md            REQUIRED — source of truth: application, specs, parts, rationale
   netlist/<sheet>.yaml              declarative connectivity (canonical)
   Parts Library/<MPN>/<MPN>.SchLib  parts used in this project only (+ .PcbLib, .pdf)
   altium/                           the generator backend for this project
```

Do not create a shared parts dir at the repo root. The duplication is
intentional — a project folder is a complete, transportable unit.

## Build

From the repo root, with the spike-venv interpreter (Python 3.11–3.12 +
`altium-monkey`; venv lives outside the repo at
`C:\Users\mking\Downloads\altium_spike\.venv`):

```powershell
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe -m test1.altium.build_project
```

This builds all 6 child sheets + the hierarchical root, runs the two gates per
sheet, and writes `test1/altium/out/test1.PrjPcb` + one `.SchDoc` per sheet + the
merged `out/lib/parts.SchLib`. `out/` is generated (gitignored).

To open / verify in real Altium (this Windows machine has AD26 installed), see
the `altium-launch-and-verify` skill.

## Pipeline

```
  design_requirements.md ─► netlist/<sheet>.yaml ─► test1/altium/build_<sheet>.py ─► build_project
        (manual)              (declarative,            (place from netlist,            (orchestrator:
                               canonical)               route from live pin             per sheet → validate
                                                        hot-spots, relative coords)      → lint → render SVG;
                                                                                         emit .PrjPcb + .SchDoc)
```

### Gates (per sheet, in order)

1. **Connectivity validator** ([`test1/gen/validator.py`](test1/gen/validator.py),
   reused backend-agnostic) — every YAML net member must land in a connected
   component named that net. Raises `ValidationError`; **fails the build**.
2. **Layout linter** ([`test1/altium/layout_lint.py`](test1/altium/layout_lint.py))
   — geometric checks the validator can't see (silent shorts via wire overlap,
   ports impaling bodies, labels bumping symbols, off-page text, …). Severities
   `ERROR/WARNING/INFO`, reported per sheet as `E/W/I`. A clean build is `0/0/0`
   on every sheet. ERROR fails the build; WARNING/INFO are advisory.
3. **Parse + render** — `AltiumSheet.render_svg` (altium_monkey `to_svg`) is the
   in-process parse gate; the GUI serves the SVGs.

The full rule set and the builder API are documented in the
`altium-circuit-from-topology` skill.

### Coordinate convention

Coordinates are **mils, Y-up (Altium native), 100-mil grid**. All routing is
**chip-pin-relative** — the only anchor is each IC's `place_from_netlist(x, y)`;
everything else is `pins["<n>"][axis] ± delta`, so shifting a chip cascades
without downstream edits. Centering is a build-time global offset, not per-part
translation. `off_grid` and `diagonal_wire` are lint ERRORs.

### Lint-first iteration

When a visual issue surfaces, first add a `_check_*` to `layout_lint.py`, then
fix the offending case — every check is one less future round-trip. Do not weaken
or fundamentally restructure the linter; only add checks or refine thresholds
with evidence.

## Skills

- [`altium-symbol-from-datasheet`](.claude/skills/altium-symbol-from-datasheet.md) — make/import a `.SchLib` (pin-spec author or Ultra Librarian).
- [`altium-circuit-from-topology`](.claude/skills/altium-circuit-from-topology.md) — build a full project from a netlist + topology; the builder API + every layout rule the linter enforces.
- [`altium-launch-and-verify`](.claude/skills/altium-launch-and-verify.md) — open in real Altium AD26, preview sheets, run the fidelity oracle.
- [`design-review`](.claude/skills/design_review.md) — read-only functional + requirements audit → `error_log.md`.
- [`review-fix-queue`](.claude/skills/review-fix-queue.md) — triage queued review fixes via the YAML→builder→rebuild path.

## GUI

[`test1/gui/`](test1/gui/) — FastAPI backend (port 8765) drives the Altium
pipeline and serves renders; React+Vite frontend (port 5173). See
[test1/gui/README.md](test1/gui/README.md).
