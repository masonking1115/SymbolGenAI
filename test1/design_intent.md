# Design intent — cross-sheet gotchas

Facts an agent **cannot derive from a single sheet's netlist** but must respect
before editing. These are deliberate architectural decisions; treat a change
that breaks one as a topology decision needing human approval, not a routine edit.

Keep this file short and high-signal. One fact per bullet. Cite the sheets/refs
involved so it's verifiable.

## Power / rails

- **U10 (TPS7A8401A VDDA LDO) is in ANY-OUT pin-strap mode, and the strap pins
  are an FPGA-controlled feature — not spare straps.** The `LDO_SET_*` pins
  (U10.5,6,7,9,10,11) are routed as global nets through 0Ω resistors
  **R122–R127 on the FMC sheet to the FPGA (LA22–LA27)**. The FPGA *dynamically
  programs VOUT (≈0.6–1.0 V)* over these pins; at power-on they float → 0.5 V
  floor. **Do not** convert U10 to a fixed external-divider/adjustable config to
  add a feed-forward cap (CFF): that destroys the programmable-VDDA feature and
  orphans the six `LDO_SET_*` globals + R122–R127. A true CFF is only possible in
  adjustable mode; the two goals are mutually exclusive. (Verified run
  663dd7435673.) If HF PSRR must improve, that is a human-level architecture
  tradeoff — STOP and report, don't auto-apply.

- **U10 FB/SNS are strapped to OUT** (`internal_LDO_OUT_bus`). A capacitor wired
  OUT→FB therefore shorts across one node (the `shorted_component` gate catches
  it). OUT-side bulk/HF caps (C13/C18/C14/C19 → OUT/GND) are the realizable form.

## Bias

- **R40/R41 = 3.65 kΩ 0.1% sense resistors** set the OPA bias current; the sim
  deck (`opa_bias`) extracts these from `bias.yaml`'s `value` field via
  `design_extract.sense_resistance()` (parses "3.65k 0.1%" → 3650 Ω). Changing
  them changes the simulated ideal-current formula too — keep value + sim in sync.
  **Value was lowered from 5.11k → 3.65k** because at 5.11k the regulated
  full-scale capped at ~484 µA (I·R left no headroom over the 0.5 V DUT
  compliance), failing rule BLK_BIAS_FS_CEILING (needs ≥640 µA). **Do NOT raise
  R40/R41 back toward 5.11k** to "match the part number" — fix the MPN instead
  (see next bullet). The direction is fixed: lower R_sense satisfies the ceiling.

- **R40/R41 value↔MPN mismatch RESOLVED (2026-05-30).** Repointed `lib_id`
  `Lib:TNPW06035K11BEEA` (5.11k) → `Lib:TNPW06033K65BEEA` (3.65k 0.1%, same
  TNPW0603 e3 series) to match the 3.65k value (rule CHK_VALUE_MATCHES_MPN). A new
  per-MPN `.SchLib` was authored (`Parts Library/TNPW06033K65BEEA/`) from a pinspec
  copied from the 5.11k sibling, so pin geometry is IDENTICAL and `build_bias.py`
  routing doesn't shift. The pre-existing package mismatch was fixed in the same
  pass: footprint `R_0402_1005Metric` → `R_0603_1608Metric` (TNPW0603 is a 0603,
  confirmed RR1608M in tnpw_e3.pdf). Do NOT raise the value back to 5.11k — see
  prior bullet (lower R_sense is required for the FS ceiling).

- **R42/R43 are DNP (0Ω jumpers left unpopulated)** — the 2N7002 isolator is the
  active POR-failsafe path, not the jumper. Don't model/treat them as closed.

- **U40 (MCP4728) "external VREF tied to 3.3V" is an EEPROM config BIT, not a
  pin.** The MCP4728 has NO VREF pin (10-pin VQFN: VDD/SCL/SDA/*LDAC/RDY/4×VOUT/
  VSS). "External reference" per the datasheet (22187E p.1) *is* VDD — selecting
  it (per channel, in the config register/EEPROM) sets output range 0–VDD for
  rail-to-rail swing. VDD is already on +3V3 (U40.1), so the requirement is
  satisfied by config alone. **Do not add a VREF net/pin to "tie VREF to 3.3V"**
  — it would be a phantom pin and break connectivity. Rule SEM_MCP4728_VREF_EXTERNAL
  is a config/firmware assertion, not a schematic-wireable one.

- **U10 (TPS7A8401A) open-drain PG already has its pull-up — R12 (10kΩ→+3V3)
  sits on the PG node (`internal_LDO_PG_stub`: U10.4 + R12.2 + R13.2), with R13
  (1kΩ series) out to the FMC `LDO_PG` net.** Rule SEM_LDO_PG_OPEN_DRAIN is
  already satisfied; don't add a second pull-up. The semantic evaluator can't see
  R12's far-side wiring (it only gets the rule-refdes pin→net map + the sheet
  part list), so this rule may re-fire spuriously — it's not a missing part.

<!-- Add new cross-sheet facts here as they're discovered. Prefer adding a fact
     the moment an agent had to rediscover it the hard way. -->
