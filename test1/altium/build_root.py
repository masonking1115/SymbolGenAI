"""Root sheet — Altium port of gen/build_root.py.

Embeds the 6 child sheets as hierarchical sheet symbols in a 2x3 grid and
declares the parent-child crossing pins (sheet entries). Directions are from
the CHILD's perspective. Project-wide nets (SCL/SDA) use ports inside the
children and need no parent entry. Coordinates in mils; Altium Y grows UP so
the top row sits at the larger y.
"""

from __future__ import annotations

from .config import OUT_DIR, RENDER_DIR
from .shared import AltiumSheet, build_centered

W, H = 4000, 2600
GAP_X, GAP_Y = 1200, 1200
X0, Y_BOT = 400, 400
Y_TOP = Y_BOT + H + GAP_Y
COL = [X0, X0 + W + GAP_X, X0 + 2 * (W + GAP_X)]

# (child, title, (x, y))
LAYOUT = [
    ("fmc",        "FMC Connector",          (COL[0], Y_TOP)),
    ("power",      "Power",                  (COL[1], Y_TOP)),
    ("bobcat",     "Bobcat DUT",             (COL[2], Y_TOP)),
    ("eeprom",     "EEPROM",                 (COL[0], Y_BOT)),
    ("bias",       "Bias Generators",        (COL[1], Y_BOT)),
    ("connectors", "Connectors / Breakouts", (COL[2], Y_BOT)),
]

# entries: (name, io [child's view], side, distance_from_top_mil)
ENTRIES = {
    "fmc": [("VADJ", "output", "right", 200), ("LDO_EN", "output", "right", 600),
            ("LDO_PG", "input", "right", 800), ("LSW_EN", "output", "right", 1000)],
    "power": [("VADJ", "input", "left", 200), ("LDO_EN", "input", "left", 600),
              ("LDO_PG", "output", "left", 800), ("LSW_EN", "input", "left", 1000)],
    "bobcat": [("BIAS0", "input", "left", 200), ("BIAS1", "input", "left", 400),
               ("CLK_OUT0", "output", "right", 200), ("CLK_OUT1", "output", "right", 400),
               ("CLK_OUT2", "output", "right", 600), ("CLK_OUT3", "output", "right", 800),
               ("GPIO0", "output", "right", 1200), ("GPIO1", "output", "right", 1400),
               ("GPIO2", "output", "right", 1600), ("GPIO3", "output", "right", 1800)],
    "eeprom": [],
    "bias": [("BIAS0", "output", "right", 200), ("BIAS1", "output", "right", 400)],
    "connectors": [("CLK_OUT0", "input", "left", 200), ("CLK_OUT1", "input", "left", 400),
                   ("CLK_OUT2", "input", "left", 600), ("CLK_OUT3", "input", "left", 800),
                   ("GPIO0", "input", "left", 1200), ("GPIO1", "input", "left", 1400),
                   ("GPIO2", "input", "left", 1600), ("GPIO3", "input", "left", 1800)],
}


def build_root() -> AltiumSheet:
    s = AltiumSheet(name="root", title="test1 — Bobcat Carrier (root)")
    for child, title, (x, y) in LAYOUT:
        s.sheet_symbol(child, title, x, y, W, H, ENTRIES[child])
    return s


def main() -> int:
    s = build_centered(build_root)
    out = s.save(OUT_DIR / "root.SchDoc")
    svg = s.render_svg(RENDER_DIR / "root.svg")
    print(f"wrote {out.name} + {svg.name} (6 sheet symbols)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
