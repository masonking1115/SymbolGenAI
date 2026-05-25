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
    # Place TPS7A8401A at (129.54, 129.54) — snapped to nearest 50-grid corner.
    # Body spans local x ∈ [-20.32, 20.32] (40.64 wide), local y ∈ [-22.86, 20.32].
    # World coords: chip body x ∈ [109.22, 149.86], y ∈ [109.22, 152.4].
    U1 = place_from_netlist(s, nl, "U10", x=129.54, y=129.54)
    # Pin world coords (recompute the important ones):
    # IN (pins 15,16,17): local (-20.32, 20.32/17.78/15.24) → world (109.22, 109.22/111.76/114.30)
    # EN (14): (-20.32, 10.16) → (109.22, 119.38)
    # BIAS (12): (-20.32, 5.08) → (109.22, 124.46)
    # NR_SS (13): (-20.32, -2.54) → (109.22, 132.08)
    # 50_mV..1.6_V (5,6,7,9,10,11): left side, lower
    # OUT (1,19,20): (20.32, 10.16/7.62/5.08) → (149.86, 119.38/121.92/124.46)
    # SNS (2): (20.32, 0) → (149.86, 129.54)
    # FB (3): (20.32, -7.62) → (149.86, 137.16)
    # PG (4): (20.32, 20.32) → (149.86, 109.22)
    # GND (8): (20.32, -17.78) → (149.86, 147.32)
    # GND (18): (20.32, -20.32) → (149.86, 149.86)
    # PAD (21): (20.32, -22.86) → (149.86, 152.4)

    # +3V3 input rail at top (y = 95.25)
    RAIL_3V3_Y = 95.25
    GND_RAIL_Y = 175.26

    # IN pins (15, 16, 17) + BIAS pin (12) → +3V3 via a single vertical bus at
    # x=101.60. KiCad auto-connects the horizontal stub endpoints landing on
    # the bus interior (T-intersection), so no explicit junctions are needed.
    for px, py in [U1["15"], U1["16"], U1["17"], U1["12"]]:
        s.add(wire(px, py, 101.60, py))
    s.add(wire(101.60, U1["12"][1], 101.60, RAIL_3V3_Y))
    power_at(s, "+3V3", 101.60, RAIL_3V3_Y)

    # IN-side decoupling row: C17 (BIAS bypass, W3) + C10 (10µF) + C11 (0.1µF).
    # Each cap top → shared +3V3 rail; each bot → shared GND rail. KiCad
    # auto-junctions where the cap-pin endpoints land on the rail interiors.
    # C11 at 92.71 (not 95.25) so its body clears R10 (EN pulldown) at x=99.06.
    for ref, cx in [("C17", 82.55), ("C10", 87.63), ("C11", 92.71)]:
        place_from_netlist(s, nl, ref, x=cx, y=129.54)
        s.add(wire(cx, 125.73, cx, RAIL_3V3_Y))
        s.add(wire(cx, 133.35, cx, GND_RAIL_Y))
    s.add(wire(82.55, RAIL_3V3_Y, 101.60, RAIL_3V3_Y))  # +3V3 rail across caps + IN bus
    s.add(wire(82.55, GND_RAIL_Y, 92.71, GND_RAIL_Y))   # GND rail across cap bottoms
    power_at(s, "GND", 87.63, GND_RAIL_Y)

    # EN pin (14) → 10k pulldown to GND, hier-label LDO_EN comes from FPGA via FMC.
    s.add(wire(U1["14"][0], U1["14"][1], 99.06, U1["14"][1]))
    place_from_netlist(s, nl, "R10", x=99.06, y=124.46)
    s.add(wire(99.06, 120.65, 99.06, U1["14"][1]))
    s.add(wire(99.06, 128.27, 99.06, GND_RAIL_Y))
    s.add(wire(92.71, GND_RAIL_Y, 99.06, GND_RAIL_Y))   # bridge IN-rail (ends at C11=92.71) → R10 col
    s.add(junction(99.06, GND_RAIL_Y))
    # LDO_EN pushed to x=80.01 (same column as LDO_SET labels) so cap top-drop
    # columns at x=87.63 (C10) and x=92.71 (C11) don't cross the label text.
    s.add(hier_label("LDO_EN", "input", 80.01, U1["14"][1], angle=180, justify="right"))
    s.add(wire(80.01, U1["14"][1], 99.06, U1["14"][1]))
    s.add(junction(99.06, U1["14"][1]))

    # NR_SS (13): 10nF cap to GND. C12 sits on its own NR_X column (NOT R10's
    # x=99.06) so R10.bot's GND drop doesn't pass through C12.top — that
    # would silently short NR_SS to GND. cy is chosen so C12.bot stays above
    # the LDO_SET pin row (pin 11 at y=139.7) — places the cap entirely
    # between pin 13's tap row (132.08) and the LDO_SET fanout zone.
    NR_X = 104.14
    s.add(wire(U1["13"][0], U1["13"][1], NR_X, U1["13"][1]))
    place_from_netlist(s, nl, "C12", x=NR_X, y=134.62)
    s.add(wire(NR_X, 130.81, NR_X, U1["13"][1]))
    s.add(wire(NR_X, 138.43, NR_X, GND_RAIL_Y))
    s.add(wire(99.06, GND_RAIL_Y, NR_X, GND_RAIL_Y))   # extend GND rail to NR_X

    # ===== Cluster B: ANY-OUT setpoint pins (FPGA-driven via FMC LA bank) =====
    LDO_SET_PINS = [
        ("5",  "LDO_SET_50mV"),
        ("6",  "LDO_SET_100mV"),
        ("7",  "LDO_SET_200mV"),
        ("9",  "LDO_SET_400mV"),
        ("10", "LDO_SET_800mV"),
        ("11", "LDO_SET_1V6"),
    ]
    # Labels at x = px - 29.21 (NOT -12.7): -12.7 lands at x=96.52, and the
    # label text (~12 chars left of anchor) extends back through C10/C11's
    # GND-drop columns at x=87.63/92.71 — visually it looks like the cap
    # GND drops pass straight through the label boxes. -29.21 puts the
    # anchor at x=80.01, with text extending leftward into clear space PAST
    # all three cap columns (C17 at 82.55, C10 at 87.63, C11 at 92.71).
    # Caught by _check_wire_crosses_label_text in the layout linter.
    for pn, net in LDO_SET_PINS:
        px, py = U1[pn]
        s.add(wire(px, py, px - 29.21, py))
        s.add(global_label(net, "input", px - 29.21, py, angle=180, justify="right"))

    # ===== Cluster B: OUT side =====
    # OUT bus is the single vertical wire built later from U1["1"] down to FB
    # at U1["3"]; pin 19 and pin 20 stub endpoints land on its interior via
    # KiCad's auto-T-junction. Junction at U1["1"] is needed because three
    # endpoints meet there (pin 1, jumper tap, FB extension top).
    OUT_BUS_X = 165.1
    for pn in ("1", "19", "20"):
        px, py = U1[pn]
        s.add(wire(px, py, OUT_BUS_X, py))
    s.add(junction(OUT_BUS_X, U1["1"][1]))

    # SNS (2) → kelvin sense to a point AFTER the bulk caps (E9 fix).
    SNS_SENSE_X = 185.42
    s.add(wire(U1["2"][0], U1["2"][1], 166.37, U1["2"][1]))               # SNS stub right
    s.add(wire(166.37, U1["2"][1], 166.37, 116.84))                       # up clear of bus
    s.add(wire(166.37, 116.84, SNS_SENSE_X, 116.84))                      # across to sense x
    s.add(wire(SNS_SENSE_X, 116.84, SNS_SENSE_X, U1["1"][1]))             # down to OUT trace
    s.add(junction(SNS_SENSE_X, U1["1"][1]))                              # tie to OUT net

    # FB (3) → tie to OUT BUS locally (ANY-OUT mode uses internal feedback).
    # The FB stub endpoint lands on the OUT bus interior — T-intersection
    # auto-connects without an explicit junction.
    s.add(wire(U1["3"][0], U1["3"][1], OUT_BUS_X, U1["3"][1]))
    s.add(wire(OUT_BUS_X, U1["1"][1], OUT_BUS_X, U1["3"][1]))

    # PG (4) — open-drain output. Needs (a) a 10kΩ pull-up to +3V3 (E6) and
    # (b) a 1kΩ series resistor in front of the FMC PG_C2M pin (W10).
    PG_TAP_X = 157.48
    PG_Y = U1["4"][1]
    s.add(wire(U1["4"][0], PG_Y, PG_TAP_X, PG_Y))                # PG pin → tap
    s.add(junction(PG_TAP_X, PG_Y))
    place_from_netlist(s, nl, "R12", x=PG_TAP_X, y=PG_Y - 13.97)
    s.add(wire(PG_TAP_X, PG_Y, PG_TAP_X, PG_Y - 10.16))          # tap → R12 bot
    s.add(wire(PG_TAP_X, PG_Y - 17.78, PG_TAP_X, PG_Y - 21.59))  # R12 top → +3V3
    power_at(s, "+3V3", PG_TAP_X, PG_Y - 21.59)
    place_from_netlist(s, nl, "R13", x=PG_TAP_X + 7.62, y=PG_Y, angle=90)
    s.add(wire(PG_TAP_X, PG_Y, PG_TAP_X + 3.81, PG_Y))           # tap → R13 left
    s.add(wire(PG_TAP_X + 11.43, PG_Y, PG_TAP_X + 15.24, PG_Y))  # R13 right → hier
    s.add(hier_label("LDO_PG", "output", PG_TAP_X + 15.24, PG_Y, angle=0))

    # GND pins (8, 18, 21) → GND
    for pn in ("8", "18", "21"):
        px, py = U1[pn]
        s.add(wire(px, py, px + 5.08, py))
        power_at(s, "GND", px + 5.08, py)

    # OUT-side decoupling: 22µF (C13) and 0.1µF (C14). Top stubs end on the
    # OUT-row horizontal (jumper tap built below) — auto-T. Bottom stubs end
    # on the GND rail; one explicit rail segment ties C13's drop to the GND
    # symbol; C14 and downstream caps land on rail interior.
    place_from_netlist(s, nl, "C13", x=172.72, y=129.54)
    s.add(wire(172.72, 125.73, 172.72, U1["1"][1]))
    s.add(wire(172.72, 133.35, 172.72, GND_RAIL_Y))
    s.add(wire(172.72, GND_RAIL_Y, 180.34, GND_RAIL_Y))   # C13.bot → GND symbol
    power_at(s, "GND", 180.34, GND_RAIL_Y)

    place_from_netlist(s, nl, "C14", x=180.34, y=129.54)
    s.add(wire(180.34, 125.73, 180.34, U1["1"][1]))
    s.add(wire(180.34, 133.35, 180.34, GND_RAIL_Y))

    # ===== Cluster C: Output jumpers (3× 1×2 → VDDD, VDDA1, VDDA2) =====
    # Each jumper fans from JX leftward to a common drop column at JX-5.08,
    # which connects once to the OUT bus. KiCad auto-junctions where the
    # per-jumper horizontals meet the drop column interior.
    JX = 195.58
    COMMON_X = JX - 5.08
    TOP_JY = 119.38
    BOT_JY = TOP_JY + 2 * 17.78
    for i, (ref, rail) in enumerate([("J10", "+VDDD"), ("J11", "+VDDA1"), ("J12", "+VDDA2")]):
        jy = TOP_JY + i * 17.78
        place_from_netlist(s, nl, ref, x=JX, y=jy)
        s.add(wire(JX, jy, COMMON_X, jy))                              # pin 1 → drop col
        # TSW-102 has both pins on the LEFT side (body to right); pin 2's rail
        # tap exits DOWNWARD (orthogonal to body) instead of through the body.
        # Offset chosen so jumper Value text (at jy+5.08) clears rail bbox.
        s.add(wire(JX, jy + 2.54, JX, jy + 10.16))
        power_at(s, rail, JX, jy + 10.16)
    s.add(wire(COMMON_X, TOP_JY, COMMON_X, BOT_JY))                   # vertical drop
    s.add(wire(COMMON_X, U1["1"][1], OUT_BUS_X, U1["1"][1]))          # OUT-row tap

    # ===== Cluster D: Load switch (TPS22916) =====
    U2 = place_from_netlist(s, nl, "U11", x=270.51, y=129.54)
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

    # C15 — VIN decouple. 1µF bulk per W6. Top pin sits ON the VADJ wire
    # (auto-T); bottom drops to GND rail (auto-T at rail interior).
    C6_CENTER_Y = U2["A2"][1] + 3.81
    place_from_netlist(s, nl, "C15", x=C6_X, y=C6_CENTER_Y)
    s.add(wire(C6_X, U2["A2"][1] + 7.62, C6_X, GND_RAIL_Y))
    s.add(wire(C6_X, GND_RAIL_Y, 180.34, GND_RAIL_Y))

    # C16 — VOUT decouple. 1µF bulk per W7.
    C7_X = U2["A1"][0] + 7.62
    C7_CENTER_Y = U2["A1"][1] + 3.81
    place_from_netlist(s, nl, "C16", x=C7_X, y=C7_CENTER_Y)
    s.add(wire(C7_X, U2["A1"][1] + 7.62, C7_X, GND_RAIL_Y))
    s.add(wire(C6_X, GND_RAIL_Y, C7_X, GND_RAIL_Y))

    # ON pull-down R11 (10k) + LSW_EN hier-label, vertical, between ON stub
    # and GND rail below the load switch. R2.bot endpoint lands on the GND
    # rail's interior (the C15 → 180.34 segment passes through R2_X) — auto-T,
    # so no separate rail extension wire needed.
    R2_CENTER_Y = U2["B2"][1] + 7.62
    place_from_netlist(s, nl, "R11", x=R2_X, y=R2_CENTER_Y)
    s.add(wire(R2_X, U2["B2"][1] + 3.81, R2_X, U2["B2"][1]))    # R2 top → ON row
    s.add(wire(R2_X, U2["B2"][1], U2["B2"][0], U2["B2"][1]))    # across to ON pin
    s.add(hier_label("LSW_EN", "input", LSW_LABEL_X, U2["B2"][1], angle=180, justify="right"))
    s.add(wire(LSW_LABEL_X, U2["B2"][1], R2_X, U2["B2"][1]))    # LSW_EN → R2 top stub
    s.add(junction(R2_X, U2["B2"][1]))
    s.add(wire(R2_X, U2["B2"][1] + 11.43, R2_X, GND_RAIL_Y))    # R2 bot → GND rail (auto-T)

    validate(s, nl)
    return s
