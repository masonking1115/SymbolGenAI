"""Connectors sheet — Altium port of gen/build_connectors.py.

Same declarative source of truth (netlist/connectors.yaml, loaded via the
SHARED gen.netlist loader) and the SAME strict validator (gen.validator.validate)
— only the layout backend changes from KiCad s-expr to Altium binary.

Clusters:
  A. CLK_OUT0–3 SMAs (J50–J53), vertical stack on the left.
  B. OSC_EN / WEIGHT_EN / SAMPLE_TRIG SMAs (J54–J56) — SMA-side 0Ω (R50–R52)
     in-line, depop to switch routing to the FMC LA-bank path.
  C. GPIO 1×4 header (J57).
  D. GND test clips (TP50–TP52).

Coordinate notes (all mils, 100-mil grid, Y grows UP):
  - SMA (HRM-G-300-467B-1) orient=0 → pin 1 hot-spot at place_x + 500.
  - Resistor (Device:R) orient=0 → pin 1 at y+100 (top), pin 2 at y−100 (bottom).
  - Resistor orient=3 → pin 1 at x+100 (right), pin 2 at x−100 (left).
  - TSW-104-05-G-S orient=0 → pins (1,2) at (x−100,y+500)/(x+100,y+500) top;
                                     (3,4) at (x−100,y−500)/(x+100,y−500) bottom.
  - Keystone-5011 orient=0 → pin 1 at place_x + 500.
"""

from __future__ import annotations

from ..gen.netlist import load_netlist
from ..gen.validator import validate
from .build_symbols import get_library
from .config import OUT_DIR, RENDER_DIR
from .shared import AltiumSheet

GRID = 100  # mil

# ---------------------------------------------------------------------------
# Layout constants (all mils)
# ---------------------------------------------------------------------------

# Cluster A: CLK_OUT0–3 SMAs (J50–J53)  — left column
A_SMA_X   = 3000    # SMA body placement x; pin 1 hot-spot at A_SMA_X + 500
A_PORT_X  = 2200    # port anchor x (left of SMA)
A_ROW_Y   = [9000, 10000, 11000, 12000]   # y rows for CLK_OUT0..3

# Cluster B: OSC/WEIGHT/TRIG SMAs (J54–J56) + 0Ω (R50–R52) — centre column
B_SMA_X   = 8000    # SMA body placement x; pin 1 at B_SMA_X + 500
B_RES_X   = 6400    # R body x (orient=3 → pin1 at x+100, pin2 at x−100)
B_PORT_X  = 5600    # port anchor x
B_ROW_Y   = [9000, 10000, 11000]           # y rows for OSC_EN/WEIGHT_EN/SAMPLE_TRIG

# Cluster C: GPIO 1×4 header (J57)
C_HDR_X   = 12000
C_HDR_Y   = 9500    # centre; pins 1/2 at y+500, pins 3/4 at y−500
C_PORT_X  = 10800

# Cluster D: GND test clips (TP50–TP52)
D_ROW_Y   = 2000
D_CLIP_X  = [1000, 3000, 5000]   # placement x; pin 1 at x+500


def build_connectors() -> tuple[AltiumSheet, object]:
    nl = load_netlist("connectors")
    lib, lmap = get_library()
    # A2: the breakout banks (CLK_OUT/SAMPLE_TRIG ports + J5x bodies) extend to
    # X~17438 / Y~13595, ~900 / ~1900 mil past A3. A2 (23390x16535) frames it
    # cleanly without repositioning dozens of placed parts.
    s = AltiumSheet(name="connectors",
                    title="test1 — Connectors / Breakouts",
                    paper="A2")

    def place(ref, x, y, orientation=0):
        return s.place_from_netlist(lib, lmap, nl, ref, x, y,
                                    orientation=orientation)

    # -----------------------------------------------------------------------
    # Cluster A: CLK_OUT0–3 SMAs (J50–J53)
    # Each SMA pin 1 (the signal pin) exits LEFT to a hier port.
    # -----------------------------------------------------------------------
    clk_nets = ("CLK_OUT0", "CLK_OUT1", "CLK_OUT2", "CLK_OUT3")
    for i, net in enumerate(clk_nets):
        ref = f"J{50 + i}"
        y = A_ROW_Y[i]
        pins = place(ref, A_SMA_X, y)          # pin 1 → (A_SMA_X+500, y)
        pin1 = pins["1"]                        # (3500, y)
        # Wire from SMA pin outward right then back is unnecessary — the body
        # already faces right; instead just route left from pin1 to the port.
        # Because the SMA body pin exits to the RIGHT (x+500), we draw the wire
        # leftward from that hot-spot to the port column.
        s.wire(pin1[0], pin1[1], A_PORT_X, y)
        s.port(net, A_PORT_X, y)

    # -----------------------------------------------------------------------
    # Cluster B: OSC_EN / WEIGHT_EN / SAMPLE_TRIG
    #   J54–J56  (SMA) and R50–R52 (0Ω in-line)
    #
    # Net topology per signal:
    #   [port/global-label]—wire—R.pin2(left)   R.pin1(right)—wire—J.pin1—[SMA body]
    #                                             ^unnamed internal stub^
    #
    # R orient=3 (270°): pin1 at x+100 (right, SMA-side), pin2 at x−100 (left, label-side)
    # -----------------------------------------------------------------------
    b_nets = ("OSC_EN", "WEIGHT_EN", "SAMPLE_TRIG")
    b_refs_r = ("R50", "R51", "R52")
    b_refs_j = ("J54", "J55", "J56")
    for i, (net, r_ref, j_ref) in enumerate(zip(b_nets, b_refs_r, b_refs_j)):
        y = B_ROW_Y[i]
        # Place 0Ω resistor (horizontal, orient=3)
        # pin1=(B_RES_X+100, y) → SMA side (unnamed internal stub net)
        # pin2=(B_RES_X−100, y) → labeled net (OSC_EN / WEIGHT_EN / SAMPLE_TRIG)
        R = place(r_ref, B_RES_X, y, orientation=3)
        r_pin1 = R["1"]   # (6500, y)
        r_pin2 = R["2"]   # (6300, y)

        # Place SMA (orient=0) → pin1 at B_SMA_X+500
        J = place(j_ref, B_SMA_X, y)
        j_pin1 = J["1"]   # (8500, y)

        # Wire: R.pin2 (left, labeled side) ←→ port
        s.wire(r_pin2[0], r_pin2[1], B_PORT_X, y)
        s.port(net, B_PORT_X, y)

        # Wire: SMA.pin1 → R.pin1 (internal stub, no label needed)
        s.wire(j_pin1[0], j_pin1[1], r_pin1[0], r_pin1[1])

    # -----------------------------------------------------------------------
    # Cluster C: GPIO 1×4 header (J57)
    # J57 orient=0:
    #   pin 1 → (C_HDR_X−100, C_HDR_Y+500)
    #   pin 2 → (C_HDR_X+100, C_HDR_Y+500)
    #   pin 3 → (C_HDR_X−100, C_HDR_Y−500)
    #   pin 4 → (C_HDR_X+100, C_HDR_Y−500)
    # Route each pin to a distinct port row via L-shaped wires, staggering
    # x-offsets to avoid 4-way crossings.
    # -----------------------------------------------------------------------
    J57 = place("J57", C_HDR_X, C_HDR_Y)
    # J57 pins are a clean 1x4 column (pin1..4 at x=11500, y=9800/9600/9400/9200,
    # 200 mil apart). Route each pin straight LEFT to its own port row so the
    # four GPIO port labels never share a row (the old jog put GPIO1 on top of
    # GPIO0). All wires are parallel horizontals -> no crossings.
    for i, net in enumerate(("GPIO0", "GPIO1", "GPIO2", "GPIO3")):
        px, py = J57[str(i + 1)]
        s.wire(px, py, C_PORT_X, py)
        s.port(net, C_PORT_X, py)

    # -----------------------------------------------------------------------
    # Cluster D: GND test clips (TP50–TP52)
    # Keystone-5011 orient=0 → pin 1 at place_x + 500.
    # Route a short downward stub from pin1 to a GND power symbol.
    # -----------------------------------------------------------------------
    GND_STUB = 200   # mil below pin
    for i in range(3):
        ref = f"TP{50 + i}"
        x = D_CLIP_X[i]
        pins = place(ref, x, D_ROW_Y)
        pin1 = pins["1"]   # (x+500, D_ROW_Y)
        gnd_y = pin1[1] - GND_STUB
        s.wire(pin1[0], pin1[1], pin1[0], gnd_y)
        s.power_at("GND", pin1[0], gnd_y)

    # Same strict validator as the KiCad backend — true functional parity.
    validate(s, nl)
    return s, nl


def main() -> int:
    s, _nl = build_connectors()
    out = s.save(OUT_DIR / "connectors.SchDoc")
    svg = s.render_svg(RENDER_DIR / "connectors.svg")
    print(f"validated OK | wrote {out.name} + {svg.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
