"""Bobcat sheet — Altium port of gen/build_bobcat.py.

Same declarative source (netlist/bobcat.yaml, loaded via the shared gen.netlist
loader) and the SAME strict validator (gen.validator.validate). Only the layout
backend changes from KiCad s-expr to Altium binary.

Differences from the KiCad builder, all mechanical:
  - coordinates are mils on a 100-mil grid (KiCad used mm),
  - Altium Y grows UP, so "below the chip" = smaller y, "above" = larger y,
  - wires route from placed-component pin hot-spots returned by place(),
  - global_label/hier_label -> Altium Port,
  - power_at(s, rail, x, y) -> s.power_at(rail, x, y),
  - junction objects are cosmetic; connectivity rides T-intersections / pin
    endpoints, which both Altium and the validator treat as connected.

Bobcat (U20) is a QFN-40 placed at (5000, 5000). Measured pin geometry:
  Left edge   (x=3600): pins 1..10, y = 5900 down to 4100 (step 200).
  Bottom edge (y=3500): pins 11..20, x = 4100 .. 5900 (step 200).
  Right edge  (x=6400): pins 21..30, y = 4000 .. 6000 (gap at EP), 41(EP)=5000.
  Top edge    (y=6500): pins 31..40, x = 5900 down to 4100 (step 200).
Passives (measured): R orient0 vertical pin1=+100y/pin2=-100y; R orient1
  horizontal pin1=-100x/pin2=+100x; R orient3 horizontal pin1=+100x/pin2=-100x;
  C orient0 vertical pin1=+100y/pin2=-100y; C orient1 horizontal pin1=-100x/pin2=+100x.

Power nets (+VDDD/+VDDA1/+VDDA2/+VDDIO/GND) use LOCAL power symbols at each
member — same-rail symbols share a name, so the validator unions each member's
own component to the rail name (no global rail wire needed). The two INTERNAL
nets (VDDA1_path, VDDA2_path) ARE physically wired into single components.
"""

from __future__ import annotations

from altium_monkey import PortIOType, PortStyle

from ..gen.netlist import load_netlist
from ..gen.validator import validate
from .build_symbols import get_library
from .config import OUT_DIR, RENDER_DIR
from .shared import AltiumSheet, build_centered

GRID = 100  # mil


def build_bobcat() -> tuple[AltiumSheet, object]:
    nl = load_netlist("bobcat")
    lib, lmap = get_library()
    # A2: the CLK_OUT/GPIO port banks + R30-33 ladder extend to X~16885 /
    # Y~13650, ~350 / ~1960 mil past A3. A2 (23390x16535) frames it without
    # repositioning the placed DUT clusters.
    s = AltiumSheet(name="bobcat", title="test1 — Bobcat DUT", paper="A2")

    def place(ref, x, y, orientation=0, unit=1):
        return s.place_from_netlist(lib, lmap, nl, ref, x, y,
                                    orientation=orientation, unit=unit)

    # =====================================================================
    # Cluster A: Bobcat chip (U20) + GND exposed pad (pin 41)
    # =====================================================================
    # U20 sits high enough that the SPI cluster + pulls (which hang ~3000 mil
    # below the chip bottom) stay at positive y, fully inside the sheet border.
    # Every coordinate below derives from U20's pins except VDDIO_ROW_CY, which
    # is raised by the same amount — so the whole layout is a uniform translate
    # (routing/shorts unchanged), just lifted into the page.
    U = place("U20", 5000, 7200)
    CHIP_LEFT_X = U["1"][0]      # 3600
    CHIP_RIGHT_X = U["21"][0]    # 6400
    CHIP_BOT_Y = U["11"][1]      # 3500
    CHIP_TOP_Y = U["31"][1]      # 6500

    # Pin 41 (EP, right edge at y=5000) -> short stub right -> GND symbol.
    ep_x, ep_y = U["41"]
    s.wire(ep_x, ep_y, ep_x + 400, ep_y)
    s.power_at("GND", ep_x + 400, ep_y)

    # =====================================================================
    # Cluster B: VDDD decoupling (pins 12, 20 — bottom edge)
    #   per-pin local +VDDD symbol + cap to GND, no horizontal rail.
    # =====================================================================
    # Caps hang well BELOW the chip (smaller y). Each pin column:
    #   pin -> down to +VDDD symbol -> down to cap pin1 -> cap pin2 -> GND.
    VDDD_PSYM_Y = CHIP_BOT_Y - 600     # 2900 — +VDDD symbol taps off here
    VDDD_CAP_CY = CHIP_BOT_Y - 1500    # 2000 — cap centre (pin1=+100, pin2=-100)
    VDDD_GND_Y = CHIP_BOT_Y - 2400     # 1100 — GND below cap
    # The chip pin runs straight DOWN to the cap; the +VDDD glyph taps off to the
    # SIDE on a short stub (terminating it) rather than straddling the vertical
    # run — so it needs no post-build auto_fix_power relocation. Opposite sides
    # for the two pins keeps the rail-name texts apart. (Generation no-straddle
    # rule; see ShEET.power_at stub= / layout_lint.power_straddles_net.)
    for ref, pn, vddd_stub in [("C20", "12", -200), ("C21", "20", +200)]:
        px, py = U[pn]
        s.wire(px, py, px, VDDD_CAP_CY + 100)       # pin straight down to cap pin1
        s.power_at("+VDDD", px, VDDD_PSYM_Y, stub=vddd_stub)  # glyph beside the net
        place(ref, px, VDDD_CAP_CY)
        s.wire(px, VDDD_CAP_CY - 100, px, VDDD_GND_Y)   # cap pin2 down to GND
        s.power_at("GND", px, VDDD_GND_Y)
    # Title BELOW the cap/GND column so it doesn't sit on top of C20.
    s.text("VDDD core bypass", U["12"][0] - 400, VDDD_GND_Y - 400)
    # C44: 10uF post-jumper bulk on +VDDD (F-7, DUT-side). +VDDD is a named power
    # rail, so the cap connects by power-symbol alone (like the VDDIO bulk row) —
    # placed one column LEFT of the C20/C21 pair, clear of the chip pins, with its
    # own +VDDD/GND glyphs on opposite pins so the rail-name texts don't collide.
    C44_X = U["12"][0] - 1200
    place("C44", C44_X, VDDD_CAP_CY)
    s.wire(C44_X, VDDD_CAP_CY + 100, C44_X, VDDD_CAP_CY + 500)   # pin1(top) -> +VDDD
    s.power_at("+VDDD", C44_X, VDDD_CAP_CY + 500, stub=-200)
    s.wire(C44_X, VDDD_CAP_CY - 100, C44_X, VDDD_GND_Y)          # pin2(bottom) -> GND
    s.power_at("GND", C44_X, VDDD_GND_Y)
    s.text("VDDD bulk 10uF", C44_X - 400, VDDD_GND_Y - 400)

    # =====================================================================
    # Cluster D: VDDA1 path (pin 1, left edge) — series 0R R20 + C22 decouple
    #   internal_VDDA1_path = {U20.1, R20.1, C22.1}; +VDDA1 = {R20.2}
    # =====================================================================
    p1x, p1y = U["1"]    # (3600, 5900)
    # R20 horizontal to the LEFT of pin1. orient=3: pin1=+100x (right=chip side),
    # pin2=-100x (left=rail side). Net: R20.1=chip-side (internal), R20.2=+VDDA1.
    R20_CX = p1x - 700   # 2900
    place("R20", R20_CX, p1y, orientation=3)
    R20p = s.pins_of("R20", 1)   # 1=(3000,5900) chip; 2=(2800,5900) rail
    s.wire(p1x, p1y, R20p["1"][0], p1y)                   # chip pin1 -> R20.1
    s.wire(R20p["2"][0], p1y, R20_CX - 500, p1y)          # R20.2 -> +VDDA1
    s.power_at("+VDDA1", R20_CX - 500, p1y)               # (2400, 5900)
    # C22 decoupling: internal net wants C22.1 on the chip/R20.1 side. Pin1 (the
    # VDDA1 top-left pin, y=5900) is ABOVE all SAMPLE_OUT left-exit lanes
    # (y<=5700), so the C22 tap column at x=3000 is only safe ABOVE y=5900.
    # Place C22 ABOVE pin1's row, orient=2 (pin1=bottom, pin2=top): pin1 routes
    # DOWN to the R20.1 tap at (3000,5900), pin2 routes UP to GND. The pin1 wire
    # stays at y>=5900, clear of every SAMPLE_OUT lane.
    C22_TAP_X = R20p["1"][0]    # 3000 — the cap column
    C22_CY = p1y + 900          # 6800 — above pin1's row
    place("C22", C22_TAP_X, C22_CY, orientation=2)
    C22 = s.pins_of("C22", 1)   # 1=(3000,6700) bottom ; 2=(3000,6900) top
    # C22.1(bottom) taps the chip-pin1->R20.1 horizontal at its MID-SPAN (x=3300),
    # NOT at R20.1 (x=3000): drop, jog right, then down to the wire. This keeps the
    # 90deg bend off R20 pin1, which is left to a single straight horizontal stub.
    C22_TAP_PT_X = R20p["1"][0] + 300   # 3300 — mid-span of the (3000..3600) wire
    s.wire(C22["1"][0], C22["1"][1], C22["1"][0], p1y + 200)  # C22.1 down to y=6100
    s.wire(C22["1"][0], p1y + 200, C22_TAP_PT_X, p1y + 200)   # jog right to x=3300
    s.wire(C22_TAP_PT_X, p1y + 200, C22_TAP_PT_X, p1y)        # down to T at (3300,5900)
    # C22.2(top) -> GND: hang LEFT (away from the chip) so the GND symbol clears the
    # U20 body by >100 mil and still sits BELOW its net (wire enters from above).
    C22_GX = C22_TAP_X - 400          # 2600 — left of the cap, clear of U20 (left edge ~3600)
    C22_UP_Y = C22["2"][1] + 200      # 7100 — pin2 stub rises (parallel to the body)
    C22_GY = C22["2"][1] - 400        # 6500
    s.wire(C22["2"][0], C22["2"][1], C22["2"][0], C22_UP_Y)   # pin2(top) up (vertical)
    s.wire(C22["2"][0], C22_UP_Y, C22_GX, C22_UP_Y)          # left at the raised row
    s.wire(C22_GX, C22_UP_Y, C22_GX, C22_GY)                 # down to GND stub
    s.power_at("GND", C22_GX, C22_GY)
    # C45: 10uF post-jumper bulk on internal_VDDA1_path (F-7, DUT-side). The
    # internal net is unlabeled (wired-only), so C45 must physically join it.
    # Placed in the clear band to the LEFT of the C22/+VDDA1 column (well clear of
    # the chip left edge at x=3600), tapping the chip-pin1->R20.1 wire interior at
    # (3400,5900) via a riser UP to a lane above C22, then west to C45's column and
    # down INTO pin1 (in-line, vertical) so the cap sits in the net's path.
    C45_X = 1600                     # clear band left of +VDDA1 glyph (x=2400)
    C45_CY = C22_CY + 600            # 7400 — above C22's GND, clear band
    place("C45", C45_X, C45_CY, orientation=2)
    C45 = s.pins_of("C45", 1)        # 1=(1600,7300) bottom ; 2=(1600,7500) top
    C45_TAP_PT_X = R20p["1"][0] + 400   # 3400 — on the (3000..3600) internal wire (on-grid)
    C45_LANE_Y = C45["1"][1] - 300   # 7000 — west-run lane, above C22 (6900)
    s.junction(C45_TAP_PT_X, p1y)
    s.wire(C45_TAP_PT_X, p1y, C45_TAP_PT_X, C45_LANE_Y)      # riser UP off the internal net
    s.wire(C45_TAP_PT_X, C45_LANE_Y, C45_X, C45_LANE_Y)      # west at the raised lane to C45's col
    s.wire(C45_X, C45_LANE_Y, C45_X, C45["1"][1])            # up INTO C45.1 (in-line, vertical)
    C45_GX = C45_X - 400             # 1200 — left of the cap
    C45_UP_Y = C45["2"][1] + 200     # 7700
    C45_GY = C45["2"][1] - 400       # 7100
    s.wire(C45["2"][0], C45["2"][1], C45["2"][0], C45_UP_Y)   # pin2(top) up
    s.wire(C45["2"][0], C45_UP_Y, C45_GX, C45_UP_Y)          # left at raised row
    s.wire(C45_GX, C45_UP_Y, C45_GX, C45_GY)                 # down to GND stub
    s.power_at("GND", C45_GX, C45_GY)

    # =====================================================================
    # Cluster E: VDDA2 path (pins 26, 27 tied, right edge) — series R21 + C23
    #   internal_VDDA2_path = {U20.26, U20.27, R21.2, C23.1}; +VDDA2 = {R21.1}
    # =====================================================================
    # Pins 26 (y=5200) and 27 (y=5400) sit in the clear band between the OWT
    # lanes (y<=4800) and the BIAS lanes (y>=5600). The EP-GND stub spans
    # x[6400,6800] at y=5000. BIAS exits are kept SHORT (end at x=6800, below).
    # So the tie column at x=6900 is a CLEAN vertical corridor (no right-exit
    # lane crosses x=6900 in the band y[5400,6700]).
    p26x, p26y = U["26"]   # (6400, 5200)
    p27x, p27y = U["27"]   # (6400, 5400)
    TIE_X = p26x + 500     # 6900 — clean vertical tie corridor
    s.wire(p26x, p26y, TIE_X, p26y)        # pin26 -> tie
    s.wire(p27x, p27y, TIE_X, p27y)        # pin27 -> tie
    s.wire(TIE_X, p26y, TIE_X, p27y)       # vertical tie 26<->27
    # R21 series 0R, horizontal on the pin27 row (y=5400). orient=3: pin1=+100x
    # (right=rail=+VDDA2), pin2=-100x (left=chip side). Net: R21.2 chip, R21.1 rail.
    R21_CX = TIE_X + 800   # 7700
    R21_y = p27y           # 5400 row (above the OWT lanes, below BIAS pin28 row 5600)
    place("R21", R21_CX, R21_y, orientation=3)
    R21p = s.pins_of("R21", 1)   # 1=(7800,5400) rail ; 2=(7600,5400) chip
    s.wire(TIE_X, R21_y, R21p["2"][0], R21_y)              # tie -> R21.2 (chip side)
    s.wire(R21p["1"][0], R21_y, R21_CX + 500, R21_y)       # R21.1 -> +VDDA2
    s.power_at("+VDDA2", R21_CX + 500, R21_y)              # (8200, 5400)
    # C23 decoupling: net wants C23.1 on the chip side (tie). Place C23 ABOVE the
    # tie on the x=6900 corridor, orient=2 (pin1=bottom, pin2=top): pin1 down to
    # the tie (T at (6900,5400)=pin27 tie endpoint); pin2 up to GND. The corridor
    # above the tie (y 5400..6700) is clear since BIAS exits end at x=6800.
    C23_CY = p27y + 900    # 6300 — above the tie, on the x=6900 corridor
    place("C23", TIE_X, C23_CY, orientation=2)
    C23 = s.pins_of("C23", 1)   # 1=(6900,6200) bottom ; 2=(6900,6400) top
    s.wire(C23["1"][0], C23["1"][1], TIE_X, p27y)          # C23.1(bottom) -> tie col (T at 6900,5400)
    # C23.2(top) -> GND: jog right then drop so the GND symbol sits BELOW the
    # wire (enters from above), not above its net.
    C23_GX = TIE_X + 400              # 7300
    C23_UP_Y = C23["2"][1] + 200      # 6600 — pin2 stub rises (parallel to the body)
    C23_GY = C23["2"][1] - 400        # 6000
    s.wire(C23["2"][0], C23["2"][1], C23["2"][0], C23_UP_Y)  # pin2(top) up (vertical)
    s.wire(C23["2"][0], C23_UP_Y, C23_GX, C23_UP_Y)         # right at the raised row
    s.wire(C23_GX, C23_UP_Y, C23_GX, C23_GY)                # down to GND stub
    s.power_at("GND", C23_GX, C23_GY)
    # C46: 10uF post-jumper bulk on internal_VDDA2_path (F-7, DUT-side). Placed in
    # the clear band to the RIGHT of R21 (past the +VDDA2 glyph), tapping the
    # internal net by extending a horizontal stub EAST off R21.2's row to a riser
    # column, so no wire runs through R21's pins (avoids passive_on_corner) and
    # nothing crosses the chip body. pin1(bottom) drops onto the riser; pin2(top)
    # up to its own GND glyph.
    C46_X = R21_CX + 1600            # 9300 — well right of R21 (7700) and +VDDA2 (8200)
    C46_CY = R21_y + 1200            # 6600 — above the R21 row, clear band
    place("C46", C46_X, C46_CY, orientation=2)
    C46 = s.pins_of("C46", 1)        # 1=(9300,6500) bottom ; 2=(9300,6700) top
    # Tap the tie->R21.2 internal wire at its mid-span (x=7200,y=5400), riser UP to
    # a clear lane ABOVE the R21 row, then east to C46.1 — staying clear of the
    # +VDDA2 rail wire (which runs east of R21 on the y=5400 row). The tap is on
    # the wire interior, not on a pin; x=7200 is clear above y=5400 (BIAS exits
    # end at x=6800), so the riser doesn't cross any signal lane.
    C46_TAP_X = TIE_X + 300          # 7200 — mid-span of the tie->R21.2 wire
    C46_LANE_Y = C46["1"][1] - 300   # 6200 — east-run lane BELOW C46.1 (clear of R21 row)
    s.junction(C46_TAP_X, R21_y)
    s.wire(C46_TAP_X, R21_y, C46_TAP_X, C46_LANE_Y)          # riser UP off the internal net
    s.wire(C46_TAP_X, C46_LANE_Y, C46_X, C46_LANE_Y)         # east at the raised lane to C46's column
    s.wire(C46_X, C46_LANE_Y, C46_X, C46["1"][1])            # up INTO C46.1 (in-line, vertical)
    C46_GX = C46_X + 400             # 9700 — right of the cap
    C46_UP_Y = C46["2"][1] + 200     # 6900
    C46_GY = C46["2"][1] - 400       # 6300
    s.wire(C46["2"][0], C46["2"][1], C46["2"][0], C46_UP_Y)  # pin2(top) up
    s.wire(C46["2"][0], C46_UP_Y, C46_GX, C46_UP_Y)         # right at the raised row
    s.wire(C46_GX, C46_UP_Y, C46_GX, C46_GY)                # down to GND stub
    s.power_at("GND", C46_GX, C46_GY)

    # =====================================================================
    # Cluster C: VDDIO decoupling — per-pin local +VDDIO symbols + cap row
    # =====================================================================
    # VDDIO chip pins: 7(left), 13(bottom), 22(right), 33+34(top). Each gets a
    # local +VDDIO power symbol on a short stub away from the chip.
    # pin 7 (left, x=3600,y=4700): stub left
    px, py = U["7"]
    s.wire(px, py, px - 600, py)
    s.power_at("+VDDIO", px - 600, py)
    # pin 13 (bottom): drop down to clear the pin-12 +VDDD symbol row (both are
    # bottom pins; an inline glyph would collide the rail names), then tap the
    # +VDDIO glyph off to the SIDE on a short stub. Capping the vertical drop with
    # an up-pointing rail glyph would make it point INTO the net (net above it) —
    # the wrong-side case auto_fix_power_stub_side corrects; placing it on a
    # horizontal stub avoids that (see layout_lint.power_stub_side).
    px, py = U["13"]
    s.wire(px, py, px, py - 1000)
    s.power_at("+VDDIO", px, py - 1000, stub=-400)
    # pin 22 (right, x=6400,y=4200): stub right
    px, py = U["22"]
    s.wire(px, py, px + 600, py)
    s.power_at("+VDDIO", px + 600, py)
    # pins 33, 34 (top): stub up. These two top pins are only 200 mil apart, so
    # equal 600-mil stubs put both +VDDIO rail-name texts on the same row where
    # they collide into a smear (label_overlap). Stagger the stub lengths (like
    # pin 13 vs pin 12) so the two glyphs sit on different rows and their names
    # clear each other vertically.
    for pn, stub in (("33", 600), ("34", 1000)):
        px, py = U[pn]
        s.wire(px, py, px, py + stub)
        s.power_at("+VDDIO", px, py + stub)

    # VDDIO cap row (C24..C29) — the caps connect ONLY to local +VDDIO / GND
    # power symbols (no wired rail), so they live in an empty band well clear of
    # every signal lane: lower-right of the sheet, below the OWT cluster.
    VDDIO_ROW_CY = 3700                # empty band, well below the chip (raised with U20)
    VDDIO_ROW_X0 = CHIP_RIGHT_X + 2400 # 8800 leftmost cap
    for i, ref in enumerate(["C24", "C25", "C26", "C27", "C28", "C29"]):
        cx = VDDIO_ROW_X0 + i * 500
        place(ref, cx, VDDIO_ROW_CY)
        # pin1 (top) up to +VDDIO ; pin2 (bottom) down to GND.
        s.wire(cx, VDDIO_ROW_CY + 100, cx, VDDIO_ROW_CY + 500)
        s.power_at("+VDDIO", cx, VDDIO_ROW_CY + 500)
        s.wire(cx, VDDIO_ROW_CY - 100, cx, VDDIO_ROW_CY - 500)
        s.power_at("GND", cx, VDDIO_ROW_CY - 500)
    s.text("VDDIO supply bypass", VDDIO_ROW_X0, VDDIO_ROW_CY + 800)

    # =====================================================================
    # Cluster F: SPI / control pull network (bottom-edge pins 14..19)
    # =====================================================================
    # Each SPI pin drops DOWN to its own horizontal label row (unique y), exits
    # LEFT to a Port. Pull R taps the vertical drop in its own column.
    SPI_PINS = [
        # (pin, net, io, pull_type, pull_ref)
        ("14", "MOSI",      PortIOType.INPUT,  "down", "R22"),
        ("15", "MISO",      PortIOType.OUTPUT, None,   None),
        ("16", "SCLK",      PortIOType.INPUT,  "down", "R23"),
        ("17", "CS_L",      PortIOType.INPUT,  "up",   "R24"),
        ("18", "SPI_DMODE", PortIOType.INPUT,  "down", "R25"),
        ("19", "RESET_N",   PortIOType.INPUT,  "up",   "R26"),
    ]
    # Label rows sit well below the chip (below the VDDD cluster GND at y=1100).
    SPI_ROW_Y0 = CHIP_BOT_Y - 3000   # 500 topmost SPI row (highest pin -> ... )
    SPI_ROW_STEP = 400               # rows 200 apart minimum; use 400 for clarity
    SPI_PORT_X = CHIP_LEFT_X - 2400  # 1200 — port column, left of everything
    # Pull resistors live in a column to the RIGHT of the drop, so the pull stub
    # doesn't share x with any neighbouring pin's drop column.
    for i, (pn, net, io, pull_type, pull_ref) in enumerate(SPI_PINS):
        px, py = U[pn]
        row_y = SPI_ROW_Y0 - i * SPI_ROW_STEP
        s.wire(px, py, px, row_y)               # drop from pin to its row
        s.wire(px, row_y, SPI_PORT_X, row_y)    # horizontal LEFT to port
        s.port(net, SPI_PORT_X, row_y, io=io, style=PortStyle.LEFT_RIGHT)
        if pull_type is None:
            continue
        # Tap the drop at tap_y, route RIGHT into a pull column.
        tap_y = row_y + 200
        pull_x = px + 300 + i * 100   # unique per-pin pull column
        s.wire(px, tap_y, pull_x, tap_y)        # tap -> pull column (T at (px,tap_y))
        if pull_type == "down":
            # R vertical BELOW the tap: pin1(top) fed by a vertical stub down from
            # the tap turn, pin2(bottom) to GND — both stubs parallel to the body.
            place(pull_ref, pull_x, tap_y - 200)
            s.wire(pull_x, tap_y, pull_x, tap_y - 100)        # tap turn → R.1 (vertical)
            s.wire(pull_x, tap_y - 300, pull_x, tap_y - 600)  # R.2 → GND
            s.power_at("GND", pull_x, tap_y - 600)
        else:  # "up" — pull-up to +VDDIO
            # R vertical ABOVE the tap: pin2(bottom) fed by a vertical stub up from
            # the tap turn, pin1(top) to +VDDIO — both stubs parallel to the body.
            place(pull_ref, pull_x, tap_y + 200)
            s.wire(pull_x, tap_y, pull_x, tap_y + 100)        # tap turn → R.2 (vertical)
            s.wire(pull_x, tap_y + 300, pull_x, tap_y + 600)  # R.1 → +VDDIO
            s.power_at("+VDDIO", pull_x, tap_y + 600)

    # =====================================================================
    # Cluster G1: SAMPLE_OUT* on left edge (pins 2-6, 8-11)
    # =====================================================================
    # Left-edge pins exit straight LEFT to ports. Pin 11 is on the BOTTOM edge
    # (x=4100,y=3500); route it left at its own y.
    SAMPLE_PORT_X = CHIP_LEFT_X - 2400   # 1200 (share column convention)
    for pn, net in [("2", "SAMPLE_OUTV"), ("3", "SAMPLE_OUT0"), ("4", "SAMPLE_OUT1"),
                    ("5", "SAMPLE_OUT2"), ("6", "SAMPLE_OUT3"), ("8", "SAMPLE_OUT4"),
                    ("9", "SAMPLE_OUT5"), ("10", "SAMPLE_OUT6")]:
        px, py = U[pn]
        s.wire(px, py, SAMPLE_PORT_X, py)
        s.port(net, SAMPLE_PORT_X, py, io=PortIOType.OUTPUT, style=PortStyle.LEFT_RIGHT)
    # pin 11 (bottom edge) -> down a touch to a unique row then left.
    p11x, p11y = U["11"]   # (4100, 3500)
    S11_Y = CHIP_BOT_Y - 200   # 3300 — unique row, clear of SPI rows (<=500)
    s.wire(p11x, p11y, p11x, S11_Y)
    s.wire(p11x, S11_Y, SAMPLE_PORT_X, S11_Y)
    s.port("SAMPLE_OUT7", SAMPLE_PORT_X, S11_Y, io=PortIOType.OUTPUT, style=PortStyle.LEFT_RIGHT)

    # =====================================================================
    # Cluster G2: OSC_EN / WEIGHT_EN / SAMPLE_TRIG (right edge 23,24,25) + pulls
    # =====================================================================
    OWT_PORT_X = CHIP_RIGHT_X + 2800   # 9200 past pull columns
    OWT_PULL_ROW_Y = CHIP_BOT_Y - 700  # 2800 below chip body for the R bodies
    OWT = [
        ("23", "OSC_EN",      "R27", CHIP_RIGHT_X + 900),
        ("24", "WEIGHT_EN",   "R28", CHIP_RIGHT_X + 1300),
        ("25", "SAMPLE_TRIG", "R29", CHIP_RIGHT_X + 1700),
    ]
    for pn, net, pull_ref, pull_x in OWT:
        px, py = U[pn]
        s.wire(px, py, OWT_PORT_X, py)                 # chip pin -> port (horizontal)
        # INPUT: Bobcat pins 23/24/25 are chip INPUTS (Pin List §1) — the enable/
        # trigger source (SMA default, or FMC alt) drives INTO Bobcat. The driver
        # lives on the source leg (connectors.yaml OUTPUT), so this port is the sink.
        s.port(net, OWT_PORT_X, py, io=PortIOType.INPUT, style=PortStyle.LEFT_RIGHT)
        # Pull drops as a T-branch off this horizontal at pull_x.
        place(pull_ref, pull_x, OWT_PULL_ROW_Y + 100)  # R vertical, pin1 top
        s.wire(pull_x, py, pull_x, OWT_PULL_ROW_Y + 200)   # tap down to R pin1
        s.wire(pull_x, OWT_PULL_ROW_Y, pull_x, OWT_PULL_ROW_Y - 400)  # R pin2 -> GND
        s.power_at("GND", pull_x, OWT_PULL_ROW_Y - 400)

    # =====================================================================
    # Cluster G3: BIAS0/1 (right edge 28,29) — ports, no pull
    # =====================================================================
    # BIAS exits are kept SHORT (end at x=6800) so they do NOT span the VDDA2
    # tie corridor at x=6900 (see Cluster E). Ports sized smaller to fit.
    for pn, net in [("28", "BIAS0"), ("29", "BIAS1")]:
        px, py = U[pn]
        # End the exit at x=6500 so the port BODY (extends to 6800) stops short
        # of the VDDA2 tie corridor at x=6900 (a body reaching into it would be
        # impaled by the corridor wire — wire_through_port).
        s.wire(px, py, px + 100, py)            # -> x=6500
        s.port(net, px + 100, py, io=PortIOType.INPUT,
               style=PortStyle.LEFT_RIGHT, width_mils=300)

    # NC pins 21, 30 (right edge)
    for pn in ("21", "30"):
        px, py = U[pn]
        s.wire(px, py, px + 300, py)
        s.no_connect(px + 300, py)

    # =====================================================================
    # Cluster G4: CLK_OUT3/2/1/0 (top edge 31,32,35,36) — ports up
    # =====================================================================
    CLK = [
        ("31", "CLK_OUT3", CHIP_TOP_Y + 2600),
        ("32", "CLK_OUT2", CHIP_TOP_Y + 2200),
        ("35", "CLK_OUT1", CHIP_TOP_Y + 1800),
        ("36", "CLK_OUT0", CHIP_TOP_Y + 1400),
    ]
    CLK_PORT_X = CHIP_RIGHT_X + 1200   # 7600 right of chip body
    for pn, net, target_y in CLK:
        px, py = U[pn]
        s.wire(px, py, px, target_y)                 # up from pin
        s.wire(px, target_y, CLK_PORT_X, target_y)   # right to port
        s.port(net, CLK_PORT_X, target_y, io=PortIOType.OUTPUT, style=PortStyle.LEFT_RIGHT)

    # =====================================================================
    # Cluster G5: GPIO0-3 (top edge 37,38,39,40) + 10k pull-downs
    # =====================================================================
    # Each pin drops UP to its OWN row, exits LEFT to a port. CRITICAL (mirrors
    # the KiCad builder's anti-short rule): assign the LOWEST-x pin (40) to the
    # row CLOSEST to the chip and the highest-x pin (37) to the farthest row, and
    # make every GPIO horizontal span ONLY [port_x, pin_x]. Then a higher pin's
    # vertical drop (at larger x) never lands on a lower row's horizontal
    # (which ends at a smaller x). Pulls drop DOWN toward the chip in a column
    # strictly between the pin's x and the next-lower pin's x, so the pull
    # vertical clears every other GPIO row too.
    GPIO = [   # (pin, net, pull_ref, pull_x) — ordered LOW x (closest row) -> HIGH x
        ("40", "GPIO0", "R33", 4000),   # px=4100 -> closest row
        ("39", "GPIO1", "R32", 4200),   # px=4300
        ("38", "GPIO2", "R31", 4400),   # px=4500
        ("37", "GPIO3", "R30", 4600),   # px=4700 -> farthest row
    ]
    GPIO_PORT_X = CHIP_LEFT_X - 2400   # 1200 (left side)
    # All four pull-down bottoms collect onto ONE vertical GND rail (a clean comb)
    # ending in a SINGLE GND symbol, instead of four GND glyphs stepped down in a
    # ragged staircase (the user's "GND should be grounded neatly with the others"
    # note). The collector sits just right of the pull columns at x=4800 — a clean
    # gap between the GPIO3 pin drop (x=4700) and the CLK pin column (x=4900) — so
    # each R-bottom reaches it with a short east stub at its own row.
    GND_COLLECT_X = 4800
    pd_bottoms = []
    for i, (pn, net, pull_ref, pull_x) in enumerate(GPIO):
        px, py = U[pn]
        # Row pitch i*600 (was i*400): consecutive pull-down R bodies are 200 mil
        # apart in x and 600 in y -> ~632-mil diagonal gap, above cramped_cluster's
        # 300-mil floor. (Only the rows move further OUT; the GND drops still run
        # down each R's px-100 column, so the proven anti-short routing is intact.)
        row_y = CHIP_TOP_Y + 1400 + i * 600
        s.wire(px, py, px, row_y)                   # up to own row
        s.wire(px, row_y, GPIO_PORT_X, row_y)       # LEFT to port (span [1200, px])
        s.port(net, GPIO_PORT_X, row_y, io=PortIOType.OUTPUT, style=PortStyle.LEFT_RIGHT)
        # pull-down R30..R33: .1 on GPIO net (row side), .2 to the shared GND rail.
        # R orient0: pin1=top, pin2=bottom. Place R BELOW the row; pin1(top) taps
        # the row, pin2(bottom) routes EAST to the GND collector.
        R_CY = row_y - 400                          # R centre below the row
        place(pull_ref, pull_x, R_CY)
        Rp = s.pins_of(pull_ref, 1)  # 1=(pull_x,R_CY+100) ; 2=(pull_x,R_CY-100)
        s.wire(pull_x, row_y, pull_x, Rp["1"][1])           # row tap -> R.1(top)
        # R.2(bottom) drops a short vertical stub, then turns EAST to the GND
        # collector — both stubs parallel to the body, the turn clear of the pin.
        drop_y = Rp["2"][1] - 200
        s.wire(pull_x, Rp["2"][1], pull_x, drop_y)             # R.2(bot) down (vertical)
        s.wire(pull_x, drop_y, GND_COLLECT_X, drop_y)          # then east to collector
        pd_bottoms.append(drop_y)
    # Vertical GND collector tying all four R-bottoms, one GND symbol below the
    # lowest. Interior taps are T-intersections (auto-junctioned), same net.
    top_y, bot_y = max(pd_bottoms), min(pd_bottoms)
    s.wire(GND_COLLECT_X, top_y, GND_COLLECT_X, bot_y)
    for y in sorted(pd_bottoms)[1:-1]:
        s.junction(GND_COLLECT_X, y)
    gnd_y = bot_y - 300
    s.wire(GND_COLLECT_X, bot_y, GND_COLLECT_X, gnd_y)
    s.power_at("GND", GND_COLLECT_X, gnd_y)

    # Same strict validator as the KiCad backend.
    validate(s, nl)
    return s, nl


def main() -> int:
    s, _nl = build_centered(build_bobcat)
    out = s.save(OUT_DIR / "bobcat.SchDoc")
    svg = s.render_svg(RENDER_DIR / "bobcat.svg")
    print(f"validated OK | wrote {out.name} + {svg.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
