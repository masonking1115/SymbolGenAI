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

    # --- U30: 24AA08 at (100.33, 119.38) — 50-grid corner. Pins on left edge
    # (1-4 at y=119.38..127.0) and right edge (5-8 mirrored).
    U30 = place_from_netlist(s, nl, "U30", x=100.33, y=119.38)
    CHIP_LEFT_X  = U30["1"][0]   # left-side pin x
    CHIP_RIGHT_X = U30["8"][0]   # right-side pin x (= VCC)

    # --- Left side: pins 1-4 (A0/A1/A2/VSS) → shared GND rail (Rule 7).
    gnd_bus(s, [U30[pn] for pn in ("1", "2", "3", "4")], rail_x=CHIP_LEFT_X - 7.62)

    # +3V3 rail (~14 mm above chip top) + GND rail (~15 mm below chip bottom)
    RAIL_Y     = U30["1"][1] - 13.97
    GND_RAIL_Y = U30["4"][1] + 15.24

    # Pin 8 VCC → up to +3V3 rail
    VCC_COL_X = CHIP_RIGHT_X + 7.62
    s.add(wire(*U30["8"], VCC_COL_X, U30["8"][1]))
    s.add(wire(VCC_COL_X, U30["8"][1], VCC_COL_X, RAIL_Y))

    # Pin 7 WP → down to GND (separate column, not stacked with VCC)
    WP_COL_X = CHIP_RIGHT_X + 12.7
    s.add(wire(*U30["7"], WP_COL_X, U30["7"][1]))
    s.add(wire(WP_COL_X, U30["7"][1], WP_COL_X, GND_RAIL_Y))
    power_at(s, "GND", WP_COL_X, GND_RAIL_Y)

    # Pins 6/5 SCL/SDA → horizontal bus, exits as global_label (project-wide I²C).
    I2C_LABEL_X = CHIP_RIGHT_X + 60.96
    s.add(wire(*U30["6"], I2C_LABEL_X, U30["6"][1]))
    s.add(global_label("SCL", "bidirectional", I2C_LABEL_X, U30["6"][1], angle=0))
    s.add(wire(*U30["5"], I2C_LABEL_X, U30["5"][1]))
    s.add(global_label("SDA", "bidirectional", I2C_LABEL_X, U30["5"][1], angle=0))

    # --- C30: decoupling cap. Pin 1 (top, +3V3) lands on RAIL_Y; pin 2 to GND_RAIL_Y.
    C30_X = CHIP_RIGHT_X + 24.13
    C30_Y = RAIL_Y + 11.43        # cap center; pin 1 at RAIL_Y, pin 2 at RAIL_Y+7.62*2
    place_from_netlist(s, nl, "C30", x=C30_X, y=C30_Y)
    s.add(wire(C30_X, C30_Y - 3.81, C30_X, RAIL_Y))           # top to +3V3 rail
    s.add(wire(C30_X, C30_Y + 3.81, C30_X, GND_RAIL_Y))       # bottom to GND rail
    power_at(s, "GND", C30_X, GND_RAIL_Y)

    # --- R60 (SCL pull-up): vertical, placed well above SCL line so the body
    # doesn't crowd C30 or R61.
    R60_X = CHIP_RIGHT_X + 39.37
    R60_Y = RAIL_Y + 7.62
    place_from_netlist(s, nl, "R60", x=R60_X, y=R60_Y)
    s.add(wire(R60_X, R60_Y - 3.81, R60_X, RAIL_Y))             # to +3V3 rail
    s.add(wire(R60_X, R60_Y + 3.81, R60_X, U30["6"][1]))        # down to SCL
    s.add(junction(R60_X, U30["6"][1]))

    # --- R61 (SDA pull-up): one grid right of R60.
    R61_X = R60_X + 12.7
    R61_Y = R60_Y
    place_from_netlist(s, nl, "R61", x=R61_X, y=R61_Y)
    s.add(wire(R61_X, R61_Y - 3.81, R61_X, RAIL_Y))
    s.add(wire(R61_X, R61_Y + 3.81, R61_X, U30["5"][1]))
    s.add(junction(R61_X, U30["5"][1]))

    # --- +3V3 rail: one horizontal wire tying VCC, C30, R60, R61 together ---
    s.add(wire(VCC_COL_X, RAIL_Y, R61_X, RAIL_Y))
    for x in (C30_X, R60_X):
        s.add(junction(x, RAIL_Y))
    # +3V3 power symbol at the right end of the rail.
    power_at(s, "+3V3", R61_X, RAIL_Y)

    # Strict validation: every YAML-declared net member is in a connected
    # component named that net (raises ValidationError otherwise).
    validate(s, nl)
    return s
