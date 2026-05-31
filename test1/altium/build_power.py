"""Power sheet — Altium port of gen/build_power.py.

Same declarative source (netlist/power.yaml, loaded via shared gen.netlist
loader) and the same strict validator (gen.validator.validate).

Functional clusters:
  A. LDO body (U10 TPS7A8401A): IN×3 on top, setpoint + EN + NR_SS pins on
     left side, OUT/SNS/FB/PG/GND on right side.
  B. LDO OUT bus: OUT×3 + SNS kelvin + FB strap, bulk caps C13/C14.
  C. Output jumpers J10/J11/J12 → +VDDD/+VDDA1/+VDDA2.
  D. Load switch U11 (TPS22916): VADJ→+VDDIO, C15/C16, R11 + LSW_EN port.

Coordinate conventions (mils, 100-mil grid, Y grows UP):
  U10 centred at (5000, 5000).
  Actual pin geometry (measured from place_from_netlist):
    U10: IN 15,16,17 on top (y=6300); pins 7–14 on left edge (x=4300);
         pins 5,6 at bottom-left (y=3700); OUT/PG/GND on right (x=5700).
    Passives R/C: pin1 at centre+100y, pin2 at centre-100y.
    R orient=1 (horizontal): pin1 at centre-100x, pin2 at centre+100x.
    R orient=3 (horizontal flipped): pin1 at centre+100x, pin2 at centre-100x.
    J (header, orient=0): pin1 at centre+500y, pin2 at centre-500y.
    U11 (TPS22916 @ 11000,5000): A2(VIN)=(10500,5100), A1(VOUT)=(11500,5100),
                                   B1(GND)=(11500,4900), B2(ON)=(10500,4900).

Wire-crossing rules (Altium T-intersection = connected):
  A wire ENDPOINT that lies on another wire's INTERIOR is auto-connected.
  Two wires that merely CROSS (interior-to-interior) are NOT connected.
  Therefore: cap vertical wires and LDO_SET horizontal wires must ONLY cross
  (no endpoint on the other wire's interior). Achieve this by keeping cap
  columns strictly disjoint from port-wire endpoints, and by keeping R10/C12
  GND drop wires in columns clear of horizontal +3V3/signal wires.
"""

from __future__ import annotations

from altium_monkey import PortIOType, PortStyle

from ..gen.netlist import load_netlist
from ..gen.validator import validate
from .build_symbols import get_library
from .config import OUT_DIR, RENDER_DIR
from .shared import AltiumSheet, build_centered
from .units import text_width_mil

GRID = 100  # mil


def build_power() -> tuple[AltiumSheet, object]:
    nl = load_netlist("power")
    lib, lmap = get_library()
    s = AltiumSheet(name="power", title="test1 — Power (LDO + Load Switch)", paper="A3")

    def place(ref, x, y, orientation=0, unit=1):
        return s.place_from_netlist(lib, lmap, nl, ref, x, y,
                                    orientation=orientation, unit=unit)

    # =========================================================================
    # Cluster A: LDO body (U10 TPS7A8401A) centred at (5000, 5000)
    # =========================================================================
    U10 = place("U10", 5000, 5000)
    # Measured pin world coordinates:
    #   Top:        pin15=(4800,6300), pin16=(5000,6300), pin17=(5200,6300)
    #   Left edge:  pin14=(4300,5600)EN, pin12=(4300,5400)BIAS,
    #               pin13=(4300,5200)NR_SS, pin11=(4300,5000), pin10=(4300,4800),
    #               pin9=(4300,4600), pin7=(4300,4400)
    #   Bottom-left: pin5=(4900,3700), pin6=(5100,3700)
    #   Right edge: pin4=(5700,5800)PG, pin1=(5700,5600)OUT,
    #               pin19=(5700,5400)OUT, pin20=(5700,5200)OUT,
    #               pin2=(5700,5000)SNS, pin3=(5700,4800)FB,
    #               pin8=(5700,4600)GND, pin18=(5700,4400)GND, pin21=(5700,4200)GND-pad

    # UL TPS7A8401A pin map (placed at 5000,5000):
    #   left  x=4200: IN 15(5800) 16(5700) 17(5600), EN 14(5400), BIAS 12(5200),
    #                 NR_SS 13(4900), setpoints 11(4600) 10(4500) 9(4400)
    #                 7(4300) 6(4200) 5(4100)
    #   right x=5800: PG 4(5800), OUT 1(5400) 19(5300) 20(5200), SNS 2(5000),
    #                 FB 3(4700), GND 8(4300) 18(4200) PAD 21(4100)
    CHIP_RIGHT_X = U10["1"][0]    # 5800

    RAIL_3V3_Y = 6600            # +3V3 rail, above the chip top pin (5800)
    GND_RAIL_Y = 3300            # GND rail, below the chip bottom pin (4100)

    # Far-west port column (EN + setpoints); side="left" bodies sit in the margin.
    PORT_CONN_X = 1600

    def _pw(name):                       # port body width that fits the name
        return max(700, int(text_width_mil(name)) + 300)

    def setport(net, py, io=PortIOType.INPUT):
        s.port(net, PORT_CONN_X, py, io=io, style=PortStyle.LEFT_RIGHT,
               width_mils=_pw(net), side="left")

    # ---- IN pins 15/16/17 (left, 5600-5800): vertical bus → riser to +3V3 ---
    IN_X = U10["15"][0]                  # 4200 (left pin column)
    s.wire(IN_X, U10["17"][1], IN_X, U10["15"][1])      # bus 5600..5800 (T's pin16)
    # pin16 sits mid-bus — the pin endpoint auto-connects to the collinear wire,
    # so no junction dot is needed here.
    s.wire(IN_X, U10["15"][1], IN_X, RAIL_3V3_Y)        # riser up to the rail

    # ---- BIAS (pin12, 5200): west, then up to the +3V3 rail -----------------
    BIAS_X = 3800
    s.wire(U10["12"][0], U10["12"][1], BIAS_X, U10["12"][1])
    s.wire(BIAS_X, U10["12"][1], BIAS_X, RAIL_3V3_Y)

    # ---- +3V3 rail (PWR3V3 stub … IN riser) + VIN bypass caps ---------------
    PWR3V3_X = 2000
    s.wire(PWR3V3_X, RAIL_3V3_Y, IN_X, RAIL_3V3_Y)
    s.junction(BIAS_X, RAIL_3V3_Y)
    s.wire(PWR3V3_X, RAIL_3V3_Y, PWR3V3_X, RAIL_3V3_Y + 300)
    s.power_at("+3V3", PWR3V3_X, RAIL_3V3_Y + 300)

    C11_X, C10_X, C17_X = 2400, 2900, 3400
    # Body sits BELOW the rail so both stubs run vertical (collinear with the
    # body): pin1 rises to the rail, pin2 drops to GND. The 90° turn is on the
    # rail, clear of the pins.
    C_CAP_Y = RAIL_3V3_Y - 200
    for ref, cx in [("C11", C11_X), ("C10", C10_X), ("C17", C17_X)]:
        place(ref, cx, C_CAP_Y)
        s.wire(cx, C_CAP_Y + 100, cx, RAIL_3V3_Y)       # pin1 → +3V3 rail (vertical)
        s.junction(cx, RAIL_3V3_Y)
        s.wire(cx, C_CAP_Y - 100, cx, GND_RAIL_Y)       # pin2 → GND rail
    s.text("LDO VIN bypass", C11_X - 100, RAIL_3V3_Y + 300)

    # GND rail across the cap bottoms (extended west to R10) → one GND stub
    R10_X = 1800
    s.wire(R10_X, GND_RAIL_Y, C17_X, GND_RAIL_Y)
    s.wire(C10_X, GND_RAIL_Y, C10_X, GND_RAIL_Y - 300)
    s.power_at("GND", C10_X, GND_RAIL_Y - 300)

    # ---- EN (pin14, 5400): LDO_EN port + R10 pull-down to the GND rail -------
    EN_Y = U10["14"][1]                  # 5400
    s.wire(U10["14"][0], EN_Y, PORT_CONN_X, EN_Y)
    setport("LDO_EN", EN_Y)
    R10_CY = EN_Y - 200                  # body below the EN wire; both stubs vertical
    place("R10", R10_X, R10_CY)
    s.wire(R10_X, R10_CY + 100, R10_X, EN_Y)            # pin1 → EN wire (vertical)
    s.junction(R10_X, EN_Y)
    s.wire(R10_X, R10_CY - 100, R10_X, GND_RAIL_Y)      # pin2 → GND rail

    # ---- NR_SS (pin13, 4900): C12 (10nF) to GND -----------------------------
    NR_X   = 3600                        # between caps (3400) and chip (4200)
    C12_CY = 2700                        # below the GND rail
    place("C12", NR_X, C12_CY)
    s.wire(U10["13"][0], U10["13"][1], NR_X, U10["13"][1])
    s.wire(NR_X, U10["13"][1], NR_X, C12_CY + 100)
    s.wire(NR_X, C12_CY - 100, NR_X, C12_CY - 400)
    s.power_at("GND", NR_X, C12_CY - 400)

    # =========================================================================
    # Setpoint taps (left, 100-mil pitch) → far-west ports, fanned to a clean
    # 200-mil row spacing via short jogs east of the chip. (pin, jog_x, row_y);
    # jog_x=None → straight west at the pin's own row.
    # =========================================================================
    SETPOINTS = [
        ("11", "LDO_SET_1V6",   4100, 4800),
        ("10", "LDO_SET_800mV", 4000, 4600),
        ("9",  "LDO_SET_400mV", None, 4400),
        # pin7's jog must sit WEST of pin6's: pin7's port row (4200) equals pin6's
        # own pin row, so their horizontal legs would otherwise overlap (short).
        ("7",  "LDO_SET_200mV", 3700, 4200),
        ("6",  "LDO_SET_100mV", 3900, 4000),
        ("5",  "LDO_SET_50mV",  3500, 3800),
    ]
    for pn, net, jog_x, row_y in SETPOINTS:
        px, py = U10[pn]
        if jog_x is None:
            s.wire(px, py, PORT_CONN_X, py)
        else:
            s.wire(px, py, jog_x, py)
            s.wire(jog_x, py, jog_x, row_y)
            s.wire(jog_x, row_y, PORT_CONN_X, row_y)
        setport(net, row_y)

    # =========================================================================
    # Cluster B: OUT bus (pins 1/19/20), SNS kelvin, FB strap
    # =========================================================================
    # OUT pins all at x=5700: pin1=(5700,5600), pin19=(5700,5400), pin20=(5700,5200)
    OUT_BUS_X = CHIP_RIGHT_X + 700   # 6400
    OUT_Y = U10["1"][1]              # 5600

    for pn in ("1", "19", "20"):
        px, py = U10[pn]
        s.wire(px, py, OUT_BUS_X, py)

    # Vertical OUT bus from pin20 row up to pin1 row
    s.wire(OUT_BUS_X, U10["20"][1], OUT_BUS_X, OUT_Y)
    s.junction(OUT_BUS_X, OUT_Y)

    # SNS (pin 2) kelvin: route to post-cap point at x=SNS_SENSE_X.
    # U10["2"] = (5700, 5000)
    SNS_SENSE_X = OUT_BUS_X + 1500   # 7900
    SNS_JOG_COL = OUT_BUS_X + 100    # 6500
    SNS_JOG_Y   = OUT_Y + 100        # 5700

    s.wire(U10["2"][0], U10["2"][1], SNS_JOG_COL, U10["2"][1])
    s.wire(SNS_JOG_COL, U10["2"][1], SNS_JOG_COL, SNS_JOG_Y)
    s.wire(SNS_JOG_COL, SNS_JOG_Y, SNS_SENSE_X, SNS_JOG_Y)
    s.wire(SNS_SENSE_X, SNS_JOG_Y, SNS_SENSE_X, OUT_Y)
    s.junction(SNS_SENSE_X, OUT_Y)

    # FB (pin 3): strap to OUT bus (ANY-OUT internal feedback)
    FB_Y = U10["3"][1]   # 4800
    s.wire(U10["3"][0], FB_Y, OUT_BUS_X, FB_Y)
    s.wire(OUT_BUS_X, U10["20"][1], OUT_BUS_X, FB_Y)   # extend bus down to FB

    # ---- OUT-side cap bank: bulk C13∥C18 (22µF∥22µF≈44µF COUT), HF C14
    #      (0.1µF), CFF condition C19 (10nF). Uniform 400-mil pitch on the OUT
    #      row; pin1 tops T into the OUT bus, pin2 bottoms drop to one GND rail.
    #      The window between the OUT bus (6400) and the J-cluster drop column
    #      (COMMON_COL_X=8400) only holds four clean columns at ≥400 pitch:
    #      6800 (clear of the LDO_PG riser at 6700) .. 8000 (clear of 8400).
    # Drop the bank so pin1 sits 200 BELOW the OUT trunk and reaches it with a
    # vertical stub (collinear with the V body) — the trunk no longer runs
    # horizontally THROUGH pin1 (passive_on_corner), and C19's body clears the
    # SNS riser at SNS_SENSE_X. pin2 still drops to the GND rail.
    C_OUT_DEC_Y = OUT_Y - 300   # 5300
    OUT_CAP_BANK = [
        ("C13", OUT_BUS_X + 400),    # 6800 — 22µF bulk
        ("C18", OUT_BUS_X + 800),    # 7200 — 22µF bulk (parallel → raises COUT)
        ("C14", OUT_BUS_X + 1200),   # 7600 — 0.1µF HF
        ("C19", OUT_BUS_X + 1600),   # 8000 — 10nF (CFF noise/PSRR condition)
    ]
    for ref, cx in OUT_CAP_BANK:
        place(ref, cx, C_OUT_DEC_Y)
        s.wire(cx, C_OUT_DEC_Y + 100, cx, OUT_Y)        # pin1 → OUT row
        s.wire(cx, C_OUT_DEC_Y - 100, cx, GND_RAIL_Y)   # pin2 → GND rail

    # One GND rail under the bank; the GND symbol hangs at the right (east) end
    # so it terminates the rail (not straddling) and stays clear of the J-cluster
    # drop column at COMMON_COL_X.
    BANK_L = OUT_CAP_BANK[0][1]    # 6800
    BANK_R = OUT_CAP_BANK[-1][1]   # 8000
    s.wire(BANK_L, GND_RAIL_Y, BANK_R, GND_RAIL_Y)
    s.power_at("GND", BANK_R, GND_RAIL_Y)

    # OUT-row bus: OUT_BUS_X → SNS_SENSE_X (cap pin1 tops tap as T-intersections);
    # C19 (8000) taps the SNS_SENSE_X→COMMON_COL_X extension added in cluster C.
    s.wire(OUT_BUS_X, OUT_Y, SNS_SENSE_X, OUT_Y)

    s.text("LDO VOUT bypass", BANK_L - 300, RAIL_3V3_Y + 300)

    # ---- PG (pin 4): pull-up R12 → +3V3; series R13 → LDO_PG port ----------
    # U10["4"] = (5700, 5800) — PG_Y=5800
    PG_Y = U10["4"][1]   # 5800

    # PG tap stub to the right of chip
    PG_TAP_X = CHIP_RIGHT_X + 300   # 6000
    s.wire(U10["4"][0], PG_Y, PG_TAP_X, PG_Y)
    # R12 pin2 drops onto this PG line from above (see junction below).

    # R12 (pull-up 10k): vertical, pin1 top → +3V3 rail, pin2 bottom → PG line.
    # Body raised one grid so pin2 sits ABOVE the horizontal PG line and feeds it
    # with a short vertical stub — both stubs collinear with the body, the PG
    # turn clear of the pin.
    R12_CY = PG_Y + 200   # 6000
    place("R12", PG_TAP_X, R12_CY)
    s.wire(PG_TAP_X, R12_CY - 100, PG_TAP_X, PG_Y)   # pin2 → PG line (vertical)
    s.junction(PG_TAP_X, PG_Y)
    R12_TOP_Y = R12_CY + 100   # 6100
    # Wire R12 pin1 up to +3V3 rail
    s.wire(PG_TAP_X, R12_TOP_Y, PG_TAP_X, RAIL_3V3_Y)
    # Extend +3V3 rail from IN-pin16 column to PG_TAP column
    s.wire(U10["16"][0], RAIL_3V3_Y, PG_TAP_X, RAIL_3V3_Y)
    s.junction(U10["16"][0], RAIL_3V3_Y)

    # R13 (series 1k, horizontal): YAML says R13.1=LDO_PG, R13.2=PG_stub.
    # With orient=1: pin1=LEFT=(R13_CX-100, PG_Y), pin2=RIGHT=(R13_CX+100, PG_Y).
    # We need pin2 (RIGHT) = PG_stub side, pin1 (LEFT) = LDO_PG side.
    # That means: PG_TAP_X is connected to the RIGHT of R13, and port to the LEFT.
    # Place R13 to the LEFT of PG_TAP, so pin1 is further left (toward port).
    # R13_CX chosen so pin2 = PG_TAP_X → R13_CX + 100 = PG_TAP_X → R13_CX = 5900.
    # But R12_CY=5900 is R12's centre at x=PG_TAP_X=6000. R13_CX=5900 at y=5800 is fine (different y).
    # Actually: R13_CX = PG_TAP_X - 100 - 300 = 5600 (pin2 at 5700=CHIP_RIGHT_X, pin1 at 5500).
    # Hmm, that overlaps with chip. Let's go further right: place R13 to the RIGHT of PG_TAP.
    # R13_CX so pin2 (RIGHT side with orient=1) = PG_TAP_X:
    # Wait: orient=1 (DEG_90): pin1=LEFT=(cx-100,cy), pin2=RIGHT=(cx+100,cy).
    # We want pin2=RIGHT connected to PG stub at PG_TAP_X → R13_CX+100 = PG_TAP_X → R13_CX = 5900.
    # Then pin1=LEFT = (5800, PG_Y). That's to the LEFT of PG_TAP_X=6000 — OK.
    # But the wire (PG_TAP_X, PG_Y)→(R13pin2=5900+100=6000, PG_Y) has length 0 since PG_TAP_X=6000!
    # So R13_CX=5900, pin2=(6000, 5800)=PG_TAP_X → R13 pin2 IS AT PG_TAP location.
    # That's actually fine for connectivity (same coord = connected), but we need a separate path.
    # Better: place R13 to the right of PG_TAP:
    # R13_CX=6800, pin2=(6900,5800), pin1=(6700,5800)
    # Then: wire from PG_TAP(6000) to pin2(6900): (6000,5800)→(6900,5800)
    # LDO_PG port at pin1(6700,5800): but 6700 is BETWEEN 6000 and 6900 → port endpoint
    # at x=6700 on interior of the PG→pin2 wire → T-intersection → port sees same net as PG stub. BAD.
    #
    # CORRECT: LDO_PG port must NOT have its endpoint on the wire connecting PG_TAP to R13 pin2.
    # Solution: Wire from PG_TAP to R13 pin2, then wire from R13 pin1 further right to LDO_PG port.
    # For that to work, pin1 must be to the RIGHT of pin2 (away from chip).
    # With orient=3 (DEG_270): pin1=RIGHT=(cx+100,cy), pin2=LEFT=(cx-100,cy).
    # Place R13 at R13_CX, orient=3: pin1=(R13_CX+100, PG_Y), pin2=(R13_CX-100, PG_Y).
    # We want pin2 (LEFT = PG stub side) at PG_TAP_X or near it, and pin1 further right.
    # R13_CX-100 = PG_TAP_X+100 → R13_CX = PG_TAP_X+200 = 6200.
    # pin2 = (6100, PG_Y), pin1 = (6300, PG_Y)
    # Wire PG_TAP(6000)→pin2(6100): short stub (6000,5800)→(6100,5800)
    # Wire pin1(6300)→LDO_PG_PORT(6800): (6300,5800)→(6800,5800)
    # Check: does (6000,5800)→(6100,5800) endpoint (6100,5800) land on OUT_BUS interior?
    # OUT_BUS at x=6400 — different x. Safe.
    # Does (6300,5800)→(6800,5800) cross anything? OUT_BUS is at y=4800..5600 at x=6400.
    # The OUT_BUS has wire from (6400,5200) to (6400,5600). PG wire at y=5800 — different y. Safe.

    R13_CX = PG_TAP_X + 600   # 6600 — spaced clear of R12 (diagonal gap ~453 > 300)
    place("R13", R13_CX, PG_Y, orientation=3)
    # orient=3 -> pin2=(6300,5800) on the PG-stub side, pin1=(6500,5800) outward.
    s.wire(PG_TAP_X, PG_Y, R13_CX - 100, PG_Y)        # 6000 -> 6300 (R13 pin2)
    # LDO_PG: jog right then UP into the clear band above the OUT caps so the
    # port body never lands on the C13/C14 value text (the old glob). The body
    # extends east (side="right") into open space; the wire ends at its west
    # edge from below, so it is not impaled.
    LDO_PG_X = R13_CX + 300            # 6900 (clear of SNS jog column 6500)
    LDO_PG_Y = RAIL_3V3_Y - 600        # 6500 (above caps, below the +3V3 rail)
    s.wire(R13_CX + 100, PG_Y, LDO_PG_X, PG_Y)        # 6500 -> 6700
    s.wire(LDO_PG_X, PG_Y, LDO_PG_X, LDO_PG_Y)        # up 5800 -> 6500
    s.port("LDO_PG", LDO_PG_X, LDO_PG_Y,
           io=PortIOType.OUTPUT, style=PortStyle.LEFT_RIGHT, side="right")

    # ---- GND pins (8, 18, 21) → ONE shared GND symbol ----------------------
    # These three GND pins sit in a 100-mil-pitch column (x=5800, y=4100/4200/
    # 4300). Giving each its own GND symbol stacked them 100 mil apart so the
    # glyph bars/labels collided (label_overlap). Bus them to a single vertical
    # GND rail just right of the chip and hang ONE GND symbol below the lowest pin
    # — tidier and the textbook way to ground a cluster. gnd_bus T's each pin into
    # the rail (Altium auto-junctions), so connectivity is identical.
    GND_RAIL_X = U10["8"][0] + 400      # 6200 — clear of the OUT bus at 6400
    s.gnd_bus([U10["8"], U10["18"], U10["21"]], GND_RAIL_X)

    # =========================================================================
    # Cluster C: Output jumpers J10→+VDDD, J11→+VDDA1, J12→+VDDA2
    # =========================================================================
    # J (TSW-102, orient=0): pin1=(JX, JCY+500), pin2=(JX, JCY-500).
    # Common drop column at COMMON_COL_X, jumper centres at JX.
    # Stagger jumpers vertically.

    COMMON_COL_X = SNS_SENSE_X + 500   # 8400
    JX           = COMMON_COL_X + 500  # 8900

    # UL TSW-102 puts pin1 at the symbol CENTRE (pin2 100 mil below), so set
    # J10's centre at OUT_Y to land pin1 on the OUT-row bus; stagger the rest.
    J10_CY = OUT_Y          # pin1 == OUT_Y
    J11_CY = J10_CY - 1300
    J12_CY = J11_CY - 1300

    for (ref, rail, jcy) in [("J10", "+VDDD", J10_CY), ("J11", "+VDDA1", J11_CY), ("J12", "+VDDA2", J12_CY)]:
        J = place(ref, JX, jcy)
        j1x, j1y = J["1"]
        j2x, j2y = J["2"]
        # Pin1 → common drop column (horizontal wire, endpoint at COMMON_COL_X)
        s.wire(j1x, j1y, COMMON_COL_X, j1y)
        # Pin2 → power rail symbol. The TSW-102 jumper's DRAWN body extends ~600
        # mil right of pin2, so a 500-mil stub lands the rail glyph on the body
        # (label_over_symbol). Use 800 so the rail clears the jumper rectangle.
        s.wire(j2x, j2y, j2x + 800, j2y)
        s.power_at(rail, j2x + 800, j2y)

    # Vertical drop column
    J10_p1y = s.pins_of("J10")["1"][1]   # 5600
    J12_p1y = s.pins_of("J12")["1"][1]   # 3000
    s.wire(COMMON_COL_X, J10_p1y, COMMON_COL_X, J12_p1y)
    # J11 pin1 row taps the column interior
    J11_p1y = s.pins_of("J11")["1"][1]   # 4300
    s.junction(COMMON_COL_X, J11_p1y)

    # Connect common column to OUT-row horizontal bus
    s.wire(SNS_SENSE_X, OUT_Y, COMMON_COL_X, OUT_Y)
    s.junction(COMMON_COL_X, OUT_Y)

    # =========================================================================
    # Cluster D: Load switch U11 (TPS22916) — shifted RIGHT so its west-side
    # input ports (VADJ/LSW_EN) get a clean left margin (clear of the jumpers
    # and C15) for their bodies. The ON net drops to its own low row so C15's
    # GND leg never lands on it. Sheet auto-upgrades to A3 to hold the width.
    # =========================================================================
    # Placed at x=12600 (was 12000): the west-side VADJ/LSW_EN ports extend their
    # 700-mil bodies LEFT toward the output jumpers, whose DRAWN bodies reach to
    # x~9560. The +600 shift opens the west margin so those port bodies clear the
    # jumpers (label_over_symbol) while keeping the whole cluster's relative
    # geometry (VADJ_X, LSW_X, R11_X, C15_X all derive from U11.A2).
    U11 = place("U11", 12600, 5000)
    # A2(VIN)=11500,5100  A1(VOUT)=12500,5100  B1(GND)=12500,4900  B2(ON)=11500,4900
    VIN_Y  = U11["A2"][1]   # 5100
    VOUT_Y = U11["A1"][1]   # 5100
    ON_Y   = U11["B2"][1]   # 4900

    # ---- VIN (A2) <- VADJ port (body in the clean left margin) --------------
    VADJ_X = U11["A2"][0] - 1000          # 10500 connection
    s.wire(U11["A2"][0], VIN_Y, VADJ_X, VIN_Y)
    s.port("VADJ", VADJ_X, VIN_Y, io=PortIOType.INPUT,
           style=PortStyle.LEFT_RIGHT, side="left")

    # ---- C15 (1µF) VADJ decoupling: pin1 taps the VADJ wire, pin2 -> GND -----
    C15_X  = VADJ_X + 500                 # 11000 (between port and chip)
    C15_CY = VIN_Y - 200                  # body below VADJ; both stubs vertical
    place("C15", C15_X, C15_CY)
    s.wire(C15_X, C15_CY + 100, C15_X, VIN_Y)          # pin1 → VADJ wire (vertical)
    s.junction(C15_X, VIN_Y)
    s.wire(C15_X, C15_CY - 100, C15_X, C15_CY - 300)   # pin2 down (clear of ON)
    s.power_at("GND", C15_X, C15_CY - 300)

    # ---- ON (B2): drop to a LOW row, west to LSW_EN; R11 pull-down ----------
    ON_LOW_Y = ON_Y - 400                 # 4500 — ON bus runs below the VADJ row
    s.wire(U11["B2"][0], ON_Y, U11["B2"][0], ON_LOW_Y)
    LSW_X = VADJ_X - 200                  # left of R11, clear of J11 (see U11 +600 shift)
    s.wire(U11["B2"][0], ON_LOW_Y, LSW_X, ON_LOW_Y)
    s.port("LSW_EN", LSW_X, ON_LOW_Y, io=PortIOType.INPUT,
           style=PortStyle.LEFT_RIGHT, side="left")
    R11_X  = VADJ_X                       # 10500 — taps the ON bus, drops to GND
    R11_CY = ON_LOW_Y - 200               # body below the ON bus; both stubs vertical
    place("R11", R11_X, R11_CY)
    s.wire(R11_X, R11_CY + 100, R11_X, ON_LOW_Y)       # pin1 → ON bus (vertical)
    s.junction(R11_X, ON_LOW_Y)
    s.wire(R11_X, R11_CY - 100, R11_X, R11_CY - 300)
    s.power_at("GND", R11_X, R11_CY - 300)

    # ---- VOUT (A1) -> +VDDIO, with C16 decoupling (east of U11) -------------
    VDDIO_X = U11["A1"][0] + 800          # 13300
    s.wire(U11["A1"][0], VOUT_Y, VDDIO_X, VOUT_Y)
    s.power_at("+VDDIO", VDDIO_X, VOUT_Y)
    C16_X  = U11["A1"][0] + 400           # 12900
    C16_CY = VOUT_Y - 200                 # body below VOUT; both stubs vertical
    place("C16", C16_X, C16_CY)
    s.wire(C16_X, C16_CY + 100, C16_X, VOUT_Y)         # pin1 → VOUT wire (vertical)
    s.junction(C16_X, VOUT_Y)
    s.wire(C16_X, C16_CY - 100, C16_X, C16_CY - 300)
    s.power_at("GND", C16_X, C16_CY - 300)

    # ---- GND (B1) -> GND (drop straight down, clear of VOUT/C16) ------------
    s.wire(U11["B1"][0], U11["B1"][1], U11["B1"][0], U11["B1"][1] - 400)
    s.power_at("GND", U11["B1"][0], U11["B1"][1] - 400)

    # =========================================================================
    # Validate and return
    # =========================================================================
    validate(s, nl)
    return s, nl


def main() -> int:
    s, _nl = build_centered(build_power)
    out = s.save(OUT_DIR / "power.SchDoc")
    svg = s.render_svg(RENDER_DIR / "power.svg")
    print(f"validated OK | wrote {out.name} + {svg.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
