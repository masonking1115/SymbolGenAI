"""EEPROM child sheet — 24AA08-I-SN I²C EEPROM.

Phase B: parts inventory + nets are declared in netlist/eeprom.yaml. This
file only owns LAYOUT (positions + wire routing). At the end of build_eeprom
the strict validator cross-checks that every YAML net member is in a
connected component named that net.
"""

from __future__ import annotations

from .config import (
    PAGE_NUMBERS,
    PROJECT_NAME,
    SHEET_UUIDS,
)
from .netlist import load_netlist
from .shared import (
    Sheet,
    global_label,
    gnd_bus,
    junction,
    place_from_netlist,
    power_at,
    wire,
)
from .validator import validate


def build_eeprom() -> Sheet:
    nl = load_netlist("eeprom")
    s = Sheet(name="eeprom", uuid=SHEET_UUIDS["eeprom"],
              page=PAGE_NUMBERS["eeprom"],
              title=f"{PROJECT_NAME} — EEPROM (24AA08 I²C)")

    # --- U30: 24AA08 at (100, 120). Body x ∈ [100, 176.2], y ∈ [120, 127.62].
    # Pin world coords at angle 0:
    #   1 A_0 (100, 120)        5 SDA (176.2, 127.62)
    #   2 A_1 (100, 122.54)     6 SCL (176.2, 125.08)
    #   3 A_2 (100, 125.08)     7 WP  (176.2, 122.54)
    #   4 VSS (100, 127.62)     8 VCC (176.2, 120)
    place_from_netlist(s, nl, "U30", x=100, y=120)

    # --- Left side: pins 1-4 (A0/A1/A2/VSS) → shared GND rail (Rule 7).
    gnd_bus(s, [(100, y) for y in (120, 122.54, 125.08, 127.62)], rail_x=92.71)

    # +3V3 rail runs horizontally at y = 105.41 (14.59 mm above chip top)
    RAIL_Y = 105.41
    GND_RAIL_Y = 142.24  # 14.62 mm below chip bottom

    # Pin 8 VCC → up to +3V3 rail
    s.add(wire(176.2, 120, 184.15, 120))
    s.add(wire(184.15, 120, 184.15, RAIL_Y))

    # Pin 7 WP → down to GND (separate column, not stacked with VCC)
    s.add(wire(176.2, 122.54, 189.23, 122.54))
    s.add(wire(189.23, 122.54, 189.23, GND_RAIL_Y))
    power_at(s, "GND", 189.23, GND_RAIL_Y)

    # Pin 6 SCL → horizontal bus, exits as global_label (project-wide I²C).
    SCL_LABEL_X = 237.49
    SDA_LABEL_X = 237.49
    s.add(wire(176.2, 125.08, SCL_LABEL_X, 125.08))
    s.add(global_label("SCL", "bidirectional", SCL_LABEL_X, 125.08, angle=0))

    s.add(wire(176.2, 127.62, SDA_LABEL_X, 127.62))
    s.add(global_label("SDA", "bidirectional", SDA_LABEL_X, 127.62, angle=0))

    # --- C30: decoupling cap. Place at (200.66, 116.84) so pins land on grid.
    # Pin 1 (top, +3V3) at (200.66, 113.03); pin 2 (bot, GND) at (200.66, 120.65).
    place_from_netlist(s, nl, "C30", x=200.66, y=116.84)
    s.add(wire(200.66, 113.03, 200.66, RAIL_Y))           # top to +3V3 rail
    s.add(wire(200.66, 120.65, 200.66, GND_RAIL_Y))       # bottom to GND rail
    power_at(s, "GND", 200.66, GND_RAIL_Y)

    # --- R60 (SCL pull-up): vertical, placed well above the SCL line so the
    # body doesn't crowd C30 or R61.
    # Place at (215.9, 113.03). Pin 1 (top, +3V3) at (215.9, 109.22); pin 2
    # (bot) at (215.9, 116.84). Then route pin 2 down to SCL line at y=125.08.
    place_from_netlist(s, nl, "R60", x=215.9, y=113.03)
    s.add(wire(215.9, 109.22, 215.9, RAIL_Y))             # to +3V3 rail
    s.add(wire(215.9, 116.84, 215.9, 125.08))             # down to SCL
    s.add(junction(215.9, 125.08))

    # --- R61 (SDA pull-up): same column-spacing rule. Place at (228.6, 113.03)
    # — 12.7 mm right of R60 — so the value labels don't crowd.
    place_from_netlist(s, nl, "R61", x=228.6, y=113.03)
    s.add(wire(228.6, 109.22, 228.6, RAIL_Y))
    s.add(wire(228.6, 116.84, 228.6, 127.62))
    s.add(junction(228.6, 127.62))

    # --- +3V3 rail: one horizontal wire tying VCC, C30, R60, R61 together ---
    s.add(wire(184.15, RAIL_Y, 228.6, RAIL_Y))
    # Junctions where verticals tap the rail
    for x in (200.66, 215.9):
        s.add(junction(x, RAIL_Y))
    # +3V3 power symbol — its pin sits at the symbol origin, so place AT the
    # rail (its triangle extends upward in editor view = lower y on screen)
    power_at(s, "+3V3", 228.6, RAIL_Y)

    # Strict validation: every YAML-declared net member is in a connected
    # component named that net (raises ValidationError otherwise).
    validate(s, nl)
    return s
