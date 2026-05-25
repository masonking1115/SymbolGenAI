"""FMC child sheet — VITA 57.1 LPC connector + LA-bank 0Ω routing.

Parts inventory + nets live in netlist/fmc.yaml. The ASP-134606-01 symbol
is multi-unit (one unit per row); each row gets its own refdes (J1=u1=C,
J2=u2=D, J3=u3=G, J4=u4=H) so YAML members write `J<n>:u<n>.<pin>`.

LA-bank routing is driven by `LA_ASSIGN` (in gen.config) plus the LA_ROUTING
table below — which net → which 0Ω refdes + label kind/shape. The mass
GND-bussing of unrouted FMC pins is unchanged from Phase A.
"""

from __future__ import annotations

from .config import (
    LA_ASSIGN,
    PAGE_NUMBERS,
    PROJECT_NAME,
    SHEET_UUIDS,
)
from .netlist import load_netlist
from .shared import (
    Sheet,
    global_label,
    hier_label,
    junction,
    no_connect,
    place_from_netlist,
    power_at,
    wire,
)
from .validator import validate


def build_fmc() -> Sheet:
    nl = load_netlist("fmc")
    s = Sheet(name="fmc", uuid=SHEET_UUIDS["fmc"],
              page=PAGE_NUMBERS["fmc"],
              title=f"{PROJECT_NAME} — FMC LPC Connector (Power + I²C only)")

    UNIT_X = {1: 80, 2: 140, 3: 200, 4: 260}    # rows C, D, G, H
    UNIT_Y = 95
    row_letters = {1: "C", 2: "D", 3: "G", 4: "H"}

    units: dict[int, dict[str, tuple[float, float]]] = {}
    for unit_num, row_letter in row_letters.items():
        units[unit_num] = place_from_netlist(
            s, nl, f"J{unit_num}",
            x=UNIT_X[unit_num], y=UNIT_Y, unit=unit_num,
        )

    def pin(row: str, num: int) -> tuple[float, float]:
        unit = {"C": 1, "D": 2, "G": 3, "H": 4}[row]
        return units[unit][f"{row}{num}"]

    # ===== 3P3V (C36, C38, C40, D39) → +3V3 =====
    for r, n in [("C", 36), ("C", 38), ("C", 40), ("D", 39)]:
        px, py = pin(r, n)
        s.add(wire(px, py, px + 7.62, py))
        power_at(s, "+3V3", px + 7.62, py, angle=90)

    # ===== VADJ (G40, H39) → VADJ hier label =====
    for r, n in [("G", 40), ("H", 39)]:
        px, py = pin(r, n)
        s.add(wire(px, py, px + 10.16, py))
        s.add(hier_label("VADJ", "output", px + 10.16, py, angle=0))

    # ===== I²C — global_label (project-wide bus) =====
    s.add(wire(*pin("D", 30), pin("D", 30)[0] + 10.16, pin("D", 30)[1]))
    s.add(global_label("SCL", "bidirectional", pin("D", 30)[0] + 10.16, pin("D", 30)[1], angle=0))
    s.add(wire(*pin("D", 31), pin("D", 31)[0] + 10.16, pin("D", 31)[1]))
    s.add(global_label("SDA", "bidirectional", pin("D", 31)[0] + 10.16, pin("D", 31)[1], angle=0))

    # ===== Strapping: PRSNT_M2C_L (H2), GA0 (C34), GA1 (C35) → GND =====
    for r, n in [("H", 2), ("C", 34), ("C", 35)]:
        px, py = pin(r, n)
        s.add(wire(px, py, px + 7.62, py))
        power_at(s, "GND", px + 7.62, py)

    # ===== PG_C2M (C1) → LDO_PG hier label =====
    px, py = pin("C", 1)
    s.add(wire(px, py, px + 10.16, py))
    s.add(hier_label("LDO_PG", "input", px + 10.16, py, angle=0))

    # ===== NC pins (12V, 3P3VAUX, VREF_A_M2C) =====
    for r, n in [("C", 32), ("D", 35), ("D", 37), ("H", 1)]:
        px, py = pin(r, n)
        s.add(no_connect(px, py))

    # ===== LA-bank signal routing (E1, E2, E5, E7, W1) =====
    LA_ROUTING = [
        # (net_name, R_refdes, label_kind, label_shape_at_fmc_side)
        ("SAMPLE_OUTV",   "R100", "global", "input"),
        ("SAMPLE_OUT0",   "R101", "global", "input"),
        ("SAMPLE_OUT1",   "R102", "global", "input"),
        ("SAMPLE_OUT2",   "R103", "global", "input"),
        ("SAMPLE_OUT3",   "R104", "global", "input"),
        ("SAMPLE_OUT4",   "R105", "global", "input"),
        ("SAMPLE_OUT5",   "R106", "global", "input"),
        ("SAMPLE_OUT6",   "R107", "global", "input"),
        ("SAMPLE_OUT7",   "R108", "global", "input"),
        ("MISO",          "R112", "global", "input"),
        ("CS_L",          "R109", "global", "output"),
        ("SCLK",          "R110", "global", "output"),
        ("MOSI",          "R111", "global", "output"),
        ("SPI_DMODE",     "R113", "global", "output"),
        ("RESET_N",       "R114", "global", "output"),
        ("OSC_EN",        "R115", "global", "output"),
        ("WEIGHT_EN",     "R116", "global", "output"),
        ("SAMPLE_TRIG",   "R117", "global", "output"),
        ("BIAS_ISO0",     "R120", "global", "output"),
        ("BIAS_ISO1",     "R121", "global", "output"),
        ("LDO_SET_50mV",  "R122", "global", "output"),
        ("LDO_SET_100mV", "R123", "global", "output"),
        ("LDO_SET_200mV", "R124", "global", "output"),
        ("LDO_SET_400mV", "R125", "global", "output"),
        ("LDO_SET_800mV", "R126", "global", "output"),
        ("LDO_SET_1V6",   "R127", "global", "output"),
        ("LDO_EN",        "R118", "hier",   "output"),
        ("LSW_EN",        "R119", "hier",   "output"),
    ]
    la_routed: set[tuple[str, int]] = set()
    for net, r_ref, kind, shape in LA_ROUTING:
        row, num = LA_ASSIGN[net]
        px, py = pin(row, num)
        R_x = px + 8.0
        label_x = px + 20.0
        place_from_netlist(s, nl, r_ref, x=R_x, y=py, angle=90)
        s.add(wire(px, py, R_x - 3.81, py))
        s.add(wire(R_x + 3.81, py, label_x, py))
        if kind == "global":
            s.add(global_label(net, shape, label_x, py, angle=0))
        else:
            s.add(hier_label(net, shape, label_x, py, angle=0))
        la_routed.add((row, num))

    # ===== GND on unlabeled pins =====
    wired: set[tuple[str, int]] = {
        ("C", 1), ("C", 32), ("C", 34), ("C", 35),
        ("C", 36), ("C", 38), ("C", 40),
        ("D", 30), ("D", 31), ("D", 35), ("D", 37), ("D", 39),
        ("G", 40),
        ("H", 1), ("H", 2), ("H", 39),
    }
    # Skip LA bank pins — they're for future Bobcat signal wiring
    la_bank = set()
    la_ranges = {
        "C": [(8,9), (11,12), (14,15), (17,18), (20,21), (23,24), (26,27)],
        "D": [(10,11), (14,15), (18,19), (22,23), (26,27)],
        "G": [(7,8), (10,11), (13,14), (16,17), (19,20), (22,23), (25,26),
              (28,29), (31,32), (34,35), (37,38), (4,5)],
        "H": [(6,7), (9,10), (12,13), (15,16), (18,19), (21,22), (24,25),
              (27,28), (30,31), (33,34), (36,37), (2,3)],
    }
    for row, pairs in la_ranges.items():
        for a, b in pairs:
            la_bank.add((row, a))
            la_bank.add((row, b))
    # Also reserve: gigabit pairs, clock pairs, GBTCLK, JTAG.
    for row, n in [("D",2),("D",3),("D",6),("D",7),("G",4),("G",5),
                    ("C",4),("C",5),
                    ("C",29),("C",30),("C",31),("C",33)]:
        la_bank.add((row, n))
    # NC the JTAG pins.
    for r, n in [("C",29),("C",30),("C",31),("C",33)]:
        px, py = pin(r, n)
        if (r, n) not in wired:
            s.add(no_connect(px, py))
            wired.add((r, n))

    # Ground all unwired non-LA pins via a per-row rail.
    GND_RAIL_OFFSET = 17.78
    for row, _ in [("C", 1), ("D", 2), ("G", 3), ("H", 4)]:
        gnd_pins = [n for n in range(1, 41)
                    if (row, n) not in wired
                    and (row, n) not in la_bank
                    and (row, n) not in la_routed]
        if not gnd_pins:
            continue
        first_px, first_py = pin(row, gnd_pins[0])
        _, last_py = pin(row, gnd_pins[-1])
        rail_x = first_px + GND_RAIL_OFFSET
        for n in gnd_pins:
            px, py = pin(row, n)
            s.add(wire(px, py, rail_x, py))
        s.add(wire(rail_x, first_py, rail_x, last_py))
        for n in gnd_pins[1:-1]:
            _, py = pin(row, n)
            s.add(junction(rail_x, py))
        gnd_y = last_py + 5.08
        s.add(wire(rail_x, last_py, rail_x, gnd_y))
        power_at(s, "GND", rail_x, gnd_y)

    # NC the LA-bank pins NOT routed via LA_ROUTING. Sort for deterministic
    # output (la_bank is a set; iteration order varies across Python runs).
    for r, n in sorted(la_bank):
        if (r, n) in wired or (r, n) in la_routed:
            continue
        px, py = pin(r, n)
        s.add(no_connect(px, py))

    validate(s, nl)
    return s
