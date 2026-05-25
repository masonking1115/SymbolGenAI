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
    # Body local x ∈ [-20.32, 20.32], y ∈ [-22.86, 20.32].
    U1 = place_from_netlist(s, nl, "U10", x=129.54, y=129.54)

    # All downstream coords are expressed RELATIVE to U1's pin world coords,
    # so any future origin shift cascades automatically. The bookmark pins:
    #   U1["15"] = top-left IN pin    (chip_left, chip_top)
    #   U1["1"]  = top-right OUT pin  (chip_right, OUT row)
    #   U1["18"] = bottom-right GND   (chip_right, chip_bot)
    # Local pin layout for reference:
    #   IN (15,16,17): left edge, top.   EN (14), BIAS (12), NR_SS (13): left edge, mid.
    #   50_mV..1.6_V (5,6,7,9,10,11): left edge, lower.
    #   OUT (1,19,20): right edge, top.  SNS (2), FB (3): right edge, mid.
    #   PG (4): right edge, topmost.     GND (8,18): right edge, bot. PAD (21): right edge, bottom-most.
    CHIP_LEFT  = U1["15"][0]
    CHIP_RIGHT = U1["1"][0]
    CHIP_TOP_Y = U1["15"][1]                # IN[15]-row, top
    BIAS_Y     = U1["12"][1]                # BIAS pin row
    EN_Y       = U1["14"][1]
    NR_Y       = U1["13"][1]
    OUT_Y      = U1["1"][1]                 # OUT[1] row — also the OUT-bus join row

    RAIL_3V3_Y = CHIP_TOP_Y - 13.97         # +3V3 input rail (above chip)
    GND_RAIL_Y = U1["18"][1] + 25.4         # GND rail (below chip)

    # IN pins (15,16,17) + BIAS pin (12) → +3V3 via a single vertical bus.
    # Bus column sits 7.62 mm (3 grid) left of the chip pins; KiCad auto-T's
    # where each stub lands on the bus interior, so no explicit junctions needed.
    IN_BUS_X = CHIP_LEFT - 7.62
    for px, py in [U1["15"], U1["16"], U1["17"], U1["12"]]:
        s.add(wire(px, py, IN_BUS_X, py))
    s.add(wire(IN_BUS_X, BIAS_Y, IN_BUS_X, RAIL_3V3_Y))
    power_at(s, "+3V3", IN_BUS_X, RAIL_3V3_Y)

    # IN-side decoupling row: C17 (BIAS bypass) + C10 (10µF) + C11 (0.1µF).
    # Each cap is 5.08 mm apart; C11 is one grid LEFT of the IN-bus so its
    # body clears R10 (EN pulldown).
    R10_X = CHIP_LEFT - 10.16
    C_DECOUPLE_Y = U1["1"][1] + 10.16       # row 10.16 below OUT-row → same as old y=129.54
    C11_X = R10_X - 6.35
    C10_X = C11_X - 5.08
    C17_X = C10_X - 5.08
    for ref, cx in [("C17", C17_X), ("C10", C10_X), ("C11", C11_X)]:
        place_from_netlist(s, nl, ref, x=cx, y=C_DECOUPLE_Y)
        s.add(wire(cx, C_DECOUPLE_Y - 3.81, cx, RAIL_3V3_Y))
        s.add(wire(cx, C_DECOUPLE_Y + 3.81, cx, GND_RAIL_Y))
    s.add(wire(C17_X, RAIL_3V3_Y, IN_BUS_X, RAIL_3V3_Y))   # +3V3 rail across caps + IN bus
    s.add(wire(C17_X, GND_RAIL_Y, C11_X, GND_RAIL_Y))      # GND rail across cap bottoms
    power_at(s, "GND", C10_X, GND_RAIL_Y)

    # EN pin (14) → R10 (10k) pulldown to GND, hier_label LDO_EN from FMC.
    R10_Y = EN_Y + 5.08
    s.add(wire(U1["14"][0], EN_Y, R10_X, EN_Y))
    place_from_netlist(s, nl, "R10", x=R10_X, y=R10_Y)
    s.add(wire(R10_X, R10_Y - 3.81, R10_X, EN_Y))
    s.add(wire(R10_X, R10_Y + 3.81, R10_X, GND_RAIL_Y))
    s.add(wire(C11_X, GND_RAIL_Y, R10_X, GND_RAIL_Y))      # bridge IN-rail GND → R10 col
    s.add(junction(R10_X, GND_RAIL_Y))
    # LDO_EN at the LDO_SET label column so cap top-drop columns at C10/C11
    # don't cross the label text (caught by _check_wire_crosses_label_text).
    LABEL_FAR_LEFT_X = CHIP_LEFT - 29.21
    s.add(hier_label("LDO_EN", "input", LABEL_FAR_LEFT_X, EN_Y, angle=180, justify="right"))
    s.add(wire(LABEL_FAR_LEFT_X, EN_Y, R10_X, EN_Y))
    s.add(junction(R10_X, EN_Y))

    # NR_SS (13): C12 (10nF) on its own column (NOT R10_X) so R10.bot's GND
    # drop doesn't pass through C12.top — that would silently short NR_SS to
    # GND. cy is chosen so C12.bot stays above the LDO_SET pin 11 row.
    NR_X = CHIP_LEFT - 5.08
    C12_Y = NR_Y + 2.54
    s.add(wire(U1["13"][0], NR_Y, NR_X, NR_Y))
    place_from_netlist(s, nl, "C12", x=NR_X, y=C12_Y)
    s.add(wire(NR_X, C12_Y - 3.81, NR_X, NR_Y))
    s.add(wire(NR_X, C12_Y + 3.81, NR_X, GND_RAIL_Y))
    s.add(wire(R10_X, GND_RAIL_Y, NR_X, GND_RAIL_Y))       # extend GND rail to NR_X

    # ===== Cluster B: ANY-OUT setpoint pins (FPGA-driven via FMC LA bank) =====
    LDO_SET_PINS = [
        ("5",  "LDO_SET_50mV"),
        ("6",  "LDO_SET_100mV"),
        ("7",  "LDO_SET_200mV"),
        ("9",  "LDO_SET_400mV"),
        ("10", "LDO_SET_800mV"),
        ("11", "LDO_SET_1V6"),
    ]
    # Labels at chip_left - 29.21 sit past all three cap GND-drop columns
    # (C17 at chip_left-26.67, C10 at -21.59, C11 at -16.51) — caught by
    # _check_wire_crosses_label_text.
    for pn, net in LDO_SET_PINS:
        px, py = U1[pn]
        s.add(wire(px, py, LABEL_FAR_LEFT_X, py))
        s.add(global_label(net, "input", LABEL_FAR_LEFT_X, py, angle=180, justify="right"))

    # ===== Cluster B: OUT side =====
    # OUT bus is one vertical wire from U1["1"] (OUT top) down to U1["3"] (FB);
    # pins 19/20 stubs land on its interior via auto-T. Junction at U1["1"] is
    # needed because three endpoints meet there (pin 1, jumper tap, FB top).
    OUT_BUS_X = CHIP_RIGHT + 15.24
    for pn in ("1", "19", "20"):
        px, py = U1[pn]
        s.add(wire(px, py, OUT_BUS_X, py))
    s.add(junction(OUT_BUS_X, OUT_Y))

    # SNS (2) → kelvin sense to a point AFTER the bulk caps (E9 fix).
    SNS_JOG_X = CHIP_RIGHT + 16.51
    SNS_JOG_Y = OUT_Y - 2.54
    SNS_SENSE_X = CHIP_RIGHT + 35.56
    s.add(wire(U1["2"][0], U1["2"][1], SNS_JOG_X, U1["2"][1]))   # SNS stub right
    s.add(wire(SNS_JOG_X, U1["2"][1], SNS_JOG_X, SNS_JOG_Y))     # up clear of bus
    s.add(wire(SNS_JOG_X, SNS_JOG_Y, SNS_SENSE_X, SNS_JOG_Y))    # across to sense x
    s.add(wire(SNS_SENSE_X, SNS_JOG_Y, SNS_SENSE_X, OUT_Y))      # down to OUT trace
    s.add(junction(SNS_SENSE_X, OUT_Y))                          # tie to OUT net

    # FB (3) → tie to OUT BUS locally (ANY-OUT mode uses internal feedback).
    # The FB stub endpoint lands on the OUT bus interior — auto-T.
    s.add(wire(U1["3"][0], U1["3"][1], OUT_BUS_X, U1["3"][1]))
    s.add(wire(OUT_BUS_X, OUT_Y, OUT_BUS_X, U1["3"][1]))

    # PG (4) — open-drain output. (a) 10kΩ pull-up R12 to +3V3, (b) 1kΩ R13 in
    # series before the FMC PG_C2M pin.
    PG_TAP_X = CHIP_RIGHT + 7.62
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

    # OUT-side decoupling: 22µF (C13) and 0.1µF (C14). Tops land on OUT-row
    # horizontal (jumper tap below); bottoms drop to GND rail.
    C13_X = CHIP_RIGHT + 22.86
    C14_X = CHIP_RIGHT + 30.48
    place_from_netlist(s, nl, "C13", x=C13_X, y=C_DECOUPLE_Y)
    s.add(wire(C13_X, C_DECOUPLE_Y - 3.81, C13_X, OUT_Y))
    s.add(wire(C13_X, C_DECOUPLE_Y + 3.81, C13_X, GND_RAIL_Y))
    s.add(wire(C13_X, GND_RAIL_Y, C14_X, GND_RAIL_Y))   # C13.bot → GND symbol
    power_at(s, "GND", C14_X, GND_RAIL_Y)

    place_from_netlist(s, nl, "C14", x=C14_X, y=C_DECOUPLE_Y)
    s.add(wire(C14_X, C_DECOUPLE_Y - 3.81, C14_X, OUT_Y))
    s.add(wire(C14_X, C_DECOUPLE_Y + 3.81, C14_X, GND_RAIL_Y))

    # ===== Cluster C: Output jumpers (3× 1×2 → VDDD, VDDA1, VDDA2) =====
    # Each jumper fans from JX leftward to a common drop column at JX-5.08
    # that connects once to the OUT bus. KiCad auto-junctions where the
    # per-jumper horizontals meet the drop-column interior.
    JX = CHIP_RIGHT + 45.72
    COMMON_X = JX - 5.08
    TOP_JY = OUT_Y
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
    s.add(wire(COMMON_X, OUT_Y, OUT_BUS_X, OUT_Y))                    # OUT-row tap

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
    s.add(wire(C6_X, GND_RAIL_Y, C14_X, GND_RAIL_Y))   # extend GND rail across to U1's C14

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
