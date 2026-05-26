"""opa_bias deck builder — the precision V-to-I bias loop (one channel).

Topology (channel 0, from bias.yaml):
    MCP4728 VOUTA ──► OPA2388 +IN
    OPA2388 OUT  ──► PMOS(Q40) gate
    PMOS source  ──► R_sense(5.11k) ──► +3V3,  and ──► OPA2388 -IN  (feedback)
    PMOS drain   ──► 2N7002(Q42) isolator ──► BIAS0

The loop forces V(source) = V(DAC), so the current through R_sense is
    I_bias = (V(+3V3) - V(DAC)) / R_sense          (0..646 µA full-scale)
i.e. the DAC voltage *inversely* sets the bias current. Accuracy is set by
the op-amp (offset + finite gain), not the pass FET — that's the whole point
of the feedback loop, and it's what dc_sweep measures.

Modes:
    dc_sweep          — sweep V_DAC 0..3.3, measure I_bias vs ideal
    ac_stability      — closed-loop response peaking (phase-margin proxy)
    transient_settling— step V_DAC, measure settle time + overshoot
    por               — power-on: DAC at default 0xFFF + BIAS_ISO low → bias
                        must be ~0 reaching the DUT (fail-safe gate)
"""

from __future__ import annotations

from .. import param_map
from ..catalog import resolve_boundaries
from ..models import opa_models
from ..stubs import emit_stub

R_SENSE = 5110.0          # 5.11k 0.1% channel sense resistor
VDD = 3.3                 # +3V3 rail (DAC reference = VDD)

_MODE_TO_SIMTYPE = {
    "dc_sweep": "dc_sweep",
    "ac_stability": "ac_stability",
    "transient_settling": "transient_settling",
    "por": "por_failsafe",
}

# Catalog net name → SPICE node. BIAS_ISO drives the isolator gate; +3V3 is
# the supply; BIAS0 is the output into the DUT bias load.
_NET_TO_NODE = {
    "+3V3": "V3V3",
    "BIAS0": "BIAS0",
    "BIAS_ISO0": "BIAS_ISO0",
}


def _ideal_ibias(v_dac: float) -> float:
    return max(0.0, (VDD - v_dac) / R_SENSE)


def _core_topology(v_dac_src: str) -> list[str]:
    """The loop wiring, shared by every mode. `v_dac_src` is the SPICE line
    that defines the DAC output node VDAC (a source — DC, swept, or PWL)."""
    return [
        "* --- MCP4728 DAC output (behavioral: a programmed voltage) ---",
        v_dac_src,
        "* --- OPA2388: OUT=OPAOUT +IN=VDAC -IN=VSENSE V+=V3V3 V-=0 ---",
        "XOPA OPAOUT VDAC VSENSE V3V3 0 OPA2388"
        + (f" PARAMS:{param_map.params_string('OPA2388')}" if param_map.applied('OPA2388') else ""),
        "* --- PMOS pass element Q40: D=BIASD G=OPAOUT S=VSENSE ---",
        "MQ40 BIASD OPAOUT VSENSE V3V3 PMOS_PMZ1200",
        "* --- sense R: VSENSE -> +3V3 (feedback samples VSENSE) ---",
        f"RSENSE VSENSE V3V3 {R_SENSE}",
        "* --- 2N7002 isolator Q42: D=BIASD G=BIAS_ISO0 S=BIASO ---",
        "MQ42 BIASD BIAS_ISO0 BIASO 0 NMOS_2N7002",
        "* --- ammeter into the BIAS output node (current into the DUT) ---",
        "VSNS_BIAS BIASO BIAS0 0",
    ]


def _boundaries_for(sim_type: str, *, exclude=("BIAS0",)) -> list[str]:
    """Emit boundary stubs from the catalog, skipping nets the topology
    drives internally via an ammeter (BIAS0 gets its load below)."""
    lines = ["* Boundary stubs (from blocks.yaml)"]
    for net, spec in resolve_boundaries("opa_bias", sim_type).items():
        if net in exclude:
            continue
        node = _NET_TO_NODE.get(net)
        if node is None:
            lines.append(f"* boundary {net}: not modeled — skipped")
            continue
        lines.append(emit_stub(spec["stub"], node, spec["params"]))
    return lines


def build_deck(*, mode: str, dac_mid: float = 1.65) -> tuple[str, dict[str, list[str]]]:
    """Build an opa_bias deck + trace specs.

    dac_mid: the DAC voltage used as the operating point for AC/settling.
    """
    if mode not in _MODE_TO_SIMTYPE:
        raise ValueError(f"unknown mode: {mode!r}")
    sim_type = _MODE_TO_SIMTYPE[mode]

    head = "* test1 sim — opa_bias (OPA2388 V-to-I bias loop, channel 0)\n\n" + opa_models()

    # BIAS output load: the DUT bias pin is a low-compliance current input.
    # A small resistor keeps the pass FET in saturation while we measure the
    # delivered current through VSNS_BIAS.
    bias_load = "* DUT bias input (low-compliance current sink)\nRBIASLOAD BIAS0 0 100"

    trace_specs: dict[str, list[str]] = {}

    if mode == "dc_sweep":
        dac = "VDAC VDAC 0 DC 0"
        bnds = _boundaries_for(sim_type)
        core = _core_topology(dac)
        analysis = """.control
dc VDAC 0 3.3 0.033
wrdata dc_sweep.dat i(vsns_bias) v(vsense) v(opaout)
.endc
"""
        trace_specs["dc_sweep"] = ["i(vsns_bias)", "v(vsense)", "v(opaout)"]

    elif mode == "ac_stability":
        # Closed-loop small-signal response V(VSENSE)/V(VDAC). Unity at DC
        # (loop forces VSENSE=VDAC); peaking near crossover ⇒ low phase margin.
        dac = f"VDAC VDAC 0 DC {dac_mid} AC 1"
        bnds = _boundaries_for(sim_type)
        core = _core_topology(dac)
        analysis = """.control
ac dec 60 10 100meg
wrdata ac_stability.dat vdb(vsense) vp(vsense)
.endc
"""
        trace_specs["ac_stability"] = ["vdb(vsense)", "vp(vsense)"]

    elif mode == "transient_settling":
        # Step the DAC by ~0.3V mid-scale; watch the bias current settle.
        lo, hi = dac_mid, dac_mid - 0.3   # lower DAC ⇒ higher current
        dac = f"VDAC VDAC 0 PWL(0 {lo} 100u {lo} 101u {hi})"
        bnds = _boundaries_for(sim_type)
        core = _core_topology(dac)
        analysis = """.control
tran 0.2u 400u uic
wrdata transient_settling.dat i(vsns_bias) v(vsense) v(vdac)
.endc
"""
        trace_specs["transient_settling"] = ["i(vsns_bias)", "v(vsense)", "v(vdac)"]

    elif mode == "por":
        # Fail-safe: virgin MCP4728 powers up at code 0xFFF → VOUT = VDD, and
        # BIAS_ISO low → isolator open. Bias reaching the DUT must be ~0.
        dac = f"VDAC VDAC 0 DC {VDD}"          # default full-scale code ⇒ I=0
        bnds = _boundaries_for(sim_type)       # BIAS_ISO0 driven low by catalog
        core = _core_topology(dac)
        analysis = """.control
op
print i(vsns_bias) v(vsense) v(biasd) v(bias_iso0)
.endc
"""

    deck = "\n".join([head, "", *bnds, "", *core, bias_load, "", analysis, ".end"])
    return deck, trace_specs


# ---------------------------------------------------------------------------
# Analyzers


def analyze_dc_sweep(trace, *, err_limit_frac: float = 0.01) -> dict:
    """V-to-I accuracy vs ideal (VDD - V_DAC)/R_sense.

    Scored only over the *regulated* range — where the op-amp output isn't
    railed. A single-supply op-amp can't drive the PMOS gate below ground, so
    the loop saturates near full-scale (V_DAC→0); that compliance ceiling is
    reported as i_max_regulated_A rather than scored as error, which is the
    honest DV finding (accurate up to the headroom limit)."""
    import numpy as np
    v_dac = trace.col("time")              # DC sweep var = VDAC
    i_meas = trace.col("i(vsns_bias)")
    opaout = trace.col("v(opaout)")
    ideal = np.array([_ideal_ibias(v) for v in v_dac])
    # Regulated where the op-amp output is off both rails (0 .. VDD).
    regulated = (opaout > 0.05) & (opaout < VDD - 0.05)
    worst = 0.0
    worst_at = None
    i_max_reg = 0.0
    for vd, im, il, reg in zip(v_dac, i_meas, ideal, regulated):
        if not reg or il <= 0:
            continue
        i_max_reg = max(i_max_reg, il)
        frac = abs(im - il) / il
        if frac > worst:
            worst, worst_at = frac, float(vd)
    return {
        "check": "dc_sweep_vtoi_accuracy",
        "full_scale_A": float(VDD / R_SENSE),
        "i_max_regulated_A": float(i_max_reg),
        "worst_err_pct": round(float(worst) * 100, 3),
        "worst_at_vdac_V": worst_at,
        "err_limit_pct": err_limit_frac * 100,
        "overall": "OK" if worst <= err_limit_frac else "FAIL",
    }


def analyze_ac_stability(trace, *, peak_limit_dB: float = 3.0) -> dict:
    """Closed-loop peaking as a phase-margin proxy. Flat (~0 dB) = well
    damped; a resonant peak > ~3 dB indicates < ~45° phase margin."""
    import numpy as np
    f = trace.col("time")                  # AC sweep var = frequency
    mag = trace.col("vdb(vsense)")
    dc_gain = float(mag[0])
    peak = float(np.max(mag))
    peaking = peak - dc_gain
    # crossover: first freq where response drops 3 dB below DC
    idx = np.where(mag <= dc_gain - 3.0)[0]
    f_3dB = float(f[idx[0]]) if len(idx) else None
    return {
        "check": "ac_stability_peaking",
        "dc_gain_dB": round(dc_gain, 3),
        "peaking_dB": round(peaking, 3),
        "peak_limit_dB": peak_limit_dB,
        "bandwidth_3dB_Hz": f_3dB,
        "overall": "OK" if peaking <= peak_limit_dB else "FAIL",
    }


def analyze_transient_settling(trace, *, settle_frac: float = 0.01,
                               settle_limit_s: float = 50e-6) -> dict:
    """Settling time + overshoot of the bias current after a DAC step."""
    import numpy as np
    t = trace.col("time")
    i = trace.col("i(vsns_bias)")
    i_final = float(np.mean(i[-50:]))
    i_start = float(np.mean(i[:20]))
    span = abs(i_final - i_start) or 1e-12
    band = settle_frac * abs(i_final)
    # find the step instant (largest change in DAC)
    vdac = trace.col("v(vdac)")
    step_idx = int(np.argmax(np.abs(np.diff(vdac))))
    t_step = float(t[step_idx])
    # settle: last time outside the +/- band, after the step
    settle_t = None
    for k in range(len(t) - 1, step_idx, -1):
        if abs(i[k] - i_final) > band:
            settle_t = float(t[k + 1] - t_step) if k + 1 < len(t) else None
            break
    overshoot = (float(np.max(i[step_idx:])) - i_final) / span if i_final > i_start \
        else (i_final - float(np.min(i[step_idx:]))) / span
    ok = settle_t is not None and settle_t <= settle_limit_s
    return {
        "check": "transient_settling",
        "i_final_A": i_final,
        "settle_time_s": settle_t,
        "settle_limit_s": settle_limit_s,
        "overshoot_frac": round(float(overshoot), 4),
        "overall": "OK" if ok else "FAIL",
    }


def analyze_por(op: dict, *, leak_limit_A: float = 1e-6) -> dict:
    """Fail-safe: bias current reaching the DUT at power-on must be ~0."""
    i_bias = abs(op.get("i(vsns_bias)", 0.0))
    return {
        "check": "por_failsafe",
        "bias_current_at_por_A": i_bias,
        "leak_limit_A": leak_limit_A,
        "overall": "OK" if i_bias <= leak_limit_A else "FAIL",
    }
