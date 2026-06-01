# Bobcat Board — Design Requirements

> **Ground truth + scope.** This document captures ONLY the customer's requirements,
> from (1) the slide deck `[External] Bobcat Board Design.pdf` (Unconventional AI,
> 2026-05-15) and (2) the Deliverables list below. It is intentionally **agnostic to
> our implementation** — no chosen part numbers, circuit topology beyond what the deck
> specifies, reference designators, or exact connector pin assignments appear here.
> Those live in `design_implementation.md` (how we built it) and the design-review
> notes. Where the deck's block diagram shows a single nominal (VADJ "1.8 V", LDO
> "0.8 V"), the governing values are the ranges on the dedicated slides.

## Application
A carrier board for the **Bobcat** test chip. It plugs into the **FMC connector of a
Genesys 2 platform** and extends away from it, to break out and exercise Bobcat for
bring-up and characterization.

**Bobcat package** (per the deck's footprint drawing; units mm): 40-lead QFN, body
**5 × 5 mm**, **0.4 mm** lead pitch, exposed thermal/ground pad (pin 41) **3.5 × 3.5 mm**,
~0.85 mm thick.

## Deliverables (review scope)
The engagement is **System and Schematic Design** + **Board Design**.

**System and Schematic Design — key tasks:**
- System block diagram and component selection
- External interface pinout and review with Unconventional [AI]
- Power analysis / budget
- Simulation / analysis of analog bias circuits (functionality, resolution, noise)
- Schematic entry (including symbol creation)
- BOM

**Board Design — key tasks:**
- Footprint creation
- Stackup
- Placement study
- Review

**Deliverables:**
- System block diagram
- Interface pinouts
- Preliminary BOM
- Board outline and approximate component locations

## System block diagram (from the deck)
The FMC terminal (bottom) brings in **3.3 V** and **VADJ**. 3.3 V feeds the EEPROM, the
LDO, and the Bias block. VADJ passes through a **switch** to Bobcat VDDIO. The LDO
generates Bobcat's low rails. Bobcat connects out to: SMA connectors (CLK_OUT and the
OSC_EN/WEIGHT_EN/SAMPLE_TRIG group), a header (GPIO), the Bias block (I²C + BIAS), and
back to the FMC for SPI / RESET_N / SAMPLE_OUT and I²C.

## Power
- **From the FMC:** 3.3 V (3P3V); **VADJ, 1.2–3.3 V**; 12 V available but unused.
- **Bobcat rails:** VDDD, VDDA1, VDDA2 = **0.6–1.0 V** (from the on-board LDO); VDDIO = VADJ
  (through the load switch and a 1×2 jumper).

## Functional blocks (required behavior)

### Bobcat (DUT) — pinout & connections
40-QFN, exposed pad (pin 41) = GND. Required passives / connections:
- **Decoupling capacitors** on VDDD, VDDIO, VDDA1, VDDA2.
- **Series 0 Ω** on VDDA1, VDDA2.
- **10 kΩ pull-downs** on GPIO0–3, SPI_DMODE, SCLK, MOSI, OSC_EN, WEIGHT_EN, SAMPLE_TRIG.
- **10 kΩ pull-ups** on CS_L, RESET_N.
- **CLK_OUT0–3** to SMA connectors.
- **OSC_EN, WEIGHT_EN, SAMPLE_TRIG** to SMA connectors, with 0 Ω resistor options to the FPGA.
- **GPIO0–3** to a **1×4, 100 mil header**.

Bobcat pin functions (from the deck's pinout): power/ground — VDDD, VDDIO (multiple),
VDDA1, VDDA2 (multiple), exposed-pad GND; bias — BIAS0, BIAS1; clocks — CLK_OUT0–3;
SPI — CS_L, SCLK, MOSI, MISO, SPI_DMODE; control — RESET_N, OSC_EN, WEIGHT_EN,
SAMPLE_TRIG, GPIO0–3; sampling — SAMPLE_OUTV, SAMPLE_OUT0–7.

### FMC interface
- **Mating connector:** VITA 57.1 **LPC** (per the Genesys 2 host).
- **VADJ** → Bobcat VDDIO through a **load switch** and a **1×2 jumper**.
- **3P3V** → EEPROM, LDO, Bias.
- **LA / HA signals** through **series 0 Ω resistors**:
  - SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N
  - OSC_EN, WEIGHT_EN, SAMPLE_TRIG — with 0 Ω options to SMA connectors
  - ANY-OUT and EN inputs for the LDO
  - Enable signal for the load switch
- **I²C (SCL/SDA)** → EEPROM and Bias.

### LDO
- **TPS7A8401A** (named in the deck).
- **3.3 V input.**
- **0.6–1.0 V output**, set via ANY-OUT inputs connected to the FPGA.
- **EN** input from the FPGA with a **10 kΩ pull-down**.
- Outputs to Bobcat **VDDD, VDDA1, VDDA2** through **1×2 jumpers**.

### Bias
- Two **independent programmable current sources** for BIAS0 and BIAS1; nominally
  **320 µA at 0.5 V**.
- Programmable range **0–640 µA**, step size **~1 µA**.
- **3.3 V supply.**
- **Off by default.**
- **Preferred option:** an I²C **current** DAC (default off) connected to the BIASx pin
  via a 1×2 jumper.
- **Backup option:** an I²C **voltage** DAC driving the + terminal of an op-amp; op-amp
  output drives a PMOS gate; PMOS source ties to the op-amp − terminal and to 3.3 V
  through a resistor; PMOS drain → BIASx via a 1×2 jumper; off by default.

### EEPROM
- **3.3 V** supply, **I²C**, **8 Kbit**.

### Load switch
- **VADJ 1.2–3.3 V.**
- **Enable** input from the FPGA with a **10 kΩ pull-down**.

### Socket
- **Ironwood Electronics CG25-QFN-2003.** The drawing defines screw holes and keep-out areas.

## Mechanical / PCB / fabrication
- **Mounting holes** at the corners furthest from the FMC, for standoffs.
- **FMC single width: 69 mm.**
- **Target 50 Ω impedance** for traces going to the SMA connectors.
- **Silkscreen** for all reference designators.
- **Target 4–6 layers**, at least **1.6 mm** total thickness.
- **Test clips for GND.**

## Reference links (from the customer deck)
- Genesys 2 platform — <https://digilent.com/reference/programmable-logic/genesys-2/start>
- VITA 57.1 FMC signals & pinout — <https://fmchub.github.io/appendix/VITA57_FMC_HPC_LPC_SIGNALS_AND_PINOUT.html>
- TPS7A84x LDO datasheet — <https://www.ti.com/lit/ds/symlink/tps7a84a.pdf>
- Ironwood CG25-QFN-2003 socket drawing — <https://www.ironwoodelectronics.com/wp-content/uploads/2021/09/CG25-QFN-2003Dwg.pdf>
- Unconventional AI — <https://unconv.ai>
