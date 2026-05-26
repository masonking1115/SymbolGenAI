"""AI-assisted simulation layer for the test1 schematic pipeline.

Closes the feedback loop after lint + design-review: takes the YAML net
description (or a kicad-cli SPICE export), augments active parts with
behavioral models, runs ngspice in batch mode, and emits a JSON summary
the agent can read.

Scope of the PoC:
  - Driven from netlist/power.yaml (LDO + load switch + decoupling).
  - Three sim types: DC op-point, transient power-up, transient load-step.
  - Behavioral models only — no vendor .lib files required.
"""
