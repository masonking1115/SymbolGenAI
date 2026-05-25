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
    # Each block 95 mm wide, 60 mm tall, spaced 15 mm apart.
    W, H = 100, 65
    GAP_X, GAP_Y = 25, 30
    X0, Y0 = 30, 35

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
    sheet_pins = {
        "fmc": [
            SheetPin("VADJ",   "output", "right",  5),    # exits FMC toward Power
            SheetPin("LDO_EN", "output", "right", 15),    # FPGA → FMC → Power
            SheetPin("LDO_PG", "input",  "right", 20),    # Power → FMC → FPGA
            SheetPin("LSW_EN", "output", "right", 25),    # FPGA → FMC → Power
        ],
        "power": [
            SheetPin("VADJ",   "input",  "left",  5),     # enters Power from FMC
            SheetPin("LDO_EN", "input",  "left", 15),     # enters Power
            SheetPin("LDO_PG", "output", "left", 20),     # exits Power
            SheetPin("LSW_EN", "input",  "left", 25),     # enters Power
        ],
        "bobcat": [
            SheetPin("BIAS0",    "input",  "left",  5),   # from Bias channel 0
            SheetPin("BIAS1",    "input",  "left", 10),   # from Bias channel 1
            SheetPin("CLK_OUT0", "output", "right", 5),
            SheetPin("CLK_OUT1", "output", "right", 10),
            SheetPin("CLK_OUT2", "output", "right", 15),
            SheetPin("CLK_OUT3", "output", "right", 20),
            SheetPin("GPIO0",    "output", "right", 30),
            SheetPin("GPIO1",    "output", "right", 35),
            SheetPin("GPIO2",    "output", "right", 40),
            SheetPin("GPIO3",    "output", "right", 45),
        ],
        "eeprom": [],   # SCL/SDA are global_label
        "bias": [
            SheetPin("BIAS0", "output", "right", 5),
            SheetPin("BIAS1", "output", "right", 10),
        ],
        "connectors": [
            SheetPin("CLK_OUT0", "input", "left",  5),
            SheetPin("CLK_OUT1", "input", "left", 10),
            SheetPin("CLK_OUT2", "input", "left", 15),
            SheetPin("CLK_OUT3", "input", "left", 20),
            SheetPin("GPIO0",    "input", "left", 30),
            SheetPin("GPIO1",    "input", "left", 35),
            SheetPin("GPIO2",    "input", "left", 40),
            SheetPin("GPIO3",    "input", "left", 45),
        ],
    }

    for child, (sx, sy) in layout:
        s.add(sheet_block(child, SHEET_UUIDS[child], PAGE_NUMBERS[child],
                          sx, sy, W, H, sheet_pins[child]))

    return s
