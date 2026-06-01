# test1 — Design Implementation (our build)

This is the **non-normative** companion to `design_requirements.md`. The requirements
doc states WHAT the customer needs (ground truth = the Bobcat slide deck + the
deliverables list). THIS doc records HOW we implemented it: specific part choices,
circuit topology beyond the deck, exact FMC pin assignments, refdes, design
decisions, and the design-review findings. None of this is a customer requirement —
it can change without changing the requirements.

---

## Component selection (our choices)
The deck names only the LDO (TPS7A8401A) and the FMC/socket; the rest are our picks.

| Function | Part chosen | Package | Notes |
|---|---|---|---|
| LDO | TPS7A8401A | VQFN-20 3.5×3.5 mm | named by the customer; ANY-OUT 0.5–2.075 V @ 25 mV covers the required 0.6–1.0 V |
| Bias DAC | MCP4728 (MCP4728T-E/UN) | MSOP-10 | quad 12-bit I²C voltage DAC; external VREF = 3.3 V for rail-to-rail |
| Bias op-amp | OPA2388 (OPA2388IDGK) | VSSOP-8 | dual precision RRIO, zero-drift (alternates: MCP6V52 / TLV9002) |
| Bias pass FET | PMZ1200UPEYL | SOT883 / DFN1006-3 | small-signal PMOS |
| Bias sense R | 3.65 kΩ 0.1% thin-film (TNPW06033K65BEEA) | 0603 | R40/R41 — value is OUR choice (see decision below) |
| EEPROM | 24AA08-I-SN | SOIC-8 | 8-Kbit I²C |
| Load switch | TPS22916CNYFPR | WCSP | gates VADJ → VDDIO |
| FMC connector | ASP-134606-01 | — | VITA 57.1 LPC, 160-pin |
| 0Ω / jumpers / passives | CRCW0402 0Ω, CR0402 series, GRM caps | 0402/0603 | per BOM |

The live BOM is generated from the netlist: `python test1/generate_bom.py` → `test1/test1_bom.xlsx`.

## Bias circuit — as built (deck's backup topology, as drawn)
We implement the deck's **backup** option (I²C voltage DAC → op-amp → PMOS V-to-I
loop), not the preferred current-DAC, because no single off-the-shelf current DAC met
0–640 µA / ~1 µA-step cleanly. Per-channel, exactly as the deck draws it:
- MCP4728 VOUTx → OPA2388 +IN; op-amp OUT → PMOS gate.
- PMOS source → 3.3 V through the 3.65 kΩ sense R; source node also → op-amp −IN.
- PMOS drain → BIASx directly via the 1×2 jumper (no isolation FET).
- I_load = (3.3 V − V_DAC) / R_sense, covering 0–640 µA (~0.16 µA/LSB at 12-bit).

**Off by default (deck requirement) is enforced by the MCP4728 itself:** a virgin/POR
DAC powers up at code 0xFFF → V_OUT = 3.3 V → PMOS gate high → PMOS OFF → 0 µA into
Bobcat. Firmware must program a known/off DAC code before enabling current. This is
the deck's intended mechanism and needs no extra parts.

**History (2026-06-01): the isolation FETs were removed.** An earlier revision added
series NMOS isolators Q42/Q43 (BSS138) + gate pull-downs R44/R45, gated by BIAS_ISO0/1
from the FMC LA bank, as belt-and-suspenders hardware enforcement of "off by default."
That created a spec conflict: the LA bank is VADJ-referenced, so at the deck's 1.2 V
VADJ floor the gate overdrive (~0.7 V) was below any standard NMOS Vth — bias couldn't
turn on across the full VADJ 1.2–3.3 V range the customer requires. Since the FET was
**our** addition (not in the deck) and the DAC POR code already satisfies "off by
default," we removed Q42/Q43/R42–R45 and the BIAS_ISO0/1 FMC signals (R120/R121,
LA20_P/LA21_P now unused) to match the deck and eliminate the conflict (F-3 resolved).

## FMC LPC pinout — as wired (VITA 57.1, Genesys 2 host side)
Rows C/D/G/H × 1–40. Pin *names* mate 1:1 (mezzanine C*n* ↔ carrier C*n*); the
footprint implements the physical mirror, not the netlist. Authoritative per-pin table:
`Parts Library/ASP-134606-01/VITA57.1_FMC_HPC_LPC_SIGNALS_AND_PINOUT.xlsx` (FMCHUB).

### Power & management pins
| Pin(s) | Net | Use |
|---|---|---|
| C39, D36, D38, D40 | 3P3V | EEPROM, LDO Vin, Bias |
| G39, H40 | VADJ (1.2–3.3 V) | load switch → VDDIO |
| D32 | 3P3VAUX | NC |
| C35, C37 | 12P0V | NC |
| H1 | VREF_A_M2C | NC |
| H2 | PRSNT_M2C_L | tie GND on mezzanine |
| C34, D35 | GA0, GA1 | tie per carrier slot (typically GND) |
| D1 | PG_C2M | LDO PG output (C1 is GND — corrected from an earlier C1 misplacement) |

### Control / sideband
| Pin | Net | Use |
|---|---|---|
| C30 | SCL | I²C → EEPROM + Bias |
| C31 | SDA | I²C → EEPROM + Bias |
| D29/D30/D31/D33/D34 | TCK/TDI/TDO/TMS/TRST_L | JTAG — NC unless chained |

### Clocks (LVDS, M2C, available but unused unless noted)
H4/H5 CLK0_M2C, G2/G3 CLK1_M2C, C4/C5 GBTCLK0_M2C, D2/D3 DP0_C2M, D6/D7 DP0_M2C.

### LA bank (signal→LA-index is ours; LA-index→pin is fixed by VITA 57.1)
P pin of each pair, single-ended. See `gen/config.py` `LA_ASSIGN`.
- **Bobcat → FMC LA (via 0Ω):** SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N.
- **FMC LA → Bobcat (via 0Ω, SMA-routable):** OSC_EN, WEIGHT_EN, SAMPLE_TRIG.
- **FMC LA → control:** LDO EN, ANY-OUT setpoints (LDO_SET_*), load-switch EN. (The
  former bias-isolation enables BIAS_ISO0/1 on LA20_P/LA21_P were removed with the
  isolation FETs; those LA pins are now unused.)

LA-pair locations (CC = clock-capable):
- Row C: C10/C11 LA06, C14/C15 LA10, C18/C19 LA14, C22/C23 LA18_CC, C26/C27 LA27
- Row D: D8/D9 LA01_CC, D11/D12 LA05, D14/D15 LA09, D17/D18 LA13, D20/D21 LA17_CC, D23/D24 LA23, D26/D27 LA26
- Row G: G6/G7 LA00_CC, G9/G10 LA03, G12/G13 LA08, G15/G16 LA12, G18/G19 LA16, G21/G22 LA20, G24/G25 LA22, G27/G28 LA25, G30/G31 LA29, G33/G34 LA31, G36/G37 LA33
- Row H: H7/H8 LA02, H10/H11 LA04, H13/H14 LA07, H16/H17 LA11, H19/H20 LA15, H22/H23 LA19, H25/H26 LA21, H28/H29 LA24, H31/H32 LA28, H34/H35 LA30, H37/H38 LA32

All other C/D/G/H pins are **GND** per the standard — **61 GND pins** (all wired to the
GND net; FMC GND net = 64 members incl. the 3 strap pins):
C1,C4,C5,C8,C9,C12,C13,C16,C17,C20,C21,C24,C25,C28,C29,C32,C33,C36,C38,C40,
D2,D3,D6,D7,D10,D13,D16,D19,D22,D25,D28,D37,D39,
G1,G4,G5,G8,G11,G14,G17,G20,G23,G26,G29,G32,G35,G38,G40,
H3,H6,H9,H12,H15,H18,H21,H24,H27,H30,H33,H36,H39.

### ANY-OUT setpoint bit weights (TPS7A8401A low-range — base 0.5 V, 25 mV/LSB)
Net names use the TRUE 8401A weight (corrected from 8400A high-range labels, 2026-05-31).
| U10 pin | Net | Weight | FMC LA |
|---|---|---|---|
| 5 | LDO_SET_25mV | 25 mV | LA22_P G24 |
| 6 | LDO_SET_50mV | 50 mV | LA23_P D23 |
| 7 | LDO_SET_100mV | 100 mV | LA24_P H28 |
| 9 | LDO_SET_200mV | 200 mV | LA25_P G27 |
| 10 | LDO_SET_400mV | 400 mV | LA26_P D26 |
| 11 | LDO_SET_800mV | 800 mV | LA27_P C26 |
VOUT 0.6 V = 0.5 + 0.1 → ground pin 7. VOUT 1.0 V = 0.5+0.4+0.1 → ground pins 10, 7.

## Design decisions / history
- **Bias polarity (2026-05-24):** confirmed against the deck (p7) that current is sourced
  INTO BIASx → PMOS high-side topology.
- **Shared-rail LDO (E8):** one TPS7A8401A feeds VDDD/VDDA1/VDDA2 through 3×1×2 jumpers,
  all tapping the same LDO output bus (installing >1 shorts the rails to one voltage) —
  intentional (all three rails track together during sweep). For independent setpoints,
  replicate the LDO block 3×.
- **FMC LA pinning (corrected 2026-05-27):** rows C↔D / G↔H were transposed in an early
  revision (signals on GND pins, +3V3/VADJ shorted); corrected to real LPC P-pin positions.
- **Sense R 5.11 kΩ → 3.65 kΩ (2026-05-30):** at 5.11 kΩ the regulated full-scale capped
  ~484 µA (failed the ≥640 µA spec — I·R left no headroom over the 0.5 V compliance).

## Assembly / provisioning notes
- **MCP4728 EEPROM / bias off-by-default (W8) — now the SOLE fail-safe (no isolation FET):**
  A *factory-virgin* MCP4728 ships with internal VREF=2.048 V and EEPROM code 0x000,
  which would drive the PMOS toward full-on at POR. The deck's off-by-default mechanism
  is the DAC code at the rail (0xFFF with VREF=VDD → V_OUT=3.3 V → PMOS off), so the part
  **must be EEPROM-provisioned to VREF=VDD + code 0xFFF before/at board bring-up.** Boot
  sequence: read EEPROM → if not already safe, program VREF=VDD & codes=0xFFF → write the
  desired DAC code → bias flows. Because there is no longer a hardware isolation FET, this
  EEPROM provisioning is what guarantees ~0 bias at power-on (verified by the por_failsafe
  sim, which assumes the safe code). Pre-program the MCP4728 EEPROM as a build/assembly step.
- **I²C pull-ups (W4):** R60/R61 (2.2 kΩ to +3V3) are local SCL/SDA pull-ups; DNP them if
  the Genesys 2 carrier already pulls the bus, to stay within IOL.

## Design-review findings (EXTERNAL_REVIEW_2026-05-31)
Full notes: `test1/review/EXTERNAL_REVIEW_2026-05-31.md`. Status as of 2026-06-01:
- **F-1 (GND pins floating) — RESOLVED.** All 61 LPC GND pins wired (FMC GND = 64 members).
- **F-1b (PG_C2M on wrong pin) — RESOLVED.** LDO_PG moved C1 → D1.
- **F-2 (LDO setpoint names 8400A vs 8401A) — RESOLVED.** Renamed to true 8401A weights.
- **F-4 (stale BOM) — RESOLVED.** Regenerated (R40/R41 = 3.65k/TNPW06033K65BEEA).
- **F-6 (footprint vs datasheet) — RESOLVED.** MSOP-10 / VSSOP-8 / SOT883.
- **F-3 (bias NMOS gate drive at low VADJ) — RESOLVED by removal (2026-06-01).** The
  isolation FET was *our* addition, not in the deck, and it was the source of the
  VADJ≥2.5 V conflict. Reverted to the deck's literal backup topology (PMOS drain →
  BIASx directly); off-by-default is now the MCP4728 POR/EEPROM code. Bias works across
  the full VADJ 1.2–3.3 V range. Removed: Q42/Q43, R42–R45, BIAS_ISO0/1 (R120/R121),
  and the matching rules; sim por_failsafe re-grounded to the DAC mechanism (passes).
  Tradeoff: POR safety now depends on EEPROM provisioning (see assembly notes W8).
- **F-7 (no post-jumper bulk decap) — RESOLVED (2026-06-01).** Added 10 µF post-jumper
  bulk caps C44/C45/C46 at the DUT-side +VDDD / VDDA1-path / VDDA2-path rails. (Numbered
  C44+ to avoid a refdes clash — C30 is already the EEPROM-sheet decap.)
- **F-5 (no gate-stop R, MEDIUM) — DEFERRED to an AC/step sim.** A gate-stop R fixes a
  stability problem not yet demonstrated (the bias loop runs at slow I²C rates). Removing
  the isolation FET simplified the loop, so the right trigger is a bias-loop AC/step sim
  on the as-built loop; add 100 Ω–1 kΩ series gate R only if the sim shows it's needed.
