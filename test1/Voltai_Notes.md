# Voltai Notes — test1

User feedback log for the Bobcat carrier-board design. Mason uses the Voltai parts-explorer AI alongside this SymbolLibraryAI workflow; this file captures how the two tools are being used together, what worked, what didn't, and any cross-tool decisions.

Append new entries at the top. Date every entry.

---

## 2026-05-24 — Parts Library folder structure + Ultra Librarian extraction workflow
- **Folder layout:** `test1/Parts Library/<MPN>/` per part, holding `<MPN>.kicad_sym` + `<MPN>.pretty/*.kicad_mod` + `<MPN>.pdf`. Self-contained per part; replaces the flat `datasheets/` folder.
- **UL coverage survey:** every catalog BOM part (18/18 non-DUT) exists on Ultra Librarian. Google `site:ultralibrarian.com` indexing is patchy — for ground truth use `https://app.ultralibrarian.com/search?queryText=<MPN>` (returns the real per-MPN hit list).
- **Orderable-suffix gotcha:** UL stores ICs by orderable variant, not the bare family name. Mapping at download time: `TPS7A8401A` → `TPS7A8401ARGRR`, `MCP4728` → `MCP4728-E/UN`, `OPA2388` → `OPA2388IDR`.
- **UL download flow is manual:** UL is auth-gated + JS-driven, so Claude cannot fetch the zips itself. User downloads, drops zips at `Parts Library/` root, Claude unzips into the matching MPN folder.
- **UL zip structure:** `KiCADv6/<timestamp>.kicad_sym` + `KiCADv6/footprints.pretty/*.kicad_mod` + boilerplate (`readme.txt`, `ImportGuides.html`). Symbol filename is auto-timestamped — rename to `<MPN>.kicad_sym` on extract. **No 3D STEP** in any default drop; STEP is a separate UL download selection.
- **Vendor-mismatch risk:** UL serves multiple manufacturer entries for generic MPNs (2N7002 listed under onsemi, Nexperia, Diodes Inc, **Diotec**). The first 2N7002 zip pulled was Diotec and contained a `Diode-NC_pin` symbol, not a MOSFET. After every extract, verify with `grep -o '(symbol "[^"]*"' <MPN>.kicad_sym | head -1` — the symbol's internal name must plausibly match the device.
- **Format validation:** run `kicad-cli sym upgrade --force <MPN>.kicad_sym` per drop to confirm KiCad 10 parse. UL ships KiCad v6 format; upgrade is a one-shot per drop and catches malformed files early.
- **Status:** 16/18 catalog parts populated. Still pending UL drops: `PMZ1200UPEYL` (bias PMOS Q1/Q2) and `CC0805KFX7R6BB106` (10 µF bulk MLCC). `Bobcat` (DUT) is custom — no UL entry, will need a hand-built symbol.

## 2026-05-24 — Parts selection workflow established
- Copied the per-row prompts from the rightmost column of [test1_bom.xlsx](test1_bom.xlsx) into the Voltai parts-explorer AI.
- **Default selection authority:** Voltai parts-explorer AI selects all parts for this design unless explicitly overridden.
- Selections returned by Voltai should be entered back into `test1_bom.xlsx` (Manufacturer / MPN / Distributor P/N / Datasheet URL columns).

## 2026-05-24 — Bias polarity fix: NMOS low-side reverted to PMOS high-side
- Cross-check against the only Bobcat spec we have ([External] Bobcat Board Design.pdf, page 7) showed the BIASx pins require current SOURCED INTO the pin from a high-side source. Quote: *"Independent programmable current sources for BIAS0 and BIAS1 (nominally 320 µA at 0.5 V)"* with the backup topology drawn as PMOS-from-3.3V → BIASx.
- The prior NMOS low-side V-to-I would have sunk current the opposite direction — wrong polarity for Bobcat.
- BOM changes applied to fix:
  - Q1/Q2: 2N7002 (NMOS) → **PMZ1200UPEYL (PMOS)** — restores the original Voltai pick.
  - R_sense: TNPW06033K16BEEA (3.16 kΩ) → **TNPW06035K11BEEA (5.11 kΩ)** — resized so I_FS = 3.3 V / 5.11 kΩ ≈ 646 µA over a 0–3.3 V V_DAC range.
  - MCP4728: configure external V_REF input tied to 3.3 V (NOT the internal 2.048 V ref) so the DAC output can reach 3.3 V and fully shut off the PMOS at I=0.
  - MCP4728 EEPROM default code: 0x000 → **0xFFF** (V_OUT = 3.3 V → PMOS off → 0 µA at POR).
  - Qen1/Qen2 (DNP) stays NMOS as a series pass switch on the high-side current path; no part change.
- Datasheet needed: **PMZ1200UPE.pdf** (was deleted in earlier stale-datasheet cleanup before the polarity issue surfaced; needs to be re-added). All other bias-loop datasheets remain valid (opa2388.pdf, tnpw_e3.pdf covers the new resistor value, 2n7002.pdf for the enable FET).

## 2026-05-24 — V-to-I bias topology supersedes both Voltai DAC picks
- Voltai picked **MCP4728** (quad voltage DAC) for the "Current DAC (preferred bias)" line and **LTC2633** (dual voltage DAC) for the "Voltage DAC (backup bias)" line. Both are voltage DACs.
- Cross-reference flagged the mismatch: MCP4728 cannot drive BIASx as a current source — it only fits the backup transconductance topology. That left no current-DAC pick and a redundant second voltage DAC.
- **Resolution:** collapse to a single bias topology using the MCP4728 already on the board. Both BIAS0 and BIAS1 implemented as V-DAC → op-amp + NMOS + R_sense (I_load = V_DAC / R_sense).
- BOM changes applied:
  - Dropped the LTC2633 line entirely (U6).
  - Reduced MCP4728 from qty 2 (U4/U5) to qty 1 (U4) — uses 2 of 4 channels.
  - Op-amp changed from OPA2376 → **OPA2388** (lower Vos, better accuracy at low bias currents). Alternates: MCP6V52, TLV9002.
  - PMOS pass element (PMZ1200UPEYL) replaced with **NMOS (2N7002 / BSS138)**. Topology is now low-side.
  - Added R_sense line: 2× 3.16 kΩ 0.1% thin-film 0603 (sets I_FS = 648 µA, 0.16 µA/LSB).
  - Added optional DNP enable FET line for hard hardware isolation.
- Action item for parts agent: select the new R_sense MPN (prompt added to BOM row). Datasheets for OPA2388 and 2N7002 still need to be dropped into `datasheets/`.

## 2026-05-24 — Claude is ~5× faster than Voltai on part-selector queries
- For the BOM agent prompts, Claude returns a candidate MPN in roughly **1/5 the wall-clock time** Voltai takes.
- Combined with the context-retention advantage logged below, this strengthens the case for Claude as the primary driver and Voltai as a secondary cross-check rather than the lead source.

## 2026-05-24 — Claude Code is the primary chat surface, Voltai is the parts oracle
- Preferring **Claude Code over Voltai for the conversational driver of a design**.
- **Why:** Claude Code retains continuous context across the session (and via memory across sessions), which matters when a design unfolds over many decisions that reference earlier ones. Voltai sessions feel noisy when jumping between them — the context doesn't carry, so each new query re-explains background.
- **Practical split:** Claude Code = design conversation, file edits, planning, schematic generation. Voltai = parts oracle for individual MPN lookups, fed by the BOM prompts.
- Implication: when a part decision needs design context (e.g., "given how we're using the LDO, does this MPN fit?"), ask Claude Code; when it's a pure spec-to-part lookup, Voltai is fine.

## 2026-05-24 — Three-way benchmarking added to parts selection
- After creating the blank BOM with prompts, for **every** prompt I'm running it through three sources in parallel:
  1. **Voltai parts explorer** in **global** mode
  2. **Voltai knowledge agent**
  3. **Claude**, asked independently (outside this project context)
- Goal: cross-check Voltai's recommendations against an unrelated reasoning source and against Voltai's own knowledge mode, so I can spot disagreements before committing an MPN to the BOM.
- Convergence (all three pick the same / equivalent part) → high confidence, log and move on.
- Divergence → note the candidates here and reconcile before filling in `test1_bom.xlsx`.

---

## Open feedback / observations
<!-- Use this section to capture in-flight thoughts that haven't been resolved yet. Promote to a dated entry once acted on. -->

-

---

## Things to revisit
<!-- Items that depend on a Voltai response or a downstream step. -->

-
