# Project Memory — SymbolLibraryAI

Handoff doc for resuming work in a new chat. Read this first.

## Project overview

AI-assisted EDA tooling. Inputs: a stack of part datasheets + freeform design requirements. Outputs: validated KiCad symbol libraries (`.kicad_sym`) and complete application schematics (`.kicad_sch`) that open in eeschema. Long-term: integrate a Python simulation feedback loop (ngspice) and graft these capabilities onto the user's existing platform with its own chat front end.

Repo: `git@github.com:masonking1115/SymbolGenAI.git` (main).

## Repo layout

```
SymbolLibraryAI/
├── PROJECT_MEMORY.md                ← this file
├── README.md
├── .claude/skills/                  ← per-stage skill docs (see "Skills" below)
├── test1/                           ← active Bobcat carrier-board project (see test1/design_requirements.md)
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

## Editing workflow in eeschema — persist edits without "false saves"

eeschema saves to disk on Cmd+S reliably; the two real risks are (a) symbol-shape edits diverging between the embedded `lib_symbols` block and the canonical `.kicad_sym`, and (b) disk-saved files not reaching git.

**Rule 1 — Symbol-shape edits go through the Symbol Editor on the canonical `.kicad_sym` only.**
- Never use **right-click → Edit Symbol** on a placed instance. That writes only to the embedded `lib_symbols` block inside `<project>.kicad_sch` and the change vanishes the next time `generate.py` regenerates the schematic.
- Instead: open `<project>/datasheets/<MPN>/<MPN>.kicad_sym` in the standalone Symbol Editor, make the change, save. Then in eeschema run **Tools → Update Symbols from Library** to refresh the embedded copy.
- Schematic-level edits (placement, wires, refdes, value, label text) are fine to do directly in eeschema — those legitimately belong in the `.kicad_sch`.

**Rule 2 — End every editing session with a git commit.**
- Cmd+S writes to disk; nothing reaches GitHub until `git add && git commit && git push`.
- At the end of any eeschema session, prompt the user (or just do it if asked) to commit the dirty `.kicad_sch` / `.kicad_pro` / `.kicad_sym` files so the work is durable across machines.
- Quick check before exiting: `git status` should be clean (apart from gitignored `.history/`, `.kicad_prl`, `~*.lck`).

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

## Current state at handoff (updated 2026-05-27)

> ⚠️ There are ACTIVE THREADS + OPEN DECISIONS at the bottom of this file
> (Altium migration, project rename). Read those before resuming work.

`test1/` (Bobcat carrier board) is the active project and now has a full **GUI** on top of the generator/review/sim pipeline.

**Generator core (unchanged):** per-sheet package at [test1/gen/](test1/gen/); seven sheets emit through `python3 test1/gen_schematic.py --no-reopen` with strict netlist validation + layout linter ([test1/gen/layout_lint.py](test1/gen/layout_lint.py)). `netlist/*.yaml` is the **declarative source of truth**; `gen/build_<sheet>.py` place parts; renders/parse-gates via `kicad-cli`. Coords on the 50-grid floor.

**The GUI** — [test1/gui/](test1/gui/), built/expanded over recent sessions:
- Backend: FastAPI ([gui/backend/app.py](test1/gui/backend/app.py)) runs `gen_schematic.py`/`run_review.py` as subprocesses, serves PNG renders + symbol SVGs, and drives `claude -p` for chat/apply/sim/compaction ([gui/backend/agent.py](test1/gui/backend/agent.py)). Port 8765.
- Frontend: React+Vite+TS ([gui/frontend/](test1/gui/frontend/)); Vite dev on 5173 proxying `/api`→8765. **Build/verify with the LOCAL binaries**: `./node_modules/.bin/tsc --noEmit -p .` then `./node_modules/.bin/vite build` (`npx tsc` pulls a wrong global package).
- Tabs (sidebar order): **Design Resources · Library · Schematic Generator · Simulation · Design Review**. Right-hand AgentRail = chat + changelog + pipeline status.
- **Chat is now a general, multi-session context partner** (no longer changelog-only). Store `gui/state/chats.json` (migrated from legacy `chat.json`); per-session transcript + compaction + a default session that loads on startup; endpoints `/api/chat/sessions/*`. Changelog sits below the chat and is opt-in (only when a design change is explicitly requested).
- **Design Resources tab** ([gui/frontend/src/tabs/Resources.tsx](test1/gui/frontend/src/tabs/Resources.tsx)): Datasheets (lists Parts Library PDFs + upload → `Parts Library/<MPN>/`), Design Requirements (upload pdf/docx/pptx → `test1/resources/requirements/`), Skills (markdown CRUD → `test1/resources/skills/`, meant to later steer chat sessions). Uploads are base64 JSON (no `python-multipart` dep); endpoints `/api/resources/*`.
- **Simulation subsystem**: ngspice-backed, context-first ([test1/sim/](test1/sim/)); agent setup/interpret passes read datasheets+requirements+netlist, cache device/scenario params, interpret results vs spec.

**Branding:** lightning-bolt logo (source `images.png` at repo root) processed to a transparent 256px square at `gui/frontend/public/logo.png`, wired as favicon (index.html) + sidebar brand mark (Sidebar.tsx). ⚠️ **UNCOMMITTED at handoff** (see git state).

**Bobcat VDDIO caps:** a demo had removed C28+C29 from the builder's placement loop; **re-added** in [test1/gen/build_bobcat.py](test1/gen/build_bobcat.py) (loop back to C24–C29). The netlist always defined/wired them; C29 was regrouped next to C28 (committed `3390e41`). Regenerating returns `bobcat.kicad_sch`/PNG to committed state.

**Recent commits (branch `main`, pushed):** `3390e41` C29 regroup · `33b2487` general chat + Design Resources + datasheet icons · `fac0397` GUI layout (proportional/collapse-safe splitters) · `2bc819b` sim subsystem.

**Git state at handoff (uncommitted):** `M gui/frontend/index.html`, `M gui/frontend/src/components/Sidebar.tsx`, `?? gui/frontend/public/` (logo.png), `?? images.png` — i.e. the logo/favicon work is done but not yet committed.

- **New parts going forward**: create `Parts Library/<MPN>/` (test1) or `<project>/datasheets/<MPN>/` and place both `.kicad_sym` and `.pdf`. Never a shared repo-root datasheets dir.
- **Recovery references** (if previous artifacts are ever needed):
  - Phase 1 Electron MVP: commits `d070e42`–`234cd37`.
  - Earlier demo projects (TPS7E72_demo, LNA_LDO_chain, LDO_LNA_Demo) + their part libraries (TPS7E72, SKY67150-396LF, BFC237076104): up to commit `add3cd6`.

## Things explicitly not in the repo

- The KiCad source tree at `~/Downloads/kicad/` (symlinked as `kicad/`, gitignored — too big and machine-specific).
- KiCad build artifacts (`build/`, install paths).
- The user-level `sym-lib-table` (`~/Library/Preferences/kicad/10.99/`) — must be re-registered per machine if the symbol browser is needed.
- `.env*`, `.claude/settings.local.json`, `.vscode/`, `.idea/`.
- KiCad transient files: `.history/`, `*.kicad_prl`, `~*.lck`, `*/render/`, `fp-info-cache`.

## Altium migration — ACTIVE THREAD (started 2026-05-27)

Direction: replicate the test1 KiCad pipeline on **Altium**, enabled by **`github.com/wavenumber-eng/altium_monkey`** — a pure-Python toolkit that reads/writes Altium native binary files (`.SchDoc/.SchLib/.PcbDoc/.PcbLib/.IntLib`), renders SVG, and authors symbols/footprints **without Altium installed or its scripting API**. (Primarily Windows-validated; macOS "basic", Linux limited. Needs Python 3.11–3.12. `.IntLib` extraction-only; some PCB-edit gaps. Binary-format fidelity is the main risk since it's reverse-engineered.)

**Strategy:** keep `netlist/*.yaml` canonical; swap only the KiCad backend. Mapping: KiCad text s-expr ↔ altium_monkey binary read/write; `kicad-cli` render ↔ altium_monkey SVG.
- **Must replace (KiCad-coupled):** `gen/shared.py` (primitives — the core seam), `gen/symbols.py` (pin-coord extraction), `gen/validator.py`, `gen/config.py` (`KICAD_CLI`), `gen/layout_lint.py` (coords), `gen_schematic.py` (render), parts library (`.kicad_sym`→`.SchLib`, `.pretty`→`.PcbLib`, ~21 MPNs).
- **Light touch:** `review/*`, GUI backend (kicad-cli paths, PNG endpoints, agent prompts), sim (net-name mapping).
- **Format-agnostic (no change):** netlist YAML, design_requirements, the React frontend, the chat/Design-Resources work.

**Gate 0 (de-risk before investing):** prove altium_monkey can (1) write a minimal `.SchDoc` (2 parts + wire + net label + power port), (2) **open it in REAL Altium uncorrupted**, (3) render SVG, (4) author a `.SchLib` symbol + `.PcbLib` footprint.

**Hardware reality:** user's Mac is **M4 (Apple Silicon, arm64), macOS 26.3.1**. VMware Fusion/Parallels on Apple Silicon run only Windows 11 ARM, and Altium is x86 → emulated → unsupported/risky. **No good VM path for real Altium on this Mac.** User has a separate **Windows PC, but it's not yet available**.
**Plan agreed:** run the altium_monkey smoke test **on the Mac** for the pure-Python steps (write `.SchDoc`, self round-trip write→read, render SVG, author symbol/footprint); **defer "open in real Altium" to the Windows machine**. The Mac env check (needs Python 3.11–3.12; clone into an isolated spike dir outside this repo + venv) was the immediate next step when this session ended. `gh` CLI is NOT installed.

## OPEN DECISIONS at this handoff (resolve next session)

1. **Project rename to "HW/SW Codesigner" — NOT YET DONE** (user requested, then moved sessions). Display-name strings to change: `gui/frontend/index.html` `<title>` ("test1 — Bobcat Carrier"); `App.tsx` `TAB_TITLES` ("… / test1") + `projectLabel` ("SCH-EVAL..."); `Sidebar.tsx` footer ("test1 · Bobcat carrier"); `gui/frontend/package.json` name ("test1-gui" → "hw-sw-codesigner", slash-free); `README.md` ("# Symbol Library AI"). **KEEP "Bobcat Carrier" as the board name.** Do NOT rename `test1/` paths or `test1.gui.*` localStorage keys (breaks paths / resets saved layouts). Scope still to confirm: UI-only vs full UI+README+package vs also renaming the GitHub repo.
2. **Where Altium work lives:** integrate altium_monkey into this repo vs maintain a separate fork. Unresolved — when asked for an altium_monkey *fork* URL, user pasted their existing `SymbolGenAI` repo (possible conflation); confirm intent.
3. **GitHub repo rename** (SymbolGenAI → hw-sw-codesigner?) is an account action the user does in repo Settings; can't be done from here (no `gh`, no GitHub auth). The git remote auto-redirects after a rename.

## Open suggestions never acted on

- Scaffold the artifact-template files (`spec.yaml`, `parts/<MPN>.json`, `nets.yaml`, `bom.yaml`) and a per-stage skill file so each pipeline chunk has a clear contract. (test1 hard-codes its netlist YAML per sheet — the abstract template is still TBD.)
- Wire the Skills (`test1/resources/skills/*.md`) into chat sessions to actually steer them (currently storage-only).
- Integrate the symbol/schematic generation pipeline into the user's internal platform with its own chat front end (waiting on the user to share that platform).
