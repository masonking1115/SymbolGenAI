# Onboarding — HW/SW Codesigner

**Read this first.** It ramps a new AI session (or teammate) from zero to running
the full pipeline, and flags the landmines that waste time if you discover them
the hard way. After this, read [PROJECT_MEMORY.md](PROJECT_MEMORY.md) for depth.

---

## 1. Orient in 60 seconds

This is **AI-assisted EDA tooling**. You give it part datasheets + a freeform
design spec; it produces a validated **Altium** schematic project (`.PrjPcb` +
per-sheet `.SchDoc`), a native Altium symbol library (`.SchLib`), and footprints
(`.PcbLib`). A local GUI drives a generate → review → simulate loop.

The active project is **`test1/`** — the *Bobcat carrier board* (a test-chip
carrier that plugs into a Genesys 2 FPGA's FMC connector).

**The pipeline in one line:**
`design_requirements.md` (human spec) → `netlist/<sheet>.yaml` (declarative
connectivity, the canonical truth) → `altium/build_<sheet>.py` (places parts,
routes from live pin coordinates) → `build_project` (validates + lints + renders
each sheet, emits the Altium project).

### ⚠️ The #1 landmine: this is Altium, NOT KiCad

The project **started on a KiCad backend and that backend was removed.** Altium
(via pure-Python `altium_monkey`) is now the *only* backend. If you see a doc,
comment, or old commit talking about `.kicad_sym` / `.kicad_sch` / `eeschema` /
`kicad-cli` as the active pipeline, **it is stale** — ignore it as current
instruction. The surviving `gen/` modules (`netlist.py`, `validator.py`,
`config.py`, `symbols.py`, `shared.py`) are backend-neutral and reused; the
KiCad-coupled builders were replaced by `test1/altium/`. (A few docs keep
*labeled historical* KiCad references on purpose — those are fine.)

### Other things that are NOT true (anti-stale guard)

- This is **not** a Mac. It is the **Windows 11 PC** with **Altium Designer AD26
  installed and licensed**. Any "Apple Silicon / no Altium VM / defer to Windows"
  narrative is resolved history.
- The Altium migration is **complete**, not "Gate 0 / in progress." All 6 sheets
  build, validate, and pass the real-Altium fidelity oracle.
- Paper sizes use **Altium's real drawable frames** (A3 = 15500×11100 mil), *not*
  ISO 216 (16535×11690). Don't size content to ISO.

---

## 2. Environment (this machine)

| Thing | Value |
|---|---|
| Repo root | `C:\Users\mking\Downloads\HW-SW_CoDesigner\SymbolGenAI` |
| Python venv (has `altium-monkey`, `pyyaml`, `fastapi`, `pymupdf`+`reportlab`) | `C:\Users\mking\Downloads\altium_spike\.venv` — **outside the repo** |
| Python / altium_monkey | 3.12.2 / `2026.5.26` |
| Altium Designer | AD26 at `C:\Program Files\Altium\AD26\X2.EXE` |
| Shell | PowerShell (Windows). Use the **full venv interpreter path** — there is no activated venv by default. |

**The interpreter you will use for almost everything** (copy this — it's `$PY`
in the commands below):

```
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe
```

> If the venv path above doesn't exist on a fresh machine, that's the one piece
> of host-specific setup: create a Python 3.11–3.12 venv outside the repo and
> `pip install altium-monkey pyyaml fastapi "uvicorn[standard]" pydantic pymupdf reportlab`.

---

## 3. Run the full pipeline

### A. Build the schematic (the core generator + linter)

From the **repo root**, with the venv interpreter:

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m test1.altium.build_project
```

This builds all 6 child sheets + the hierarchical root, runs the two gates per
sheet, and writes `test1/altium/out/test1.PrjPcb` + one `.SchDoc` per sheet + the
merged `out/lib/parts.SchLib` + `out/render/<sheet>.svg` + `out/lint.json`.

**A healthy run ends with:**
```
symbol library: clean
eeprom       A4     0/0/0          OK
connectors   A2     0/0/0          OK
power        A3     0/0/0          OK
bias         A2     0/0/0          OK
fmc          A3     0/0/0          OK
bobcat       A2     0/0/0          OK
root         A3     OK
FAILURES: none
```
`0/0/0` is `ERROR/WARNING/INFO` lint counts. **`FAILURES: none` + all-zero lint is
the green state** — this is your regression check after any change.

> **Windows gotcha:** if you run a single sheet directly (not via `build_project`)
> and it prints a non-ASCII glyph (e.g. `→`, `Ω`), Windows' cp1252 console
> raises `UnicodeEncodeError`. Prefix the command with `PYTHONUTF8=1` (Bash) or
> set `$env:PYTHONUTF8=1` (PowerShell). The GUI backend already forces this on
> its subprocesses.

### B. Run the GUI (optional — for the human-in-the-loop loop)

Two processes:

```powershell
# 1. backend (port 8765) — MUST use the venv interpreter (needs altium_monkey)
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\gui\backend\app.py

# 2. frontend (port 5173, proxies /api -> 8765) — in a second terminal
cd test1\gui\frontend
npm install          # one time
npm run dev
```
Open <http://localhost:5173>. The chat/apply features in the GUI shell out to the
`claude` CLI (`agent.py`) and reuse your existing `claude` auth.

> **Frontend build/verify gotcha:** use the **local** binaries —
> `.\node_modules\.bin\tsc -b` then `.\node_modules\.bin\vite build`. A global
> `tsc` pulls the wrong package.

### C. Open / verify in real Altium (optional)

```powershell
& "C:\Program Files\Altium\AD26\X2.EXE" "C:\Users\mking\Downloads\HW-SW_CoDesigner\SymbolGenAI\test1\altium\out\test1.PrjPcb"
```
Altium is single-instance and slow to launch (~30 s); pass the `.PrjPcb` and use
**Project → Compile** for ERC / cross-sheet net resolution. Full detail +
the unattended fidelity oracle are in the `altium-launch-and-verify` skill.

---

## 4. How to make a change (the golden path)

**Never hand-edit `.SchDoc` binaries or the `out/` files.** The flow is always:

1. Edit the **source**: `test1/netlist/<sheet>.yaml` (connectivity — the truth)
   and/or `test1/altium/build_<sheet>.py` (placement/routing) and/or
   `test1/Parts Library/<MPN>/<MPN>.SchLib` (symbol).
2. **Rebuild:** `… -m test1.altium.build_project`.
3. **Verify:** must return `FAILURES: none`, and the sheet you touched should be
   `0/0/0`. The connectivity validator (hard gate) raises on any
   disconnect/short; the layout linter (quality gate) reports geometry issues.

**Lint-first rule:** when a *visual* layout problem appears that the linter
didn't catch, FIRST add a `_check_*` to `test1/altium/layout_lint.py`, THEN fix
the offending case. Every check is one less future round-trip. **Do not weaken or
fundamentally restructure the linter** — only add checks or refine a threshold
with evidence.

---

## 5. Gotchas that will cost you an hour (learned the hard way)

- **Body boxes use the TRUE drawn extent, not pin coordinates.** A single-column
  part (FMC connector, SMA, header) has a drawn body rectangle offset to one side
  of its pins. The linter measures clearance against `PlacedPart.graphic_box`
  (from altium_monkey's `full_bounds_mils()`). When placing a port near such a
  connector, clear the *drawn body edge*, not the pin x — else `label_over_symbol`
  / `label_symbol_clearance` fires.
- **Altium frame ≠ ISO paper.** Content that fits "ISO A3" can overflow Altium's
  smaller A3 frame and land in the border/title-block zone. `_PAPER_MIL` holds the
  real Altium sizes + `_PAPER_MARGIN`; `offpage_text` checks the usable area.
- **Junctions are cosmetic.** altium_monkey can't emit a junction real Altium
  keeps. Connectivity rides **T-intersections** (Altium auto-junctions) + pins.
  **Never route a 4-way crossing** — split into offset T's. `redundant_junction`
  INFO is expected on a pin.
- **A wire ending on a pin auto-connects** — don't add a junction dot there.
- **Signal-port net names don't propagate** in altium_monkey's single-sheet
  `to_netlist` (power ports do). Cross-sheet connectivity is real only after
  Altium **compiles** the `.PrjPcb`; the netlist YAML is the declared truth.
- **The SVG preview ignores power-port orientation** (GND-down/rail-up). The
  binary is correct — don't "fix" orientation based on the SVG render.
- **Ultra Librarian symbols:** UL stores parts under the *orderable* variant, not
  the bare MPN, and `symlib.symbol_name(mpn)` resolves the real name at read time.
  **Always verify part identity after a UL download** — UL serves multiple
  manufacturers per generic MPN (a 2N7002 download once turned out to be a diode).
- **`out/` is generated.** Safe to delete and rebuild. (Some `out/*` snapshots are
  committed as a convenience, so they show up in `git status` after a rebuild —
  that's expected.)

---

## 6. Repo map (where things live)

```
SymbolGenAI/
├── ONBOARDING.md                ← you are here
├── PROJECT_MEMORY.md            ← full handoff (read second)
├── README.md                    ← top-level overview
├── docs/pipeline.tex            ← LaTeX architecture writeup (compile w/ pdflatex)
├── .claude/skills/              ← stage contracts (see table below)
└── test1/                       ← active project: Bobcat carrier
    ├── design_requirements.md   ← SOURCE OF TRUTH for what's designed + why
    ├── netlist/<sheet>.yaml     ← declarative connectivity (canonical)
    │     bias, bobcat, connectors, eeprom, fmc, power
    ├── Parts Library/<MPN>/     ← per-MPN .SchLib (+ .PcbLib, .pdf) — 23 parts, strict isolation
    ├── altium/                  ← THE GENERATOR BACKEND
    │     build_project.py       ←   orchestrator (entry point)
    │     build_<sheet>.py       ←   per-sheet placement/routing
    │     layout_lint.py         ←   the geometry gate (23 rules)
    │     shared.py              ←   AltiumSheet primitives, _PAPER_MIL, graphic_box
    │     author_symbol.py/symlib.py/build_symbols.py  ← symbol authoring/merge
    │     verify/                ←   real-Altium fidelity oracle + FINDINGS.md
    │     out/                   ←   GENERATED output (.PrjPcb/.SchDoc/render/lint.json)
    ├── gen/                     ← backend-neutral core (netlist loader, validator) — REUSED
    ├── gui/                     ← FastAPI backend (8765) + React/Vite frontend (5173)
    ├── sim/                     ← ngspice simulation subsystem
    ├── review/                  ← findings.json + fix_queue.json (GUI-driven review)
    └── error_log.md             ← review output artifact (GUI READS it — leave in place)
```

### Skills (`.claude/skills/`) — the stage contracts

| Skill | Use when |
|---|---|
| `altium-circuit-from-topology` | Build a full project from a netlist + topology. **The builder API + every layout rule the linter enforces.** Read this before editing any `build_<sheet>.py`. |
| `altium-symbol-from-datasheet` | Make/import a `.SchLib` — author from a datasheet pin-spec, or import from Ultra Librarian. |
| `altium-launch-and-verify` | Open in real Altium AD26, preview sheets, or run the fidelity oracle. |
| `design-review` | Read-only functional + requirements audit → `error_log.md`. |
| `review-fix-queue` | Triage queued review fixes via the YAML→builder→rebuild path. |

---

## 7. First moves for a new session

1. Read this file, then skim [PROJECT_MEMORY.md](PROJECT_MEMORY.md).
2. Run `build_project` (§3A) and confirm the green state — this proves your env
   works and gives you the baseline.
3. For a layout/routing task, read the `altium-circuit-from-topology` skill and
   the relevant `build_<sheet>.py`. For a symbol task, the
   `altium-symbol-from-datasheet` skill. For a review, the `design-review` skill.
4. Make changes via the golden path (§4); keep the linter green; commit only when
   the user asks.
