"""Root sheet — embeds the 6 child sheets in a 2×3 grid, declares the
parent-child hierarchical pins (per-child direction = from child's
perspective). Project-wide nets (SCL/SDA, deferred LA-bank signals) use
global_label inside children and don't need parent pins here.
"""

from __future__ import annotations

from .config import (
    PAGE_NUMBERS,
    PROJECT_NAME,
    ROOT_UUID,
    SHEET_UUIDS,
)
from .shared import Sheet, SheetPin, sheet_block


def build_root() -> Sheet:
    s = Sheet(name="root", uuid=ROOT_UUID, page=PAGE_NUMBERS["root"],
              title=f"{PROJECT_NAME} — Bobcat Carrier (root)")

    # 6 sheet blocks in a 2x3 grid, A3 paper (420 x 297 mm usable ~ 400 x 280).
    # All dims snapped to 50-grid (multiples of 1.27 mm).
    W, H = 100.33, 64.77
    GAP_X, GAP_Y = 25.4, 30.48
    X0, Y0 = 30.48, 35.56

    layout = [
        ("fmc",        (X0,                 Y0)),
        ("power",      (X0 + W + GAP_X,     Y0)),
        ("bobcat",     (X0 + 2*(W+GAP_X),   Y0)),
        ("eeprom",     (X0,                 Y0 + H + GAP_Y)),
        ("bias",       (X0 + W + GAP_X,     Y0 + H + GAP_Y)),
        ("connectors", (X0 + 2*(W+GAP_X),   Y0 + H + GAP_Y)),
    ]

    # Crossing-signal pin lists per child (parent's view).
    # These describe what nets exit/enter each sheet at the root level.
    # Directions are from the CHILD's perspective: input = into child, output = out of child.
    # Sheet-pin direction convention: each parent pin matches the CHILD's
    # hier_label direction (i.e. direction is from the child sheet's
    # perspective). Project-wide nets (SCL/SDA, deferred LA-bank signals)
    # use global_label inside child sheets and don't need parent pins here.
    # All pin offsets are 50-grid (multiples of 1.27 mm); 5.08 mm uniform spacing.
    sheet_pins = {
        "fmc": [
            SheetPin("VADJ",   "output", "right",  5.08),    # exits FMC toward Power
            SheetPin("LDO_EN", "output", "right", 15.24),    # FPGA → FMC → Power
            SheetPin("LDO_PG", "input",  "right", 20.32),    # Power → FMC → FPGA
            SheetPin("LSW_EN", "output", "right", 25.4),     # FPGA → FMC → Power
        ],
        "power": [
            SheetPin("VADJ",   "input",  "left",  5.08),     # enters Power from FMC
            SheetPin("LDO_EN", "input",  "left", 15.24),     # enters Power
            SheetPin("LDO_PG", "output", "left", 20.32),     # exits Power
            SheetPin("LSW_EN", "input",  "left", 25.4),      # enters Power
        ],
        "bobcat": [
            SheetPin("BIAS0",    "input",  "left",  5.08),   # from Bias channel 0
            SheetPin("BIAS1",    "input",  "left", 10.16),   # from Bias channel 1
            SheetPin("CLK_OUT0", "output", "right", 5.08),
            SheetPin("CLK_OUT1", "output", "right", 10.16),
            SheetPin("CLK_OUT2", "output", "right", 15.24),
            SheetPin("CLK_OUT3", "output", "right", 20.32),
            SheetPin("GPIO0",    "output", "right", 30.48),
            SheetPin("GPIO1",    "output", "right", 35.56),
            SheetPin("GPIO2",    "output", "right", 40.64),
            SheetPin("GPIO3",    "output", "right", 45.72),
        ],
        "eeprom": [],   # SCL/SDA are global_label
        "bias": [
            SheetPin("BIAS0", "output", "right", 5.08),
            SheetPin("BIAS1", "output", "right", 10.16),
        ],
        "connectors": [
            SheetPin("CLK_OUT0", "input", "left",  5.08),
            SheetPin("CLK_OUT1", "input", "left", 10.16),
            SheetPin("CLK_OUT2", "input", "left", 15.24),
            SheetPin("CLK_OUT3", "input", "left", 20.32),
            SheetPin("GPIO0",    "input", "left", 30.48),
            SheetPin("GPIO1",    "input", "left", 35.56),
            SheetPin("GPIO2",    "input", "left", 40.64),
            SheetPin("GPIO3",    "input", "left", 45.72),
        ],
    }

    for child, (sx, sy) in layout:
        s.add(sheet_block(child, SHEET_UUIDS[child], PAGE_NUMBERS[child],
                          sx, sy, W, H, sheet_pins[child]))

    return s
