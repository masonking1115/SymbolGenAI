---
name: altium-launch-and-verify
description: Open the generated Altium project in real Altium Designer (AD26) on this Windows machine, render/preview sheets without the GUI, and run the unattended real-Altium verification oracle that diffs altium_monkey output against Altium's own SCH API. Use whenever the user asks to "open in Altium", "load the design", "view the schematic", validate/verify a .SchDoc or .PrjPcb, or check binary fidelity.
---

# Launching & verifying Altium on this machine

This Windows 11 PC is the Altium-capable machine. **Altium Designer AD26 is installed + licensed** at `C:\Program Files\Altium\AD26\X2.EXE`. The pure-Python `altium_monkey` toolkit (in the spike venv at `C:\Users\mking\Downloads\altium_spike\.venv`) authors the binary files; real Altium is only needed to open/compile/verify them. See [[altium-migration-windows]].

## The three things "open / view / verify" can mean

### 1. Open in real Altium (interactive)
Launch Altium Designer with the project and let the user look at it / compile it:

```powershell
& "C:\Program Files\Altium\AD26\X2.EXE" "c:\Users\mking\Downloads\HW-SW_CoDesigner\SymbolGenAI\test1\altium\out\test1.PrjPcb"
```

Pass the `.PrjPcb` (the project) so Altium loads all sheets and can **Project → Compile** to resolve cross-sheet net names (single-sheet `to_netlist` does not propagate signal-port names — compile is how you verify cross-sheet connectivity). For a single sheet, pass the `.SchDoc`.

After launching, just report it's up — don't poll the process or run verification commands the user didn't ask for. Altium is **single-instance**, and the verify oracle (below) kills `X2.EXE` on exit — so **close all Altium before running the oracle**, and never run the oracle while the user has Altium open for real work.

### 2. Preview without Altium (the fast loop)
Real Altium takes ~30 s to launch and is heavyweight. For an iteration loop, render the sheet SVG instead:
- `AltiumSheet.render_svg(path)` (or `build_project`) writes `out/render/<sheet>.svg`. The GUI serves these as `image/svg+xml`; an `<img>` renders them fine.
- To rasterize for the agent to *see* it: the dev-only `test1/altium/_render.py` does SVG → reportlab PDF → pymupdf PNG (cairo is NOT available on Windows, so the direct SVG→PNG path doesn't work; `pymupdf` + `reportlab` are installed in the spike venv).
- **Caveat:** altium_monkey's SVG renderer **ignores power-port orientation** (it draws the same glyph regardless of 90°/270°). The binary stores orientation correctly, so real Altium renders GND-down / rails-up right — but the SVG preview won't show the rotation. Don't "fix" orientation based on the SVG.

### 3. Verify binary fidelity (the real-Altium oracle)
`test1/altium/verify/run_altium_verify.py` drives real Altium AD26 **unattended**: it generates a DelphiScript + `.PrjScr`, has Altium enumerate every object through its own SCH API, and diffs the counts against altium_monkey's reader. This is the one fidelity check altium_monkey cannot self-perform (the binary format is reverse-engineered).

- Gotcha: `RunScript` needs `ProjectName=<.PrjScr>|ProcName=<module>Proc` — a bare `FileName=` is silently ignored.
- It launches Altium ~30 s, runs headless-ish, self-exits, and the harness kills `X2.EXE` on exit. **Close all Altium first.**
- **Verified result:** real Altium opens altium_monkey `.SchDoc` files uncorrupted and agrees on components / wires / ports / power_ports / net_labels / no_erc. The **only** divergence is **junctions**: altium_monkey can't emit a junction real Altium keeps (a bare one is dropped; one with Color breaks altium_monkey's own reader — an upstream write bug, repro at `out/junction_repro.SchDoc`). The migration is unaffected: connectivity rides T-intersections (Altium auto-junctions) + pins, and 4-way crossings are forbidden by the linter. Full detail in `test1/altium/verify/FINDINGS.md`.

## Native ERC
Altium-native ERC isn't run automatically — it needs a fragile scripted compile and is noisy on single-member port nets. Let the user **Project → Compile** in the open GUI when they want ERC. The build-time gates are `gen.validator` (connectivity) + `layout_lint` (geometry) — see [[altium-circuit-from-topology]].

## What to tell the user when "open in Altium" is asked
Launch `X2.EXE` with the `.PrjPcb` and report it's up. Mention they can Project → Compile for ERC / cross-sheet net resolution. Don't explain the oracle plumbing unless they ask to verify fidelity.
