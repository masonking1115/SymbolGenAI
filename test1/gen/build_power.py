"""Power child sheet — TPS7A8401A LDO + TPS22916 load switch (layout only).

Parts inventory + nets are declared in netlist/power.yaml. validate() runs
at the end and confirms every YAML net is properly wired.

Functional clusters:
  A. LDO input side  — IN×3 + BIAS to +3V3, decoupling (C10/C11/C17),
                       EN pull-down (R10), NR_SS cap (C12).
  B. LDO output side — OUT×3 bus, kelvin SNS routing (E9), FB local strap,
                       PG with pull-up R12 (E6) + series R13 (W10),
                       ANY-OUT setpoint pins as global_labels (E5),
                       bulk caps C13/C14.
  C. Output jumpers  — 3× 1×2 headers fan OUT bus to +VDDD/+VDDA1/+VDDA2.
  D. Load switch     — VADJ → +VDDIO via TPS22916 + 1µF bulk caps C15/C16
                       (W6/W7), LSW_EN pull-down R11.
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
    hier_label,
    junction,
    place_from_netlist,
    power_at,
    wire,
)
from .validator import validate


def build_power() -> Sheet:
    nl = load_netlist("power")
    s = Sheet(name="power", uuid=SHEET_UUIDS["power"],
              page=PAGE_NUMBERS["power"],
              title=f"{PROJECT_NAME} — Power (LDO + Load Switch)")

    # ===== Cluster A: LDO body =====
    # Place TPS7A8401A at (130, 130). Body spans local x ∈ [-20.32, 20.32] (40.64 wide),
    # local y ∈ [-22.86, 20.32] (43.18 tall).
    # World coords: chip body x ∈ [109.68, 150.32], y ∈ [109.68, 152.86].
    U1 = place_from_netlist(s, nl, "U10", x=130, y=130)
    # Pin world coords (recompute the important ones):
    # IN (pins 15,16,17): local (-20.32, 20.32/17.78/15.24) → world (109.68, 109.68/112.22/114.76)
    # EN (14): (-20.32, 10.16) → (109.68, 119.84)
    # BIAS (12): (-20.32, 5.08) → (109.68, 124.92)
    # NR_SS (13): (-20.32, -2.54) → (109.68, 132.54)
    # 50_mV..1.6_V (5,6,7,9,10,11): left side, lower
    # OUT (1,19,20): (20.32, 10.16/7.62/5.08) → (150.32, 119.84/122.38/124.92)
    # SNS (2): (20.32, 0) → (150.32, 130)
    # FB (3): (20.32, -7.62) → (150.32, 137.62)
    # PG (4): (20.32, 20.32) → (150.32, 109.68)
    # GND (8): (20.32, -17.78) → (150.32, 147.78)
    # GND (18): (20.32, -20.32) → (150.32, 150.32)
    # PAD (21): (20.32, -22.86) → (150.32, 152.86)

    # +3V3 input rail at top (y = 95.25)
    RAIL_3V3_Y = 95.25
    GND_RAIL_Y = 175.26

    # IN pins → +3V3 (junction the three IN stubs together)
    for px, py in [U1["15"], U1["16"], U1["17"]]:
        s.add(wire(px, py, px - 7.62, py))
    s.add(wire(102.06, U1["15"][1], 102.06, RAIL_3V3_Y))   # vertical riser
    s.add(wire(102.06, U1["16"][1], 109.68, U1["16"][1]))  # already covered
    s.add(junction(102.06, U1["16"][1]))
    s.add(junction(102.06, U1["17"][1]))
    # Actually simpler: drop a vertical bus at x=102.06 covering all three Y values
    # and add junctions at each.
    s.add(wire(102.06, U1["17"][1], 102.06, U1["15"][1]))
    # BIAS pin → +3V3 (separately stubbed)
    s.add(wire(U1["12"][0], U1["12"][1], 102.06, U1["12"][1]))
    s.add(junction(102.06, U1["12"][1]))
    s.add(wire(102.06, U1["12"][1], 102.06, RAIL_3V3_Y))
    power_at(s, "+3V3", 102.06, RAIL_3V3_Y)

    # IN-side decoupling: 10µF (C10) and 0.1µF (C11) between +3V3 and GND, left of LDO
    place_from_netlist(s, nl, "C10", x=87.63, y=130)
    s.add(wire(87.63, 126.19, 87.63, RAIL_3V3_Y))
    s.add(junction(87.63, RAIL_3V3_Y))
    s.add(wire(87.63, RAIL_3V3_Y, 102.06, RAIL_3V3_Y))
    s.add(wire(87.63, 133.81, 87.63, GND_RAIL_Y))

    place_from_netlist(s, nl, "C11", x=95.25, y=130)
    s.add(wire(95.25, 126.19, 95.25, RAIL_3V3_Y))
    s.add(junction(95.25, RAIL_3V3_Y))
    s.add(wire(95.25, 133.81, 95.25, GND_RAIL_Y))

    # C17 — dedicated bypass for the LDO BIAS pin (W3) on the +3V3 input column.
    place_from_netlist(s, nl, "C17", x=82.55, y=130)
    s.add(wire(82.55, 126.19, 82.55, RAIL_3V3_Y))
    s.add(junction(82.55, RAIL_3V3_Y))
    s.add(wire(82.55, RAIL_3V3_Y, 87.63, RAIL_3V3_Y))   # extend rail leftward to C17
    s.add(wire(82.55, 133.81, 82.55, GND_RAIL_Y))

    # GND rail bottom
    s.add(wire(82.55, GND_RAIL_Y, 95.25, GND_RAIL_Y))
    s.add(junction(82.55, GND_RAIL_Y))
    s.add(junction(87.63, GND_RAIL_Y))
    s.add(junction(95.25, GND_RAIL_Y))
    power_at(s, "GND", 87.63, GND_RAIL_Y)

    # EN pin (14) → 10k pulldown to GND, hier-label LDO_EN comes from FPGA via FMC.
    s.add(wire(U1["14"][0], U1["14"][1], 99.06, U1["14"][1]))
    place_from_netlist(s, nl, "R10", x=99.06, y=124.92)
    s.add(wire(99.06, 121.11, 99.06, U1["14"][1]))
    s.add(wire(99.06, 128.73, 99.06, GND_RAIL_Y))
    s.add(wire(95.25, GND_RAIL_Y, 99.06, GND_RAIL_Y))
    s.add(junction(99.06, GND_RAIL_Y))
    s.add(hier_label("LDO_EN", "input", 91.44, U1["14"][1], angle=180, justify="right"))
    s.add(wire(91.44, U1["14"][1], 99.06, U1["14"][1]))
    s.add(junction(99.06, U1["14"][1]))

    # NR_SS (13): 10nF cap to GND
    s.add(wire(U1["13"][0], U1["13"][1], 99.06, U1["13"][1]))
    place_from_netlist(s, nl, "C12", x=99.06, y=137.16)
    s.add(wire(99.06, 133.35, 99.06, U1["13"][1]))
    s.add(wire(99.06, 140.97, 99.06, GND_RAIL_Y))
    s.add(junction(99.06, GND_RAIL_Y))

    # ===== Cluster B: ANY-OUT setpoint pins (FPGA-driven via FMC LA bank) =====
    LDO_SET_PINS = [
        ("5",  "LDO_SET_50mV"),
        ("6",  "LDO_SET_100mV"),
        ("7",  "LDO_SET_200mV"),
        ("9",  "LDO_SET_400mV"),
        ("10", "LDO_SET_800mV"),
        ("11", "LDO_SET_1V6"),
    ]
    for pn, net in LDO_SET_PINS:
        px, py = U1[pn]
        s.add(wire(px, py, px - 10.16, py))
        s.add(global_label(net, "input", px - 10.16, py, angle=180, justify="right"))

    # ===== Cluster B: OUT side =====
    OUT_BUS_X = 165.1
    for pn in ("1", "19", "20"):
        px, py = U1[pn]
        s.add(wire(px, py, OUT_BUS_X, py))
    s.add(wire(OUT_BUS_X, U1["1"][1], OUT_BUS_X, U1["20"][1]))   # vertical OUT bus
    for pn in ("1", "20"):
        _, py = U1[pn]
        s.add(junction(OUT_BUS_X, py))

    # SNS (2) → kelvin sense to a point AFTER the bulk caps (E9 fix).
    SNS_SENSE_X = 185.0
    s.add(wire(U1["2"][0], U1["2"][1], 165.5, U1["2"][1]))               # SNS stub right
    s.add(wire(165.5, U1["2"][1], 165.5, 117.0))                          # up clear of bus
    s.add(wire(165.5, 117.0, SNS_SENSE_X, 117.0))                         # across to sense x
    s.add(wire(SNS_SENSE_X, 117.0, SNS_SENSE_X, U1["1"][1]))              # down to OUT trace
    s.add(junction(SNS_SENSE_X, U1["1"][1]))                              # tie to OUT net

    # FB (3) → tie to OUT BUS locally (ANY-OUT mode uses internal feedback).
    s.add(wire(U1["3"][0], U1["3"][1], OUT_BUS_X, U1["3"][1]))
    s.add(wire(OUT_BUS_X, U1["1"][1], OUT_BUS_X, U1["3"][1]))
    s.add(junction(OUT_BUS_X, U1["3"][1]))

    # PG (4) — open-drain output. Needs (a) a 10kΩ pull-up to +3V3 (E6) and
    # (b) a 1kΩ series resistor in front of the FMC PG_C2M pin (W10).
    PG_TAP_X = 158.0
    PG_Y = U1["4"][1]
    s.add(wire(U1["4"][0], PG_Y, PG_TAP_X, PG_Y))                # PG pin → tap
    s.add(junction(PG_TAP_X, PG_Y))
    place_from_netlist(s, nl, "R12", x=PG_TAP_X, y=PG_Y - 13.49)
    s.add(wire(PG_TAP_X, PG_Y, PG_TAP_X, PG_Y - 9.68))           # tap → R12 bot
    s.add(wire(PG_TAP_X, PG_Y - 17.3, PG_TAP_X, PG_Y - 21.11))   # R12 top → +3V3
    power_at(s, "+3V3", PG_TAP_X, PG_Y - 21.11)
    place_from_netlist(s, nl, "R13", x=PG_TAP_X + 7.62, y=PG_Y, angle=90)
    s.add(wire(PG_TAP_X, PG_Y, PG_TAP_X + 3.81, PG_Y))           # tap → R13 left
    s.add(wire(PG_TAP_X + 11.43, PG_Y, PG_TAP_X + 15.24, PG_Y))  # R13 right → hier
    s.add(hier_label("LDO_PG", "output", PG_TAP_X + 15.24, PG_Y, angle=0))

    # GND pins (8, 18, 21) → GND
    for pn in ("8", "18", "21"):
        px, py = U1[pn]
        s.add(wire(px, py, px + 5.08, py))
        power_at(s, "GND", px + 5.08, py)

    # OUT-side decoupling: 22µF (C13) and 0.1µF (C14) — between OUT bus and GND
    place_from_netlist(s, nl, "C13", x=172.72, y=130)
    s.add(wire(172.72, 126.19, 172.72, U1["1"][1]))
    s.add(wire(OUT_BUS_X, U1["1"][1], 172.72, U1["1"][1]))
    s.add(junction(OUT_BUS_X, U1["1"][1]))
    s.add(wire(172.72, 133.81, 172.72, GND_RAIL_Y))
    s.add(wire(172.72, GND_RAIL_Y, 180.34, GND_RAIL_Y))
    power_at(s, "GND", 180.34, GND_RAIL_Y)

    place_from_netlist(s, nl, "C14", x=180.34, y=130)
    s.add(wire(180.34, 126.19, 180.34, U1["1"][1]))
    s.add(wire(172.72, U1["1"][1], 180.34, U1["1"][1]))
    s.add(junction(172.72, U1["1"][1]))
    s.add(junction(180.34, U1["1"][1]))
    s.add(wire(180.34, 133.81, 180.34, GND_RAIL_Y))
    s.add(junction(180.34, GND_RAIL_Y))

    # ===== Cluster C: Output jumpers (3× 1×2 → VDDD, VDDA1, VDDA2) =====
    JX = 195.58
    for i, (ref, rail) in enumerate([("J10", "+VDDD"), ("J11", "+VDDA1"), ("J12", "+VDDA2")]):
        jy = 119.38 + i * 17.78
        place_from_netlist(s, nl, ref, x=JX, y=jy)
        s.add(wire(JX, jy, JX - 5.08, jy))
        s.add(wire(JX - 5.08, jy, JX - 5.08, U1["1"][1]))
        s.add(wire(JX - 5.08, U1["1"][1], OUT_BUS_X, U1["1"][1]))
        s.add(junction(OUT_BUS_X, U1["1"][1]))
        s.add(wire(JX, jy + 2.54, JX + 7.62, jy + 2.54))
        power_at(s, rail, JX + 7.62, jy + 2.54)

    # ===== Cluster D: Load switch (TPS22916) =====
    U2 = place_from_netlist(s, nl, "U11", x=270, y=130)
    C6_X         = U2["A2"][0] - 7.62
    VADJ_LABEL_X = U2["A2"][0] - 15.24
    R2_X         = U2["A2"][0] - 22.86
    LSW_LABEL_X  = U2["A2"][0] - 30.48

    # VIN (A2) ← VADJ hier label. Wire runs straight across; C6's top pin
    # (at C6_X, VIN_y) sits ON this wire and is auto-detected by KiCad.
    s.add(wire(U2["A2"][0], U2["A2"][1], VADJ_LABEL_X, U2["A2"][1]))
    s.add(hier_label("VADJ", "input", VADJ_LABEL_X, U2["A2"][1], angle=180, justify="right"))

    # GND (B1)
    s.add(wire(U2["B1"][0], U2["B1"][1], U2["B1"][0] + 5.08, U2["B1"][1]))
    power_at(s, "GND", U2["B1"][0] + 5.08, U2["B1"][1])

    # VOUT (A1) → +VDDIO
    s.add(wire(U2["A1"][0], U2["A1"][1], U2["A1"][0] + 12.7, U2["A1"][1]))
    power_at(s, "+VDDIO", U2["A1"][0] + 12.7, U2["A1"][1])

    # C15 — VIN decouple. 1µF bulk per W6.
    C6_CENTER_Y = U2["A2"][1] + 3.81
    place_from_netlist(s, nl, "C15", x=C6_X, y=C6_CENTER_Y)
    s.add(junction(C6_X, U2["A2"][1]))                          # tap on VADJ wire
    s.add(wire(C6_X, U2["A2"][1] + 7.62, C6_X, GND_RAIL_Y))     # bot → GND rail
    s.add(wire(C6_X, GND_RAIL_Y, 180.34, GND_RAIL_Y))
    s.add(junction(C6_X, GND_RAIL_Y))

    # C16 — VOUT decouple. 1µF bulk per W7.
    C7_X = U2["A1"][0] + 7.62
    C7_CENTER_Y = U2["A1"][1] + 3.81
    place_from_netlist(s, nl, "C16", x=C7_X, y=C7_CENTER_Y)
    s.add(junction(C7_X, U2["A1"][1]))                          # tap on VOUT wire
    s.add(wire(C7_X, U2["A1"][1] + 7.62, C7_X, GND_RAIL_Y))
    s.add(wire(C6_X, GND_RAIL_Y, C7_X, GND_RAIL_Y))
    s.add(junction(C7_X, GND_RAIL_Y))

    # ON pull-down R11 (10k) + LSW_EN hier-label, vertical, between ON stub
    # and GND rail below the load switch.
    R2_CENTER_Y = U2["B2"][1] + 7.62
    place_from_netlist(s, nl, "R11", x=R2_X, y=R2_CENTER_Y)
    s.add(wire(R2_X, U2["B2"][1] + 3.81, R2_X, U2["B2"][1]))    # R2 top → ON row
    s.add(wire(R2_X, U2["B2"][1], U2["B2"][0], U2["B2"][1]))    # across to ON pin
    s.add(hier_label("LSW_EN", "input", LSW_LABEL_X, U2["B2"][1], angle=180, justify="right"))
    s.add(wire(LSW_LABEL_X, U2["B2"][1], R2_X, U2["B2"][1]))    # LSW_EN → R2 top stub
    s.add(junction(R2_X, U2["B2"][1]))
    s.add(wire(R2_X, U2["B2"][1] + 11.43, R2_X, GND_RAIL_Y))    # R2 bot → GND rail
    s.add(junction(R2_X, GND_RAIL_Y))
    s.add(wire(C6_X, GND_RAIL_Y, R2_X, GND_RAIL_Y))             # extend GND rail left to R2

    validate(s, nl)
    return s
