"""FMC sheet — Altium port of gen/build_fmc.py.

VITA 57.1 LPC connector (ASP-134606-01, multi-unit: u1=row C, u2=row D,
u3=row G, u4=row H — each row gets its own refdes J1..J4) plus the LA-bank 0Ω
series-resistor routing (R100..R127). Same declarative source of truth
(netlist/fmc.yaml + gen.config.LA_ASSIGN) and the SAME strict validator.

Coordinates are mils on a 100-mil grid; Altium Y grows UP.

Pin hot-spot geometry of the placed ASP-134606-01 unit (verified empirically):
  placed at (cx, cy) the 40 pins lay out as a SINGLE VERTICAL COLUMN:
    x = cx - 500 (the left edge) for ALL 40 pins,
    y = cy + 3900 - (n-1)*200   (pin n; n=1 highest, n=40 lowest),
    every pin points LEFT (orientation 180) -> route LEFT (smaller x).
This matches the KiCad single-column symbol. Every wire/label/port for a pin
exits LEFT of the column.

Each LA signal is wired  FMC-pin -> 0Ω(R<n>) -> port:
  * R<n>.2 is the FMC-pin (chip) side  -> internal stub net (FMC pin + R.2)
  * R<n>.1 is the label side           -> the named global/hier net
A horizontal resistor (orientation 1: pin1=left label side, pin2=right chip
side) is placed in line with (same y as) its FMC pin so the stub is a single
straight wire — no T's, no crossings.

The 4 units are laid LEFT-TO-RIGHT as 4 vertical columns, spaced far enough in
x that each column's left-exit routing region (resistor + port, ~2500 mil of
reach) never collides with the column to its left.
"""

from __future__ import annotations

from altium_monkey import PortIOType

from ..gen.config import LA_ASSIGN
from ..gen.netlist import load_netlist
from ..gen.validator import validate
from .build_symbols import get_library
from .config import OUT_DIR, RENDER_DIR
from .shared import AltiumSheet

GRID = 100  # mil

# net -> (R_refdes, label_kind, port_io)
LA_ROUTING = [
    ("SAMPLE_OUTV",   "R100", "global", PortIOType.INPUT),
    ("SAMPLE_OUT0",   "R101", "global", PortIOType.INPUT),
    ("SAMPLE_OUT1",   "R102", "global", PortIOType.INPUT),
    ("SAMPLE_OUT2",   "R103", "global", PortIOType.INPUT),
    ("SAMPLE_OUT3",   "R104", "global", PortIOType.INPUT),
    ("SAMPLE_OUT4",   "R105", "global", PortIOType.INPUT),
    ("SAMPLE_OUT5",   "R106", "global", PortIOType.INPUT),
    ("SAMPLE_OUT6",   "R107", "global", PortIOType.INPUT),
    ("SAMPLE_OUT7",   "R108", "global", PortIOType.INPUT),
    ("MISO",          "R112", "global", PortIOType.INPUT),
    ("CS_L",          "R109", "global", PortIOType.OUTPUT),
    ("SCLK",          "R110", "global", PortIOType.OUTPUT),
    ("MOSI",          "R111", "global", PortIOType.OUTPUT),
    ("SPI_DMODE",     "R113", "global", PortIOType.OUTPUT),
    ("RESET_N",       "R114", "global", PortIOType.OUTPUT),
    ("OSC_EN",        "R115", "global", PortIOType.OUTPUT),
    ("WEIGHT_EN",     "R116", "global", PortIOType.OUTPUT),
    ("SAMPLE_TRIG",   "R117", "global", PortIOType.OUTPUT),
    ("BIAS_ISO0",     "R120", "global", PortIOType.OUTPUT),
    ("BIAS_ISO1",     "R121", "global", PortIOType.OUTPUT),
    ("LDO_SET_50mV",  "R122", "global", PortIOType.OUTPUT),
    ("LDO_SET_100mV", "R123", "global", PortIOType.OUTPUT),
    ("LDO_SET_200mV", "R124", "global", PortIOType.OUTPUT),
    ("LDO_SET_400mV", "R125", "global", PortIOType.OUTPUT),
    ("LDO_SET_800mV", "R126", "global", PortIOType.OUTPUT),
    ("LDO_SET_1V6",   "R127", "global", PortIOType.OUTPUT),
    ("LDO_EN",        "R118", "hier",   PortIOType.OUTPUT),
    ("LSW_EN",        "R119", "hier",   PortIOType.OUTPUT),
]


def build_fmc() -> tuple[AltiumSheet, object]:
    nl = load_netlist("fmc")
    lib, lmap = get_library()
    s = AltiumSheet(name="fmc", title="test1 — FMC LPC Connector (VITA 57.1)")

    row_for_unit = {1: "C", 2: "D", 3: "G", 4: "H"}
    unit_for_row = {"C": 1, "D": 2, "G": 3, "H": 4}

    # Each unit is a single vertical column. Pins all share x = cx-500 and exit
    # LEFT, so all routing (resistor + port) lives to the LEFT of the column.
    # Columns are laid LEFT-TO-RIGHT with COL_DX spacing > the max left reach
    # (~2700 mil) so column k's routing never reaches column k-1's pins.
    # The leftmost column's pins sit at x = CX1-500 = 3000, and the farthest
    # port reach is pin_x - 2500 = 500 (>= 300 OK).
    CX1 = 3500
    COL_DX = 3500
    UNIT_CX = {u: CX1 + (u - 1) * COL_DX for u in (1, 2, 3, 4)}
    UNIT_CY = 5000   # same vertical band; pins span y 1100..8900

    units: dict[int, dict[str, tuple[int, int]]] = {}
    for u in (1, 2, 3, 4):
        units[u] = s.place_from_netlist(lib, lmap, nl, f"J{u}",
                                        UNIT_CX[u], UNIT_CY, unit=u)
        # Title sits well ABOVE the auto-placed "J{u}" value Comment (which
        # renders ~150 mil above the top pin) so the two don't form a glob.
        s.text(f"J{u}  FMC LPC row {row_for_unit[u]}",
               UNIT_CX[u] - 500, UNIT_CY + 4600)

    def pin(row: str, num: int) -> tuple[int, int]:
        return units[unit_for_row[row]][f"{row}{num}"]

    # Track which (row,num) pins we've consumed so the leftover pins get NC'd.
    wired: set[tuple[str, int]] = set()

    # Left-reach distances (mils) measured from the pin, toward the port side.
    POWER_REACH = 600      # pin -> power port stub
    SPECIAL_REACH = 900    # pin -> hier/global label
    R_GAP = 800            # pin -> resistor centre (R.2 lands at R_GAP-100)
    LABEL_GAP = 2300       # pin -> port (beyond the resistor)

    # Power pins sit in a single column 200 mil apart; if every symbol used the
    # same stub length the adjacent GND/+3V3 glyphs would stack and collide.
    # Stagger the stub length by pin parity so vertically-adjacent power symbols
    # land in different x columns (caught by the label_overlap lint otherwise).
    # Stagger by pin parity AND net group: a +3V3 stub and a GND stub from
    # different columns can otherwise reach the same x at adjacent rows and their
    # glyph text collides. The +300 GND offset keeps the two groups in separate
    # columns regardless of which pins line up.
    def power_reach(n: int, net: str = "") -> int:
        base = POWER_REACH if n % 2 == 0 else POWER_REACH + 600
        return base + (300 if net == "GND" else 0)

    # ===== +3V3 (C39, D36, D38, D40 per VITA 57.1) — short stub LEFT to +3V3 ===
    for r, n in [("C", 39), ("D", 36), ("D", 38), ("D", 40)]:
        px, py = pin(r, n)
        ex = px - power_reach(n, "+3V3")
        s.wire(px, py, ex, py)
        s.power_at("+3V3", ex, py)
        wired.add((r, n))

    # ===== GND strapping (PRSNT_M2C_L=H2, GA0=C34, GA1=D35 — tie to GND) =====
    for r, n in [("H", 2), ("C", 34), ("D", 35)]:
        px, py = pin(r, n)
        ex = px - power_reach(n, "GND")
        s.wire(px, py, ex, py)
        s.power_at("GND", ex, py)
        wired.add((r, n))

    # ===== VADJ (G39, H40 per VITA 57.1) output port =====
    for r, n in [("G", 39), ("H", 40)]:
        px, py = pin(r, n)
        ex = px - SPECIAL_REACH
        s.wire(px, py, ex, py)
        s.port("VADJ", ex, py, io=PortIOType.OUTPUT)
        wired.add((r, n))

    # ===== LDO_PG (C1) input port =====
    px, py = pin("C", 1)
    ex = px - SPECIAL_REACH
    s.wire(px, py, ex, py)
    s.port("LDO_PG", ex, py, io=PortIOType.INPUT)
    wired.add(("C", 1))

    # ===== I²C global ports (SCL=C30, SDA=C31 per VITA 57.1) =====
    for net, (r, n) in [("SCL", ("C", 30)), ("SDA", ("C", 31))]:
        px, py = pin(r, n)
        ex = px - SPECIAL_REACH
        s.wire(px, py, ex, py)
        s.port(net, ex, py, io=PortIOType.BIDIRECTIONAL)
        wired.add((r, n))

    # ===== Intentional NC: 12P0V (C35, C37), 3P3VAUX (D32), VREF_A_M2C (H1) =====
    # (12 V is available but unused; AUX and VREF not required — see PPT p.5.)
    for r, n in [("C", 35), ("C", 37), ("D", 32), ("H", 1)]:
        s.no_connect(*pin(r, n))
        wired.add((r, n))

    # ===== LA-bank 0Ω routing =====
    # Each named signal: FMC pin --(stub)--> R.2 ; R.1 --(label leg)--> port.
    # Resistor placed horizontally, same y as the FMC pin, LEFT of it.
    #   orientation 1: pin1 = -100x (LEFT, label/port side),
    #                  pin2 = +100x (RIGHT, chip/FMC side).
    # So R.2 (right) meets the FMC pin's left-exit stub and R.1 (left) carries
    # the named net out to the port.
    for net, r_ref, kind, io in LA_ROUTING:
        row, num = LA_ASSIGN[net]
        px, py = pin(row, num)
        r_cx = px - R_GAP
        R = s.place_from_netlist(lib, lmap, nl, r_ref, r_cx, py, orientation=1)
        r2x, r2y = R["2"]   # FMC-pin side (right, x = r_cx + 100)
        r1x, r1y = R["1"]   # label side   (left,  x = r_cx - 100)
        # FMC pin -> R.2 (straight horizontal stub == internal net)
        s.wire(px, py, r2x, r2y)
        # R.1 -> port leg (continue left)
        label_x = px - LABEL_GAP
        s.wire(r1x, r1y, label_x, py)
        s.port(net, label_x, py, io=io)
        wired.add((row, num))

    # ===== NC every remaining pin (uncovered by validation, kept clean to
    #       avoid any false unions on this dense layout) =====
    for u in (1, 2, 3, 4):
        row = row_for_unit[u]
        for n in range(1, 41):
            if (row, n) in wired:
                continue
            s.no_connect(*pin(row, n))

    validate(s, nl)
    return s, nl


def main() -> int:
    s, _nl = build_fmc()
    out = s.save(OUT_DIR / "fmc.SchDoc")
    svg = s.render_svg(RENDER_DIR / "fmc.svg")
    print(f"validated OK | wrote {out.name} + {svg.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
