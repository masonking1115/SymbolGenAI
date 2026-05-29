# Project Memory — HW/SW Codesigner

Handoff doc for resuming work in a new session. Read this first.

## What this is

AI-assisted EDA tooling. Inputs: part datasheets + freeform design requirements.
Outputs: a validated **Altium** schematic project (`.PrjPcb` + per-sheet
`.SchDoc`) plus a native Altium symbol library (`.SchLib`) / footprints
(`.PcbLib`). A GUI drives the generate / review / simulate loop; long-term aim is
a Python/ngspice simulation feedback loop and integration into the user's own
platform.

Repo: `github.com/masonking1115/SymbolGenAI` (branch `main`). Working directory:
`HW-SW_CoDesigner/SymbolGenAI`.

> **History note:** the project began on a KiCad backend (`.kicad_sym`/`.kicad_sch`
> via `kicad-cli`/eeschema). That backend was **removed** (commit
> "Remove KiCad backend; drive Altium only"). Altium is now the only backend.
> If you find a doc or comment describing KiCad as the active pipeline, it is
> stale — the `gen/` package's KiCad-coupled modules were replaced by
> `test1/altium/`. The `netlist/*.yaml` source of truth and the connectivity
> validator (`gen/validator.py`, `gen/netlist.py`) are backend-agnostic and were
> reused unchanged.

## Environment (this machine)

This is the **Windows 11 PC** and it is the Altium-capable machine — Altium
Designer **AD26** is installed and licensed at `C:\Program Files\Altium\AD26\X2.EXE`.

- Generator + GUI backend run under an **isolated spike venv** (Python 3.11–3.12)
  at `C:\Users\mking\Downloads\altium_spike\.venv` — outside this repo. It has
  `altium-monkey`, `pyyaml`, `fastapi`/`uvicorn`, `pymupdf`+`reportlab` (for SVG
  rasterizing; cairo is not available on Windows).
- See the `[[altium-environment-setup]]` and `[[altium-migration-windows]]`
  memories for exact CLI invocations.

## Repo layout

```
SymbolGenAI/
├── PROJECT_MEMORY.md          ← this file
├── README.md                  ← top-level overview (Altium pipeline)
├── docs/pipeline.tex          ← LaTeX architecture writeup (compile w/ pdflatex)
├── .claude/skills/            ← per-stage skill contracts (see "Skills")
└── test1/                     ← active project: Bobcat carrier board
    ├── design_requirements.md ← SOURCE OF TRUTH for what's being designed
    ├── netlist/<sheet>.yaml   ← declarative connectivity (canonical)
    ├── Parts Library/<MPN>/   ← per-MPN .SchLib (+ .PcbLib, .pdf) — strict isolation
    ├── altium/                ← the Altium generator backend (see altium/README.md)
    ├── gui/                   ← FastAPI backend (8765) + React/Vite frontend (5173)
    ├── sim/                   ← ngspice simulation subsystem (context-first)
    ├── review/                ← review findings.json + fix_queue.json (GUI-driven)
    └── error_log.md           ← review output artifact (GUI reads it — leave in place)
```

**Per-project isolation is strict.** Every design is a self-contained folder
including its parts; two projects using the same MPN each carry their own copy.
A project folder is a complete, transportable unit. Put new artifacts inside the
project folder, never at the repo root.

`design_requirements.md` is the source of truth for **what is being designed and
why** — read it first when entering a project. It already captures the bias-loop
design rationale (high-side PMOS V-to-I, OPA2388, external 3.3 V Vref, 0xFFF
EEPROM at POR, 5.11 kΩ sense, default-populated NMOS isolation FETs).

## The generator

Entry point (from the repo root, with the spike-venv interpreter):

```powershell
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe -m test1.altium.build_project
```

This builds all 6 child sheets + the hierarchical root, runs the two gates per
sheet, and writes `test1/altium/out/test1.PrjPcb` + one `.SchDoc` per sheet +
the merged `out/lib/parts.SchLib`. `out/` is generated — safe to delete and
regenerate (gitignored).

**Two gates per sheet (in order):**
1. **Connectivity validator** (`gen/validator.py`, reused from the old backend) —
   every YAML-declared net member must land in a connected component named that
   net. Raises `ValidationError`; **fails the build**. Backend-agnostic
   (coordinate-based), so it gates Altium and once gated KiCad identically.
2. **Layout linter** (`test1/altium/layout_lint.py`) — geometric checks the
   validator can't see. Severities `ERROR/WARNING/INFO`; reported per sheet as
   `E/W/I`. A clean build is `0/0/0` on every sheet and `FAILURES: none`.

A cosmetic-note auto-fixer (`AltiumSheet.auto_fix_text`) nudges overlapping
`text` notes before the gate; power glyphs that straddle a net are auto-offset.

**Coordinates are mils, Y-up (Altium native), 100-mil grid.** All routing is
**chip-pin-relative** — the only anchor is each IC's `place_from_netlist(x, y)`;
everything else is `pins["<n>"][axis] ± delta`, so shifting a chip cascades
cleanly. Centering is a build-time global offset, not per-part translation.

### The linter rules (current set)

`layout_lint.py` `RULES` registry (surfaced in the GUI Generator tab):
`off_grid`, `diagonal_wire`, `out_of_bounds`, `component_overlap`,
`power_orientation`, `visible_param_glob`, `wire_through_label`,
`power_straddles_net`, `ground_on_top`, `wire_through_body`, `off_center`,
`cramped_spacing`, `label_overlap`, `label_over_symbol`,
`label_symbol_clearance`, `wire_through_port`, `offpage_text`, `wire_overlap`,
`stub_t_short`, `bridged_drop`, `duplicate_wire`, `redundant_junction`, and the
library-scope `pin_name_overlap`.

Two non-obvious linter facts (see `[[label-symbol-clearance-rule]]` and
`[[altium-paper-sizes]]`):
- Body boxes use the **true drawn extent** (`PlacedPart.graphic_box` from
  altium_monkey's `full_bounds_mils()`), not the pin column — single-column parts
  (FMC connectors) have a body rectangle offset to one side that a pin-only box
  misses. `label_symbol_clearance` flags a port/note within 50 mil of a drawn
  body (aligned passive value labels exempt).
- `_PAPER_MIL` holds Altium's **real drawable frame sizes** (A3 = 15500×11100,
  *not* ISO 16535×11690), with `_PAPER_MARGIN` for the border/reference-zone band;
  `offpage_text` checks the usable area inside the margin.

**Lint-first iteration:** when a visual issue surfaces, first add a `_check_*` to
`layout_lint.py`, then fix the offending case. Every check is one less future
round-trip. **Do not weaken or fundamentally restructure the linter** — only add
checks or refine thresholds with evidence.

### Sheets (test1 — Bobcat carrier)

| Sheet | Block | Paper |
|---|---|---|
| eeprom | 24AA08 I²C EEPROM | A4 |
| connectors | CLK/OSC/GPIO SMAs + 1×4 header | A2 |
| power | TPS7A8401A LDO + output jumpers + TPS22916 load switch | A3 |
| bias | MCP4728 DAC + OPA2388 + PMOS + sense + NMOS isolation | A2 |
| fmc | VITA 57.1 LPC 160-pin connector | A3 |
| bobcat | Bobcat QFN DUT + decoupling/pulls | A2 |
| root | sheet symbols only (hierarchical) | A3 |

## The symbol library (native Altium)

Source of truth is per-MPN `Parts Library/<MPN>/<MPN>.SchLib` (the symbol named
after the MPN), either downloaded from **Ultra Librarian** (catalog parts) or
authored from a JSON pin-spec via `python -m test1.altium.author_symbol <MPN>`
(custom/DUT parts). `build_symbols.get_library()` merges every per-MPN `.SchLib`
(+ stock R/C/L passives) into `out/lib/parts.SchLib`, rebuilding only when a
source is newer.

Key facts:
- UL stores parts under the **orderable variant**, not the bare MPN
  (`MCP4728` → `MCP4728-E/UN`); `symlib.symbol_name(mpn)` resolves the real
  internal name at read time (renaming via `to_json`/`from_json` is lossy for
  pins). See `[[ul-symbol-import]]`.
- **Verify part identity after any UL download** — UL serves multiple
  manufacturers per generic MPN; a 2N7002 download once turned out to be a diode.
- Builders route from **live pin hot-spots** returned by `place()`, so exact
  symbol coords don't matter — but swapping a symbol with a different pin
  arrangement breaks that sheet's routing (re-route after a swap).

## The GUI

`test1/gui/` — FastAPI backend (`backend/app.py`, port **8765**) drives the
Altium pipeline as subprocesses, serves sheet SVG/PNG renders + symbol SVGs, and
runs `claude -p` for chat/apply/sim (`backend/agent.py`). React+Vite+TS frontend
(`frontend/`, dev on **5173**, proxies `/api`→8765).

- Build the backend's subprocesses with the spike venv interpreter; the backend
  forces `PYTHONUTF8`/`PYTHONIOENCODING` on them so a non-ASCII glyph can't crash
  the build. See `[[gui-altium-backend]]` and `[[lint-autofix-and-generate-fix]]`.
- Build/verify the frontend with the **local** binaries:
  `./node_modules/.bin/tsc --noEmit -p .` then `./node_modules/.bin/vite build`.
- Tabs: **Design Resources · Library · Schematic Generator · Simulation · Design
  Review**. Right rail = multi-session chat + opt-in changelog + pipeline status.
- Review flow: upload a PDF → parsed into `review/findings.json`; clicking
  **Apply** parks a request in `review/fix_queue.json` for the agent to triage
  (see the `review-fix-queue` skill). `error_log.md` is the human-review output,
  read by the backend — leave it in place.

## Skills (`.claude/skills/`)

Each is a contract for a stage of work.

| Skill | Use when |
|---|---|
| `altium-symbol-from-datasheet` | Make/import a `.SchLib` from a datasheet (pin-spec author) or Ultra Librarian. |
| `altium-circuit-from-topology` | Build a full Altium project from a netlist + topology; documents the builder API + every layout rule the linter enforces. |
| `altium-launch-and-verify` | Open the project in real Altium AD26, preview sheets, or run the unattended real-Altium fidelity oracle. |
| `design-review` | Read-only functional + requirements audit of the design → `error_log.md`. |
| `review-fix-queue` | Agent-loop half of the review flow: triage queued fixes, apply via the YAML→builder→rebuild path. |

## Known limitations (Altium backend)

- **Signal-port net names** don't propagate in altium_monkey's single-sheet
  `to_netlist` (power ports do); real Altium resolves them on **Project →
  Compile**. Cross-sheet connectivity is verified by opening the `.PrjPcb`.
- **Junctions are cosmetic** — altium_monkey can't emit a junction real Altium
  keeps; connectivity rides T-intersections (Altium auto-junctions) + pins, and
  4-way crossings are forbidden by the linter. Detail in
  `test1/altium/verify/FINDINGS.md`.
- **SVG preview ignores power-port orientation** (the binary/real Altium is
  correct) — don't "fix" orientation from the SVG.

## Things not in the repo

- The spike venv at `C:\Users\mking\Downloads\altium_spike\.venv` (machine-specific).
- `test1/altium/out/` build artifacts are generated (gitignored — though some
  committed `out/*.SchDoc`/render/lint snapshots exist as a convenience).
- `.env*`, `.claude/settings.local.json`, `.vscode/`, `.idea/`, GUI runtime state
  (`test1/gui/state/`).

## Open / deferred

- **Project rename to "HW/SW Codesigner"** is partially reflected (working dir is
  `HW-SW_CoDesigner`). UI display strings and `package.json` name may still say
  "test1"/"Symbol Library AI"; the board name stays **Bobcat Carrier**. Do NOT
  rename `test1/` paths or `test1.gui.*` localStorage keys (breaks paths / resets
  layouts).
- **Simulation loop** (ngspice) is scaffolded in `test1/sim/` but not yet a
  closed feedback loop into the BOM.
- **Platform integration** — grafting this pipeline onto the user's internal
  platform with its own chat front end (waiting on access).
