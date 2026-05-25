"""Bias child sheet — MCP4728 quad I²C DAC + 2× V-to-I bias channel.

Parts inventory + nets live in netlist/bias.yaml. validate() runs at the
end. U41 (OPA2388) is dual op-amp — `place_from_netlist(..., unit=1)` for
channel 0, `unit=2` for channel 1.
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


def build_bias() -> Sheet:
    nl = load_netlist("bias")
    s = Sheet(name="bias", uuid=SHEET_UUIDS["bias"],
              page=PAGE_NUMBERS["bias"],
              title=f"{PROJECT_NAME} — Bias Generators")

    GND_Y = 200.66

    # ===== Cluster A: MCP4728 DAC =====
    # Body: x ∈ [80, 151.12], y ∈ [80, 90.16].
    # Pin world (angle 0):
    #   1 VDD   (80, 80)        6 VOUTA (151.12, 90.16)
    #   2 SCL   (80, 82.54)     7 VOUTB (151.12, 87.62)
    #   3 SDA   (80, 85.08)     8 VOUTC (151.12, 85.08)
    #   4 *LDAC (80, 87.62)     9 VOUTD (151.12, 82.54)
    #   5 RDY*  (80, 90.16)    10 VSS   (151.12, 80)
    U1 = place_from_netlist(s, nl, "U40", x=80, y=80)

    # I²C in (left side) — SCL/SDA serve 3 sheets, so global_label.
    for pn, net in [("2", "SCL"), ("3", "SDA")]:
        px, py = U1[pn]
        s.add(wire(px, py, 67.31, py))
        s.add(global_label(net, "bidirectional", 67.31, py, angle=180, justify="right"))

    # *LDAC (4) — tie to GND for transparent latching
    s.add(wire(U1["4"][0], U1["4"][1], 67.31, U1["4"][1]))
    power_at(s, "GND", 67.31, U1["4"][1], angle=270)

    # RDY/*BSY (5) — leave NC
    s.add(no_connect(U1["5"][0], U1["5"][1]))

    # VDD (1) → +3V3
    s.add(wire(U1["1"][0], U1["1"][1], 75.18, U1["1"][1]))
    s.add(wire(75.18, U1["1"][1], 75.18, 67.31))
    power_at(s, "+3V3", 75.18, 67.31)

    # VSS (10) → GND
    s.add(wire(U1["10"][0], U1["10"][1], 158.75, U1["10"][1]))
    s.add(wire(158.75, U1["10"][1], 158.75, GND_Y))
    power_at(s, "GND", 158.75, GND_Y)

    # VOUTC, VOUTD unused — NC
    s.add(no_connect(U1["8"][0], U1["8"][1]))
    s.add(no_connect(U1["9"][0], U1["9"][1]))

    # MCP4728 decoupling
    DECAP_X1 = 55.88
    place_from_netlist(s, nl, "C40", x=DECAP_X1, y=80)
    s.add(wire(DECAP_X1, 76.19, DECAP_X1, 67.31))
    s.add(wire(DECAP_X1, 67.31, 75.18, 67.31))
    s.add(junction(75.18, 67.31))
    s.add(wire(DECAP_X1, 83.81, DECAP_X1, GND_Y))
    power_at(s, "GND", DECAP_X1, GND_Y)

    # ===== Bias channel builder — used twice (BIAS0, BIAS1) =====
    def bias_channel(ch_idx: int, x0: float, dac_pin: str, out_net: str,
                     opa_ref: str, pmos_ref: str, sense_ref: str,
                     nmos_ref: str, cap_ref: str,
                     par_jumper_ref: str, iso_pulldown_ref: str) -> None:
        """Place one bias channel."""
        opa_unit = ch_idx + 1  # ch0 → unit 1, ch1 → unit 2
        OPA = place_from_netlist(s, nl, opa_ref, x=x0 + 25, y=110, unit=opa_unit)
        in_pin  = "3" if opa_unit == 1 else "5"
        neg_pin = "2" if opa_unit == 1 else "6"
        out_pin = "1" if opa_unit == 1 else "7"

        # +IN ← DAC VOUTx
        dac_x, dac_y = U1[dac_pin]
        in_x, in_y = OPA[in_pin]
        s.add(wire(dac_x, dac_y, x0 + 5.08, dac_y))
        s.add(wire(x0 + 5.08, dac_y, x0 + 5.08, in_y))
        s.add(wire(x0 + 5.08, in_y, in_x, in_y))

        # PMOS gate ← OPA out
        Q = place_from_netlist(s, nl, pmos_ref, x=x0 + 50, y=110)
        gate_x, gate_y = Q["1"]
        src_x, src_y = Q["2"]
        drn_x, drn_y = Q["3"]
        out_x, out_y = OPA[out_pin]
        s.add(wire(out_x, out_y, gate_x, out_y))
        if out_y != gate_y:
            s.add(wire(gate_x, out_y, gate_x, gate_y))

        # PMOS source → +3V3 via sense R. The PMZ1200UPEYL has source AND drain
        # on the SAME vertical (local x=7.62), so a direct vertical wire from
        # source up to R.bot would pass through drain → silent short. Detour
        # east of the body, then north, then back west to R.bot.
        # R is also pushed up to y=95 (was 100) to give bbox spacing vs Q.
        R_SENSE_Y = 95
        R_TOP_Y = R_SENSE_Y - 3.81
        R_BOT_Y = R_SENSE_Y + 3.81
        # Detour x must fit BETWEEN the drain detour column (src_x + 2.54) and
        # the NMOS-gate-to-BIAS_ISO-label horizontal which starts at
        # nm_g[0] - 7.62 = src_x + 4.76. Using src_x + 3.81 (half-grid) clears
        # both — drain south at +2.54, gate-label wire from +4.76 rightward.
        SRC_DETOUR_X = src_x + 3.81
        place_from_netlist(s, nl, sense_ref, x=src_x, y=R_SENSE_Y)
        # Source → R.bot via east-north-west detour around Q body
        s.add(wire(src_x, src_y, SRC_DETOUR_X, src_y))
        s.add(wire(SRC_DETOUR_X, src_y, SRC_DETOUR_X, R_BOT_Y))
        s.add(wire(SRC_DETOUR_X, R_BOT_Y, src_x, R_BOT_Y))
        # R.top → +3V3 (straight up)
        s.add(wire(src_x, R_TOP_Y, src_x, R_TOP_Y - 5))
        power_at(s, "+3V3", src_x, R_TOP_Y - 5)

        # OPA -IN feedback from PMOS source
        neg_x, neg_y = OPA[neg_pin]
        s.add(wire(neg_x, neg_y, neg_x, src_y + 7.62))
        s.add(wire(neg_x, src_y + 7.62, src_x, src_y + 7.62))
        s.add(wire(src_x, src_y + 7.62, src_x, src_y))
        s.add(junction(src_x, src_y))

        # PMOS drain → 2N7002 → BIASx hier_label (with parallel 0Ω jumper).
        # Drain is on the same vertical as source — a direct south wire from
        # drain crosses the Q body. Detour east-then-south-then-east to clear.
        # Drain detour x sits BETWEEN the body edge and the source detour so
        # the two detours don't co-occupy a column (which would re-short them).
        nmos_x = x0 + 70
        nmos_y = drn_y + 10.16
        NM = place_from_netlist(s, nl, nmos_ref, x=nmos_x, y=nmos_y)
        nm_g = NM["1"]; nm_s = NM["2"]; nm_d = NM["3"]
        DRN_DETOUR_X = drn_x + 2.54     # closer to body than SRC_DETOUR_X (5.08)
        s.add(wire(drn_x, drn_y, DRN_DETOUR_X, drn_y))
        s.add(wire(DRN_DETOUR_X, drn_y, DRN_DETOUR_X, nm_d[1]))
        s.add(wire(DRN_DETOUR_X, nm_d[1], nm_d[0], nm_d[1]))
        # Parallel 0Ω jumper across NMOS D-S. The hier_label exits PAST the
        # jumper at (par_x + 5.08, nm_s.y) so the source-side horizontal isn't
        # drawn twice (jumper tap and label-stub previously overlapped).
        par_x = nmos_x + 15.24
        place_from_netlist(s, nl, par_jumper_ref, x=par_x, y=nmos_y)
        s.add(junction(nm_d[0], nm_d[1]))
        s.add(wire(nm_d[0], nm_d[1], par_x, nm_d[1]))
        s.add(wire(par_x, nm_d[1], par_x, nmos_y - 3.81))
        s.add(junction(nm_s[0], nm_s[1]))
        s.add(wire(nm_s[0], nm_s[1], par_x, nm_s[1]))
        s.add(wire(par_x, nm_s[1], par_x, nmos_y + 3.81))
        # BIASx hier_label exits right of the jumper column. 3 wires meet at
        # (par_x, nm_s.y): nm_s-stub, vertical-down to R42, horizontal to label.
        s.add(junction(par_x, nm_s[1]))
        s.add(wire(par_x, nm_s[1], par_x + 5.08, nm_s[1]))
        s.add(hier_label(out_net, "output", par_x + 5.08, nm_s[1], angle=0))
        iso_net = f"BIAS_ISO{ch_idx}"
        s.add(wire(nm_g[0], nm_g[1], nm_g[0] - 7.62, nm_g[1]))
        s.add(global_label(iso_net, "input", nm_g[0] - 7.62, nm_g[1], angle=180, justify="right"))

        # 10kΩ pull-down on BIAS_ISO gate
        iso_pd_x = nm_g[0] - 3.81
        s.add(junction(iso_pd_x, nm_g[1]))
        place_from_netlist(s, nl, iso_pulldown_ref, x=iso_pd_x, y=nm_g[1] + 5.08)
        s.add(wire(iso_pd_x, nm_g[1], iso_pd_x, nm_g[1] + 1.27))
        s.add(wire(iso_pd_x, nm_g[1] + 8.89, iso_pd_x, nm_g[1] + 12.7))
        power_at(s, "GND", iso_pd_x, nm_g[1] + 12.7)

        # Op-amp V+ / V- power pins (unit 1 only — they're shared across units)
        if opa_unit == 1:
            vplus_x, vplus_y = OPA["8"]
            vminus_x, vminus_y = OPA["4"]
            s.add(wire(vplus_x, vplus_y, vplus_x, vplus_y - 5.08))
            power_at(s, "+3V3", vplus_x, vplus_y - 5.08)
            s.add(wire(vminus_x, vminus_y, vminus_x, vminus_y + 5.08))
            power_at(s, "GND", vminus_x, vminus_y + 5.08)

        # Channel decoupling cap on +3V3 near the OPA
        place_from_netlist(s, nl, cap_ref, x=x0 + 15, y=95)
        s.add(wire(x0 + 15, 91.19, x0 + 15, 87.63))
        power_at(s, "+3V3", x0 + 15, 87.63)
        s.add(wire(x0 + 15, 98.81, x0 + 15, 105))
        power_at(s, "GND", x0 + 15, 105)

    # Channel 0 (BIAS0): MCP4728 VOUTA → OPA2388 unit 1
    bias_channel(0, x0=180, dac_pin="6", out_net="BIAS0",
                 opa_ref="U41", pmos_ref="Q40", sense_ref="R40",
                 nmos_ref="Q42", cap_ref="C42",
                 par_jumper_ref="R42", iso_pulldown_ref="R44")
    # Channel 1 (BIAS1): MCP4728 VOUTB → OPA2388 unit 2
    bias_channel(1, x0=295, dac_pin="7", out_net="BIAS1",
                 opa_ref="U41", pmos_ref="Q41", sense_ref="R41",
                 nmos_ref="Q43", cap_ref="C43",
                 par_jumper_ref="R43", iso_pulldown_ref="R45")

    validate(s, nl)
    return s
