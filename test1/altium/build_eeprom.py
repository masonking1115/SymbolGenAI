"""EEPROM sheet — Altium port of gen/build_eeprom.py.

Same declarative source of truth (netlist/eeprom.yaml, loaded via the SHARED
gen.netlist loader) and the SAME strict validator (gen.validator.validate) —
only the layout backend changes from KiCad s-expr to Altium binary.

Differences from the KiCad builder, all mechanical:
  - coordinates are mils on a 100-mil grid (KiCad used mm on a 1.27mm grid),
  - Altium Y grows UP, so "above the chip" = larger y (KiCad y-down was smaller),
  - wires route from placed-component pin hot-spots returned by place(),
  - global_label(SCL/SDA) -> Altium Port,
  - junction objects are cosmetic (Altium drops them); connectivity rides the
    T-intersections, which both Altium and the validator treat as connected.

Structure mirrors the KiCad sheet: U30 with pins 1-4 on a left GND bus, VCC up
to a +3V3 rail shared by C30 decoupling + R60/R61 pull-ups, WP + C30 return to
GND, and SCL/SDA exiting right as ports with their pull-ups tapping the lines.
"""

from __future__ import annotations

from pathlib import Path

from ..gen.netlist import load_netlist
from ..gen.validator import validate
from .build_symbols import get_library
from .config import OUT_DIR, RENDER_DIR
from .shared import AltiumSheet, build_centered

GRID = 100  # mil


def build_eeprom() -> tuple[AltiumSheet, object]:
    nl = load_netlist("eeprom")
    lib, lmap = get_library()
    s = AltiumSheet(name="eeprom", title="test1 — EEPROM (24AA08 I2C)")

    def place(ref, x, y):
        return s.place_from_netlist(lib, lmap, nl, ref, x, y)

    # --- U30: 24AA08 centred at (4000, 5000). Left pins 1-4 (x=3500, y high->low
    #     5300..4700), right pins 8/7/6/5 (x=4500, same y rows). ---
    U30 = place("U30", 4000, 5000)
    CHIP_LEFT_X = U30["1"][0]     # 3500
    CHIP_RIGHT_X = U30["8"][0]    # 4500

    # Left side pins 1-4 (A0/A1/A2/VSS) -> shared GND rail (one GND port).
    s.gnd_bus([U30[p] for p in ("1", "2", "3", "4")], rail_x=CHIP_LEFT_X - 300)

    # Rails: +3V3 ~1400 mil above chip top, GND ~1500 mil below chip bottom.
    RAIL_Y = U30["1"][1] + 1400          # 6700
    GND_RAIL_Y = U30["4"][1] - 1500      # 3200

    # Pin 8 VCC -> up to +3V3 rail.
    VCC_COL_X = CHIP_RIGHT_X + 300       # 4800
    s.wire(*U30["8"], VCC_COL_X, U30["8"][1])
    s.wire(VCC_COL_X, U30["8"][1], VCC_COL_X, RAIL_Y)

    # Pin 7 WP -> down to GND rail (own column).
    WP_COL_X = CHIP_RIGHT_X + 100        # 4600
    s.wire(*U30["7"], WP_COL_X, U30["7"][1])
    s.wire(WP_COL_X, U30["7"][1], WP_COL_X, GND_RAIL_Y)

    # Pins 6/5 SCL/SDA -> horizontal lines exiting right as ports.
    PORT_X = CHIP_RIGHT_X + 2600         # 7100
    s.wire(*U30["6"], PORT_X, U30["6"][1])
    s.port("SCL", PORT_X, U30["6"][1])
    s.wire(*U30["5"], PORT_X, U30["5"][1])
    s.port("SDA", PORT_X, U30["5"][1])

    # --- C30 decoupling: pin1 (top) on +3V3 rail, pin2 (bottom) to GND rail. ---
    C30_X = CHIP_RIGHT_X + 700           # 5200
    C30 = place("C30", C30_X, RAIL_Y - 500)   # CAP pin1 hot-spot = center_y + 500
    s.wire(C30["1"][0], C30["1"][1], C30_X, RAIL_Y)          # already on rail y
    s.wire(C30["2"][0], C30["2"][1], C30_X, GND_RAIL_Y)      # bottom down to GND

    # --- R60 (SCL pull-up): top to +3V3 rail, bottom taps the SCL line. ---
    R60_X = CHIP_RIGHT_X + 1100          # 5600
    R60 = place("R60", R60_X, U30["6"][1] + 500)   # pin2 hot-spot lands on SCL y
    s.wire(R60["1"][0], R60["1"][1], R60_X, RAIL_Y)
    s.wire(R60["2"][0], R60["2"][1], R60_X, U30["6"][1])     # onto SCL line (T)

    # --- R61 (SDA pull-up): one column right; bottom taps the SDA line. ---
    R61_X = CHIP_RIGHT_X + 1500          # 6000
    R61 = place("R61", R61_X, U30["5"][1] + 500)
    s.wire(R61["1"][0], R61["1"][1], R61_X, RAIL_Y)
    s.wire(R61["2"][0], R61["2"][1], R61_X, U30["5"][1])     # onto SDA line (T)

    # --- +3V3 rail: one horizontal wire tying VCC, C30, R60, R61; +3V3 port. ---
    s.wire(VCC_COL_X, RAIL_Y, R61_X, RAIL_Y)
    for x in (C30_X, R60_X):
        s.junction(x, RAIL_Y)
    s.power_at("+3V3", R61_X, RAIL_Y)

    # --- GND rail (bottom): tie WP column + C30 return; one GND port. ---
    s.wire(WP_COL_X, GND_RAIL_Y, C30_X, GND_RAIL_Y)
    s.power_at("GND", C30_X, GND_RAIL_Y)

    # Same strict validator as the KiCad backend — true functional parity.
    validate(s, nl)
    return s, nl


def main() -> int:
    s, _nl = build_centered(build_eeprom)
    out = s.save(OUT_DIR / "eeprom.SchDoc")
    svg = s.render_svg(RENDER_DIR / "eeprom.svg")
    print(f"validated OK | wrote {out.name} + {svg.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
