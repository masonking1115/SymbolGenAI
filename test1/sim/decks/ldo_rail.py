"""LDO-rail deck builder.

Reads netlist/power.yaml + netlist/bobcat.yaml and produces a SPICE deck
that simulates the +3V3 → LDO(U10) → VADJ → load-switch(U11) → +VDDIO
path with all decoupling caps in place.

The PoC pins +VDDIO as the rail-of-interest because that's what most of
the bobcat-side caps and pulls hang off of, so it's where load-step
droop will be most visible.

Three sim modes are exposed:
  - "op"        : DC operating point — read settled node voltages.
  - "powerup"   : Transient — ramp LDO_EN then LSW_EN, observe sequencing.
  - "load_step" : Transient — fully-settled rails, then step load current.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .. import param_map
from ..catalog import resolve_boundaries
from ..models import all_models
from ..stubs import emit_stub


NETLIST_DIR = Path(__file__).resolve().parents[2] / "netlist"

# CLI mode name → catalog sim_type name.
_MODE_TO_SIMTYPE = {
    "op": "dc_op_point",
    "powerup": "transient_powerup",
    "load_step": "transient_load_step",
    "line_reg": "line_regulation",
}

# Output voltages the ANY-OUT setpoint pins can select (datasheet ANY-OUT
# decoding approximated by representative rails the board exposes). Used by
# the setpoint-coverage check to confirm every selectable rail regulates
# with dropout headroom.
SETPOINT_RAILS_V = [0.8, 1.0, 1.2, 1.5, 1.8]

# Schematic net name (as keyed in blocks.yaml) → SPICE node in this deck.
# Boundary nets absent from this map aren't modeled by the current topology
# (e.g. LDO_PG — the behavioral LDO has no PG pin yet) and are skipped.
_NET_TO_NODE = {
    "+3V3": "V3V3",
    "LDO_EN": "LDO_EN",
    "LSW_EN": "LSW_EN",
    "+VDDIO": "VDDIO",
}


# ---------------------------------------------------------------------------
# YAML helpers


_SI = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
       "k": 1e3, "meg": 1e6, "g": 1e9}


def _parse_value(s: str) -> float:
    """Parse an EE-style value like '10uF', '0.1uF', '10k', '0.038'."""
    if s is None:
        return 0.0
    s = str(s).strip().rstrip("FfHhΩΩohmsOHMS").strip()
    m = re.match(r"^([\d.]+)\s*([a-zA-Z]*)$", s)
    if not m:
        return float(s)  # raises if truly unparseable
    num, suffix = m.group(1), m.group(2).lower()
    if not suffix:
        return float(num)
    if suffix.lower() == "meg":
        return float(num) * 1e6
    return float(num) * _SI.get(suffix[0], 1.0)


def _load_parts(sheet: str) -> dict:
    path = NETLIST_DIR / f"{sheet}.yaml"
    data = yaml.safe_load(path.read_text())
    return data.get("parts", {})


def _caps_with_net(sheet_parts: dict, top_net_pin_map: dict[str, str]) -> list[tuple[str, float]]:
    """Pull caps where pin .1 sits on a named net.

    top_net_pin_map maps "<refdes>.<pin>" → True membership. Returns list of
    (refdes, capacitance_F) for caps with .1 in the set.
    """
    out: list[tuple[str, float]] = []
    for ref, spec in sheet_parts.items():
        if not ref.startswith("C"):
            continue
        if f"{ref}.1" not in top_net_pin_map:
            continue
        val = spec.get("value") if isinstance(spec, dict) else None
        if val is None:
            continue
        try:
            out.append((ref, _parse_value(val)))
        except ValueError:
            continue
    return out


def _net_members(yaml_path: Path, netname: str) -> set[str]:
    data = yaml.safe_load(yaml_path.read_text())
    members = data.get("nets", {}).get(netname, {}).get("members", []) or []
    return set(members)


# ---------------------------------------------------------------------------
# Deck assembly


def _preamble() -> str:
    return f"""* test1 sim — LDO rail (TPS7A8401A + TPS22916 load switch)
* Auto-generated from netlist/power.yaml + netlist/bobcat.yaml.

{all_models()}
"""


def _input_caps_block(caps: list[tuple[str, float]], node: str = "VIN") -> str:
    lines = [f"* Input decoupling on {node}"]
    for ref, val in caps:
        lines.append(f"{ref}  {node} 0 {val:.3e}")
    return "\n".join(lines)


def _output_caps_block(caps: list[tuple[str, float]], node: str) -> str:
    lines = [f"* Decoupling on {node}"]
    for ref, val in caps:
        lines.append(f"{ref}  {node} 0 {val:.3e}")
    return "\n".join(lines)


def build_deck(*, mode: str, vout_set: float = 1.8,
               ) -> tuple[str, dict[str, list[str]]]:
    """Build a SPICE deck plus the trace spec for the runner.

    Boundary sources/loads (the +3V3 supply, EN drives, +VDDIO load) come
    from the catalog (blocks.yaml) via resolve_boundaries(), so the partition
    lives in data. The internal topology (LDO, switch, decoupling) is built
    in code below since it's inherently per-block wiring.

    Returns (deck_text, trace_specs).
    """
    if mode not in _MODE_TO_SIMTYPE:
        raise ValueError(f"unknown mode: {mode!r}")
    sim_type = _MODE_TO_SIMTYPE[mode]
    power_parts = _load_parts("power")
    bobcat_parts = _load_parts("bobcat")
    power_yaml = NETLIST_DIR / "power.yaml"
    bobcat_yaml = NETLIST_DIR / "bobcat.yaml"

    # Input-side decoupling sits on +3V3
    in_caps_members = _net_members(power_yaml, "+3V3")
    in_caps = _caps_with_net(power_parts, in_caps_members)

    # OUT bulk caps — sit on the internal LDO_OUT bus (we model that as
    # node VOUT, which we will also tie to VADJ since the jumpers pass-
    # through in normal operation).
    out_caps_members = _net_members(power_yaml, "internal_LDO_OUT_bus")
    out_caps = _caps_with_net(power_parts, out_caps_members)

    # VADJ-side cap (C15 — between LDO_OUT and the load switch input)
    vadj_caps_members = _net_members(power_yaml, "VADJ")
    vadj_caps = _caps_with_net(power_parts, vadj_caps_members)

    # +VDDIO caps — across both power.yaml (C16) and bobcat.yaml (C24-29)
    vddio_caps: list[tuple[str, float]] = []
    pm = _net_members(power_yaml, "+VDDIO")
    bm = _net_members(bobcat_yaml, "+VDDIO")
    vddio_caps.extend(_caps_with_net(power_parts, pm))
    vddio_caps.extend(_caps_with_net(bobcat_parts, bm))

    head = _preamble()

    # --- Boundary stubs (catalog-driven, per sim type) ---------------------
    # Sources (+3V3, EN drives) and the +VDDIO load all come from blocks.yaml.
    boundaries = resolve_boundaries("ldo_rail", sim_type)
    bnd_lines = ["* Boundary stubs (from blocks.yaml)"]
    for net, spec in boundaries.items():
        node = _NET_TO_NODE.get(net)
        if node is None:
            bnd_lines.append(f"* boundary {net}: not modeled in current topology — skipped")
            continue
        bnd_lines.append(emit_stub(spec["stub"], node, spec["params"]))

    # --- Internal topology (per-block wiring, built in code) ---------------
    # VSNS_LDO is a 0V ammeter between the LDO output and the rail so we can
    # read the LDO's output (inrush) current — subcircuit branch currents
    # aren't otherwise reachable in ngspice.
    blocks = [
        _input_caps_block(in_caps, "V3V3"),
        f"* LDO (TPS7A8401A) — VOUT_SET={vout_set}V; datasheet params:{param_map.params_string('TPS7A8401A') or ' (defaults)'}",
        f"XU10  V3V3 VOUT_LDO LDO_EN 0 LDO_TPS7A8401A PARAMS: VOUT_SET={vout_set}"
        + param_map.params_string("TPS7A8401A"),
        "VSNS_LDO VOUT_LDO VOUT 0",
        _output_caps_block(out_caps + vadj_caps, "VOUT"),
        "* Tie LDO_OUT to VADJ (jumper closed in normal use)",
        "RJUMP VOUT VADJ 0.001",
        f"* Load switch (TPS22916); datasheet params:{param_map.params_string('TPS22916CNYFPR') or ' (defaults)'}",
        "XU11  VADJ VDDIO LSW_EN 0 SW_TPS22916"
        + (f" PARAMS:{param_map.params_string('TPS22916CNYFPR')}" if param_map.applied('TPS22916CNYFPR') else ""),
        _output_caps_block(vddio_caps, "VDDIO"),
    ]

    # --- Analysis ----------------------------------------------------------
    trace_specs: dict[str, list[str]] = {}
    if mode == "op":
        analysis = """.control
op
print v(v3v3) v(vout) v(vadj) v(vddio) v(ldo_en) v(lsw_en)
print i(v3v3)
.endc
"""
    elif mode == "powerup":
        # i(vsns_ldo) is the LDO output current → inrush during the ramp.
        # Window covers the real load-switch turn-on (TPS22916 tON ~3ms),
        # which is far slower than the LDO soft-start.
        analysis = """.control
tran 2u 9m uic
wrdata powerup.dat v(v3v3) v(vout) v(vadj) v(vddio) v(ldo_en) v(lsw_en) i(vsns_ldo)
.endc
"""
        trace_specs["powerup"] = ["v(v3v3)", "v(vout)", "v(vadj)", "v(vddio)",
                                   "v(ldo_en)", "v(lsw_en)", "i(vsns_ldo)"]
    elif mode == "load_step":
        # Pre-bias the rails to their steady state, then watch the step.
        # We don't probe load current — it's set deterministically by the PWL
        # source and ngspice can't reach into subcircuit branch currents
        # without explicit .save directives.
        # Window must outlast the load-switch turn-on (TPS22916 tON ~3ms) so the
        # rail is fully settled before the step at 8ms — otherwise droop is
        # measured against a still-ramping rail.
        analysis = """.control
tran 1u 11m
wrdata load_step.dat v(vddio) v(vout) v(vadj)
.endc
"""
        trace_specs["load_step"] = ["v(vddio)", "v(vout)", "v(vadj)"]
    elif mode == "line_reg":
        # Sweep the +3V3 source across its tolerance; the output must stay
        # regulated. VV3V3_SRC is the source emitted by the RailIn stub.
        analysis = """.control
dc VV3V3_SRC 3.0 3.6 0.02
wrdata line_reg.dat v(vout) v(vddio)
.endc
"""
        trace_specs["line_reg"] = ["v(vout)", "v(vddio)"]
    else:
        raise ValueError(f"unknown mode: {mode!r}")

    deck = "\n".join([head, *bnd_lines, *blocks, "", analysis, ".end"])
    return deck, trace_specs


# ---------------------------------------------------------------------------
# Result analysis — turn raw waveforms into PASS/FAIL margins.


def analyze_op_point(op: dict[str, float], *, vout_set: float = 1.8) -> dict:
    """Score a DC op-point result against expected rail values."""
    rails = {
        "v(v3v3)":  ("+3V3 input",  3.3,  0.05),
        "v(vout)":  ("LDO_OUT",     vout_set, 0.05),
        "v(vadj)":  ("VADJ",        vout_set, 0.05),
        "v(vddio)": ("+VDDIO",      vout_set, 0.10),  # +Rdson drop
    }
    findings = []
    for k, (label, expected, tol) in rails.items():
        v = op.get(k)
        if v is None:
            findings.append({"rail": label, "status": "MISSING", "expected": expected})
            continue
        err = abs(v - expected)
        findings.append({
            "rail": label, "node": k, "expected_V": expected,
            "measured_V": v, "abs_err_V": err,
            "status": "OK" if err <= tol else "OUT_OF_BAND",
            "tol_V": tol,
        })
    return {"check": "dc_op_point", "rails": findings,
            "overall": "OK" if all(f.get("status") == "OK" for f in findings) else "FAIL"}


def analyze_load_step(trace, *, vout_set: float = 1.8,
                       droop_limit_V: float = 0.05,
                       recovery_limit_s: float = 100e-6) -> dict:
    """Quantify droop + recovery on +VDDIO after the load step.

    The step instant is auto-detected as the sharpest downward sample-to-
    sample change, so the analysis doesn't depend on knowing t_step (which
    lives in the catalog) and is immune to slow soft-start creep before it.
    """
    import numpy as np
    t = trace.col("time")
    v = trace.col("v(vddio)")
    dv = np.diff(v)
    step_idx = int(np.argmin(dv))          # sharpest drop = the load step
    t_step = float(t[step_idx])
    v_pre = float(v[step_idx])             # level just before the drop
    v_min = float(np.min(v[step_idx:]))
    droop = v_pre - v_min
    recovery_band = v_pre - droop_limit_V / 2
    t_recover = None
    for i in range(step_idx, len(t)):
        if v[i] >= recovery_band:
            t_recover = float(t[i] - t_step)
            break
    return {
        "check": "load_step",
        "t_step_detected_s": t_step,
        "v_pre_step_V": v_pre,
        "v_min_post_step_V": v_min,
        "droop_V": droop,
        "droop_limit_V": droop_limit_V,
        "droop_status": "OK" if droop <= droop_limit_V else "FAIL",
        "recovery_time_s": t_recover,
        "recovery_limit_s": recovery_limit_s,
        "recovery_status": "OK" if (t_recover is not None and t_recover <= recovery_limit_s) else "FAIL",
        "overall": "OK" if (droop <= droop_limit_V and t_recover is not None
                            and t_recover <= recovery_limit_s) else "FAIL",
    }


def analyze_powerup(trace, *, vout_set: float = 1.8,
                    inrush_limit_A: float = 1.0) -> dict:
    """Check rails sequence (VOUT before VDDIO) and inrush stays bounded."""
    import numpy as np
    t = trace.col("time")
    vout = trace.col("v(vout)")
    vddio = trace.col("v(vddio)")
    thresh = 0.9 * vout_set

    def first_cross(y):
        idx = np.where(y >= thresh)[0]
        return float(t[idx[0]]) if len(idx) else None

    t_vout = first_cross(vout)
    t_vddio = first_cross(vddio)
    ordered = (t_vout is not None and t_vddio is not None and t_vout < t_vddio)

    peak_inrush = None
    if "i(vsns_ldo)" in trace.columns:
        peak_inrush = float(np.max(np.abs(trace.col("i(vsns_ldo)"))))
    inrush_ok = peak_inrush is None or peak_inrush <= inrush_limit_A

    return {
        "check": "powerup_sequencing",
        "vout_settle_s": t_vout,
        "vddio_settle_s": t_vddio,
        "sequence_ok": ordered,
        "peak_inrush_A": peak_inrush,
        "inrush_limit_A": inrush_limit_A,
        "inrush_status": "OK" if inrush_ok else "FAIL",
        "overall": "OK" if (ordered and inrush_ok) else "FAIL",
    }


def analyze_line_regulation(trace, *, vout_set: float = 1.8,
                            max_dvout_V: float = 0.010) -> dict:
    """Output must stay regulated as +3V3 sweeps across its tolerance."""
    import numpy as np
    vin = trace.col("time")          # DC sweep → first column is the swept Vin
    vout = trace.col("v(vout)")
    vout_span = float(np.max(vout) - np.min(vout))
    # line regulation in mV/V over the swept input range
    vin_span = float(np.max(vin) - np.min(vin)) or 1.0
    line_reg_mV_per_V = (vout_span / vin_span) * 1e3
    mean_err = float(abs(np.mean(vout) - vout_set))
    ok = vout_span <= max_dvout_V and mean_err <= 0.05
    return {
        "check": "line_regulation",
        "vin_min_V": float(np.min(vin)),
        "vin_max_V": float(np.max(vin)),
        "vout_span_V": vout_span,
        "line_reg_mV_per_V": line_reg_mV_per_V,
        "max_dvout_V": max_dvout_V,
        "overall": "OK" if ok else "FAIL",
    }


def simulate_setpoint_coverage(setpoints=None) -> dict:
    """Run a DC op-point at each selectable LDO output and confirm every rail
    regulates with dropout headroom. Multiple fast ngspice runs (one per
    setpoint), aggregated into one table — the ANY-OUT part exposes several
    rails and each must be verified, not just the nominal."""
    from ..runner import run_deck
    setpoints = setpoints or SETPOINT_RAILS_V
    rows = []
    all_ok = True
    for sp in setpoints:
        deck, _ = build_deck(mode="op", vout_set=sp)
        res = run_deck(deck)
        measured = res.op_point.get("v(vout)")
        err = abs(measured - sp) if measured is not None else None
        headroom = 3.3 - sp  # +3V3 input minus target (dropout ~0.2V)
        ok = (err is not None and err <= 0.05 and headroom >= 0.3)
        all_ok = all_ok and ok
        rows.append({
            "setpoint_V": sp,
            "measured_V": measured,
            "err_V": err,
            "headroom_V": round(headroom, 3),
            "status": "OK" if ok else "FAIL",
        })
    return {"check": "setpoint_coverage", "setpoints": rows,
            "overall": "OK" if all_ok else "FAIL"}
