"""Unit + grid helpers for the Altium backend.

The KiCad generator works in millimetres on a 1.27 mm (50 mil) grid floor.
Altium's public authoring APIs are in mils and the conventional schematic grid
is 100 mil. This module is the single place that owns the conversion so the
rest of the Altium backend never juggles raw unit math inline.

Note on Y axis: KiCad world Y grows DOWN; Altium schematic Y grows UP (mils
from the sheet's lower-left origin). Coordinate-producing code that ports a
KiCad layout must flip Y about the sheet height — `flip_y()` does that. The
current builders author directly in Altium-native coords, so they do not need
the flip; it is provided in case a future port has to ingest KiCad coordinates.
"""

from __future__ import annotations

MIL_PER_MM = 39.37007874015748   # 1 mm / 0.0254 mm-per-mil
SCH_GRID_MIL = 100.0             # standard Altium schematic placement grid


def mm_to_mil(mm: float) -> float:
    """KiCad millimetres -> Altium mils."""
    return mm * MIL_PER_MM


def mil_to_mm(mil: float) -> float:
    """Altium mils -> KiCad millimetres."""
    return mil / MIL_PER_MM


def snap(mil: float, grid: float = SCH_GRID_MIL) -> int:
    """Snap a mil value to the schematic grid, returned as int mils.

    Altium pin hot-spots and wires must land on-grid or nets fail to connect;
    this is the Altium analogue of the KiCad layout linter's grid floor.
    """
    return int(round(mil / grid) * grid)


def flip_y(y_mil: float, sheet_height_mil: float) -> float:
    """Convert a KiCad (Y-down) coord to Altium (Y-up) for a given sheet height."""
    return sheet_height_mil - y_mil


# --- pin-name geometry ------------------------------------------------------
# Pin names render INSIDE the body, growing inward from each side. If the body
# is too narrow, a long left name and a long right name on the same row collide
# into an unreadable overlap (the EEPROM "SER_DATA_I/O" over "VSS" case). These
# helpers size the body so names fit, and are shared by the symbol author
# (author_symbol) and the layout linter so both agree on the same rule.
PIN_NAME_FONT_MIL = 100.0   # FONT_DEFAULT size 10 ~= 100 mil rendered height
PIN_NAME_GAP_MIL = 120.0    # min clear gap between opposing inward names


def text_width_mil(text: str, font_mil: float = PIN_NAME_FONT_MIL) -> float:
    """Rendered width of `text` in mils for the default schematic pin font."""
    if not text or text == "~":
        return 0.0
    from altium_monkey.altium_text_metrics import measure_text_width
    return float(measure_text_width(text, font_mil))


def min_half_x_for_names(left_names, right_names, base: int = 300,
                         gap: float = PIN_NAME_GAP_MIL) -> int:
    """Smallest on-grid body half-width (mils) that keeps the widest left and
    widest right pin names from colliding. `base` is the floor (count-driven)."""
    import math
    lw = max((text_width_mil(n) for n in left_names), default=0.0)
    rw = max((text_width_mil(n) for n in right_names), default=0.0)
    need = (lw + rw + gap) / 2.0
    return max(base, int(math.ceil(need / 100.0) * 100))
