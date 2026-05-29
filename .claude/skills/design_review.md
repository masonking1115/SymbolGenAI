---
name: design-review
description: Review the design (the netlist YAML + built Altium .SchDoc/.PrjPcb) against (a) the datasheets of every IC, MOSFET and passive, and (b) the project-level design_requirements.md. Cross-references the two and emits an error_log.md of failures (must-fix) and warnings (should-fix). Never edits the design — output is read-only.
---

# Schematic design review (functional + requirements)

Use when the user asks to "review" / "audit" / "check" the design against its datasheets and/or requirements doc. Produces an `error_log.md` listing every deviation, grouped by component and severity. **Do not edit the design.** This is a read-only audit.

> The connectivity source of truth is `netlist/<sheet>.yaml` (read it via
> `gen.netlist.load_netlist`, the same loader the generator and `review/`
> package use). The built `test1/altium/out/<sheet>.SchDoc` shows what was
> actually wired (open with `AltiumSchDoc(path)` and trace pins/wires/power
> ports). Review the YAML + built design, NOT KiCad `.kicad_sch` files — the
> KiCad backend was removed. This skill is the human-judgement audit; the
> Voltai-PDF ingest path (`_review_incoming/` → `review/findings.json` →
> `review/fix_queue.json`) and its agent-loop are in [[review-fix-queue]].

## Inputs
- **Netlist YAML** (`test1/netlist/<sheet>.yaml`) — the declared connectivity per sheet.
- **Built design** (`test1/altium/out/<sheet>.SchDoc` + `out/test1.PrjPcb`) — what was actually generated/wired.
- **`design_requirements.md`** — board-level spec, pin assignments, jumper/header layout, BOM constraints, design rationale.
- **Per-part datasheets** — PDFs in the `Parts Library/<MPN>/` layout.
- **Top-level reference PDF** (e.g. an "External Bobcat Board Design.pdf") that may carry application-circuit guidance the datasheets alone don't.

If any of these are missing, ask the user to point at them before starting. Don't infer requirements from the design itself — that defeats the purpose of a review.

## Two-pass review structure

### Pass 1 — Functional correctness against datasheets (per-component)
For **each IC, FET, and bias passive** in the schematic, open its datasheet and verify:
1. **Power pins** — every VDD/VCC/AVDD/BIAS pin is at the correct rail, within Vin spec, with the datasheet-mandated decoupling cap value(s) close to the pin.
2. **Ground pins** — every GND pin tied to GND; exposed pads / thermal pads tied to GND (or whatever the datasheet specifies).
3. **Open-drain / open-collector outputs** — pull-up to the correct rail present.
4. **Reference / bypass pins** — NR_SS, BIAS, VREF, REXT, etc. — connected per datasheet (correct cap value, correct resistor, correct rail).
5. **Configuration / mode pins** — strap pins (e.g. TPS7A8401A ANY-OUT, /LDAC, address pins, /CS, /WP, mode select) match the intended configuration.
6. **NC pins** — explicit `(no_connect …)` markers on every pin the datasheet calls out as NC. Never wire NC.
7. **Polarity** — for active devices, confirm current/voltage direction: e.g., bias-current sources sourcing INTO vs sinking OUT of a pin per the chip's pin definition.
8. **Pinout symbol vs datasheet** — every symbol's pins (read via `symlib.read_pins(mpn)` on `Parts Library/<MPN>/<MPN>.SchLib`, or from the placed component) match the datasheet pin table by number and name. Symbol-library bugs are common (especially UL-sourced parts); verify at least the power and signal pins.

### Pass 2 — Correctness against design requirements
For **each top-level requirement** in `design_requirements.md`, verify:
1. **Required parts present** — every part the requirements call out exists in the schematic. Flag missing parts.
2. **Required passives present** — every pull-up, pull-down, series resistor, decoupling cap, and jumper that the requirements name is actually instantiated. Grep for value strings (`10k`, `0`, etc.) and count instances.
3. **Required net routing** — when requirements say "X via 0Ω to Y" or "A through jumper to B", trace the actual wires/labels to confirm. Don't accept matching net names alone — confirm the topology (series-R between two endpoints, etc.).
4. **Connector pin assignments** — every connector pin called out in requirements is wired to the named net (e.g., FMC C36/C38/C40/D39 = +3V3).
5. **Configuration values** — default settings, EEPROM defaults, ANY-OUT codes, etc. that the requirements specify match the wiring.
6. **Block diagram correspondence** — the implementation matches the topology described in the requirements (e.g., "VADJ through load switch to VDDIO" — verify VADJ is on the switch input and VDDIO is on the output).

### Cross-reference step
For every Pass-1 finding, check whether the datasheet **and** the requirements concur or disagree. When they disagree, treat the requirements as authoritative for the design intent — but note the datasheet conflict explicitly so the user can decide. When they concur, the deviation is unambiguous and goes to the error log.

## Severity rules

| Severity | Definition | Examples |
|---|---|---|
| **ERROR** | Board will not function, or will malfunction in a way that risks the DUT. Must fix before fab. | Required pull-up missing on open-drain PG; required bias current sourced from wrong rail; required SPI bus has no route to host; power pin tied to wrong rail. |
| **WARNING** | Board may function but violates a stated requirement, datasheet recommendation, or best practice. Should fix. | Static configuration where requirement said "FPGA-driven"; one bypass cap per N power pins instead of one per pin; missing pull-up on an off-board signal that the host *might* provide. |
| **INFO** | Observation worth noting but not actionable as a fix. | DNP-by-value-text vs DNP-by-symbol-flag mismatch; unused DAC channels NC'd; jumper interlock advisory. |

## Output format (`error_log.md`)

Single markdown file at the project root. Structure:

```markdown
# Design Review Error Log — <project name>

Date: YYYY-MM-DD
Reviewed against:
- <list of datasheets, with relative paths>
- <design_requirements.md>
- <board-level reference PDF if any>

## Summary
- N ERRORs
- N WARNINGs
- N INFOs

## ERRORs (must fix)

### E1. <short title>
**Component(s):** Refdes(s) and sheet(s)
**Requirement / datasheet reference:** quote-and-cite (file:line or page)
**Observed:** what the schematic actually does (with file:line)
**Impact:** what breaks
**Fix:** one-line suggestion (no code change — describe only)

### E2. …

## WARNINGs (should fix)

### W1. …

## INFOs

### I1. …

## Cross-references
A small table of every Pass-1 finding mapped to the requirement(s) it conflicts with, for traceability.
```

## Process checklist (do these in order)

1. **Enumerate the BOM** — walk every `netlist/<sheet>.yaml` (`parts:` block) and list every refdes with its lib_id, value, units, and DNP-by-value. Cross-check against the built `.SchDoc` if you need to confirm what was actually placed.
2. **Read the requirements doc** in full — extract every numeric spec, every required passive, every pin assignment into a checklist.
3. **Open the top-level reference PDF** — extract pinout tables and any application-circuit notes that supersede or augment the per-IC datasheets.
4. **For each IC**, open its datasheet and walk pins 1..N; verify per Pass-1 rules.
5. **For each requirement bullet**, verify per Pass-2 rules. Grep the schematic for value strings (`10k`, `0`, `2.2k`, `0.1uF`, …) and component counts to catch missing passives.
6. **Trace every cross-sheet port and power port** — verify each named net has a driver and at least one sink, on the sheets the requirements expect. A port appearing on only one sheet with nothing to pair it on the root/other sheets is usually missing wiring, not an intentional NC. (Reminder: altium_monkey's single-sheet netlister doesn't resolve signal-port names — confirm cross-sheet nets against the `.PrjPcb`, or against the netlist YAML which is the declared truth.)
7. **Write `error_log.md`** at project root. Be specific: cite `file:line` for every observation.
8. **Do not edit the schematic.** Tell the user the log is ready and let them choose what to fix.

## Tips and gotchas

- **Symbol-library bugs are common.** UL-sourced symbols sometimes mislabel power pins or omit ANY-OUT pins. Always cross-check pin numbers against the manufacturer datasheet.
- **Open-drain pins need pull-ups.** TPS7A8401A PG, I²C SDA/SCL, MCP4728 RDY/BSY — all need explicit pull-ups; "the host provides one" is a hope, not a design.
- **Ports with no wire** on one sheet still parse but dangle. Confirm both ends of every cross-sheet net (port on each side, plus the root sheet entry) actually have wires; grep the netlist YAML to see which sheets a net is declared on.
- **A cross-sheet net named on only one sheet** is dangling. Check each net name appears on every sheet the requirements expect.
- **DNP-by-value-text vs DNP convention** — confirm a part meant to be Do-Not-Populate is marked consistently. Flag any disagreement so the user picks a convention.
- **Stacked power symbols** at the same coordinate (test point + GND symbol overlaid) are easy to miss visually — confirm by reading the netlist/`.SchDoc`, not just looking at the rendered SVG.
- **Series 0Ω cap placement** — for a "decoupling + series-R" pair, the decoupling cap should be on the IC side of the 0Ω, not the supply side. Verify.
- **FMC connector standards** — the LPC/HPC variants assign specific pins to specific power/management functions; don't trust requirements doc tables blindly, cross-check against VITA 57.1.

## When to stop and ask

If the schematic and requirements deeply disagree on architecture (e.g., requirements say PMOS high-side, schematic has NMOS low-side), don't try to reconcile silently — surface the conflict to the user before logging, since one of the two documents may simply be out of date.
