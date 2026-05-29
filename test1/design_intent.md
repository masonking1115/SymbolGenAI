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

<!-- Add new cross-sheet facts here as they're discovered. Prefer adding a fact
     the moment an agent had to rediscover it the hard way. -->
