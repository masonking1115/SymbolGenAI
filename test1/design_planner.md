# test1 — Design Planner

Working notebook for the Bobcat carrier board. See [design_requirements.md](design_requirements.md) for the locked spec. This file is mutable — append, strike out, and revise as the design evolves.

## Status
- **Stage:** spec → *part fingerprints* (next: symbol generation per MPN)
- **Last updated:** 2026-05-24
- **Blockers:** none — waiting on MPN choices for load switch, EEPROM, and bias DAC(s).

## Pipeline (per README)
- [x] Capture spec → `design_requirements.md`
- [x] Per-part folder structure — `Parts Library/<MPN>/<datasheet>.pdf` (one folder per MPN; symbol + footprint to be added)
- [ ] Part fingerprints — one `.kicad_sym` per MPN under `Parts Library/<MPN>/`
- [ ] Net topology — `nets.yaml` mapping every Bobcat/FMC/peripheral pin to a net
- [ ] BOM — `bom.yaml` with values, packages, refdes
- [ ] Schematic — `test1.kicad_sch` generated via `generate.py`
- [ ] ERC + visual review in eeschema
- [ ] Commit and hand off

## Parts checklist
| Role | MPN | Datasheet on disk | Symbol generated |
|---|---|---|---|
| DUT | Bobcat (custom, 40-QFN) | — (internal) | ☐ |
| Adjustable LDO | TPS7A8401A | ✅ `datasheets/tps7a84a.pdf` | ☐ |
| Load switch | TPS22916CNYFPR | ✅ | ☐ |
| EEPROM (8-Kbit I²C) | 24AA08-I/SN | ✅ | ☐ |
| Bias V-DAC (quad I²C, ext VREF=3.3V) | MCP4728 | ✅ (`22187E.pdf`) | ☐ |
| Bias op-amp (dual RRIO) | OPA2388 | ✅ (`opa2388.pdf`) | ☐ |
| Bias PMOS pass element (high-side) | PMZ1200UPEYL | ☐ **NEED — datasheet was deleted in earlier cleanup** | ☐ |
| Bias R_sense (5.11 kΩ 0.1% thin-film) | TNPW06035K11BEEA | ✅ (`tnpw_e3.pdf` — family doc covers value) | ☐ |
| Bias enable FET (DNP, series NMOS) | 2N7002 | ✅ (`2n7002.pdf`) | ☐ |
| SMA connector | HRM(G)-300-467B-1 (verify is SMA, not MMCX) | ☐ | ☐ |
| FMC LPC (mezzanine side) | ASP-134606-01 (verify; -134604 is the standard LPC mezz) | ☐ (SEAM datasheet on disk is wrong family) | ☐ |
| 1×4 100-mil header | TSW-104-05-G-S | ✅ (`tsw_th.pdf`) | ☐ |
| 1×2 jumper header | TSW-102-05-G-S (+ shunt TBD) | ✅ (`tsw_th.pdf`) | ☐ |
| MLCC 10 µF / 1 µF / 100 nF | CC0805... / GRM155R70J105... / GRM155R71C104... | ✅ | ☐ |
| 0 Ω resistor | CRCW04020000Z0ED | ✅ | ☐ |
| 10 kΩ resistor | CR0402-FX-1002GLF | ✅ | ☐ |
| GND test point | Keystone 5011 | ✅ (`K75p62.pdf`) | ☐ |

## Open design decisions
1. **One LDO vs. three for VDDD/VDDA1/VDDA2.** Single TPS7A8401A means one shared ANY-OUT setpoint; three LDOs allow independent sweeps during bring-up at the cost of BOM/area. *Lean: three for characterization flexibility — confirm with user.*
2. ~~**Bias path: preferred (current DAC) vs. backup (voltage DAC + op-amp + PMOS).**~~ **Resolved 2026-05-24** — V-to-I topology with MCP4728 + dual RRIO op-amp + NMOS + R_sense. See decision-log entry.
3. **FMC LA-pin assignments.** Defer until schematic layout — pick pairs that minimize crossings once the parts are placed.
4. **Bobcat decoupling cap values per rail.** Need vendor recommendation. Placeholder: 100 nF + 1 µF + 10 µF per pin until specified.
5. ~~**Bias polarity (NMOS-sink vs PMOS-source).**~~ **Resolved 2026-05-24** — confirmed against Bobcat PDF page 7; reverted to PMOS high-side. See decision log.

## Next concrete steps
1. Pick MPNs for the four TBD parts above (load switch, EEPROM, bias DAC variants, SMA).
2. Generate a `.kicad_sym` in each `Parts Library/<MPN>/` folder (via the `kicad-symbol-from-datasheet` skill or via Ultra Librarian import).
3. Draft `nets.yaml` mapping:
   - All 40 Bobcat pins (+ EP)
   - FMC LPC power/control pins from the requirements doc
   - LDO, load switch, EEPROM, bias circuit, SMA, header
4. Build BOM with refdes scheme (U for ICs, R/C for passives, J for connectors, JP for jumpers, TP for test points).
5. Run the `kicad-circuit-from-topology` skill to produce `test1.kicad_sch`.
6. Open in eeschema, run ERC, fix any floating nets / unconnected pins.

## Decision log
- **2026-05-24** — **Bias polarity fix: reverted to PMOS high-side; MCP4728 reconfigured for external V_REF=3.3 V; R_sense resized to 5.11 kΩ.** Re-read of Bobcat PDF page 7 confirmed BIASx pins require current sourced INTO the pin from an external high-side source ("Independent programmable current sources... nominally 320 µA at 0.5 V" plus the backup-topology PMOS-from-3.3V description). The NMOS low-side V-to-I from the prior decision would have sunk current the wrong direction. New topology: V_DAC drives op-amp(+); op-amp drives PMOS gate; PMOS source ties to 3.3 V through R_sense=5.11 kΩ and feeds back to op-amp(−); PMOS drain → BIASx. I = (3.3 V − V_DAC) / R_sense → 0–646 µA over V_DAC = 0–3.3 V. MCP4728 EEPROM default 0xFFF (V_OUT=3.3 V → PMOS off → 0 µA at POR). MCP4728 internal 2.048 V reference cannot reach 3.3 V, so external V_REF pin is wired to the 3.3 V rail. *Cost: PMZ1200UPE datasheet was deleted in earlier cleanup and needs to be re-added.*
- **2026-05-24** — **V-to-I bias topology adopted; current-DAC line dropped.** Both BIAS0 and BIAS1 implemented as MCP4728 V-DAC → OPA2388 RRIO op-amp + 2N7002 NMOS + 3.16 kΩ 0.1% thin-film R_sense. Sizing: V_DAC 0–2.048 V (MCP4728 internal ref, gain=1), R_sense 3.16 kΩ → I_FS = 648 µA, 0.16 µA/LSB at 12-bit. Default-off via MCP4728 EEPROM = 0x000 at POR. Optional series enable FET (DNP) for hard isolation. *Rationale: no true I²C current DAC was available that met spec; collapsing to one topology saves BOM and area. MCP4728 already on board (selected by Voltai before the V-vs-I distinction was caught), so the preferred-current-DAC path was redundant.*
- **2026-05-24** — Confirmed LDO is **TPS7A8401A** (not TPS7E72 as initial filename suggested). ANY-OUT range 0.5–2.075 V covers Bobcat's 0.6–1.0 V core rails exactly. *Source: TPS7A84A datasheet, page 1, output voltage range section.*
- **2026-05-24** — `design_requirements.md` scoped to schematic-only; PCB layout requirements (impedance, layer count, mounting, footprint geometry) intentionally omitted.

## Parking lot (revisit later)
- Test point strategy beyond GND clips — add probe points on each Bobcat rail?
- Do we want an on-board USB-I²C bridge for debugging without the Genesys 2, or strictly FMC-only?
- Reverse-polarity / over-voltage protection on VADJ before the load switch?

## Risks
- **TPS7A8401A dropout at 0.6 V output from 3.3 V in:** plenty of headroom (Vin–Vout = 2.7 V), but BIAS pin tied to 3.3 V improves accuracy. Verified covered in datasheet.
- **Bias circuit accuracy at low end (≤10 µA):** 1 µA step over 0–640 µA range is ~10-bit; confirm chosen DAC actually resolves to ~1 µA at full scale.
- **FMC carrier compatibility:** Genesys 2 VADJ is set in firmware (1.2/1.5/1.8/2.5 V typical). Bobcat VDDIO needs match — confirm carrier programs VADJ to the desired Bobcat I/O rail.
