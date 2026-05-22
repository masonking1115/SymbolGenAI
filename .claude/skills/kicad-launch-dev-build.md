---
name: kicad-launch-dev-build
description: Launch KiCad's schematic editor (eeschema) and run `kicad-cli` against the user's local dev build at `/Users/masonking/Downloads/kicad/build/`. Use whenever the user asks to "open in KiCad", "load in eeschema", "view the schematic", run ERC, or render/validate a `.kicad_sch` or `.kicad_pro`. The project manager (`KiCad.app`) is broken on this machine — this skill documents the working paths so you don't rediscover the same failures.
---

# Launching KiCad from this machine's dev build

The user has a partial dev build of KiCad at `/Users/masonking/Downloads/kicad/build/`. **It is NOT a complete KiCad installation.** Only some components were built. Do not try `open -a KiCad.app`, do not try `brew install kicad` unless the user explicitly asks — go straight to the working binaries below.

## What's built (and what isn't)

```
/Users/masonking/Downloads/kicad/build/
├── kicad/KiCad.app/                   ← Project manager — BROKEN (missing _pcbnew.kiface)
│   └── Contents/
│       ├── MacOS/{kicad, kicad-cli}   ← kicad-cli WORKS; kicad GUI does not start
│       └── PlugIns/_eeschema.kiface   ← (only this one kiface exists)
├── eeschema/eeschema.app/             ← Standalone schematic editor — WORKS
│   └── Contents/
│       ├── MacOS/eeschema
│       └── PlugIns/_eeschema.kiface
├── resources/images.tar.gz            ← Icons resource — referenced by bundles but NOT installed into them
└── pcbnew/, gerbview/, pl_editor/, …  ← .app shells exist but contain no MacOS binary
```

**Working:** `kicad-cli` (validation, SVG/PDF export, sym upgrade) and standalone `eeschema.app` (open/edit/save `.kicad_sch`).

**Not working:** `KiCad.app` project manager (refuses to start without `_pcbnew.kiface`), `kicad-cli sch erc` (needs `_cvpcb.kiface` at runtime — load fails), and every other editor (pcbnew, gerbview, pl_editor, pcb_calculator, bitmap2component).

## To open a schematic in eeschema

```sh
# First time only — link images.tar.gz into the eeschema bundle (idempotent):
RES=/Users/masonking/Downloads/kicad/build/eeschema/eeschema.app/Contents/SharedSupport/resources
mkdir -p "$RES" && ln -sf /Users/masonking/Downloads/kicad/build/resources/images.tar.gz "$RES/images.tar.gz"

# Launch:
open -a /Users/masonking/Downloads/kicad/build/eeschema/eeschema.app /path/to/file.kicad_sch
```

Pass the `.kicad_sch` (not `.kicad_pro`) — eeschema opens schematic files directly without needing the project manager.

If a stale `KiCad.app` process is still hanging from a prior failed launch:
```sh
pkill -f "KiCad.app/Contents/MacOS/kicad" ; sleep 1
```

## To validate / render a schematic (no GUI)

`kicad-cli` is the workhorse. It works with no bundle setup.

```sh
KICAD_CLI=/Users/masonking/Downloads/kicad/build/kicad/KiCad.app/Contents/MacOS/kicad-cli

# Validate a symbol library:
"$KICAD_CLI" sym upgrade --force <file>.kicad_sym
# Success prints: "Saving symbol library in updated format"

# Render a schematic to SVG (also serves as a parse check):
"$KICAD_CLI" sch export svg --output <dir> <file>.kicad_sch
# Success prints: "Plotted to … Done."

# Render to PDF (small files — good for inline review in chat via Read tool):
"$KICAD_CLI" sch export pdf --output <out.pdf> <file>.kicad_sch
```

Do NOT run `kicad-cli sch erc` — it requires `_cvpcb.kiface` which doesn't exist in this build and fails with a `dlopen` error. Rely on the SVG/PDF export to catch parse failures and visually verify connectivity.

## Common error messages and what they actually mean

| Error | Meaning | Fix |
|---|---|---|
| `can't open file '…/SharedSupport/resources/images.tar.gz'` | Bundle missing icons | Symlink `build/resources/images.tar.gz` into the bundle (see above) |
| `Failed to load … _pcbnew.kiface` | Project manager refuses to start | Use `eeschema.app` instead — never `KiCad.app` |
| `Failed to load … _cvpcb.kiface` | `kicad-cli sch erc` invoked | Skip ERC; use SVG export for parse check |

## Why not install official KiCad?

You may ask, but the user has historically chosen to keep the dev build. Do not install Homebrew KiCad unless the user explicitly requests it — they want to work with the local source tree.

## What to tell the user when "open in KiCad" is asked

Just launch `eeschema.app` directly with the `.kicad_sch` and report it's up. No need to explain the bundle gymnastics — they know their setup is unusual.
