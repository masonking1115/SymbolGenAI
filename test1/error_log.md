# Design Review Error Log — test1 (Bobcat Carrier Board)

## Resolutions applied 2026-05-25

All 9 ERRORs and 10 WARNINGs from this review have been addressed in
`gen_schematic.py`. Summary by finding:

| # | Resolution |
|---|---|
| E1 | Added 14 × 0Ω routing on FMC sheet (R100–R114) wiring SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N to LA00–LA14 (P pins). |
| E2 | OSC_EN / WEIGHT_EN / SAMPLE_TRIG now have a 0Ω on the SMA side (R50–R52, default populated) AND a 0Ω on the FMC side (R115–R117, routed to LA15–LA17). User depopulates one side at bring-up to choose source. |
| E3 | Added 10 × 10 kΩ pull-downs on Bobcat sheet: MOSI/SCLK/SPI_DMODE (R22–R25 staggered offsets), OSC_EN/WEIGHT_EN/SAMPLE_TRIG (R27–R29 in a pull-bank at x=252), GPIO0–3 (R30–R33 in a pull-row at y=75). |
| E4 | Added 2 × 10 kΩ pull-ups to +VDDIO on CS_L (R24) and RESET_N (R26). +VDDIO is the load-switched rail, so pulls de-assert when the chip is unpowered. |
| E5 | TPS7A8401A pins 5/6/7/9/10/11 (ANY-OUT) now route via global_label LDO_SET_50mV/100mV/200mV/400mV/800mV/1V6 → 0Ω on FMC sheet (R122–R127) → LA22–LA27. At POR (FPGA tristated) the pins float = no contribution = V_OUT = 0.5 V floor, safely below Bobcat's 0.6 V minimum. |
| E6 | Added 10 kΩ pull-up R12 from LDO_PG to +3V3 on power sheet. |
| E7 | Q42/Q43 marked DNP via `(dnp yes)` and Value cleaned to "2N7002". Added parallel 0Ω jumpers R42/R43 (populated default) across each NMOS D-S so bias path is closed at assembly. Added 10 kΩ pull-downs R44/R45 on BIAS_ISO0/1 gates. BIAS_ISO0/1 now route via FMC 0Ω (R120/R121) to LA20/LA21 for FPGA control when Q42/Q43 are populated. |
| E8 | Documented in `design_requirements.md` as intentional shared rail; the corresponding open question removed. |
| E9 | SNS (pin 2) now routes to a kelvin sense point at (185, OUT-trace-y) — between C14 (bulk cap) and the jumper-side trace endpoint. Bulk caps are now INSIDE the regulation loop. FB (pin 3) stays strapped at the package per datasheet Figure 23 ANY-OUT mode. |
| W1 | LDO_EN routed to LA18 (D22) and LSW_EN to LA19 (G22) via 0Ω on FMC sheet (R118/R119), no longer floating. |
| W2 | Added C26, C27, C28 (3 × 0.1µF) so the +VDDIO net has 5 × 0.1µF + 1 × 1µF on Bobcat sheet — one per VDDIO pin plus a bulk. |
| W3 | Added C17 (1µF) on +3V3 input column near LDO BIAS pin. |
| W4 | Documented in `design_requirements.md` — R60/R61 may need to be DNP'd if the carrier provides its own pull-ups; verify at bring-up. |
| W5 | Removed C41 (10nF) from MCP4728 VDD — atypical and redundant per datasheet 22187E Figure 2-1. |
| W6 | Upsized C15 (TPS22916 VIN) from 0.1µF to 1µF for VADJ bulk. |
| W7 | Upsized C16 (TPS22916 VOUT) from 0.1µF to 1µF for +VDDIO bulk. |
| W8 | Documented in `design_requirements.md` — MCP4728 EEPROM provisioning required before Bobcat power-on. |
| W9 | Q42/Q43 use `(dnp yes)` flag; Value text is plain "2N7002" (no longer "2N7002 DNP"). |
| W10 | Added 1 kΩ series R13 on LDO_PG between U10 pin 4 and the LDO_PG hier-label, plus the 10 kΩ pull-up from E6. |

Refdes additions / renames (project-wide uniqueness preserved):
- Bobcat sheet adds R22–R33 (pull-ups/downs) and C26–C28 (per-pin VDDIO caps).
- Power sheet adds R12 (PG pull-up), R13 (PG series), C17 (BIAS cap); upsizes C15/C16 values.
- Bias sheet adds R42/R43 (parallel 0Ω), R44/R45 (BIAS_ISO pull-downs); removes C41.
- EEPROM R30→R60, R31→R61 (frees Bobcat decade extension).
- Connectors sheet adds R50–R52 (SMA-side 0Ω).
- FMC sheet adds R100–R127 (28 × 0Ω for LA-bank routing).

Run `python3 verify_project.py` to confirm 0 connectivity issues after the
update. Original findings preserved below for traceability.

---

Date: 2026-05-24
Reviewed against:
- `test1/design_requirements.md`
- `test1/[External] Bobcat Board Design.pdf` (board-level spec, pages 1-13)
- `test1/Parts Library/TPS7A8401A/tps7a84a.pdf` (LDO)
- `test1/Parts Library/TPS22916CNYFPR/TPS22916CNYFPR.pdf` (load switch)
- `test1/Parts Library/MCP4728/22187E.pdf` (DAC)
- `test1/Parts Library/OPA2388/opa2388.pdf` (op-amp)
- `test1/Parts Library/PMZ1200UPEYL/PMZ1200UPE.pdf` (PMOS)
- `test1/Parts Library/24AA08-I-SN/24AA08-...DS20001710.pdf` (EEPROM)
- `test1/Parts Library/ASP-134606-01/ASP-134606-01.pdf` (FMC LPC connector)
- VITA 57.1 LPC pinout (linked from design_requirements.md)

## Summary
- **9 ERRORs** (must fix before fab)
- **10 WARNINGs** (should fix)
- **6 INFOs** (observations)

---

## ERRORs (must fix)

### E1. Bobcat SPI and SAMPLE_OUT signals have no route off-board

**Component(s):** U20 (Bobcat) pins 2–6, 8–11 (SAMPLE_OUTV, SAMPLE_OUT0–7), 14–19 (MOSI, MISO, SCLK, CS_L, SPI_DMODE, RESET_N).
**Requirement:** [design_requirements.md:67-68](design_requirements.md#L67-L68) — *"Bobcat → FMC LA bank (via 0Ω): SAMPLE_OUTV, SAMPLE_OUT0–7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N (14 nets, all single-ended)."* Also Bobcat PDF page 5 (FMC Interface): *"LA and HA signals should be connected through series 0Ω resistors → SAMPLE_OUTV, SAMPLE_OUT0-7, CS_L, SCLK, MOSI, MISO, SPI_DMODE, RESET_N."*
**Observed:** Each of these 14 nets exists as a `global_label` on **only** `bobcat.kicad_sch` (lines 1479-1507) with no matching label on `fmc.kicad_sch`. Searched all six sheets — no consumer anywhere. No 0Ω resistors exist outside of bobcat.kicad_sch (only R20, R21 on VDDA1/VDDA2 — see `grep 'Value" "0"' *.kicad_sch` → 2 hits total).
**Impact:** **DUT is completely uncontrollable.** No SPI master, no reset, no sample-out capture. Board cannot be brought up.
**Fix:** Add 14 × 0Ω 0402 series resistors (lib `CRCW04020000Z0ED`) between each Bobcat signal and a corresponding FMC LA bank pin; add the LA pin-row wiring in `fmc.kicad_sch` per the LA-pair table on lines 73-76 of the requirements doc.

---

### E2. Bobcat OSC_EN, WEIGHT_EN, SAMPLE_TRIG have no FPGA path (SMA only)

**Component(s):** U20 pins 23, 24, 25.
**Requirement:** [design_requirements.md:26](design_requirements.md#L26) and [design_requirements.md:69](design_requirements.md#L69) — *"OSC_EN, WEIGHT_EN, SAMPLE_TRIG (3×) each switchable between SMA and FPGA via 0Ω resistor option."* Also Bobcat PDF page 4: *"OSC_EN, WEIGHT_EN, SAMPLE_TRIG to SMA connectors with 0Ω resistor options to FPGA."*
**Observed:** [connectors.kicad_sch:1354,1369,1384](kicad/connectors.kicad_sch) — these three globals enter the connectors sheet and tie directly to J54/J55/J56 SMAs. There is no 0Ω resistor option to FMC, and no global label for these signals on `fmc.kicad_sch`.
**Impact:** FPGA cannot drive or sense OSC_EN, WEIGHT_EN, or SAMPLE_TRIG. Only manual SMA-source operation possible.
**Fix:** For each of the 3 signals, add a junction between Bobcat-pin and SMA, with an additional 0Ω option to a dedicated FMC LA pin (DNP one side or the other as the user prefers).

---

### E3. Missing 10kΩ pull-downs on Bobcat input signals

**Component(s):** U20 pins 14 (MOSI), 16 (SCLK), 18 (SPI_DMODE), 23 (OSC_EN), 24 (WEIGHT_EN), 25 (SAMPLE_TRIG), 37–40 (GPIO0–3).
**Requirement:** [design_requirements.md:15](design_requirements.md#L15) — *"10kΩ pull-downs on GPIO0–3, SPI_DMODE, SCLK, MOSI, OSC_EN, WEIGHT_EN, SAMPLE_TRIG."* Bobcat PDF page 4 lists the same set.
**Observed:** `grep 'Value" "10k' kicad/*.kicad_sch` returns exactly 2 hits, both in `power.kicad_sch` (R10 = LDO_EN pull-down, R11 = LSW_EN pull-down). Zero 10kΩ resistors exist on `bobcat.kicad_sch`. The required pull-down library part (`CR0402-FX-1002GLF`) is present in `Parts Library/` but unused.
**Impact:** Bobcat inputs (and bidirectional GPIO at reset) float at power-up — undefined input states risk metastability, latch-up, or false triggering of OSC_EN/WEIGHT_EN/SAMPLE_TRIG. The chip is a custom test ASIC; floating inputs are explicitly disallowed per the DUT note.
**Fix:** Add 10 × 10kΩ 0402 resistors from each named pin to GND on `bobcat.kicad_sch`.

---

### E4. Missing 10kΩ pull-ups on Bobcat CS_L and RESET_N

**Component(s):** U20 pins 17 (CS_L), 19 (RESET_N).
**Requirement:** [design_requirements.md:15](design_requirements.md#L15) — *"10kΩ pull-ups on CS_L, RESET_N."* Bobcat PDF page 4 same.
**Observed:** No 10kΩ pull-ups on either net (see E3 grep). CS_L and RESET_N would float at power-up if the FPGA tristates after configuration.
**Impact:** CS_L floating may select Bobcat SPI unintentionally; RESET_N floating may hold the DUT in or out of reset unpredictably. Either condition risks corrupted bring-up.
**Fix:** Add 2 × 10kΩ 0402 resistors to +VDDIO (NOT +3V3, since CS_L/RESET_N are referenced to Bobcat's VDDIO domain). Use the load-switched +VDDIO rail so pulls de-assert when the chip is unpowered.

---

### E5. LDO ANY-OUT setpoint pins are statically configured, not FPGA-driven

**Component(s):** U10 (TPS7A8401A) pins 5 (50_mV), 6 (100_mV), 7 (200_mV), 9 (400_mV), 10 (800_mV), 11 (1.6_V).
**Requirement:** [design_requirements.md:16](design_requirements.md#L16) — *"ANY-OUT setpoint pins driven by FPGA."* Bobcat PDF page 6 (LDO): *"0.6V to 1.0V output via ANYOUT inputs connected to FPGA."*
**Observed:** [power.kicad_sch:1504-1535](kicad/power.kicad_sch#L1504-L1535):
- pin 5 (50_mV) — `no_connect` (line 1532)
- pin 6 (100_mV) — wired to `power:GND` (line 1505)
- pin 7 (200_mV) — wired to `power:GND` (line 1519)
- pin 9 (400_mV) — `no_connect` (line 1533)
- pin 10 (800_mV) — `no_connect` (line 1534)
- pin 11 (1.6_V) — `no_connect` (line 1535)

This hard-codes Vout = 0.5 + 0.1 + 0.2 = **0.8 V**. The Bobcat rails can be **swept anywhere from 0.6 V to 1.0 V** for characterization — a fixed 0.8 V defeats the purpose of the LDO selection (per requirements, TPS7A8401A was chosen specifically because its ANY-OUT covers 0.6–1.0 V).
**Impact:** No way to sweep VDDD/VDDA1/VDDA2 during bring-up; cannot characterize Bobcat at multiple voltage corners. Also blocks FPGA setpoint control through the FMC.
**Fix:** Route each ANY-OUT pin to a dedicated FMC LA pin via a series 0Ω resistor (so the GND wires above become "FMC-driven" instead). The FMC LA-bank picker note in requirements covers this. Alternatively, if FPGA-control is dropped, document that decision in design_requirements.md.

---

### E6. Open-drain LDO_PG has no pull-up resistor

**Component(s):** U10 pin 4 (PG, `open_collector` per symbol — confirmed via lib file lines 207-214).
**Requirement:** Datasheet **TI SBVS210** (TPS7A8401A) §7.3.4 (Power Good): *"PG is an open-drain output and requires an external pull-up resistor to the desired logic-high voltage (typically 10–100 kΩ)."* Also [design_requirements.md:16](design_requirements.md#L16) — *"Open-drain PG output back to FPGA."*
**Observed:** [power.kicad_sch:1548-1549](kicad/power.kicad_sch#L1548-L1549) — pin 4 wires directly through a hier-label `LDO_PG` to FMC pin C1 (`PG_C2M`). No pull-up exists on the LDO_PG net anywhere in the project.
**Impact:** PG is undriven HIGH — it sits at high-impedance when asserted, picking up noise. The FPGA may not see a reliable HIGH state, defeating the power-good handshake. Worse, on an FMC connector with no defined pull-up by the carrier, this is undefined behavior.
**Fix:** Add a 10kΩ pull-up from LDO_PG to +3V3 (mezzanine-side, on the carrier-board copy of the net) in `power.kicad_sch`.

---

### E7. Q42 / Q43 enable-NMOS gates float — no driver, no pull-down

**Component(s):** Q42, Q43 (2N7002, series isolation FETs in the bias outputs).
**Requirement:** [design_requirements.md:25](design_requirements.md#L25) — *"Optional series NMOS enable FETs (DNP, 2N7002) between PMOS drain and BIASx jumper, gated by an MCU GPIO pulled low at reset, for hard hardware isolation independent of EEPROM state."*
**Observed:**
- [bias.kicad_sch:1877](kicad/bias.kicad_sch#L1877) — `BIAS_ISO0` global label on Q42 gate, shape `input`. No matching global label on any other sheet (grep across all 6 sheets returns this single hit).
- [bias.kicad_sch:2036](kicad/bias.kicad_sch#L2036) — same for `BIAS_ISO1` / Q43.
- No pull-down resistor on either net.
**Impact:** If Q42/Q43 are populated, gates float — NMOS may be on, off, or oscillating. If left DNP (as the value text "2N7002 DNP" suggests), the BIAS0/BIAS1 outputs are unconditionally **open** with no current delivered to Bobcat. Either way the bias block is inoperable as described.
**Fix:** (a) Decide whether Q42/Q43 are populated or DNP. (b) If populated, route `BIAS_ISO0` and `BIAS_ISO1` to a controllable source (FMC LA pin via 0Ω) AND add 10kΩ pull-downs to GND so the FETs default OFF at power-up. (c) If DNP, replace Q42/Q43 with 0Ω jumpers in the same path so BIAS0/BIAS1 always source current; the "DNP isolation" requirement is then moot and should be deleted from requirements.

---

### E8. Three Bobcat power rails share one LDO output bus with no interlock

**Component(s):** J10, J11, J12 (1×2 jumper headers for +VDDD, +VDDA1, +VDDA2 selection).
**Requirement:** [design_requirements.md:16](design_requirements.md#L16) — *"Output fans out to Bobcat VDDD, VDDA1, VDDA2 each through a 1×2 jumper."* Read as: each rail individually jumper-selectable (not all three shorted at once).
**Observed:** [power.kicad_sch](kicad/power.kicad_sch) — J10, J11, J12 all attach pin-1 to the same `VLDO_OUT` bus at (190.5, 119.84). Installing more than one shunt **electrically shorts +VDDD, +VDDA1, and +VDDA2 together** at the LDO output.
**Impact:** If the user installs jumpers on all three at once (the obvious "power on everything" gesture), the three Bobcat rails become a single shared rail. Behaviorally this matches the *intent* (all three at the same voltage), but the requirements doc open-question 84 reads *"Confirm a single rail at one ANY-OUT setpoint is acceptable for all three (vs. one LDO per rail for independent setpoints during bring-up)"* — i.e., the current topology *commits* to a single shared setpoint and forecloses the "one LDO per rail" option. This is a design decision that should be made explicit, not implicit via shared-bus shorting.
**Fix:** Either (a) document that the three rails are intentionally one shared rail and remove the open question from requirements, or (b) change the topology to three independent LDOs (one per rail) per the alternative in the open question. The current schematic is in a contradictory middle state.

---

### E9. TPS7A8401A SNS and FB tied to LDO OUT — feedback senses LDO output, not the load

**Component(s):** U10 pins 1 (OUT), 2 (SNS), 3 (FB), 19 (OUT), 20 (OUT).
**Requirement:** Datasheet **TI SBVS210** Figure 23 (Typical application): *SNS routes back from the load* (after any series filtering / 0Ω); *FB is the Kelvin sense to the regulation node*. The point of separating OUT/SNS/FB is to compensate for IR drop in series filtering and PCB trace resistance.
**Observed:** [power.kicad_sch:1536-1547](kicad/power.kicad_sch#L1536-L1547) — pins 1, 2, 3, 19, 20 all short-strapped together at the (165.1, 119.84) node, immediately adjacent to U10. SNS/FB therefore measure U10's own output pin, NOT the voltage at the Bobcat load. Then a 0Ω series-R (R20 or R21) sits between the LDO output and Bobcat — IR drop across that R will not be compensated by the regulation loop.
**Impact:** For a 3 A LDO at 0.8 V with 0Ω = nominally 0 mΩ, the trace + connector + jumper IR drop is the unregulated portion. A 50 mΩ trace at 100 mA = 5 mV droop at the load — within Bobcat's spec, but the high-accuracy (0.75 %) selling point of the TPS7A8401A is wasted at the actual chip pin. Could be acceptable; flagging because the schematic explicitly strapped SNS/FB locally, foreclosing the Kelvin-sense option the part was selected for.
**Fix:** Route SNS (pin 2) and FB (pin 3) as a separate trace back from each Bobcat power pin (or from the J10/J11/J12 header outputs, which are downstream of the bulk caps). The series 0Ω resistors then sit inside the regulation loop, not outside it.

---

## WARNINGs (should fix)

### W1. LDO_EN and LSW_EN hier-labels on FMC sheet are floating

**Component(s):** Root sheet → fmc.kicad_sch interface.
**Observed:** [test1.kicad_sch:25, 27](kicad/test1.kicad_sch#L25-L27) declares `LDO_EN` and `LSW_EN` as output sheet pins on the FMC sub-sheet. Inside `fmc.kicad_sch`, the matching hierarchical_labels exist (lines 18156, 18157) **but no wire connects them to any FMC connector pin** — they hover in space at (290, 100.08) and (290, 105.16), outside the J1..J4 connector grid.
**Impact:** EN signals dangle from the host side. Combined with R10/R11 pull-downs on the power sheet, the LDO and load switch **default OFF and cannot be turned on** by the FPGA. Bring-up requires hand-strapping the EN nets or installing manual jumpers.
**Fix:** Pick FMC LA-bank pins for `LDO_EN` and `LSW_EN`, add wires from those connector pins to the existing hier-labels.

---

### W2. VDDIO has only one 1µF + one 0.1µF cap shared across five Bobcat VDDIO pins

**Component(s):** U20 pins 7, 13, 22, 33, 34 (all VDDIO); C24 (0.1µF), C25 (1µF).
**Requirement:** [design_requirements.md:15](design_requirements.md#L15) — *"Decoupling caps on VDDD, VDDIO, VDDA1, VDDA2."* (Doesn't quantify, but per-pin decoupling is standard practice for a 5x5 mm 40-QFN with 5 VDDIO pins.)
**Observed:** [bobcat.kicad_sch](kicad/bobcat.kicad_sch) — only 2 caps for 5 VDDIO pins. By contrast, VDDD (2 pins) has 2 caps (C20+C21).
**Impact:** Higher rail impedance at frequency than necessary; per-pin transient response degraded; potential coupling between VDDIO domains.
**Fix:** Add 3 more 0.1µF 0402 caps so each VDDIO pin has its own bypass.

---

### W3. No bypass cap dedicated to TPS7A8401A BIAS pin

**Component(s):** U10 pin 12 (BIAS).
**Requirement:** Datasheet TI SBVS210 §8.2.2.1: *"Place a 1 µF ceramic capacitor as close as possible to the BIAS pin."*
**Observed:** Pin 12 is connected to +3V3 with no local cap on the BIAS pin itself. C11 (0.1µF) is the nearest cap on the +3V3 rail at (95.25, 130), ~5mm away from U10.
**Impact:** BIAS pin is unbypassed at high frequency; LDO noise rejection (the headline feature) is compromised. The 4.4 µVrms noise spec assumes a clean BIAS reference.
**Fix:** Add 1 × 1µF 0402 cap from U10 pin 12 to GND, placed as close to the pin as possible on the PCB.

---

### W4. SCL/SDA pull-ups on EEPROM sheet only — bus has 3 endpoints

**Component(s):** R30, R31 (2.2kΩ pull-ups on eeprom.kicad_sch); SCL/SDA bus shared with U40 (MCP4728) on bias.kicad_sch and FMC pin D30/D31.
**Requirement:** Standard I²C topology — pull-ups should be sized for total bus capacitance.
**Observed:** 2.2kΩ to +3V3 — sized for a short, low-cap bus. If the FMC carrier has its own pull-ups on D30/D31, the parallel value is too strong (potentially below the IOL limit of one or more devices). If not, 2.2kΩ for ~3 ICs + FMC trace + carrier-side trace is on the aggressive side but acceptable.
**Impact:** Risk of over-current draw on SDA/SCL during low; or marginal rise time if carrier pull-ups also present.
**Fix:** Confirm Genesys 2 carrier's FMC I²C pull-up scheme. If carrier provides pull-ups, change R30/R31 to DNP. If carrier is high-Z, 2.2kΩ may be fine; verify against bus capacitance budget.

---

### W5. MCP4728 has 0.1µF + 10nF bypass on VDD — non-standard combination

**Component(s):** U40 pin 1 (VDD); C40 (0.1µF), C41 (10nF).
**Requirement:** Datasheet **Microchip 22187E** Figure 2-1 (typical application): *"0.1 µF bypass capacitor placed between VDD and VSS as close to the device as possible."*
**Observed:** [bias.kicad_sch](kicad/bias.kicad_sch) — C40 = 0.1µF and C41 = 10nF placed in parallel on +3V3 near U40. The 10nF is unusual; datasheet shows only 0.1µF.
**Impact:** Cost a redundant cap; not harmful. Just inconsistent with the standard reference.
**Fix:** Drop C41, or change C41 to 10µF for bulk decoupling per typical-app practice.

---

### W6. No bulk cap on VADJ at FMC entry

**Component(s):** VADJ net (FMC G40/H39 → U11 load switch VIN).
**Requirement:** [TPS22916 datasheet TPS22916 §8.2.2.2](Parts%20Library/TPS22916CNYFPR/TPS22916CNYFPR.pdf): *"A bulk capacitor (typically ≥1 µF) on VIN is recommended for transient response."*
**Observed:** [power.kicad_sch:~1700](kicad/power.kicad_sch) — only C15 = 0.1µF on the VADJ side of U11.
**Impact:** VDDIO transient response degraded under Bobcat I/O switching load.
**Fix:** Add 1 × 1µF or 10µF 0402/0805 cap on the VADJ net at U11 VIN.

---

### W7. No bulk cap on VDDIO at U11 output

**Component(s):** +VDDIO net (U11 VOUT → Bobcat pins 7/13/22/33/34).
**Requirement:** TPS22916 datasheet §8.2.2.2: *"A capacitor (typically ≥1 µF) on VOUT helps regulate VOUT during switching."*
**Observed:** Only C16 = 0.1µF on +VDDIO at U11.
**Impact:** Same as W6 — slow VDDIO transient response.
**Fix:** Add 1 × 1µF cap on +VDDIO at U11 output. (The per-pin 0.1µF on Bobcat side is separate — bulk goes here.)

---

### W8. MCP4728 internal V_REF configuration depends on EEPROM programming, no schematic indicator

**Component(s):** U40 (MCP4728).
**Requirement:** [design_requirements.md:20](design_requirements.md#L20) and [design_requirements.md:30](design_requirements.md#L30) — *"external V_REF tied to 3.3 V (NOT the internal 2.048 V ref)"* and *"MCP4728 EEPROM default code: 0xFFF (V_OUT=3.3V → PMOS off → 0 µA at POR)."*
**Observed:** MCP4728 has no physical V_REF pin (10-MSOP / 10-VQFN package). The choice between V_DD-as-V_REF and internal 2.048 V is set via I²C VREF bit (per channel), and persisted in the device's internal EEPROM. The schematic cannot enforce this configuration; the part comes from Microchip with **default V_REF = internal 2.048 V**, not VDD.
**Impact:** If a virgin MCP4728 is soldered without re-programming, V_OUT max = 2.048 V × 2 (gain bit) = 4.096 V *but clipped to VDD = 3.3 V*. The PMOS gate cannot reach VDD = source-off voltage. Bobcat will see uncontrolled bias current at POR — potentially damaging the DUT.
**Fix:** Add a board-level provisioning step or a fixture jig that programs the MCP4728's EEPROM to VREF=VDD + code=0xFFF before installing the chip on production boards. Document this in the BOM/assembly notes. Consider a footprint for a pre-programmed device only (factory-programmed orderable variant if Microchip offers one).

---

### W9. DNP convention inconsistent for Q42/Q43

**Component(s):** Q42, Q43 (2N7002 isolation FETs).
**Observed:** [bias.kicad_sch](kicad/bias.kicad_sch) — value text reads `"2N7002 DNP"` but the symbol's `(dnp …)` attribute is `no`. The two ways of declaring DNP disagree.
**Impact:** Whichever tool reads the schematic next (BOM generator, PnP placement, ERC) may or may not exclude these parts depending on which signal it reads. Risk of accidental placement or accidental exclusion.
**Fix:** Pick one convention. Recommended: set `(dnp yes)` on the symbol and change the Value field to plain `"2N7002"`. This way the DNP status is machine-readable and the value reflects the part number, not its assembly state.

---

### W10. Power-good output back to host has no buffer/diode protection

**Component(s):** LDO_PG net → FMC C1 (PG_C2M).
**Requirement:** None explicit; best practice for connecting any open-drain signal to an external connector pin.
**Observed:** LDO_PG drives FMC C1 directly through the open-drain LDO PG pin (no pull-up — see E6) and no series protection resistor.
**Impact:** If the FMC carrier ever asserts C1 high (despite the FMC spec listing it as M2C output), back-driving could damage the LDO's PG output (rated ~30 mA sink). Probability low but consequence moderate.
**Fix:** Add a 1kΩ series resistor on LDO_PG between U10 pin 4 and the hier-label, plus the 10kΩ pull-up from E6.

---

## INFOs

### I1. MCP4728 channels C and D unused (NC)

**Observation:** U40 pins 8 (VOUTC) and 9 (VOUTD) are `no_connect`. The MCP4728 is a quad DAC; this design uses 2 of 4 channels. If Bobcat ever needs additional analog setpoints (e.g., FPGA-controlled ANY-OUT for the LDO — see E5), VOUTC/D could carry those signals without adding a part.

### I2. Bobcat NC pins 21 and 30 are correctly NC'd

[bobcat.kicad_sch](kicad/bobcat.kicad_sch) explicit `(no_connect …)` markers on pins 21 and 30 match the Bobcat PDF page 4 pinout diagram (NC labels). No issue — flagging only because NCs are easy to overlook in a review.

### I3. EEPROM A0/A1/A2 tied to GND — correct for 24AA08

The 24AA08 is the 8-Kbit variant; address pins are not used (datasheet §3.4: *"Pins A0, A1, and A2 are no-connects for the 24XX08."*). Tying to GND is safe and matches the 24XX16 family convention. The I²C address is 0xA0 (1010 b3 b2 b1 with b3/b2/b1 selecting one of 8 internal pages).

### I4. FMC GND pin coverage matches VITA 57.1

Verified J1..J4 GND pin lists against requirements doc lines 33-78 and VITA 57.1 LPC spec — all GND pins (including H2 = PRSNT_M2C_L tied to GND per LPC convention) are correctly grounded. No issues.

### I5. Requirements doc internal inconsistency: H2 listed in two tables

[design_requirements.md:42](design_requirements.md#L42) lists H2 as PRSNT_M2C_L (correct per LPC); [design_requirements.md:60](design_requirements.md#L60) lists H2/H3 as CLK1_M2C_P/N (incorrect for LPC; that's an HPC-only pair). Schematic follows the first (correct) table — H2 to GND. Not a schematic bug; recommend cleaning up the requirements doc to remove the conflicting clock-table line.

### I6. Eight `+VDDIO` power symbol instances on bobcat.kicad_sch

Visual clutter, not an electrical issue: KiCad collapses identical power-symbol nets. The duplication arises from having one power symbol per VDDIO pin attachment. Optional cleanup: use a single +VDDIO label routed to all 5 pins.

---

## Cross-references — Pass-1 (datasheet) ↔ Pass-2 (requirements)

| Finding | Datasheet says | Requirements say | Schematic does | Concur? |
|---|---|---|---|---|
| E1 | (n/a — chip-side) | Route SAMPLE_OUT* + SPI to FMC LA via 0Ω | Dangling globals; no 0Ω | Reqs say yes → MISSING |
| E2 | (n/a) | SMA + 0Ω option to FPGA | SMA only | Reqs say yes → MISSING |
| E3 | Bobcat PDF p.4 says 10kΩ pull-downs | Same | None present | Both agree → MISSING |
| E4 | Bobcat PDF p.4 says 10kΩ pull-ups | Same | None present | Both agree → MISSING |
| E5 | TPS7A8401A DS: ANY-OUT settable | "Driven by FPGA" | Static 0.8 V (GND straps) | Reqs say FPGA → DEVIATION |
| E6 | TPS7A8401A DS: PG needs pull-up | "Open-drain output" | No pull-up | Both agree → MISSING |
| E7 | (n/a) | DNP NMOS w/ pull-down at reset | No pull-down, no driver | Reqs say pull-down → MISSING |
| E8 | (n/a) | One jumper per rail | All three on same bus | Topology mismatch |
| E9 | TPS7A8401A DS: SNS/FB Kelvin-sense | (silent) | Strapped locally | DS prefers separate → DEVIATION |
| W1 | (n/a) | EN driven by FPGA via FMC | EN labels not wired to FMC | Reqs say wired → MISSING |
| W3 | TPS7A8401A DS: 1µF on BIAS pin | (silent) | None | DS says yes → MISSING |
| W6 | TPS22916 DS: ≥1µF on VIN | (silent) | 0.1µF only | DS says yes → INSUFFICIENT |
| W7 | TPS22916 DS: ≥1µF on VOUT | (silent) | 0.1µF only | DS says yes → INSUFFICIENT |
| W8 | MCP4728 DS: default VREF = 2.048V int | "External VREF = 3.3V" | Needs EEPROM provisioning | Procedural gap |

---

## Notes on what was NOT reviewed

- **PCB layout** — this audit is schematic-only. Layout review (50Ω SMA trace impedance, plane stitching, decoupling cap placement on PCB, FMC mating geometry, mounting holes per Bobcat PDF page 12) is out of scope.
- **BOM cross-check** — verified parts in `Parts Library/` are referenced by the schematic, but did not audit MPN-to-symbol fidelity beyond pin-name spot checks. Recommend a separate BOM-vs-schematic pass.
- **Mechanical** — Bobcat PDF page 12 lists FMC width 69 mm and mounting-hole positions at far corners; not verified here.
- **EMI / signal integrity** — CLK_OUT* and SAMPLE_OUT* run direct from Bobcat to SMA/FMC with no termination. May need source termination or AC-coupling depending on actual signal characteristics — Bobcat PDF doesn't specify edge rates, so left as TBD.
