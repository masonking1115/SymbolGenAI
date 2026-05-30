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

# Defaults only — the ACTUAL sense-R value is read from the netlist (bias.yaml
# R40/R41) and threaded explicitly through build + analysis so the deck and the
# ideal-current formula can never disagree. These constants are the fallback /
# default-arg values; functions take r_sense/vdd params and never read these
# directly. See design_extract.sense_resistance() and service.run_block_sim.
R_SENSE = 5110.0          # 5.11k 0.1% channel sense resistor (default/fallback)
VDD = 3.3                 # +3V3 rail (DAC reference = VDD)

_MODE_TO_SIMTYPE = {
    "dc_sweep": "dc_sweep",
    "ac_stability": "ac_stability",
    "transient_settling": "transient_settling",
    "por": "por_failsafe",
    "compliance": "dc_compliance",
}

# Bobcat bias-input compliance point (PDF: "nominally 320µA at 0.5V"). The DUT
# pulls bias current with its BIASx pin sitting near 0.5 V, so the loop must be
# able to source the full range with the PMOS drain/isolator holding that 0.5 V
# — a headroom check the generic 100Ω load (BIAS node ≈ 0.03 V) doesn't exercise.
BIAS_COMPLIANCE_V = 0.5
BIAS_NOMINAL_A = 320e-6      # PDF nominal operating current

# Catalog net name → SPICE node. BIAS_ISO drives the isolator gate; +3V3 is
# the supply; BIAS0 is the output into the DUT bias load.
_NET_TO_NODE = {
    "+3V3": "V3V3",
    "BIAS0": "BIAS0",
    "BIAS_ISO0": "BIAS_ISO0",
}


# SPICE deck element ref → netlist refdes on bias.yaml, so the GUI can tie a
# model element back to the real schematic part. None = behavioral scaffolding
# with no physical part (boundary source, ammeter, DUT load stub). Channel 0
# uses R40/Q40/Q42; channel 1 would be R41/Q41/Q43 (the deck builds ch0 today).
def refdes_map(channel: int = 0) -> dict[str, str | None]:
    sense = {0: "R40", 1: "R41"}[channel]
    pmos = {0: "Q40", 1: "Q41"}[channel]
    iso = {0: "Q42", 1: "Q43"}[channel]
    return {
        "XOPA": "U41",            # OPA2388 op-amp
        "MQ40": pmos,             # PMZ1200 pass FET
        "MQ42": iso,              # 2N7002 isolator
        "RSENSE": sense,          # 5.11k sense resistor
        "VDAC": "U40",            # MCP4728 DAC — output modeled as a programmed V
        # --- model-only (no schematic part) ---
        "VSNS_BIAS": None,        # 0V ammeter into the DUT bias node
        "RBIASLOAD": None,        # DUT bias-input load stand-in
        "VBIASCOMP": None,        # DUT 0.5V compliance source (compliance sim)
        "VV3V3_SRC": None,        # off-sheet +3V3 source (boundary)
        "RV3V3_SRC": None,        # +3V3 source impedance (boundary)
        "VBIAS_ISO0_DRV": None,   # FPGA isolator drive (boundary)
    }


def _ideal_ibias(v_dac: float, vdd: float, r_sense: float) -> float:
    return max(0.0, (vdd - v_dac) / r_sense)


def _core_topology(v_dac_src: str, *, r_sense: float) -> list[str]:
    """The loop wiring, shared by every mode. `v_dac_src` is the SPICE line
    that defines the DAC output node VDAC (a source — DC, swept, or PWL).
    `r_sense` is the channel sense-R value extracted from the netlist."""
    return [
        "* --- MCP4728 DAC output (behavioral: a programmed voltage) ---",
        v_dac_src,
        "* --- OPA2388: OUT=OPAOUT +IN=VDAC -IN=VSENSE V+=V3V3 V-=0 ---",
        "XOPA OPAOUT VDAC VSENSE V3V3 0 OPA2388"
        + (f" PARAMS:{param_map.params_string('OPA2388')}" if param_map.applied('OPA2388') else ""),
        "* --- PMOS pass element Q40: D=BIASD G=OPAOUT S=VSENSE ---",
        "MQ40 BIASD OPAOUT VSENSE V3V3 PMOS_PMZ1200",
        f"* --- sense R (netlist R40): VSENSE -> +3V3 (feedback samples VSENSE) ---",
        f"RSENSE VSENSE V3V3 {r_sense:.6g}",
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


def build_deck(*, mode: str, dac_mid: float = 1.65,
               r_sense: float = R_SENSE, vdd: float = VDD,
               ) -> tuple[str, dict[str, list[str]]]:
    """Build an opa_bias deck + trace specs.

    dac_mid: the DAC voltage used as the operating point for AC/settling.
    r_sense: channel sense-R (ohms) from the netlist (design_extract); defaults
             to the as-designed 5.11k. vdd: the +3V3 rail.
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
        core = _core_topology(dac, r_sense=r_sense)
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
        core = _core_topology(dac, r_sense=r_sense)
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
        core = _core_topology(dac, r_sense=r_sense)
        analysis = """.control
tran 0.2u 400u uic
wrdata transient_settling.dat i(vsns_bias) v(vsense) v(vdac)
.endc
"""
        trace_specs["transient_settling"] = ["i(vsns_bias)", "v(vsense)", "v(vdac)"]

    elif mode == "por":
        # Fail-safe: virgin MCP4728 powers up at code 0xFFF → VOUT = VDD, and
        # BIAS_ISO low → isolator open. Bias reaching the DUT must be ~0.
        dac = f"VDAC VDAC 0 DC {vdd:.6g}"      # default full-scale code ⇒ I=0
        bnds = _boundaries_for(sim_type)       # BIAS_ISO0 driven low by catalog
        core = _core_topology(dac, r_sense=r_sense)
        analysis = """.control
op
print i(vsns_bias) v(vsense) v(biasd) v(bias_iso0)
.endc
"""

    elif mode == "compliance":
        # PDF requirement: BIASx delivers its programmed current with the DUT
        # bias pin at ~0.5 V. Pin BIAS0 to 0.5 V (the DUT compliance point) via a
        # source the ammeter feeds, and sweep the DAC: the loop must still hit the
        # ideal current across the range (i.e. enough PMOS-drain/isolator headroom
        # at 0.5 V), and in particular at the nominal 320 µA point. Overrides the
        # generic 100Ω load below with the 0.5 V compliance source.
        dac = "VDAC VDAC 0 DC 0"
        bnds = _boundaries_for(sim_type)
        core = _core_topology(dac, r_sense=r_sense)
        bias_load = (f"* DUT bias-input compliance: hold BIAS0 at {BIAS_COMPLIANCE_V} V\n"
                     f"VBIASCOMP BIAS0 0 DC {BIAS_COMPLIANCE_V:.6g}")
        # 0.01 V step (not 0.033): analyze_compliance samples the NOMINAL point by
        # nearest-V_DAC, so a coarse grid lands up to ±16 mV (≈5 µA) off 320 µA and
        # false-fails the 1% nominal check. 0.01 V keeps the nominal sample within
        # ~1.5 µA — the verdict reflects the design, not the sweep resolution.
        analysis = """.control
dc VDAC 0 3.3 0.01
wrdata dc_compliance.dat i(vsns_bias) v(vsense) v(opaout) v(biasd)
.endc
"""
        trace_specs["dc_compliance"] = ["i(vsns_bias)", "v(vsense)", "v(opaout)", "v(biasd)"]

    deck = "\n".join([head, "", *bnds, "", *core, bias_load, "", analysis, ".end"])
    return deck, trace_specs


# ---------------------------------------------------------------------------
# Analyzers


def analyze_dc_sweep(trace, *, r_sense: float = R_SENSE, vdd: float = VDD,
                     err_limit_frac: float = 0.01) -> dict:
    """V-to-I accuracy vs ideal (vdd - V_DAC)/r_sense.

    `r_sense`/`vdd` MUST be the same values the deck was built with (the netlist
    sense-R, threaded from service.run_block_sim) — the ideal-current reference
    is computed from them, so a mismatch would silently miscompute the error.

    Scored only over the *regulated* range — where the op-amp output isn't
    railed. A single-supply op-amp can't drive the PMOS gate below ground, so
    the loop saturates near full-scale (V_DAC→0); that compliance ceiling is
    reported as i_max_regulated_A rather than scored as error, which is the
    honest DV finding (accurate up to the headroom limit)."""
    import numpy as np
    v_dac = trace.col("time")              # DC sweep var = VDAC
    i_meas = trace.col("i(vsns_bias)")
    opaout = trace.col("v(opaout)")
    ideal = np.array([_ideal_ibias(v, vdd, r_sense) for v in v_dac])
    # Regulated where the op-amp output is off both rails (0 .. vdd).
    regulated = (opaout > 0.05) & (opaout < vdd - 0.05)
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
        "full_scale_A": float(vdd / r_sense),
        "r_sense_ohm": float(r_sense),
        "i_max_regulated_A": float(i_max_reg),
        "worst_err_pct": round(float(worst) * 100, 3),
        "worst_at_vdac_V": worst_at,
        "err_limit_pct": err_limit_frac * 100,
        "overall": "OK" if worst <= err_limit_frac else "FAIL",
    }


def analyze_compliance(trace, *, r_sense: float = R_SENSE, vdd: float = VDD,
                       err_limit_frac: float = 0.01,
                       compliance_v: float = BIAS_COMPLIANCE_V,
                       nominal_a: float = BIAS_NOMINAL_A) -> dict:
    """Bias delivered with the DUT pin held at the 0.5 V compliance point.

    Same V-to-I accuracy test as dc_sweep, but BIAS0 is pinned to 0.5 V so this
    verifies the loop has the drain/isolator headroom to source current into a
    real DUT bias node (not just a near-ground load). Also reports the current
    at the PDF nominal point (ideal ≈ 320 µA) and confirms the pass FET drain
    stays above the 0.5 V compliance over the regulated range."""
    import numpy as np
    v_dac = trace.col("time")                  # DC sweep var = VDAC
    i_meas = trace.col("i(vsns_bias)")
    opaout = trace.col("v(opaout)")
    biasd = trace.col("v(biasd)")              # PMOS drain (must stay > 0.5 V)
    ideal = np.array([_ideal_ibias(v, vdd, r_sense) for v in v_dac])
    regulated = (opaout > 0.05) & (opaout < vdd - 0.05)

    worst = 0.0
    worst_at = None
    i_max_reg = 0.0
    drain_min = float("inf")
    for vd, im, il, reg, bd in zip(v_dac, i_meas, ideal, regulated, biasd):
        if not reg or il <= 0:
            continue
        i_max_reg = max(i_max_reg, il)
        drain_min = min(drain_min, float(bd))
        frac = abs(im - il) / il
        if frac > worst:
            worst, worst_at = frac, float(vd)

    # current at the nominal operating point (V_DAC where ideal ≈ nominal_a)
    v_nom = vdd - nominal_a * r_sense
    j = int(np.argmin(np.abs(v_dac - v_nom)))
    i_at_nominal = float(i_meas[j])
    nom_err = abs(i_at_nominal - nominal_a) / nominal_a if nominal_a else 0.0

    drain_ok = drain_min >= compliance_v if drain_min != float("inf") else False
    ok = worst <= err_limit_frac and nom_err <= err_limit_frac and drain_ok
    return {
        "check": "dc_compliance_at_0v5",
        "compliance_V": compliance_v,
        "i_at_nominal_uA": round(i_at_nominal * 1e6, 2),
        "nominal_target_uA": round(nominal_a * 1e6, 1),
        "nominal_err_pct": round(nom_err * 100, 3),
        "worst_err_pct": round(float(worst) * 100, 3),
        "worst_at_vdac_V": worst_at,
        "i_max_regulated_uA": round(i_max_reg * 1e6, 2),
        "pmos_drain_min_V": None if drain_min == float("inf") else round(drain_min, 4),
        "err_limit_pct": err_limit_frac * 100,
        "overall": "OK" if ok else "FAIL",
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
