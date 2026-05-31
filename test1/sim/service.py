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

from . import catalog, circuit, design_extract, simconfig
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
    """Block catalog for the frontend tab (incl. per-sim-type status + the SPICE-
    model lifecycle status, so the GUI can offer Generate / Update)."""
    from . import deck_provenance
    out: list[dict] = []
    for b in catalog.load_catalog():
        has_model = has_deck_builder(b.get("id"))
        out.append({
            "id": b.get("id"),
            "title": b.get("title"),
            "sheet": b.get("sheet"),
            "group": b.get("group") or "other",   # functional domain (GUI grouping)
            "status": b.get("status"),
            # SPICE-model lifecycle: has_model + model_status (none/unknown/fresh/
            # stale) → the GUI shows "Generate SPICE model" (none) or "Update to
            # match schematic" (stale).
            "has_model": has_model,
            "model_status": deck_provenance.deck_status(b, has_model=has_model),
            # Combined per-block staleness vs the CURRENT schematic (keyed off the
            # block's OWN sheets only): {stale, model_status, run_stale, changed,
            # reason}. Drives the "out of date" badge + per-block Update button.
            "staleness": deck_provenance.block_staleness(b, has_model=has_model),
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


def _refdes_map_for(block_id: str) -> dict | None:
    """The deck's SPICE-ref → netlist-refdes map for `block_id`, so the parsed
    circuit can tie each model element back to its real schematic part."""
    if block_id == "ldo_rail":
        return ldo_rail.refdes_map()
    if block_id == "opa_bias":
        return opa_bias.refdes_map(channel=0)
    if block_id in pdn.RAIL_OF_BLOCK:
        return pdn.refdes_map()
    return None


def _result(block_id, sim_type, *, ok, status, analysis=None, op=None,
            traces=None, deck=None, message=None) -> dict:
    return {
        "block": block_id, "sim_type": sim_type,
        "pass_criterion": catalog.pass_criterion(block_id, sim_type),
        "ok": ok, "status": status,
        "analysis": analysis, "op_point": op or {},
        "plot": _package_traces(traces) if traces else [],
        "x_axis": _X_AXIS.get(sim_type), "y_label": _Y_LABEL.get(sim_type, "volts"),
        "deck": deck,
        # Parsed node-graph of exactly this deck (what's simulated), for the
        # GUI's "SPICE model" view. None if there's no deck or parsing failed.
        # refdes_map ties each model element back to a netlist refdes.
        "circuit": circuit.circuit_dict(deck, _refdes_map_for(block_id)),
        "message": message,
    }


def _verdict(analysis) -> bool:
    return (analysis or {}).get("overall", "OK") == "OK"


def run_block_sim(block_id: str, sim_type: str, *, vout_set: float | None = None,
                  overrides: dict[str, dict] | None = None) -> dict:
    # `overrides` are the GUI's ephemeral "tune before running" boundary-param
    # edits ({net: {key: value}}). They are applied via a ContextVar for the
    # duration of THIS call only (never written to blocks.yaml), so the deck
    # builders' resolve_boundaries() picks them up and they vanish afterward.
    with catalog.run_overrides(overrides):
        return _run_block_sim(block_id, sim_type, vout_set=vout_set)


def _run_block_sim(block_id: str, sim_type: str, *, vout_set: float | None = None) -> dict:
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

    # Simulator-availability gate: without ngspice on PATH (or $NGSPICE) the deck
    # can't run. Report this distinctly so the GUI says "simulator unavailable"
    # rather than showing a bogus FAIL on an empty result.
    from .runner import NGSPICE
    if not NGSPICE:
        return {**base, "ok": False, "status": "no_simulator",
                "message": "ngspice not found — install it and add to PATH, or "
                           "set the NGSPICE environment variable to its path."}

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
                "por_failsafe": "por", "dc_compliance": "compliance"}[sim_type]
        # Sense-R comes from the as-built netlist (bias.yaml R40), computed ONCE
        # and threaded into BOTH the deck and the accuracy analyzer so the
        # ideal-current reference matches the modeled resistor exactly.
        r_sense = design_extract.sense_resistance(channel=0)
        deck, specs = opa_bias.build_deck(mode=mode, r_sense=r_sense)
        res = run_deck(deck, trace_specs=specs)
        a = None
        if sim_type == "dc_sweep" and "dc_sweep" in res.traces:
            a = opa_bias.analyze_dc_sweep(res.traces["dc_sweep"],
                                          r_sense=r_sense, vdd=opa_bias.VDD)
        elif sim_type == "dc_compliance" and "dc_compliance" in res.traces:
            a = opa_bias.analyze_compliance(res.traces["dc_compliance"],
                                            r_sense=r_sense, vdd=opa_bias.VDD)
        elif sim_type == "ac_stability" and "ac_stability" in res.traces:
            a = opa_bias.analyze_ac_stability(res.traces["ac_stability"])
        elif sim_type == "transient_settling" and "transient_settling" in res.traces:
            a = opa_bias.analyze_transient_settling(res.traces["transient_settling"])
        elif sim_type == "por_failsafe":
            a = opa_bias.analyze_por(res.op_point)
        return _result(block_id, sim_type, ok=res.ok and _verdict(a),
                       status="ran", analysis=a, op=res.op_point,
                       traces=res.traces, deck=res.deck)

    # ---- PDN (vddio_pdn / vddd_pdn / vdda1_pdn / vdda2_pdn) -------------
    if block_id in pdn.RAIL_OF_BLOCK:
        rail, node, _ = pdn.RAIL_OF_BLOCK[block_id]
        mode = {"transient_load_step": "load_step",
                "ac_pdn_impedance": "impedance"}[sim_type]
        deck, specs = pdn.build_deck(block_id=block_id, mode=mode)
        res = run_deck(deck, trace_specs=specs)
        a = None
        if sim_type == "transient_load_step" and "pdn_load_step" in res.traces:
            # per-rail droop budget from the block's boundary params
            from .catalog import resolve_boundaries
            limit = resolve_boundaries(block_id, sim_type).get(rail, {}) \
                .get("params", {}).get("droop_limit_V", 0.030)
            a = pdn.analyze_load_step(res.traces["pdn_load_step"], node,
                                      droop_limit_V=limit)
        elif sim_type == "ac_pdn_impedance" and "pdn_impedance" in res.traces:
            a = pdn.analyze_impedance(res.traces["pdn_impedance"], node)
        return _result(block_id, sim_type, ok=res.ok and _verdict(a),
                       status="ran", analysis=a, traces=res.traces, deck=res.deck)

    return {**base, "ok": False, "status": "no_dispatch",
            "message": f"no deck dispatch for '{block_id}'"}


# Mode maps, shared between run + build-only. (Kept here, mirroring the inline
# dicts above, so the build-only path can't drift from what actually runs.)
_LDO_MODE = {"dc_op_point": "op", "transient_powerup": "powerup",
             "transient_load_step": "load_step", "line_regulation": "line_reg"}
_OPA_MODE = {"dc_sweep": "dc_sweep", "ac_stability": "ac_stability",
             "transient_settling": "transient_settling", "por_failsafe": "por",
             "dc_compliance": "compliance"}
_PDN_MODE = {"transient_load_step": "load_step", "ac_pdn_impedance": "impedance"}


def has_deck_builder(block_id: str) -> bool:
    """True if a Python deck builder backs this block (ldo_rail / opa_bias / a
    PDN rail). False means there's NO SPICE model for the block yet — the GUI
    offers to GENERATE one (the generate-model agent writes sim/decks/<block>.py
    + the catalog entry). The single source of truth for the dispatch in
    run_block_sim / build_deck_text, so 'can it run' and 'does it have a model'
    can't drift apart."""
    return (block_id in ("ldo_rail", "opa_bias")) or (block_id in pdn.RAIL_OF_BLOCK)


def build_deck_text(block_id: str, sim_type: str) -> str | None:
    """Build (but DON'T run) the deck for one block/sim_type and return its
    text — used to show the simulated circuit without invoking ngspice.

    Returns None when the combo has no deck (a code-built analysis like
    setpoint_coverage, a planned/not-simulatable sim, or an unknown block)."""
    block = catalog.get_block(block_id)              # KeyError if unknown
    st = next((s for s in block.get("sim_types", []) if s["type"] == sim_type), {})
    if block.get("status") != "implemented" or st.get("status") == "planned":
        return None
    try:
        if block_id == "ldo_rail":
            if sim_type not in _LDO_MODE:            # e.g. setpoint_coverage
                return None
            vout = simconfig.primary_vout(block_id, 1.8)
            return ldo_rail.build_deck(mode=_LDO_MODE[sim_type], vout_set=vout)[0]
        if block_id == "opa_bias":
            if sim_type not in _OPA_MODE:
                return None
            r_sense = design_extract.sense_resistance(channel=0)
            return opa_bias.build_deck(mode=_OPA_MODE[sim_type], r_sense=r_sense)[0]
        if block_id in pdn.RAIL_OF_BLOCK:
            if sim_type not in _PDN_MODE:
                return None
            return pdn.build_deck(block_id=block_id, mode=_PDN_MODE[sim_type])[0]
    except (KeyError, ValueError):
        return None
    return None


def circuit_for(block_id: str, sim_type: str,
                overrides: dict[str, dict] | None = None) -> dict | None:
    """Parsed node-graph for one block/sim_type's deck (no ngspice run), with
    each element tied back to its netlist refdes. None when there's no deck.
    `overrides` (ephemeral boundary-param edits) are applied for the build so the
    "SPICE model" preview reflects the same values a Run would use."""
    with catalog.run_overrides(overrides):
        return circuit.circuit_dict(build_deck_text(block_id, sim_type),
                                    _refdes_map_for(block_id))
