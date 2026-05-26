"""GUI-facing service layer.

Thin dispatch the FastAPI backend calls. Given a block id + sim type it
builds the right deck, runs ngspice, analyzes, and returns a JSON-
serializable result including downsampled traces (+ an x-axis descriptor so
the browser plots time / voltage / frequency sweeps correctly) for plotting.

Keeping this here means the sim package owns the block→deck→analysis
dispatch and the backend endpoint stays a one-liner.
"""

from __future__ import annotations

import numpy as np

from . import catalog, simconfig
from .decks import ldo_rail, opa_bias, pdn
from .runner import run_deck


# x-axis descriptor per sim type, for the frontend chart.
_TIME_MS = {"label": "time", "unit": "ms", "scale": 1e3, "log": False}
_VIN_V = {"label": "+3V3 in", "unit": "V", "scale": 1.0, "log": False}
_VDAC_V = {"label": "V_DAC", "unit": "V", "scale": 1.0, "log": False}
_FREQ_HZ = {"label": "freq", "unit": "Hz", "scale": 1.0, "log": True}

_X_AXIS = {
    "transient_powerup": _TIME_MS, "transient_load_step": _TIME_MS,
    "transient_settling": _TIME_MS, "line_regulation": _VIN_V,
    "dc_sweep": _VDAC_V, "ac_stability": _FREQ_HZ, "ac_pdn_impedance": _FREQ_HZ,
}

# y-axis label per sim type (most are volts).
_Y_LABEL = {
    "ac_stability": "magnitude (dB)", "ac_pdn_impedance": "|Z| (dB-ohm)",
    "dc_sweep": "I_bias (A) / V", "transient_settling": "I_bias (A) / V",
}


def list_blocks() -> list[dict]:
    """Block catalog for the frontend tab (incl. per-sim-type status)."""
    out: list[dict] = []
    for b in catalog.load_catalog():
        out.append({
            "id": b.get("id"),
            "title": b.get("title"),
            "sheet": b.get("sheet"),
            "status": b.get("status"),
            "description": b.get("description") or b.get("reason") or "",
            "models_needed": b.get("models_needed", []),
            "datasheets": b.get("datasheets", []),
            "sim_types": [
                {"type": s["type"], "rationale": s.get("rationale", ""),
                 "pass": s.get("pass", ""),
                 "status": s.get("status", "implemented"),
                 "defer_reason": s.get("defer_reason", "")}
                for s in b.get("sim_types", [])
            ],
        })
    return out


def _downsample(x: np.ndarray, y: np.ndarray, n: int = 500) -> tuple[list, list]:
    if x.size <= n:
        return x.tolist(), y.tolist()
    idx = np.linspace(0, x.size - 1, n).astype(int)
    return x[idx].tolist(), y[idx].tolist()


def _package_traces(traces) -> list[dict]:
    series: list[dict] = []
    for name, tr in traces.items():
        t = tr.col("time")
        for col in tr.columns:
            if col == "time":
                continue
            xs, ys = _downsample(t, tr.col(col))
            series.append({"trace": name, "signal": col, "t": xs, "v": ys})
    return series


def _result(block_id, sim_type, *, ok, status, analysis=None, op=None,
            traces=None, deck=None, message=None) -> dict:
    return {
        "block": block_id, "sim_type": sim_type,
        "pass_criterion": catalog.pass_criterion(block_id, sim_type),
        "ok": ok, "status": status,
        "analysis": analysis, "op_point": op or {},
        "plot": _package_traces(traces) if traces else [],
        "x_axis": _X_AXIS.get(sim_type), "y_label": _Y_LABEL.get(sim_type, "volts"),
        "deck": deck, "message": message,
    }


def _verdict(analysis) -> bool:
    return (analysis or {}).get("overall", "OK") == "OK"


def run_block_sim(block_id: str, sim_type: str, *, vout_set: float | None = None) -> dict:
    block = catalog.get_block(block_id)              # KeyError if unknown
    base = {"block": block_id, "sim_type": sim_type,
            "pass_criterion": catalog.pass_criterion(block_id, sim_type),
            "plot": [], "x_axis": _X_AXIS.get(sim_type)}

    # Operating point comes from the agent-determined scenario (requirements +
    # current design), not a hardcoded default. Falls back to 1.8V only if the
    # scenario hasn't been determined yet.
    if vout_set is None:
        vout_set = simconfig.primary_vout(block_id, 1.8)

    # Per-sim-type status gate (a block can be implemented yet have a planned sim).
    st = next((s for s in block.get("sim_types", []) if s["type"] == sim_type), {})
    if block.get("status") != "implemented" or st.get("status") == "planned":
        reason = st.get("defer_reason") or block.get("reason") \
            or f"'{block_id}' is '{block.get('status')}'"
        return {**base, "ok": False, "status": "planned",
                "message": reason + (f" Models needed: {block.get('models_needed')}."
                                     if block.get("models_needed") else "")}

    # ---- ldo_rail --------------------------------------------------------
    if block_id == "ldo_rail":
        if sim_type == "setpoint_coverage":
            pts = simconfig.operating_points(block_id) or None
            a = ldo_rail.simulate_setpoint_coverage(pts)
            return _result(block_id, sim_type, ok=_verdict(a), status="ran", analysis=a)
        mode = {"dc_op_point": "op", "transient_powerup": "powerup",
                "transient_load_step": "load_step",
                "line_regulation": "line_reg"}[sim_type]
        deck, specs = ldo_rail.build_deck(mode=mode, vout_set=vout_set)
        res = run_deck(deck, trace_specs=specs)
        a = None
        if sim_type == "dc_op_point":
            a = ldo_rail.analyze_op_point(res.op_point, vout_set=vout_set)
        elif sim_type == "transient_powerup" and "powerup" in res.traces:
            a = ldo_rail.analyze_powerup(res.traces["powerup"], vout_set=vout_set)
        elif sim_type == "transient_load_step" and "load_step" in res.traces:
            a = ldo_rail.analyze_load_step(res.traces["load_step"], vout_set=vout_set)
        elif sim_type == "line_regulation" and "line_reg" in res.traces:
            a = ldo_rail.analyze_line_regulation(res.traces["line_reg"], vout_set=vout_set)
        return _result(block_id, sim_type, ok=res.ok and _verdict(a),
                       status="ran", analysis=a, op=res.op_point,
                       traces=res.traces, deck=res.deck)

    # ---- opa_bias --------------------------------------------------------
    if block_id == "opa_bias":
        mode = {"dc_sweep": "dc_sweep", "ac_stability": "ac_stability",
                "transient_settling": "transient_settling",
                "por_failsafe": "por"}[sim_type]
        deck, specs = opa_bias.build_deck(mode=mode)
        res = run_deck(deck, trace_specs=specs)
        a = None
        if sim_type == "dc_sweep" and "dc_sweep" in res.traces:
            a = opa_bias.analyze_dc_sweep(res.traces["dc_sweep"])
        elif sim_type == "ac_stability" and "ac_stability" in res.traces:
            a = opa_bias.analyze_ac_stability(res.traces["ac_stability"])
        elif sim_type == "transient_settling" and "transient_settling" in res.traces:
            a = opa_bias.analyze_transient_settling(res.traces["transient_settling"])
        elif sim_type == "por_failsafe":
            a = opa_bias.analyze_por(res.op_point)
        return _result(block_id, sim_type, ok=res.ok and _verdict(a),
                       status="ran", analysis=a, op=res.op_point,
                       traces=res.traces, deck=res.deck)

    # ---- PDN (vddio_pdn / vddd_pdn) -------------------------------------
    if block_id in pdn.RAIL_OF_BLOCK:
        _, node, _ = pdn.RAIL_OF_BLOCK[block_id]
        mode = {"transient_load_step": "load_step",
                "ac_pdn_impedance": "impedance"}[sim_type]
        deck, specs = pdn.build_deck(block_id=block_id, mode=mode)
        res = run_deck(deck, trace_specs=specs)
        a = None
        if sim_type == "transient_load_step" and "pdn_load_step" in res.traces:
            a = pdn.analyze_load_step(res.traces["pdn_load_step"], node)
        elif sim_type == "ac_pdn_impedance" and "pdn_impedance" in res.traces:
            a = pdn.analyze_impedance(res.traces["pdn_impedance"], node)
        return _result(block_id, sim_type, ok=res.ok and _verdict(a),
                       status="ran", analysis=a, traces=res.traces, deck=res.deck)

    return {**base, "ok": False, "status": "no_dispatch",
            "message": f"no deck dispatch for '{block_id}'"}
