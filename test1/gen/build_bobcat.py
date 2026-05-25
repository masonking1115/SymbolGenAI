"""Bobcat child sheet — 40-QFN DUT plus decoupling, series-R isolators,
and the SPI/control pull network (layout only).

Parts inventory + nets live in netlist/bobcat.yaml. validate() at the end
of build_bobcat() confirms every YAML net is properly wired.

Clusters (functional, by supply domain + signal direction):
  A. Bobcat chip + GND EP
  B. VDDD decoupling (pins 12, 20) — per-pin caps, no horizontal rail
  C. VDDIO decoupling (pins 7, 13, 22, 33, 34) + 5×0.1µF row + 1µF bulk
  D. VDDA1 path (pin 1) — series 0Ω R20 + decoupling C22
  E. VDDA2 path (pins 26, 27) — series 0Ω R21 + decoupling C23
  F. SPI/control pull network — see gen.config / design_requirements.md
  G. SAMPLE_OUT* / CLK_OUT* / BIAS* / etc. label exits
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
    no_connect,
    place_from_netlist,
    power_at,
    wire,
)
from .validator import validate


def build_bobcat() -> Sheet:
    nl = load_netlist("bobcat")
    s = Sheet(name="bobcat", uuid=SHEET_UUIDS["bobcat"],
              page=PAGE_NUMBERS["bobcat"],
              title=f"{PROJECT_NAME} — Bobcat DUT")

    # Place Bobcat at (200, 130). Body local x ∈ [-20.32, 20.32], y ∈ [-20.32, 20.32]
    # (the chip rectangle), but pins extend to (±22.86). World body: x ∈ [179.68, 220.32].
    U1 = place_from_netlist(s, nl, "U20", x=200, y=130)

    # Pin 41 (GND, EP) at chip center (200, 130) — wire to GND symbol nearby
    s.add(wire(200, 130, 200, 144.78))
    power_at(s, "GND", 200, 144.78)

    # ===== Cluster B: VDDD decoupling =====
    # Pins 12 and 20 are both VDDD, on the chip's bottom edge.
    VDDD_PSYM_Y = 158.75   # just below chip body, above the cap
    VDDD_CAP_Y  = 167.64   # cap center
    GND_BELOW_Y = 178.0    # GND symbol below cap
    for ref, pn in [("C20", "12"), ("C21", "20")]:
        px, py = U1[pn]
        s.add(wire(px, py, px, VDDD_PSYM_Y))
        power_at(s, "+VDDD", px, VDDD_PSYM_Y)
        s.add(wire(px, VDDD_PSYM_Y, px, VDDD_CAP_Y - 3.81))
        place_from_netlist(s, nl, ref, x=px, y=VDDD_CAP_Y)
        s.add(wire(px, VDDD_CAP_Y + 3.81, px, GND_BELOW_Y))
        power_at(s, "GND", px, GND_BELOW_Y)

    # ===== Cluster D: VDDA1 path (pin 1) =====
    # Chip pins 2–11 exit LEFT along x = p1_x → p1_x - 12.7, crossing the
    # x = p1_x - 3.81 column. C22 must NOT sit in that column — place it
    # HORIZONTAL above pin 1's row instead, where the SAMPLE_OUT lanes are clear.
    p1_x, p1_y = U1["1"]
    place_from_netlist(s, nl, "R20", x=p1_x - 7.62, y=p1_y, angle=90)
    # R20 angle 90 horizontal: pin 1 (chip side) at (p1_x - 3.81, p1_y);
    # pin 2 (rail side) at (p1_x - 11.43, p1_y).
    s.add(wire(p1_x, p1_y, p1_x - 3.81, p1_y))
    s.add(wire(p1_x - 11.43, p1_y, p1_x - 17.78, p1_y))
    power_at(s, "+VDDA1", p1_x - 17.78, p1_y, angle=270)
    # VDDA1 decoupling: horizontal C22 above pin 1's row, clear of SAMPLE_OUT
    # exits. Right pin → vertical down to R20 chip-side; left pin → GND left.
    C22_LANE_Y = p1_y - 7.62
    place_from_netlist(s, nl, "C22", x=p1_x - 7.62, y=C22_LANE_Y, angle=90)
    s.add(wire(p1_x - 3.81, C22_LANE_Y, p1_x - 3.81, p1_y))           # cap right → R20.1
    s.add(wire(p1_x - 11.43, C22_LANE_Y, p1_x - 17.78, C22_LANE_Y))   # cap left → GND
    power_at(s, "GND", p1_x - 17.78, C22_LANE_Y, angle=270)

    # ===== Cluster E: VDDA2 path (pins 26, 27) =====
    p26_x, p26_y = U1["26"]
    p27_x, p27_y = U1["27"]
    TIE_X = p26_x + 5.08
    s.add(wire(p26_x, p26_y, TIE_X, p26_y))
    s.add(wire(p27_x, p27_y, TIE_X, p27_y))
    s.add(wire(TIE_X, p26_y, TIE_X, p27_y))           # vertical tie 26↔27
    mid_y = (p26_y + p27_y) / 2

    R6_Y = mid_y + 12.7
    s.add(wire(TIE_X, p26_y, TIE_X, R6_Y))            # drop from tie down to R6 lane
    place_from_netlist(s, nl, "R21", x=p26_x + 13.97, y=R6_Y, angle=90)
    s.add(wire(TIE_X, R6_Y, p26_x + 13.97 - 3.81, R6_Y))
    s.add(wire(p26_x + 13.97 + 3.81, R6_Y, p26_x + 25.4, R6_Y))
    power_at(s, "+VDDA2", p26_x + 25.4, R6_Y, angle=90)

    # Decoupling cap C23: chip-side of R21 (on the TIE_X column), placed BELOW
    # the R21 lane so the cap body sits on its own branch.
    C4_Y = R6_Y + 12.7
    place_from_netlist(s, nl, "C23", x=TIE_X, y=C4_Y)
    s.add(junction(TIE_X, R6_Y))                       # branch point at R6 lane
    s.add(wire(TIE_X, R6_Y, TIE_X, C4_Y - 3.81))       # tie → C23 top
    s.add(wire(TIE_X, C4_Y + 3.81, TIE_X, C4_Y + 7.62))  # C23 bot → GND
    power_at(s, "GND", TIE_X, C4_Y + 7.62)

    # ===== Cluster C: VDDIO decoupling =====
    for pn in ("7", "13", "22", "33", "34"):
        px, py = U1[pn]
        if pn == "7":     # left edge
            s.add(wire(px, py, px - 7.62, py))
            power_at(s, "+VDDIO", px - 7.62, py, angle=270)
        elif pn == "22":  # right edge (mid)
            s.add(wire(px, py, px + 7.62, py))
            power_at(s, "+VDDIO", px + 7.62, py, angle=90)
        elif pn == "13":  # bottom edge
            s.add(wire(px, py, px, py + 7.62))
            power_at(s, "+VDDIO", px, py + 7.62)
        else:             # 33, 34 — top edge
            s.add(wire(px, py, px, py - 5.08))
            power_at(s, "+VDDIO", px, py - 5.08, angle=90)
    # VDDIO cap row (5×0.1µF + 1×1µF; W2)
    for i, ref in enumerate(["C24", "C25", "C26", "C27", "C28"]):
        cx = 165.1 - i*5.08
        cy = 100
        place_from_netlist(s, nl, ref, x=cx, y=cy)
        s.add(wire(cx, cy - 3.81, cx, cy - 7.62))
        power_at(s, "+VDDIO", cx, cy - 7.62, angle=90)
        s.add(wire(cx, cy + 3.81, cx, cy + 7.62))
        power_at(s, "GND", cx, cy + 7.62)

    # ===== Cluster F: Pull-up/down network =====
    SPI_PINS = [
        # (pin, net, direction, pull_type, pull_ref, pull_x_offset)
        # pull_x_offset for pin 14 is 15.24 (not 12.7) to avoid landing the
        # R22 pull column on pin 19's x — pin 14 at x=196.19 with offset 12.7
        # yields 208.89 which exactly matches pin 19, silently shorting MOSI
        # GND drop to RESET_N drop.
        ("14", "MOSI",      "input",  "down", "R22", 15.24),
        ("15", "MISO",      "output", None,   None,  0.0),
        ("16", "SCLK",      "input",  "down", "R23", 17.78),
        ("17", "CS_L",      "input",  "up",   "R24", 22.86),
        ("18", "SPI_DMODE", "input",  "down", "R25", 27.94),
        ("19", "RESET_N",   "input",  "up",   "R26", 33.02),
    ]
    SPI_LABEL_Y_START = 185.42
    SPI_LABEL_Y_STEP  = 10.16
    for i, (pn, net, direction, pull_type, pull_ref, pull_xoff) in enumerate(SPI_PINS):
        px, py = U1[pn]
        label_y = SPI_LABEL_Y_START + i * SPI_LABEL_Y_STEP
        s.add(wire(px, py, px, label_y))
        s.add(global_label(net, direction, px, label_y, angle=270, justify="left"))
        if pull_type is None:
            continue
        tap_y = label_y - 2.54
        pull_x = px + pull_xoff
        s.add(junction(px, tap_y))
        s.add(wire(px, tap_y, pull_x, tap_y))
        if pull_type == "down":
            place_from_netlist(s, nl, pull_ref, x=pull_x, y=tap_y + 3.81)
            s.add(wire(pull_x, tap_y + 7.62, pull_x, tap_y + 12.7))
            power_at(s, "GND", pull_x, tap_y + 12.7)
        else:  # "up" — pull-up to +VDDIO (CS_L, RESET_N)
            place_from_netlist(s, nl, pull_ref, x=pull_x, y=tap_y - 3.81)
            s.add(wire(pull_x, tap_y - 7.62, pull_x, tap_y - 12.7))
            power_at(s, "+VDDIO", pull_x, tap_y - 12.7, angle=90)

    # SAMPLE_OUT* on left edge
    for pn, net in [("2", "SAMPLE_OUTV"), ("3", "SAMPLE_OUT0"), ("4", "SAMPLE_OUT1"),
                     ("5", "SAMPLE_OUT2"), ("6", "SAMPLE_OUT3"), ("8", "SAMPLE_OUT4"),
                     ("9", "SAMPLE_OUT5"), ("10", "SAMPLE_OUT6"), ("11", "SAMPLE_OUT7")]:
        px, py = U1[pn]
        if pn == "11":   # bottom edge pin
            s.add(wire(px, py, px, py + 10.16))
            s.add(global_label(net, "output", px, py + 10.16, angle=270))
        else:            # left edge
            s.add(wire(px, py, px - 12.7, py))
            s.add(global_label(net, "output", px - 12.7, py, angle=180, justify="right"))

    # Right-edge OSC_EN/WEIGHT_EN/SAMPLE_TRIG with 10kΩ pull-downs (E3).
    # CRITICAL: each chip pin gets its OWN vertical drop column. A previous
    # version stacked the three pulls in one column at x=252, which caused
    # the longer drop wires (pin 24/25) to pass through R27/R28's pin coords —
    # silently shorting OSC_EN/WEIGHT_EN/SAMPLE_TRIG/GND together. The
    # validator missed the short because each net's name was still present
    # in the bridged component's name set. See [[layout-rule-pin-protrusion]].
    OWT_PULL_ROW_Y = 160.0   # below chip body (body bottom ≈ 150.32)
    OWT_LABEL_X    = 235.56  # x of global_label, just right of chip pin
    OWT_PULLS = [
        # (chip pin, net, pull R refdes, R column x)
        ("23", "OSC_EN",      "R27", 252.0),
        ("24", "WEIGHT_EN",   "R28", 262.0),
        ("25", "SAMPLE_TRIG", "R29", 272.0),
    ]
    for pn, net, pull_ref, pull_x in OWT_PULLS:
        px, py = U1[pn]
        s.add(wire(px, py, OWT_LABEL_X, py))                          # chip pin → label
        s.add(global_label(net, "output", OWT_LABEL_X, py, angle=0))
        s.add(wire(OWT_LABEL_X, py, pull_x, py))                      # label → pull column
        place_from_netlist(s, nl, pull_ref, x=pull_x, y=OWT_PULL_ROW_Y)
        s.add(wire(pull_x, py, pull_x, OWT_PULL_ROW_Y - 3.81))        # drop down to R top
        s.add(wire(pull_x, OWT_PULL_ROW_Y + 3.81,
                   pull_x, OWT_PULL_ROW_Y + 8.89))                    # R bot → GND
        power_at(s, "GND", pull_x, OWT_PULL_ROW_Y + 8.89)

    # BIAS0/1 — hier_label, no pull
    for pn, net in [("28", "BIAS0"), ("29", "BIAS1")]:
        px, py = U1[pn]
        s.add(wire(px, py, px + 12.7, py))
        s.add(hier_label(net, "input", px + 12.7, py, angle=0))
    # NC pins 21, 30
    for pn in ("21", "30"):
        px, py = U1[pn]
        s.add(no_connect(px, py))

    # Top-edge pins: CLK_OUT3/2/1/0 (no pull)
    for pn, net in [("31", "CLK_OUT3"), ("32", "CLK_OUT2"),
                     ("35", "CLK_OUT1"), ("36", "CLK_OUT0")]:
        px, py = U1[pn]
        target_y = py - 25.4
        s.add(wire(px, py, px, target_y))
        s.add(hier_label(net, "output", px, target_y, angle=90, justify="left"))

    # GPIO0–3 with 10kΩ pull-downs. CRITICAL: each pin's horizontal must be at
    # its OWN y. A prior version ran all four horizontals at y=75, sharing the
    # same line — KiCad merged them into one net, silently shorting GPIO0/1/2/3
    # together. Pin x decreases 37→40 (right-to-left) and pull_x increases
    # 244→274.48, so the leftmost pin (40) must take the topmost row for each
    # vertical drop to land in its own row only (see skill rule 5).
    GPIO_PULLS = [
        # (chip pin, net, pull R refdes, R column x, horizontal row y)
        ("37", "GPIO3", "R30", 244.0,  80.0),   # rightmost pin → bottommost row
        ("38", "GPIO2", "R31", 254.16, 75.0),
        ("39", "GPIO1", "R32", 264.32, 70.0),
        ("40", "GPIO0", "R33", 274.48, 65.0),   # leftmost pin → topmost row
    ]
    for pn, net, pull_ref, pull_x, row_y in GPIO_PULLS:
        px, py = U1[pn]
        target_y = py - 25.4
        s.add(wire(px, py, px, row_y))                                # drop to own row
        s.add(hier_label(net, "output", px, target_y, angle=90, justify="left"))
        s.add(wire(px, row_y, pull_x, row_y))                         # horizontal to pull
        place_from_netlist(s, nl, pull_ref, x=pull_x, y=row_y + 3.81)
        s.add(wire(pull_x, row_y + 7.62, pull_x, row_y + 12.7))
        power_at(s, "GND", pull_x, row_y + 12.7)

    validate(s, nl)
    return s
