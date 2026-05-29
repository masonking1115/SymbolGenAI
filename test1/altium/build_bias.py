"""Bias sheet — Altium port of gen/build_bias.py.

Same declarative source of truth (netlist/bias.yaml) and strict validator.
Coordinates are mils on a 100-mil grid; Altium Y grows UP.

OPA2388 is now the Ultra-Librarian symbol: a SINGLE 8-pin part (not two
drawn units), so U41 is placed ONCE and BOTH bias channels connect to it.
Its pins (placed at centre (cx,cy)) sit at:
  left  x=cx:    +INA=3 (cy), +INB=5 (cy-100), -INA=2 (cy-200), -INB=6 (cy-300),
                 V-=4 (cy-800), V+=8 (cy-900)
  right x=cx+1600: OUTA=1 (cy), OUTB=7 (cy-100)
Channel 0 (amp A) uses 1/2/3, channel 1 (amp B) uses 5/6/7. Because the op-amp
can only be in one place, channel 1's output/feedback to Q41 (far right) run on
clear horizontal lanes ABOVE the channel-0 cluster.

Other pin hot-spots (verified empirically):
  MCP4728  at (cx,cy): left=cx-500; pins 1-5 y= cy+400/+200/0/-200/-400
                        right=cx+500; pins 6-10 y= cy-400/-200/0/+200/+400
  PMZ1200UPEYL ori=2: pin1 G=(cx+500,cy), pin2 S=(cx,cy+500), pin3 D=(cx,cy-500)
  2N7002 ori=0: pin1 G=(cx-500,cy), pin2 S=(cx,cy-500), pin3 D=(cx,cy+500)
  R/C vertical: pin1=(cx,cy+100), pin2=(cx,cy-100)

PMOS is placed ori=2 (180°): Source at TOP (cy+500), Drain at BOTTOM (cy-500),
Gate on RIGHT (cx+500). This allows clean routing:
  OPA out → PMOS.G ;  +3V3 → R.top → R.bot → S ;  D → south → NMOS.D
"""

from __future__ import annotations

from altium_monkey import PortIOType

from ..gen.netlist import load_netlist
from ..gen.validator import validate
from .build_symbols import get_library
from .config import OUT_DIR, RENDER_DIR
from .shared import AltiumSheet

GRID = 100   # mil


def build_bias() -> tuple[AltiumSheet, object]:
    nl = load_netlist("bias")
    lib, lmap = get_library()
    # A2: the two bias channels span to BIAS1's port at x~15300, which is flush
    # against Altium's A3 drawable frame (15500 wide, usable to 15300) — the port
    # body renders on the border/reference-zone. A2 (22300 wide) gives ~6700 mil
    # of right clearance. The content was laid out for ISO-A3 width (16535) but
    # Altium's A3 sheet style is only 15500; see _PAPER_MIL in shared.py.
    s = AltiumSheet(name="bias", title="test1 — Bias Generators (MCP4728 + OPA2388)", paper="A2")

    def place(ref, x, y, orientation=0, unit=1):
        return s.place_from_netlist(lib, lmap, nl, ref, x, y,
                                    orientation=orientation, unit=unit)

    # ===== Header notes =====
    s.text("BIAS BLOCK - POR FAIL-SAFE", 1000, 8400)
    s.text("Q42/Q43 (populated, default-OFF via R44/R45) block bias at POR.", 1000, 8200)
    s.text("FPGA must drive BIAS_ISO0/1 HIGH; MCP4728 defaults (code=0) are safe.", 1000, 8000)
    s.text("R42/R43 DNP -- populate ONLY to bypass FPGA control.", 1000, 7800)

    # =========================================================
    # Cluster A: MCP4728 DAC  U40 at (4000, 5000)
    # =========================================================
    U40 = place("U40", 4000, 5000)
    # UL MCP4728 pin map (placed at 4000,5000):
    #   left  x=4000: VSS=10 (4200), VDD=1 (4400), SDA=3 (4700), SCL=2 (4900), *LDAC=4 (5000)
    #   right x=6000: VOUTD=9 (4600), VOUTC=8 (4700), VOUTB=7 (4800), VOUTA=6 (4900), RDY=5 (5000)

    # I²C ports (left, west)
    PORT_X = 2000
    s.wire(*U40["2"], PORT_X, U40["2"][1])          # SCL pin2 @4900
    s.port("SCL", PORT_X, U40["2"][1], io=PortIOType.BIDIRECTIONAL)
    s.wire(*U40["3"], PORT_X, U40["3"][1])          # SDA pin3 @4700
    s.port("SDA", PORT_X, U40["3"][1], io=PortIOType.BIDIRECTIONAL)

    # *LDAC (pin4 @5000) tied to GND — own column, clear of the SCL port text
    s.wire(*U40["4"], 2800, U40["4"][1])
    s.power_at("GND", 2800, U40["4"][1])

    # NC pins on the right (RDY pin5, VOUTC pin8, VOUTD pin9)
    s.no_connect(*U40["5"])
    s.no_connect(*U40["8"])
    s.no_connect(*U40["9"])

    # VDD (pin1 @4400) → west to its own +3V3 rail. (C40 — the VDD decoupling
    # cap — now lives in the aligned decap bank below with C42/C43, connected by
    # net name only, so the DAC no longer shares a riser with it.) The rail sits
    # at the end of the horizontal stub (no vertical riser) so it neither crosses
    # the SCL/SDA wires above (y=4700/4900) nor T's into the *LDAC→GND row 5000.
    s.wire(*U40["1"], 3000, U40["1"][1])
    s.power_at("+3V3", 3000, U40["1"][1])

    # VSS (pin10 @4200) → west to x=3200, down to GND
    s.wire(*U40["10"], 3200, U40["10"][1])
    s.wire(3200, U40["10"][1], 3200, 3600)
    s.power_at("GND", 3200, 3600)

    # =========================================================
    # Decoupling bank — C40 (DAC VDD), C42 (ch0), C43 (ch1) all hang between
    # +3V3 (top) and GND (bottom) by net name only, so they group into one neat
    # aligned row instead of scattering across the sheet (decap_grouping). Pitch
    # 800 mil keeps them readable (>passive_declutter min pitch).
    # =========================================================
    DECAP_Y = 2400
    for _ref, _x in (("C40", 2600), ("C42", 3400), ("C43", 4200)):
        _C = place(_ref, _x, DECAP_Y)
        s.wire(*_C["1"], _x, DECAP_Y + 300)         # top → +3V3 (rail above)
        s.power_at("+3V3", _x, DECAP_Y + 300)
        s.wire(*_C["2"], _x, DECAP_Y - 300)         # bottom → GND (below)
        s.power_at("GND", _x, DECAP_Y - 300)

    # =========================================================
    # Single dual op-amp U41 (OPA2388, one 8-pin symbol)
    # =========================================================
    OPA_CX, OPA_CY = 8000, 5000
    OPA = place("U41", OPA_CX, OPA_CY)
    # pins: 1 OUTA(9600,5000) 2 -INA(8000,4800) 3 +INA(8000,5000) 4 V-(8000,4200)
    #       5 +INB(8000,4900) 6 -INB(8000,4700) 7 OUTB(9600,4900) 8 V+(8000,4100)

    # --- Power pins (left side, below the signal pins) ---
    vp_x, vp_y = OPA["8"]   # V+  (8000, 4100)
    vm_x, vm_y = OPA["4"]   # V-  (8000, 4200)
    # V+ → west, then UP to a +3V3 symbol so the rail arrow sits ABOVE its net,
    # pointing up OFF the net (was routed DOWN, which left the arrow below its own
    # wire pointing up into it — the power_stub_side defect). Column x=7100 above
    # y=4100 is clear (op-amp body starts at x=8000; no crossing wires), and the
    # arrow at 4600 stays below the signal-pin rows (>=4700).
    s.wire(vp_x, vp_y, vp_x - 900, vp_y)
    s.wire(vp_x - 900, vp_y, vp_x - 900, vp_y + 500)
    s.power_at("+3V3", vp_x - 900, vp_y + 500)
    # V- → west (shorter run), then down to GND (GND hangs below, points down).
    s.wire(vm_x, vm_y, vm_x - 500, vm_y)
    s.wire(vm_x - 500, vm_y, vm_x - 500, vm_y - 1000)
    s.power_at("GND", vm_x - 500, vm_y - 1000)

    # =========================================================
    # Channel cluster builder — PMOS / sense-R / NMOS / jumper /
    # pull-down / decoupling. Returns the two op-amp handoff points.
    # =========================================================
    def bias_channel(
        ch_idx: int,
        pmos_cx: int,
        pmos_ref: str,
        sense_ref: str,
        nmos_cx: int,
        nmos_cy: int,
        nmos_ref: str,
        par_ref: str,
        pd_ref: str,
        cap_ref: str,
    ) -> dict[str, tuple[int, int]]:
        PMOS_CY = 5000
        Q = place(pmos_ref, pmos_cx, PMOS_CY, orientation=2)
        gate_x, gate_y = Q["1"]    # (pmos_cx+500, PMOS_CY)
        src_x, src_y   = Q["2"]    # (pmos_cx, PMOS_CY+500)
        drn_x, drn_y   = Q["3"]    # (pmos_cx, PMOS_CY-500)

        # --- Sense R above PMOS source → +3V3 ---
        R_CY = src_y + 600
        R = place(sense_ref, src_x, R_CY)
        r_top_x, r_top_y = R["1"]   # (src_x, src_y+700)
        r_bot_x, r_bot_y = R["2"]   # (src_x, src_y+500)
        s.wire(src_x, src_y, r_bot_x, r_bot_y)        # S → R.bot
        R_V33_Y = r_top_y + 300
        s.wire(r_top_x, r_top_y, r_top_x, R_V33_Y)
        s.power_at("+3V3", r_top_x, R_V33_Y)

        # Feedback tap point on the source net (the S→R.bot segment).
        src_fb = (src_x, src_y + 300)
        s.junction(*src_fb)

        # --- PMOS drain → NMOS drain ---
        NM = place(nmos_ref, nmos_cx, nmos_cy)
        nm_g_x, nm_g_y = NM["1"]   # gate   (nmos_cx-500, nmos_cy)
        nm_s_x, nm_s_y = NM["2"]   # source (nmos_cx, nmos_cy-500)
        nm_d_x, nm_d_y = NM["3"]   # drain  (nmos_cx, nmos_cy+500)
        s.wire(drn_x, drn_y, nm_d_x, nm_d_y)

        # --- Parallel 0Ω jumper (R4x) ---
        PAR_CX = nmos_cx + 900
        PAR = place(par_ref, PAR_CX, nmos_cy)
        par_top_x, par_top_y = PAR["1"]   # (PAR_CX, nmos_cy+100)
        par_bot_x, par_bot_y = PAR["2"]   # (PAR_CX, nmos_cy-100)
        # No junction on the NMOS drain/source pins: a wire ending on a pin
        # auto-connects in Altium, so a dot there is redundant.
        s.wire(nm_d_x, nm_d_y, par_top_x, nm_d_y)
        s.wire(par_top_x, nm_d_y, par_top_x, par_top_y)
        s.wire(nm_s_x, nm_s_y, par_bot_x, nm_s_y)
        s.wire(par_bot_x, nm_s_y, par_bot_x, par_bot_y)

        # BIASx port right of jumper column — +200 keeps body clear of the
        # adjacent ch1 NMOS body and the ch1 pull-down vertical wire.
        BIAS_PORT_X = PAR_CX + 200
        s.junction(PAR_CX, nm_s_y)
        s.wire(PAR_CX, nm_s_y, BIAS_PORT_X, nm_s_y)
        s.port(f"BIAS{ch_idx}", BIAS_PORT_X, nm_s_y, io=PortIOType.OUTPUT)

        # BIAS_ISOx port + pull-down on NMOS gate. Offset -200 (was -300): the
        # port body extends LEFT from the connection, and at -300 ch1's body left
        # edge clipped the adjacent ch0 parallel-jumper R42 by ~5 mil (caught once
        # the linter used the true drawn body). -200 shifts the body right, clear
        # of R42, while staying left of the gate pin.
        ISO_PORT_X = nm_g_x - 200
        s.wire(nm_g_x, nm_g_y, ISO_PORT_X, nm_g_y)
        s.port(f"BIAS_ISO{ch_idx}", ISO_PORT_X, nm_g_y, io=PortIOType.INPUT)
        PD_CX = nm_g_x
        PD_CY = nm_g_y - 900
        # No junction on the NMOS gate pin — wire-on-pin auto-connects.
        PD = place(pd_ref, PD_CX, PD_CY)
        pd_top_x, pd_top_y = PD["1"]
        pd_bot_x, pd_bot_y = PD["2"]
        s.wire(PD_CX, nm_g_y, pd_top_x, pd_top_y)
        PD_GND_Y = pd_bot_y - 300
        s.wire(pd_bot_x, pd_bot_y, pd_bot_x, PD_GND_Y)
        s.power_at("GND", pd_bot_x, PD_GND_Y)

        # Each channel's 3-line fail-safe note is ~2500 mil wide and the two
        # PMOS columns are only 2500 mil apart, so per-column notes overlapped
        # into an unreadable glob (label_overlap). Park both channels' note
        # blocks in the open band below the DAC/op-amp instead, stacked so the
        # two 3-line blocks never share a row.
        note_x = 4400
        note_base = 3000 - (ch_idx * 800)
        s.text(f"FAIL-SAFE: BIAS_ISO{ch_idx} default-LOW (R{int(pd_ref[1:])} pull-down)",
               note_x, note_base)
        s.text(f"-> {nmos_ref} OFF at POR -> no bias until FPGA asserts HIGH.",
               note_x, note_base - 200)
        s.text(f"{par_ref} is DNP -- populate ONLY to bypass FPGA control.",
               note_x, note_base - 400)

        # (Channel decoupling cap cap_ref is placed in the shared decap bank in
        # the main body — it connects by +3V3/GND net name only, so grouping all
        # three caps into one aligned row is purely a layout choice.)
        return {"gate": (gate_x, gate_y), "src_fb": src_fb}

    # =========================================================
    # Place both channel clusters (unchanged x positions).
    # =========================================================
    ch0 = bias_channel(0, pmos_cx=11000, pmos_ref="Q40", sense_ref="R40",
                        nmos_cx=11000, nmos_cy=2800, nmos_ref="Q42",
                        par_ref="R42", pd_ref="R44", cap_ref="C42")
    ch1 = bias_channel(1, pmos_cx=13500, pmos_ref="Q41", sense_ref="R41",
                        nmos_cx=13500, nmos_cy=2800, nmos_ref="Q43",
                        par_ref="R43", pd_ref="R45", cap_ref="C43")

    # =========================================================
    # Op-amp ↔ channel links
    # =========================================================
    def link_near(pos, neg, out, dac_pin, gate, src_fb, route_y,
                  out_riser_x, out_lane, fb_drop_x, fb_lane_y):
        """Channel 0 (amp A): op-amp adjacent to its PMOS cluster.

        The PMOS is placed ori=2 so its gate pin faces RIGHT (the body's right
        edge). Driving it with a straight east wire from OUTA cut THROUGH the
        transistor body (pin_wire_crosses_body); instead the gate drive rises to
        a short lane ABOVE the sense-R/+3V3 column and drops onto the gate from
        directly above — approaching the right-edge pin from outside the body
        (same up-and-over the far channel uses).

        The feedback is routed UNDER the op-amp (down the left, across below the
        op-amp/PMOS bodies, up to the source-net tap) — a short, direct wrap that
        clears the gate riser and the far channel's risers entirely, replacing
        the old westward-jog-then-long-top-lane meander."""
        # +IN ← DAC VOUTx
        dac_x, dac_y = U40[dac_pin]
        in_x, in_y = pos
        col = dac_x + 300
        s.wire(dac_x, dac_y, col, dac_y)
        s.wire(col, dac_y, col, route_y)
        s.wire(col, route_y, in_x, route_y)
        if route_y != in_y:
            s.wire(in_x, route_y, in_x, in_y)
        # OUT → up-and-over → down onto the right-facing gate pin from above.
        ox, oy = out
        s.wire(ox, oy, out_riser_x, oy)
        s.wire(out_riser_x, oy, out_riser_x, out_lane)
        s.wire(out_riser_x, out_lane, gate[0], out_lane)
        s.wire(gate[0], out_lane, gate[0], gate[1])
        # -IN ← source feedback, routed UNDER the op-amp: west off the pin, down
        # below the op-amp body, east below the bodies, up just LEFT of the PMOS
        # body, then a short hop east onto the source-net tap.
        neg_x, neg_y = neg
        # 7000: LEFT of every op-amp left-side stub (V+ to 7100, -INB to 7300,
        # V- to 7500) so the downward riser clears all of them.
        fb_col = neg_x - 1000
        tap_x, tap_y = src_fb
        s.wire(neg_x, neg_y, fb_col, neg_y)
        s.wire(fb_col, neg_y, fb_col, fb_lane_y)
        s.wire(fb_col, fb_lane_y, fb_drop_x, fb_lane_y)
        s.wire(fb_drop_x, fb_lane_y, fb_drop_x, tap_y)
        s.wire(fb_drop_x, tap_y, tap_x, tap_y)

    def link_far(pos, neg, out, dac_pin, gate, src_fb, route_y, out_lane, fb_lane):
        """Channel 1 (amp B): PMOS cluster is far right; route OUT and feedback
        on clear horizontal lanes ABOVE the channel-0 cluster."""
        # +IN ← DAC VOUTx (same idea as near; its own route_y lane)
        dac_x, dac_y = U40[dac_pin]
        in_x, in_y = pos
        col = dac_x + 600
        s.wire(dac_x, dac_y, col, dac_y)
        s.wire(col, dac_y, col, route_y)
        s.wire(col, route_y, in_x, route_y)
        if route_y != in_y:
            s.wire(in_x, route_y, in_x, in_y)
        # OUT → up to out_lane → east → down to gate
        ox, oy = out
        riser_x = ox + 300                # just right of the op-amp body
        s.wire(ox, oy, riser_x, oy)
        s.wire(riser_x, oy, riser_x, out_lane)
        s.wire(riser_x, out_lane, gate[0], out_lane)
        s.wire(gate[0], out_lane, gate[0], gate[1])
        # -IN ← feedback: west, up to fb_lane, east, down to the source tap.
        # Distinct column from ch0 feedback (7600) and the V+/V- columns.
        neg_x, neg_y = neg
        fb_col = neg_x - 700        # 7300
        s.wire(neg_x, neg_y, fb_col, neg_y)
        s.wire(fb_col, neg_y, fb_col, fb_lane)
        drop_x = src_fb[0] - 300          # left of the Q41 body
        s.wire(fb_col, fb_lane, drop_x, fb_lane)
        s.wire(drop_x, fb_lane, drop_x, src_fb[1])
        s.wire(drop_x, src_fb[1], src_fb[0], src_fb[1])

    # Channel 0: amp A (pins +INA=3, -INA=2, OUTA=1), DAC VOUTA=pin6.
    #   out_riser_x=10200  riser between the op-amp and the PMOS (left of the
    #                      Q40 body at x=10730), up to out_lane.
    #   out_lane=6800      above the ch0 +3V3 stub (6500); the gate drops here.
    #   fb_drop_x=10600    feedback rises just LEFT of the Q40 body (10730).
    #   fb_lane_y=3600     feedback runs east UNDER the op-amp/PMOS bodies.
    link_near(OPA["3"], OPA["2"], OPA["1"], "6", ch0["gate"], ch0["src_fb"],
              route_y=5000, out_riser_x=10200, out_lane=6800,
              fb_drop_x=10600, fb_lane_y=3600)
    # Channel 1: amp B (pins +INB=5, -INB=6, OUTB=7), DAC VOUTB=pin7.
    # Lane Y values must NOT coincide with any +3V3 power-port stub endpoint:
    # the previous values out_lane=7300, fb_lane=7100 landed exactly on the
    # R40/R41 +3V3 stub endpoints, T-shorting OUTB and -INB to +3V3 — a
    # defect the Voltai review caught (2026-05-28) that our connectivity
    # validator missed (T-detection blind spot for lane-vs-stub crossings;
    # also covered by layout_lint.stub_t_short going forward). Bumped 1500
    # mil above the +3V3 stub region so collisions can't recur after small
    # geometry tweaks.
    link_far(OPA["5"], OPA["6"], OPA["7"], "7", ch1["gate"], ch1["src_fb"],
             route_y=4900, out_lane=8800, fb_lane=8600)

    # --- OUTA / OUTB descriptions (left side: near OPA; right side: near PMOS gate) ---
    # y=6500 (was 6200) for the two long notes that ran into the sense resistors
    # R40/R41 (whose bodies top out at y=6260) — lifted clear of the resistor band.
    s.text("OUTA -> Q40.G  (CH0 bias gate drive)", 9200, 6500)
    s.text("<- OUTA  gate drive", 10800, 4000)
    s.text("OUTB -> Q41.G  (CH1 bias gate drive)", 9700, 3600)
    s.text("<- OUTB  gate drive", 13400, 6500)

    validate(s, nl)
    return s, nl


def main() -> int:
    s, _nl = build_bias()
    out = s.save(OUT_DIR / "bias.SchDoc")
    svg = s.render_svg(RENDER_DIR / "bias.svg")
    print(f"validated OK | wrote {out.name} + {svg.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
