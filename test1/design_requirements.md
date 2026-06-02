# Bobcat Board — Design Requirements

> **Ground truth + scope.** This document captures ONLY the customer's requirements,
> from (1) the slide deck `[External] Bobcat Board Design.pdf` (Unconventional AI,
> 2026-05-15), (2) the **`Bobcat Pin List and Electrical Specifications.pdf`** datasheet
> (pin table + supply/IO electrical limits), (3) the customer **FAQs** (§FAQs below,
> from Unconventional AI / Jason Hou), and (4) the Deliverables list below. It is
> intentionally **agnostic to our implementation** — no chosen part numbers, circuit
> topology beyond what the deck specifies, reference designators, or exact connector pin
> assignments appear here. Those live in `design_implementation.md` (how we built it) and
> the design-review notes. Where the deck's block diagram shows a single nominal (VADJ
> "1.8 V", LDO "0.8 V"), the governing values are the ranges on the dedicated slides; for
> Bobcat's own rails and IO levels, the **pin-list datasheet** ranges govern.

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
- **Bobcat rails:** VDDD, VDDA1, VDDA2 = **0.6–1.0 V** (LDO-capable range from the on-board
  LDO); VDDIO = VADJ (through the load switch and a 1×2 jumper).
- **Bobcat operating supply limits** (pin-list datasheet §2 — these govern the rails the
  board must deliver): VDDD / VDDA1 / VDDA2 = **0.72 / 0.80 / 0.88 V** (min/typ/max);
  VDDIO = **1.62 / 1.80 / 1.98 V** (min/typ/max). So the LDO set-point and the VADJ jumper
  must land inside these windows (typ 0.80 V cores, 1.80 V IO).
- **Power budget (FAQ — conservative ceilings):** VDDA1 **< 100 mA**, VDDA2 **< 100 mA**,
  VDDD **< 20 mA**, VDDIO **< 50 mA**. VADJ draw (sizes the load switch) = the VDDIO budget,
  i.e. **< 50 mA**.

### Digital IO electrical characteristics (pin-list datasheet §3)
Referenced to VDDIO. Used when checking level compatibility with the 1.8 V VADJ/VDDIO IO
and any series/pull resistors on FMC-facing signals.
- **VIH** ≥ 0.65 × VDDIO; **VIL** ≤ 0.35 × VDDIO.
- **VOH** ≥ VDDIO − 0.45 V; **VOL** ≤ 0.45 V.
- Absolute input range: −0.3 V … VDDIO + 0.3 V.

## Functional blocks (required behavior)

### Bobcat (DUT) — pinout & connections
40-QFN, exposed pad (pin 41) = GND. Required passives / connections:
- **Decoupling capacitors** on VDDD, VDDIO, VDDA1, VDDA2 — **1× 10 µF + 1× 0.1 µF per rail**
  (FAQ).
- **Series 0 Ω** on VDDA1, VDDA2 — placeholders for optional passive filtering of the
  analog rails if needed (FAQ; no isolation/filtering is *required*, sequencing unknown).
- **10 kΩ pull-downs** on GPIO0–3, SPI_DMODE, SCLK, MOSI, OSC_EN, WEIGHT_EN, SAMPLE_TRIG.
- **10 kΩ pull-ups** on CS_L, RESET_N.
- **CLK_OUT0–3** to SMA connectors.
- **OSC_EN, WEIGHT_EN, SAMPLE_TRIG** to SMA connectors, with 0 Ω resistor options to the FPGA.
- **GPIO0–3** to a **1×4, 100 mil header**.

Bobcat pin functions (from the deck's pinout): power/ground — VDDD, VDDIO (multiple),
VDDA1, VDDA2 (multiple), exposed-pad GND; bias — BIAS0, BIAS1; clocks — CLK_OUT0–3;
SPI — CS_L, SCLK, MOSI, MISO, SPI_DMODE; control — RESET_N, OSC_EN, WEIGHT_EN,
SAMPLE_TRIG, GPIO0–3; sampling — SAMPLE_OUTV, SAMPLE_OUT0–7.

**Pin numbers & directions (deck pinout drawing — authoritative for the pin map; directions
from the pin-list datasheet §1).** Direction is from Bobcat's point of view. The **package
drawing in the deck is the governing pin map** (it resolves the pin-7 ambiguity below):
- **Power/ground:** VDDA1 (1), VDDA2 (26, 27), VDDD (12, 20), VDDIO (**7**, 13, 22, 33, 34),
  GND = exposed pad (41).
- **No-connect:** NC (21), NC (30).
- **Bobcat outputs** (drive *into* the board / FMC): MISO (15); SAMPLE_OUTV (2),
  SAMPLE_OUT0–3 (3–6), **SAMPLE_OUT4–7 (8, 9, 10, 11)**; CLK_OUT0–3 (36, 35, 32, 31).
- **Bobcat inputs** (driven *by* the board / FMC): MOSI (14), SCLK (16), CS_L (17),
  SPI_DMODE (18), RESET_N (19), OSC_EN (23), WEIGHT_EN (24), SAMPLE_TRIG (25).
- **Bidirectional:** GPIO0–3 (40, 39, 38, 37).
- **Analog inputs:** BIAS0 (28), BIAS1 (29) — bias current, **320 µA at 0.5 V nominal**.

> ℹ **Resolved — pin-7 discrepancy (pin map taken from the deck drawing).** The pin-list
> PDF *table* lists pin 7 under BOTH VDDIO ("7,13,22,33,34 = VDDIO") **and** SAMPLE_OUT4
> ("7 = SAMPLE_OUT4") — a contradiction. The **deck's package pinout drawing resolves it:
> pin 7 = VDDIO**, and the SAMPLE_OUTn block is **not** contiguous — it skips pin 7 and
> resumes at pin 8, so **SAMPLE_OUT4–7 = pins 8, 9, 10, 11**. The drawing is the governing
> pin map. (The datasheet table's "7 = SAMPLE_OUT4" row is the erroneous entry.) Worth a
> one-line note to Unconventional AI that the table and drawing disagree, but the drawing
> is unambiguous so no work is blocked.

Net **direction** above is what the `port_direction_conflict` lint rule and the FMC port
modeling must match.

### FMC interface
- **Mating connector:** VITA 57.1 **LPC** (per the Genesys 2 host).
- **VADJ** → Bobcat VDDIO through a **load switch** and a **1×2 jumper**.
- **3P3V** → EEPROM, LDO, Bias.
- **LA / HA signals** through **series 0 Ω resistors**:
  - SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N
  - OSC_EN, WEIGHT_EN, SAMPLE_TRIG — with 0 Ω options to SMA connectors
  - ANY-OUT and EN inputs for the LDO
  - Enable signal for the load switch
- **I²C (SCL/SDA)** → EEPROM and Bias. Use the **FMC I²C *system* pins** (the 3.3 V FMC
  SCL/SDA the Genesys 2 schematic dedicates to FMC) — **not** a dedicated FPGA GPIO (FAQ).

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
- **No DAC settling-speed requirement** (FAQ) — sizing is set by resolution/accuracy, not rate.
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
- **Size for VADJ ≤ 50 mA** (FAQ — VADJ is just the Bobcat IO supply / VDDIO).
- **Independent FPGA control** (FAQ — no power-sequencing lockout in hardware; the FPGA
  controls the load switch and the LDO independently).

### Socket
- **Ironwood Electronics CG25-QFN-2003.** The drawing defines screw holes and keep-out areas.

## Mechanical / PCB / fabrication
- **Mounting holes** at the corners furthest from the FMC, for standoffs.
- **FMC single width: 69 mm.**
- **Target 50 Ω impedance** for traces going to the SMA connectors.
- **Silkscreen** for all reference designators.
- **Target 4–6 layers**, at least **1.6 mm** total thickness.
- **Test clips for GND.**
- **Double-side component placement is acceptable** (FAQ).
- **No socket thermal requirement** — primarily room-temperature testing (FAQ).

## FAQs (customer clarifications)
Direct Q&A. These **refine** the requirements
above; where a FAQ tightens a value, the body sections already reflect it and cite "(FAQ)".

1. **I²C source for Bobcat — FMC system pins or a dedicated GPIO?** → **FMC I²C system pins.**
   The Genesys 2 schematic dedicates 3.3 V FMC SCL/SDA to the FMC; use those. *(→ FMC interface)*
2. **Any speed requirement for the DAC setting?** → **No.** *(→ Bias)*
3. **VADJ expected current, to size the load switch?** → **< 50 mA** — it is just the Bobcat
   IO supply. *(→ Load switch / Power)*
4. **Single- or double-side components acceptable?** → **Yes, double-side is acceptable.**
   *(→ Mechanical)*
5. **Thermal requirements for the selected Bobcat socket?** → **No** — primarily room-temperature
   testing. *(→ Mechanical / Socket)*
6. **Power budget for the Bobcat rails?** → **< 100 mA VDDA1, < 100 mA VDDA2, < 20 mA VDDD,
   < 50 mA VDDIO** ("should be conservative"). *(→ Power)*
7. **Decoupling values for the Bobcat rails?** → **1× 10 µF and 1× 0.1 µF for each rail.**
   *(→ Bobcat decoupling)*
8. **Power-sequencing lockouts to fix in hardware?** → **Unknown / none** — intent is for the
   FPGA to have **independent control** of the load switch and the LDO. *(→ Load switch)*
9. **Filtering/isolation for VDDA generation from the VDDD rail?** → **Unknown** — the **0 Ω
   series resistors on VDDA1 and VDDA2 are placeholders** for passive filtering if needed.
   *(→ Bobcat / VDDA series-R)*

## Reference links (from the customer deck)
- Genesys 2 platform — <https://digilent.com/reference/programmable-logic/genesys-2/start>
- VITA 57.1 FMC signals & pinout — <https://fmchub.github.io/appendix/VITA57_FMC_HPC_LPC_SIGNALS_AND_PINOUT.html>
- TPS7A84x LDO datasheet — <https://www.ti.com/lit/ds/symlink/tps7a84a.pdf>
- Ironwood CG25-QFN-2003 socket drawing — <https://www.ironwoodelectronics.com/wp-content/uploads/2021/09/CG25-QFN-2003Dwg.pdf>
- Unconventional AI — <https://unconv.ai>

## Source documents (requirements ground truth)
The local documents this spec is derived from (all reviewed against during design review):
- `[External] Bobcat Board Design.pdf` — customer slide deck (Unconventional AI, 2026-05-15);
  system block diagram, deck pinout, mechanical drawings, reference links.
- `resources/requirements/Bobcat Pin List and Electrical Specifications.pdf` — Bobcat
  datasheet: pin table (number/name/type/direction), supply ranges (§2), digital-IO
  electrical limits (§3). **Governs** Bobcat's rail windows, IO levels, and pin directions.
- **FAQs** (§FAQs above) — Unconventional AI / Jason Hou, 2026-05-20.
