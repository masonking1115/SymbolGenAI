# test1 — Design Requirements

## Application
Bobcat test chip carrier board. Plugs into the FMC connector of a Genesys 2 platform to break out and exercise Bobcat — a 40-pin QFN (5×5 mm, 0.4 mm pitch, exposed GND pad 41) — for bring-up and characterization.

## Specs
- **Power in (from FMC):** 3P3V (to EEPROM, LDO, Bias); VADJ 1.2–3.3V (to Bobcat VDDIO via load switch). 12P0V available but unused.
- **Bobcat rails:** VDDD, VDDA1, VDDA2 = 0.6–1.0V (from on-board LDO); VDDIO = VADJ (via load switch + jumper)
- **Interfaces:** SPI (CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N), I²C (EEPROM + Bias), GPIO0–3
- **Signal outputs:** CLK_OUT0–3, SAMPLE_OUTV, SAMPLE_OUT0–7, OSC_EN, WEIGHT_EN, SAMPLE_TRIG
- **Bias outputs:** BIAS0, BIAS1 — independent programmable current sources, 0–640 µA, ~1 µA step (nominal 320 µA @ 0.5 V)
- **FMC mating connector:** VITA 57.1 LPC (160-pin, rows C/D/G/H × 1–40), per Genesys 2.

## Parts to implement
- **Bobcat** — DUT, 40-QFN. Decoupling caps on VDDD, VDDIO, VDDA1, VDDA2. Series 0Ω on VDDA1, VDDA2. 10kΩ pull-downs on GPIO0–3, SPI_DMODE, SCLK, MOSI, OSC_EN, WEIGHT_EN, SAMPLE_TRIG. 10kΩ pull-ups on CS_L, RESET_N.
- **TPS7A8401A** (TI, VQFN-20, 3.5×3.5 mm) — high-accuracy (0.75%), low-noise (4.4 µVrms), 3 A LDO with 180 mV max dropout. Vin 1.1–6.5 V (with BIAS) or 1.4–6.5 V (without BIAS); ANY-OUT pin-programmable output **0.5–2.075 V** at 25 mV resolution (covers Bobcat 0.6–1.0 V rails). 3P3V from FMC drives Vin and BIAS. EN driven by FPGA with 10kΩ pull-down. ANY-OUT setpoint pins driven by FPGA. Open-drain PG output back to FPGA. Output fans out to Bobcat VDDD, VDDA1, VDDA2 each through a 1×2 jumper.
- **Load switch** — gates VADJ (1.2–3.3V) to Bobcat VDDIO. EN driven by FPGA with 10kΩ pull-down. Output to VDDIO via 1×2 jumper.
- **EEPROM** — 8-Kbit, I²C, 3.3V supply (for FMC IPMI / board ID).
- **Bias circuit** — two independent programmable current sources for BIAS0, BIAS1; 3.3V supply; I²C controlled; off by default. High-side PMOS V-to-I transconductance loop (per bias-polarity-fix decision, 2026-05-24):
  - **MCP4728** quad 12-bit I²C voltage DAC with **external V_REF tied to 3.3 V** (not internal 2.048 V ref) for rail-to-rail output drives the non-inverting input of a dual RRIO op-amp (OPA2388 preferred; MCP6V52 / TLV9002 alternates).
  - Op-amp output drives the gate of a small-signal PMOS (PMZ1200UPEYL).
  - PMOS source ties to 3.3 V through a 5.11 kΩ 0.1% thin-film sense resistor; the source node also feeds the op-amp inverting input.
  - PMOS drain delivers regulated current INTO the BIASx pin via a 1×2 jumper.
  - I_load = (3.3 V − V_DAC) / R_sense → 0–646 µA FS, ~0.16 µA/LSB at 12-bit. MCP4728 EEPROM programmed to **0xFFF** at bring-up → V_OUT=3.3 V → PMOS off → 0 µA at POR.
  - Optional series NMOS enable FETs (DNP, 2N7002) between PMOS drain and BIASx jumper, gated by an MCU GPIO pulled low at reset, for hard hardware isolation independent of EEPROM state.
- **SMA connectors** — CLK_OUT0–3 (4×). OSC_EN, WEIGHT_EN, SAMPLE_TRIG (3×) each switchable between SMA and FPGA via 0Ω resistor option.
- **1×4 100-mil header** — GPIO0–3 breakout.
- **GND test clips.**

## FMC LPC pinout (VITA 57.1, Genesys 2 host side)
The LPC connector populates rows **C, D, G, H** (pins 1–40 each). Source: <https://fmchub.github.io/appendix/VITA57_FMC_HPC_LPC_SIGNALS_AND_PINOUT.html>.

### Power & management pins (must connect)
| Pin(s) | Net | Use on this board |
|---|---|---|
| C36, C38, C40, D39 | **3P3V** | Supplies EEPROM, LDO Vin, Bias block |
| G40, H39 | **VADJ** (1.2–3.3V) | Through load switch → Bobcat VDDIO |
| C32 | 3P3VAUX | Leave NC (not required) |
| D35, D37 | 12P0V | Leave NC (unused) |
| H1 | VREF_A_M2C | Leave NC (LPC, no analog reference used) |
| H2 | PRSNT_M2C_L | **Tie to GND on mezzanine** (presence detect) |
| C34, C35 | GA0, GA1 | Geographical address — tie per FMC carrier slot (typically GND) |
| C1 | PG_C2M | Power-good back to carrier — drive from LDO PG / tie HIGH via pull-up if unused |

### Control / sideband
| Pin | Net | Use |
|---|---|---|
| D30 | **SCL** | I²C clock → EEPROM + Bias DAC |
| D31 | **SDA** | I²C data → EEPROM + Bias DAC |
| C29 | TCK | JTAG — leave NC unless chained |
| C30 | TDI | JTAG — leave NC |
| C31 | TDO | JTAG — leave NC |
| C33 | TMS | JTAG — leave NC |
| C34 | TRST_L | JTAG — leave NC |

### Clocks (LVDS, M2C = mezzanine→carrier, available but unused unless noted)
| Pair | Net |
|---|---|
| G4/G5 | CLK0_M2C_P/N |
| H2/H3 | CLK1_M2C_P/N |
| C4/C5 | GBTCLK0_M2C_P/N |
| D2/D3 | DP0_C2M_P/N (gigabit, unused) |
| D6/D7 | DP0_M2C_P/N (gigabit, unused) |

### LA single-ended/diff bank (LA00–LA33, 34 pairs total)
The mezzanine signals listed below route from Bobcat (or its bias/control circuitry) to FMC LA pins through series 0Ω resistors. Specific LA-pin assignments are TBD during pinning — to be picked from the LA-bank table below to minimize crossings.

**Bobcat → FMC LA bank (via 0Ω):** SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N (14 nets, all single-ended).
**FMC LA → Bobcat (via 0Ω, also SMA-routable):** OSC_EN, WEIGHT_EN, SAMPLE_TRIG (3 nets).
**FMC LA → control:** LDO EN, LDO ADJ setpoint (if DAC-driven, see open questions), Load-switch EN, optional Bias-DAC interrupts.

LA-pair locations (CC = clock-capable):
- Row C: C8/C9 LA01_CC, C11/C12 LA05, C14/C15 LA09, C17/C18 LA13, C20/C21 LA17_CC, C23/C24 LA23, C26/C27 LA26
- Row D: D10/D11 LA06, D14/D15 LA10, D18/D19 LA14, D22/D23 LA18_CC, D26/D27 LA27
- Row G: G7/G8 LA02, G10/G11 LA04, G13/G14 LA07, G16/G17 LA11, G19/G20 LA15, G22/G23 LA19, G25/G26 LA21, G28/G29 LA24, G31/G32 LA28, G34/G35 LA30, G37/G38 LA32
- Row H: H6/H7 LA00_CC, H9/H10 LA03, H12/H13 LA08, H15/H16 LA12, H18/H19 LA16, H21/H22 LA20, H24/H25 LA22, H27/H28 LA25, H30/H31 LA29, H33/H34 LA31, H36/H37 LA33

All other unlabeled pins on rows C/D/G/H are **GND** per the standard.

## Topology / block diagram
FMC (bottom) supplies 3.3V and VADJ. 3.3V feeds EEPROM, LDO, and Bias block. VADJ passes through the load switch to Bobcat VDDIO. The LDO generates 0.6–1.0V for Bobcat VDDD/VDDA1/VDDA2. Bobcat SPI, RESET_N, and SAMPLE_OUT signals route to the FMC through series 0Ω resistors (specifically: SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N on LA/HA pairs). CLK_OUT0–3 route directly to SMAs. OSC_EN, WEIGHT_EN, SAMPLE_TRIG route to SMAs with 0Ω options back to the FMC. GPIO0–3 route to a 1×4 header. I²C SCL/SDA from the FMC fans out to the EEPROM and Bias DAC.

## Notes / open questions
- Confirm decoupling cap values per rail.
- Confirm PG_C2M and GA0/GA1 strapping requirements for the Genesys 2 carrier.
- ~~**Bias polarity:**~~ **Resolved 2026-05-24** — confirmed against Bobcat PDF page 7 that current must be sourced INTO BIASx; reverted to PMOS high-side topology.
- ~~**Shared-rail LDO:**~~ **Resolved 2026-05-25 (E8)** — the design intentionally uses one TPS7A8401A feeding VDDD, VDDA1, VDDA2 through 3×1×2 jumpers (all three jumpers tap the same LDO output bus, so installing more than one shorts the rails to a single voltage). This is the design intent (all three rails track together during sweep). If independent per-rail setpoints become required later, replicate the LDO block 3× rather than adding more jumpers.
- ~~**FMC LA-bank pinning:**~~ **Resolved 2026-05-25 (E1, E2, E5, E7, W1)** — LA pins assigned sequentially LA00..LA27. See `LA_ASSIGN` in `gen_schematic.py`. Reassignment will require updating that table and re-running the generator.

## Assembly / provisioning notes
- **MCP4728 EEPROM (W8):** Virgin MCP4728 ships with VREF = internal 2.048 V; this design requires VREF = VDD (external 3.3 V) and the EEPROM default codes set to 0xFFF (PMOS off → 0 µA bias at POR). Before installing on a production board, program the MCP4728 EEPROM in-system or via a board-level fixture. **Do not power-on Bobcat until MCP4728 EEPROM has been programmed** — a virgin part can deliver uncontrolled bias current at POR and damage the DUT.
- **I²C pull-ups (W4):** R60 and R61 (2.2 kΩ to +3V3 on EEPROM sheet) provide local SCL/SDA pull-ups. If the Genesys 2 carrier provides FMC-side I²C pull-ups, R60/R61 may need to be DNP'd to avoid over-current on bus low — verify carrier pull-up scheme at bring-up and depopulate R60/R61 if the parallel value drops below the IOL spec of any device on the bus.
- **Bias isolation FETs Q42/Q43 (E7):** DNP by default per requirements. Bias path is closed by parallel 0Ω jumpers R42/R43 (populated by default). To enable FPGA-controlled hardware isolation of BIASx: (a) depopulate R42 and/or R43, (b) populate Q42 and/or Q43, (c) drive BIAS_ISO0/1 high from the FPGA (default low via the 10 kΩ pull-down on each gate, R44/R45).
