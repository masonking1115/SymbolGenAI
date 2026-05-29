# CLAUDE.md

**New here? Read [ONBOARDING.md](ONBOARDING.md) first** — it ramps you from zero
to running the full pipeline and lists the landmines. Then
[PROJECT_MEMORY.md](PROJECT_MEMORY.md) for depth.

## The one thing to know before touching anything

This is **Altium** tooling (pure-Python `altium_monkey`), **not KiCad**. The
KiCad backend was removed. Any `.kicad_sym` / `.kicad_sch` / `eeschema` /
`kicad-cli` reference describing the *active* pipeline is stale — ignore it as
current instruction.

## Critical conventions (full detail in ONBOARDING.md / PROJECT_MEMORY.md)

- **Run everything with the venv interpreter** (not bare `python`):
  `C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe`
- **Build + regression-check:** `… -m test1.altium.build_project` from the repo
  root. Green = `FAILURES: none` and every sheet `0/0/0`.
- **Change flow:** edit `netlist/<sheet>.yaml` and/or `altium/build_<sheet>.py`
  and/or a `.SchLib`, then rebuild. **Never hand-edit `out/` or `.SchDoc`
  binaries.**
- **Don't weaken the linter** (`test1/altium/layout_lint.py`) — only add `_check_*`
  rules or refine a threshold with evidence (lint-first iteration).
- **Coordinates:** mils, Y-up, 100-mil grid, chip-pin-relative routing. Paper uses
  Altium's real frame sizes, not ISO.
- Commit/push only when the user asks.
