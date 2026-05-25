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
    p1_x, p1_y = U1["1"]
    place_from_netlist(s, nl, "R20", x=p1_x - 7.62, y=p1_y, angle=90)
    # R20 angle 90 horizontal: pin 1 (chip side) at (p1_x - 3.81, p1_y);
    # pin 2 (rail side) at (p1_x - 11.43, p1_y).
    s.add(wire(p1_x, p1_y, p1_x - 3.81, p1_y))
    s.add(wire(p1_x - 11.43, p1_y, p1_x - 17.78, p1_y))
    power_at(s, "+VDDA1", p1_x - 17.78, p1_y, angle=270)
    # VDDA1 decoupling at the chip side (after series R)
    place_from_netlist(s, nl, "C22", x=p1_x - 3.81, y=p1_y + 7.62)
    s.add(wire(p1_x - 3.81, p1_y + 3.81, p1_x - 3.81, p1_y))
    s.add(junction(p1_x - 3.81, p1_y))
    s.add(wire(p1_x - 3.81, p1_y + 11.43, p1_x - 3.81, p1_y + 17.78))
    power_at(s, "GND", p1_x - 3.81, p1_y + 17.78)

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
        ("14", "MOSI",      "input",  "down", "R22", 12.7),
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

    # Right-edge OSC_EN/WEIGHT_EN/SAMPLE_TRIG with 10kΩ pull-downs (E3) in
    # pull-bank column.
    OWT_PULL_BANK_X = 252.0
    OWT_PULLS = [
        ("23", "OSC_EN",      "R27", 215.0),
        ("24", "WEIGHT_EN",   "R28", 225.16),
        ("25", "SAMPLE_TRIG", "R29", 235.32),
    ]
    for pn, net, pull_ref, pull_y in OWT_PULLS:
        px, py = U1[pn]
        s.add(wire(px, py, px + 12.7, py))
        s.add(global_label(net, "output", px + 12.7, py, angle=0))
        s.add(wire(px + 12.7, py, OWT_PULL_BANK_X, py))
        s.add(wire(OWT_PULL_BANK_X, py, OWT_PULL_BANK_X, pull_y))
        place_from_netlist(s, nl, pull_ref, x=OWT_PULL_BANK_X, y=pull_y + 3.81)
        s.add(wire(OWT_PULL_BANK_X, pull_y + 7.62, OWT_PULL_BANK_X, pull_y + 12.7))
        power_at(s, "GND", OWT_PULL_BANK_X, pull_y + 12.7)

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

    # GPIO0–3 with 10kΩ pull-downs in pull-row at y=75
    GPIO_PULL_ROW_Y = 75.0
    GPIO_PULLS = [
        ("37", "GPIO3", "R30", 244.0),
        ("38", "GPIO2", "R31", 254.16),
        ("39", "GPIO1", "R32", 264.32),
        ("40", "GPIO0", "R33", 274.48),
    ]
    for pn, net, pull_ref, pull_x in GPIO_PULLS:
        px, py = U1[pn]
        target_y = py - 25.4
        s.add(wire(px, py, px, GPIO_PULL_ROW_Y))
        s.add(hier_label(net, "output", px, target_y, angle=90, justify="left"))
        s.add(wire(px, GPIO_PULL_ROW_Y, pull_x, GPIO_PULL_ROW_Y))
        place_from_netlist(s, nl, pull_ref, x=pull_x, y=GPIO_PULL_ROW_Y + 3.81)
        s.add(wire(pull_x, GPIO_PULL_ROW_Y + 7.62, pull_x, GPIO_PULL_ROW_Y + 12.7))
        power_at(s, "GND", pull_x, GPIO_PULL_ROW_Y + 12.7)

    validate(s, nl)
    return s
