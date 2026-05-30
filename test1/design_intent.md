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

- **R40/R41 = 5.11 kΩ sense resistors** set the OPA bias current; the sim deck
  (`opa_bias`) extracts these from `bias.yaml` via `design_extract`. Changing
  them changes the simulated ideal-current formula too — keep value + sim in sync.

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
