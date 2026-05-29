"""AI-assisted simulation layer for the test1 Altium schematic pipeline.

Closes the feedback loop after lint + design-review: reads the as-built design
from netlist/<sheet>.yaml (the same declarative source the Altium builders
consume — component values flow in via sim/design_extract.py), augments active
parts with behavioral models, runs ngspice in batch mode, and emits a JSON
summary the agent interprets against datasheets + requirements.

Architecture:
  - Block catalog (blocks.yaml) curates the OFF-SHEET boundary (source impedance,
    enable timing, load currents) + pass criteria; component VALUES (caps, the
    bias sense resistor) come from the netlist via design_extract, so a design
    change flows straight into the sim.
  - Deck builders (decks/ldo_rail, opa_bias, pdn) assemble per-block SPICE.
  - Behavioral models only (models.py) — no vendor .lib files required.
"""
