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
- **Bias circuit** — two independent programmable current sources for BIAS0, BIAS1; 3.3V supply; I²C controlled; off by default. The Bobcat design document lists a *preferred* option (an I²C **current** DAC tied straight to BIASx) and a *backup* option (I²C voltage DAC → op-amp → PMOS). **We implement the backup** — a high-side PMOS V-to-I transconductance loop — because a single off-the-shelf current DAC didn't meet the 0–640 µA / ~1 µA-step range cleanly, and the op-amp loop gives a precise, sourced current into BIASx (per bias-polarity-fix decision, 2026-05-24):
  - **MCP4728** quad 12-bit I²C voltage DAC with **external V_REF tied to 3.3 V** (not internal 2.048 V ref) for rail-to-rail output drives the non-inverting input of a dual RRIO op-amp (OPA2388 preferred; MCP6V52 / TLV9002 alternates).
  - Op-amp output drives the gate of a small-signal PMOS (PMZ1200UPEYL).
  - PMOS source ties to 3.3 V through a 5.11 kΩ 0.1% thin-film sense resistor; the source node also feeds the op-amp inverting input.
  - PMOS drain delivers regulated current INTO the BIASx pin via a 1×2 jumper.
  - I_load = (3.3 V − V_DAC) / R_sense → 0–646 µA FS, ~0.16 µA/LSB at 12-bit. MCP4728 EEPROM programmed to **0xFFF** at bring-up → V_OUT=3.3 V → PMOS off → 0 µA at POR.
  - **Series NMOS isolation FETs (POPULATED default, 2N7002)** between PMOS drain and BIASx jumper, gated by `BIAS_ISO0/1` from the FPGA with 10 kΩ pull-downs (R44/R45) at the gates. Default-OFF at POR — even a virgin MCP4728 cannot push uncontrolled current into Bobcat until the FPGA explicitly asserts the isolation enable HIGH after verifying the DAC configuration. Parallel 0 Ω jumpers R42/R43 across the NMOS D-S are **DNP by default**; populate them only to bypass FPGA-side control (e.g. benchtop standalone use).
- **SMA connectors** — CLK_OUT0–3 (4×). OSC_EN, WEIGHT_EN, SAMPLE_TRIG (3×) each switchable between SMA and FPGA via 0Ω resistor option.
- **1×4 100-mil header** — GPIO0–3 breakout.
- **GND test clips.**
- **Bobcat socket** — Ironwood Electronics **CG25-QFN-2003** (the QFN test socket Bobcat seats in). Drawing defines screw holes + keep-out areas (see Reference links / [socket drawing](https://www.ironwoodelectronics.com/wp-content/uploads/2021/09/CG25-QFN-2003Dwg.pdf)).

## FMC LPC pinout (VITA 57.1, Genesys 2 host side)
The LPC connector populates rows **C, D, G, H** (pins 1–40 each). Source: <https://fmchub.github.io/appendix/VITA57_FMC_HPC_LPC_SIGNALS_AND_PINOUT.html> (LPC pinout table).

> **Corrected 2026-05-27.** A prior version of every table in this section had
> rows **C↔D and G↔H transposed** (a mirrored / bottom-side read of the
> connector). VITA 57.1 pin *names* mate 1:1 (mezzanine C*n* ↔ carrier C*n*); the
> footprint implements the physical mirror, NOT the netlist. The pins below are
> the un-swapped, spec-correct positions, verified pin-by-pin against the source.

### Power & management pins (must connect)
| Pin(s) | Net | Use on this board |
|---|---|---|
| C39, D36, D38, D40 | **3P3V** | Supplies EEPROM, LDO Vin, Bias block |
| G39, H40 | **VADJ** (1.2–3.3V) | Through load switch → Bobcat VDDIO |
| D32 | 3P3VAUX | Leave NC (not required) |
| C35, C37 | 12P0V | Leave NC (unused) |
| H1 | VREF_A_M2C | Leave NC (LPC, no analog reference used) |
| H2 | PRSNT_M2C_L | **Tie to GND on mezzanine** (presence detect) |
| C34, D35 | GA0, GA1 | Geographical address — tie per FMC carrier slot (typically GND) |
| C1 | PG_C2M | Power-good back to carrier — drive from LDO PG / tie HIGH via pull-up if unused |

### Control / sideband
| Pin | Net | Use |
|---|---|---|
| C30 | **SCL** | I²C clock → EEPROM + Bias DAC |
| C31 | **SDA** | I²C data → EEPROM + Bias DAC |
| D29 | TCK | JTAG — leave NC unless chained |
| D30 | TDI | JTAG — leave NC |
| D31 | TDO | JTAG — leave NC |
| D33 | TMS | JTAG — leave NC |
| D34 | TRST_L | JTAG — leave NC |

### Clocks (LVDS, M2C = mezzanine→carrier, available but unused unless noted)
| Pair | Net |
|---|---|
| H4/H5 | CLK0_M2C_P/N |
| G2/G3 | CLK1_M2C_P/N |
| C4/C5 | GBTCLK0_M2C_P/N |
| D2/D3 | DP0_C2M_P/N (gigabit, unused) |
| D6/D7 | DP0_M2C_P/N (gigabit, unused) |

### LA single-ended/diff bank (LA00–LA33, 34 pairs total)
The mezzanine signals below route from Bobcat (or its bias/control circuitry) to FMC LA pins through series 0Ω resistors. The *signal → LA-index* assignment is ours (chosen to minimize crossings); the *LA-index → connector pin* is fixed by VITA 57.1. The design uses the P pin of each pair, single-ended (see `gen/config.py` `LA_ASSIGN`).

**Bobcat → FMC LA bank (via 0Ω):** SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N (14 nets, all single-ended).
**FMC LA → Bobcat (via 0Ω, also SMA-routable):** OSC_EN, WEIGHT_EN, SAMPLE_TRIG (3 nets).
**FMC LA → control:** LDO EN, ANY-OUT setpoints (LDO_SET_*), Load-switch EN, Bias-isolation enables.

**ANY-OUT setpoint bit weights (TPS7A8401A, low-range — base 0.5 V, 25 mV/LSB).**
Net names match the TRUE 8401A weight of each pin (corrected 2026-05-31 — they
previously used the 8400A high-range labels, i.e. 2× these values, which would
have mis-mapped FPGA firmware). Grounding a SET pin ADDS its weight to the 0.5 V
base; an open pin contributes nothing.

| U10 pin | Net name      | Weight | FMC LA pin |
|---------|---------------|--------|------------|
| 5       | LDO_SET_25mV  | 25 mV  | LA22_P G24 |
| 6       | LDO_SET_50mV  | 50 mV  | LA23_P D23 |
| 7       | LDO_SET_100mV | 100 mV | LA24_P H28 |
| 9       | LDO_SET_200mV | 200 mV | LA25_P G27 |
| 10      | LDO_SET_400mV | 400 mV | LA26_P D26 |
| 11      | LDO_SET_800mV | 800 mV | LA27_P C26 |

Examples: VOUT 0.6 V = 0.5 + 0.1 → ground LDO_SET_100mV (pin 7). VOUT 1.0 V =
0.5 + 0.4 + 0.1 → ground LDO_SET_400mV + LDO_SET_100mV (pins 10, 7). The Bobcat
0.6–1.0 V window is fully addressable in 25 mV steps.

LA-pair locations P/N (CC = clock-capable), per VITA 57.1 LPC:
- Row C: C10/C11 LA06, C14/C15 LA10, C18/C19 LA14, C22/C23 LA18_CC, C26/C27 LA27
- Row D: D8/D9 LA01_CC, D11/D12 LA05, D14/D15 LA09, D17/D18 LA13, D20/D21 LA17_CC, D23/D24 LA23, D26/D27 LA26
- Row G: G6/G7 LA00_CC, G9/G10 LA03, G12/G13 LA08, G15/G16 LA12, G18/G19 LA16, G21/G22 LA20, G24/G25 LA22, G27/G28 LA25, G30/G31 LA29, G33/G34 LA31, G36/G37 LA33
- Row H: H7/H8 LA02, H10/H11 LA04, H13/H14 LA07, H16/H17 LA11, H19/H20 LA15, H22/H23 LA19, H25/H26 LA21, H28/H29 LA24, H31/H32 LA28, H34/H35 LA30, H37/H38 LA32

All other unlabeled pins on rows C/D/G/H are **GND** per the standard.

**Authoritative pinout reference:** `Parts Library/ASP-134606-01/VITA57.1_FMC_HPC_LPC_SIGNALS_AND_PINOUT.xlsx`
(the ANSI/VITA 57.1 FMC signals-and-pinout spreadsheet from FMCHUB; the "Low-pin
count (LPC) connector" sheet is the per-pin C/D/G/H table). Verified 2026-05-31
against our `LA_ASSIGN` (all 28 LA P-pins match) and the wired power/special pins
(3P3V/VADJ/SCL/SDA/PRSNT/VREF/12P0V/3P3VAUX all match). Per that sheet the LPC has
**61 GND pins**:
C1,C4,C5,C8,C9,C12,C13,C16,C17,C20,C21,C24,C25,C28,C29,C32,C33,C36,C38,C40,
D2,D3,D6,D7,D10,D13,D16,D19,D22,D25,D28,D37,D39,
G1,G4,G5,G8,G11,G14,G17,G20,G23,G26,G29,G32,G35,G38,G40,
H3,H6,H9,H12,H15,H18,H21,H24,H27,H30,H33,H36,H39.

> ⚠️ **F-1a (GND pins floating):** the generator does NOT wire those GND pins to the
> GND net — `build_fmc.py` No-ERCs every unwired pin, so the 61 LPC GND positions are
> isolated pads (GND net = 3 strap pins only). Fix before PCB layout.
>
> ⚠️ **F-1b (LDO_PG on the wrong pin — found 2026-05-31 via the pinout cross-check):**
> the design wires **LDO_PG to C1**, but per VITA 57.1 LPC **C1 is GND** and the
> power-good signal **PG_C2M is on D1**. LDO_PG must move from C1 → **D1**, and C1
> must join the GND net. (Mirrors the earlier C↔D pinout-error class.)

## Topology / block diagram
FMC (bottom) supplies 3.3V and VADJ. 3.3V feeds EEPROM, LDO, and Bias block. VADJ passes through the load switch to Bobcat VDDIO. The LDO generates 0.6–1.0V for Bobcat VDDD/VDDA1/VDDA2. Bobcat SPI, RESET_N, and SAMPLE_OUT signals route to the FMC through series 0Ω resistors (specifically: SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N on LA/HA pairs). CLK_OUT0–3 route directly to SMAs. OSC_EN, WEIGHT_EN, SAMPLE_TRIG route to SMAs with 0Ω options back to the FMC. GPIO0–3 route to a 1×4 header. I²C SCL/SDA from the FMC fans out to the EEPROM and Bias DAC.

## Mechanical / PCB / fab requirements
From the Bobcat design document ("Additional Requirements"). These are **PCB-layout / fabrication scope — NOT implemented by this schematic generator**; recorded here so the requirement set is complete for the downstream board design.
- **Mounting holes** at the corners furthest from the FMC, for standoffs.
- **FMC single width: 69 mm** (board form factor).
- **50 Ω target impedance** for traces routing to the SMA connectors.
- **Silkscreen for all reference designators.**
- **4–6 layers**, at least **1.6 mm** total thickness.
- **GND test clips** (also listed under Parts to implement).
- **Socket keep-outs / screw holes** per the Ironwood CG25-QFN-2003 drawing (see Reference links).

## Notes / open questions
- Confirm decoupling cap values per rail.
- Confirm PG_C2M and GA0/GA1 strapping requirements for the Genesys 2 carrier.
- ~~**Bias polarity:**~~ **Resolved 2026-05-24** — confirmed against Bobcat PDF page 7 that current must be sourced INTO BIASx; reverted to PMOS high-side topology.
- ~~**Shared-rail LDO:**~~ **Resolved 2026-05-25 (E8)** — the design intentionally uses one TPS7A8401A feeding VDDD, VDDA1, VDDA2 through 3×1×2 jumpers (all three jumpers tap the same LDO output bus, so installing more than one shorts the rails to a single voltage). This is the design intent (all three rails track together during sweep). If independent per-rail setpoints become required later, replicate the LDO block 3× rather than adding more jumpers.
- ~~**FMC LA-bank pinning:**~~ **Resolved 2026-05-25 (E1, E2, E5, E7, W1); pinout corrected 2026-05-27** — LA pins assigned sequentially LA00..LA27. See `LA_ASSIGN` in `gen/config.py`. The original assignment had rows C↔D / G↔H swapped vs VITA 57.1 (signals on GND pins, +3V3/VADJ shorted to GND); corrected to the real LPC P-pin positions. Reassignment will require updating that table and re-running the generator.

## Assembly / provisioning notes
- **MCP4728 EEPROM (W8):** Virgin MCP4728 ships with VREF = internal 2.048 V and DAC code = 0x000 — without intervention, V_DAC = 0 V at POR would drive the PMOS fully on (~646 µA full-scale bias). This is mitigated **at the schematic level** by the Q42/Q43 isolation NMOSes (populated default, default-OFF — see Bias circuit topology above), so an unprogrammed MCP4728 cannot reach Bobcat. The FPGA boot sequence is expected to: (1) read MCP4728 EEPROM, (2) program VREF = VDD and codes = 0xFFF if not already set, (3) drive DAC to the desired bias values, and (4) only then assert `BIAS_ISO0/1` HIGH. The Q42/Q43 isolation makes the EEPROM-provisioning step recoverable rather than DUT-fatal, but provisioning is still required for the bias circuit to behave correctly once enabled.
- **I²C pull-ups (W4):** R60 and R61 (2.2 kΩ to +3V3 on EEPROM sheet) provide local SCL/SDA pull-ups. If the Genesys 2 carrier provides FMC-side I²C pull-ups, R60/R61 may need to be DNP'd to avoid over-current on bus low — verify carrier pull-up scheme at bring-up and depopulate R60/R61 if the parallel value drops below the IOL spec of any device on the bus.
- **Bias isolation FETs Q42/Q43 (E7, revised 2026-05-25):** POPULATED by default. R42/R43 (parallel 0 Ω override jumpers) are DNP by default. This makes the bias circuit fail-safe at POR — BIAS_ISO0/1 default LOW via R44/R45 pull-downs, so the NMOSes are OFF and no current reaches Bobcat until the FPGA explicitly enables. The FPGA must drive BIAS_ISO0/1 HIGH (after the DAC is configured) to deliver bias. If a board needs to run without FPGA isolation control (e.g. benchtop debug with a USB-I²C dongle driving the DAC), populate R42/R43 and the bias path becomes always-closed — at that point the W8 EEPROM-provisioning concern returns in full force.

## External design review (2026-05-31) — findings + status
An external review was independently re-verified against the netlist, datasheets,
and BOM. Full working notes: `test1/review/EXTERNAL_REVIEW_2026-05-31.md`.

**Fixed in this pass (deterministic source corrections):**
- **F-2 — LDO ANY-OUT setpoint names corrected.** The `LDO_SET_*` nets used the
  TPS7A8400A high-range labels (2× the real weight) on a TPS7A8401A part, which
  would mis-map FPGA firmware. Renamed to the true 8401A weights (25/50/100/200/
  400/800 mV) across power.yaml, fmc.yaml, gen/config.py (LA_ASSIGN), and both
  builders. See the ANY-OUT setpoint bit-weight table above.
- **F-6 — footprint strings corrected** to the datasheet packages: U40 MCP4728T-E/UN
  → MSOP-10 (was VQFN-10-EP); U41 OPA2388IDGK → VSSOP-8 (was SOIC-8); Q40/Q41
  PMZ1200UPEYL → SOT883/DFN1006-3 (was DFN-3 1×1-EP). The per-part UL PcbLib holds
  the real land pattern; the yaml string is now accurate metadata.
- **F-4 — BOM regenerated** (R40/R41 now 3.65k/TNPW06033K65BEEA; the generator's
  stale LIB_DESC/template entries for 5.11k + SOT-666 were corrected).

**OPEN — needs a hardware/firmware decision (NOT changed by the generator):**
- **F-1 (CRITICAL) — FMC GND pins not wired.** ~60 LPC GND pins are No-ERC'd, not
  on the GND net. Fix requires the AUTHORITATIVE VITA 57.1 LPC GND pin list (web
  sources were inconsistent — a fetched list collided with 14 of our validated
  signal pins, i.e. it was wrong; do NOT use it). Safe fix: get the GND list from
  the VITA 57.1 spec PDF / Samtec ASP-134606-01 datasheet, cross-check that NONE
  of the 44 known non-GND pins appear in it, then either (a) add the positions to
  fmc.yaml's GND net + wire them in build_fmc.py (replace the blanket No-ERC), or
  (b) re-author the symbol's GND pins as Electrical=Power/Name=GND. MUST fix before
  layout.
- **F-3 (HIGH) — bias NMOS gate drive marginal at low VADJ.** Q42/Q43 are 2N7002
  (Vth 1.0–2.5 V, standard, not logic-level), gates driven from FMC LA pins whose
  VOH = VADJ, sources at ~0.5 V ⇒ V_GS = VADJ−0.5. At VADJ ≤ ~1.8 V (incl. the
  Genesys 2 default 1.2 V) the FETs don't conduct → no bias to Bobcat. **DECISION
  NEEDED:** (a) document the constraint "bias requires VADJ ≥ 2.5 V"; or (b) swap
  the 2N7002 for a low-Vth logic-level NMOS (e.g. Si2302 / BSS138 / AO3400, Vth ≈
  0.6–1.0 V); or (c) drive BIAS_ISO from a +3V3-domain GPIO instead of the VADJ
  LA bank. Option (b) is the cleanest if low-VADJ operation is required.
- **F-5 (MEDIUM) — no gate-stop resistor** between OPA2388 output and the PMOS
  gate (nets are direct U41↔Q40/Q41). Bias is slow (I²C-rate) so steady-state
  oscillation is unlikely, but code-write transients can ring/overshoot. **Suggest**
  a 100 Ω–1 kΩ series gate resistor (+ optional small −IN→OUT comp cap) and an AC /
  step-response sim before fab (the sim suite covers DC + PDN only, not loop AC).
- **F-7 (MEDIUM) — no post-jumper bulk decap on Bobcat rails.** Bulk (10 µF/22 µF)
  sits on the LDO output bus, before the J10/J11/J12 jumpers; the Bobcat side has
  only 0.1 µF/1 µF. **Suggest** adding a 10 µF at each of +VDDD/+VDDA1/+VDDA2 on the
  Bobcat side of the jumper (matches the original BOM decap-bank template).
