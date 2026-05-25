"""Connectors child sheet — SMAs (CLK_OUT* + OSC/WEIGHT/TRIG), GPIO header,
GND clips.

Phase B: parts inventory + nets are in netlist/connectors.yaml. This file
owns layout only (positions + wire routing). validate() runs at the end.

Clusters:
  A. CLK_OUT0–3 SMAs (J50–J53), arranged vertically on the left.
  B. OSC_EN / WEIGHT_EN / SAMPLE_TRIG SMAs (J54–J56) — SMA-side 0Ω (R50–R52)
     in-line, depop to switch routing to the FMC LA-bank path.
  C. GPIO 1×4 header (J57).
  D. GND test clips (TP50–TP52).
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
    place_from_netlist,
    power_at,
    wire,
)
from .validator import validate


def build_connectors() -> Sheet:
    nl = load_netlist("connectors")
    s = Sheet(name="connectors", uuid=SHEET_UUIDS["connectors"],
              page=PAGE_NUMBERS["connectors"],
              title=f"{PROJECT_NAME} — Connectors / Breakouts")

    # Cluster A: CLK_OUT0–3 SMAs (J50–J53), arranged vertically on the left.
    for i, net in enumerate(("CLK_OUT0", "CLK_OUT1", "CLK_OUT2", "CLK_OUT3")):
        ref = f"J{i+50}"
        sy = 100 + i*15.24
        place_from_netlist(s, nl, ref, x=100, y=sy)
        s.add(wire(100, sy, 92.71, sy))
        s.add(hier_label(net, "input", 92.71, sy, angle=180, justify="right"))

    # Cluster B: OSC_EN / WEIGHT_EN / SAMPLE_TRIG SMAs (J54–J56) — center column.
    # Multi-destination: Bobcat → SMA (via 0Ω here) AND Bobcat → FMC LA (via
    # 0Ω on FMC sheet). Each route is independently populatable — populate the
    # SMA-side 0Ω (R50-R52, default) for manual signal injection via SMA, or
    # depop and populate the FMC-side 0Ω to route from the FPGA (E2 fix).
    for i, net in enumerate(("OSC_EN", "WEIGHT_EN", "SAMPLE_TRIG")):
        j_ref = f"J{i+54}"
        r_ref = f"R{50+i}"
        sy = 100 + i*15.24
        place_from_netlist(s, nl, j_ref, x=165, y=sy)
        place_from_netlist(s, nl, r_ref, x=160, y=sy, angle=90)
        s.add(wire(165, sy, 163.81, sy))   # SMA pin → R pin1 (right)
        s.add(wire(156.19, sy, 150, sy))   # R pin2 (left) → label
        s.add(global_label(net, "input", 150, sy, angle=180, justify="right"))

    # Cluster C: GPIO 1×4 header (J57). Pin 1 = GPIO0, ..., Pin 4 = GPIO3.
    GPIO_HDR_X, GPIO_HDR_Y = 230, 100
    place_from_netlist(s, nl, "J57", x=GPIO_HDR_X, y=GPIO_HDR_Y)
    for i, net in enumerate(("GPIO0", "GPIO1", "GPIO2", "GPIO3")):
        py = GPIO_HDR_Y + i*2.54
        s.add(wire(GPIO_HDR_X, py, GPIO_HDR_X - 7.29, py))
        s.add(hier_label(net, "input", GPIO_HDR_X - 7.29, py, angle=180, justify="right"))

    # Cluster D: 3× GND test clips (Keystone-5011) — TP50–TP52.
    for i in range(3):
        ref = f"TP{i+50}"
        place_from_netlist(s, nl, ref, x=100 + i*30, y=175)
        power_at(s, "GND", 100 + i*30, 175)

    validate(s, nl)
    return s
