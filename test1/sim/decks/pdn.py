"""PDN deck builder — decoupling-network adequacy for a powered rail.

Parameterized by rail name so VDDIO / VDDD share one builder. Each
decoupling cap is modeled as a series R-L-C branch (ESR + ESL + C) — a bare
capacitor would show zero impedance at resonance and hide the anti-resonance
peaks, so ESR/ESL are essential for a meaningful PDN result.

Modes:
    load_step      — harsh, fast load step; measure droop. This is the
                     sensitive test that exposes MISSING decoupling (e.g. a
                     dropped C29) — the one the design-review path otherwise
                     relies on a human/LLM to catch.
    pdn_impedance  — inject 1A AC into the rail, measure |Z(f)| across the
                     band; decoupling must keep it under the target.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..catalog import resolve_boundaries

NETLIST_DIR = Path(__file__).resolve().parents[2] / "netlist"

_SI = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3}

# Each PDN block id → (rail net name, SPICE node, sheets to scan for caps).
RAIL_OF_BLOCK = {
    "vddio_pdn": ("+VDDIO", "VDDIO", ["power", "bobcat"]),
    "vddd_pdn":  ("+VDDD",  "VDDD",  ["bobcat"]),
}


def _parse_value(s: str) -> float:
    s = str(s).strip().rstrip("Ff")
    import re
    m = re.match(r"^([\d.]+)\s*([a-zA-Z]*)$", s)
    if not m:
        return float(s)
    num, suf = m.group(1), m.group(2).lower()
    return float(num) * (_SI.get(suf[0], 1.0) if suf else 1.0)


def _rail_caps(rail: str, sheets: list[str]) -> list[tuple[str, float]]:
    """Collect (refdes, C) for caps whose pin .1 sits on `rail`."""
    out: list[tuple[str, float]] = []
    for sheet in sheets:
        data = yaml.safe_load((NETLIST_DIR / f"{sheet}.yaml").read_text())
        members = set(data.get("nets", {}).get(rail, {}).get("members", []) or [])
        parts = data.get("parts", {})
        for ref, spec in parts.items():
            if not ref.startswith("C") or f"{ref}.1" not in members:
                continue
            val = spec.get("value") if isinstance(spec, dict) else None
            if val is not None:
                out.append((ref, _parse_value(val)))
    return out


def _cap_esr(C: float) -> float:
    """Rough 0402 MLCC ESR by value — bigger caps have lower ESR."""
    if C >= 10e-6:
        return 0.003
    if C >= 1e-6:
        return 0.010
    return 0.030


def _cap_rlc(ref: str, C: float, node: str, esl: float = 0.5e-9) -> str:
    esr = _cap_esr(C)
    return (f"L{ref} {node} {ref}_a {esl:.3e}\n"
            f"R{ref} {ref}_a {ref}_b {esr:.4g}\n"
            f"C{ref} {ref}_b 0 {C:.3e}")


def build_deck(*, block_id: str, mode: str) -> tuple[str, dict[str, list[str]]]:
    if block_id not in RAIL_OF_BLOCK:
        raise ValueError(f"no PDN rail mapping for {block_id!r}")
    rail, node, sheets = RAIL_OF_BLOCK[block_id]
    caps = _rail_caps(rail, sheets)

    sim_type = {"load_step": "transient_load_step",
                "impedance": "ac_pdn_impedance"}[mode]

    head = (f"* test1 sim — PDN ({rail}) — {len(caps)} decoupling caps "
            f"(R-L-C each)\n")

    # Source feeding the rail (VRM/switch output). Critically this is R_src in
    # SERIES WITH L_src, not a flat resistor: a real VRM holds its output
    # impedance low only up to its control-loop bandwidth (tens–hundreds of
    # kHz); above the R/L corner the supply path goes inductive and it's the
    # DECOUPLING CAPS that hold the rail. Modeling the source as a flat low-Z
    # resistor (the previous bug) let the source mask the caps, so removing
    # caps changed nothing. With L_src, the cap bank determines mid/high-freq
    # Z and load-step droop — which is the whole point of the PDN check.
    # No `AC 1` on the source: it must be an AC short for the 1A Z(f) probe.
    rail_params = resolve_boundaries(block_id, sim_type)[rail]["params"]
    v_rail = rail_params.get("V", 1.8)
    r_src = rail_params.get("R_src", 0.01)
    l_src = rail_params.get("L_src", 10e-9)   # supply-path inductance (layout estimate)
    bnds = [
        "* Rail source (VRM/switch output): R_src + L_src (inductive above R/L corner)",
        f"VSRC {node}_RAW 0 DC {v_rail}",
        f"RSRC {node}_RAW {node}_si {r_src:.4g}",
        f"LSRC {node}_si {node} {l_src:.3e}",
    ]

    cap_lines = [f"* Decoupling network on {rail}"]
    for ref, C in caps:
        cap_lines.append(_cap_rlc(ref, C, node))

    trace_specs: dict[str, list[str]] = {}
    if mode == "load_step":
        # No `uic`: ngspice solves the DC op-point first so the rail starts
        # pre-charged (load = 50mA baseline), then we step at 0.2ms. Edge is
        # 100ns, resolved by the 20ns max timestep.
        load = ("* Harsh load step (exposes missing decoupling)\n"
                f"BLOAD {node} 0 I=0.05 + 0.20*u(time-0.2m)"
                f"*min(1,(time-0.2m)/100n)")
        analysis = f""".control
tran 20n 0.4m
wrdata pdn_load_step.dat v({node.lower()})
.endc
"""
        trace_specs["pdn_load_step"] = [f"v({node.lower()})"]
    elif mode == "impedance":
        load = ("* AC current injection: |Z(f)| = V(rail)/1A\n"
                f"IAC {node} 0 AC 1")
        analysis = f""".control
ac dec 40 1k 200meg
wrdata pdn_impedance.dat vdb({node.lower()})
.endc
"""
        trace_specs["pdn_impedance"] = [f"vdb({node.lower()})"]
    else:
        raise ValueError(f"unknown mode: {mode!r}")

    deck = "\n".join([head, *bnds, "", *cap_lines, "", load, "", analysis, ".end"])
    return deck, trace_specs


# ---------------------------------------------------------------------------
# Analyzers


def analyze_load_step(trace, node: str, *, droop_limit_V: float = 0.030) -> dict:
    import numpy as np
    t = trace.col("time")
    v = trace.col(f"v({node.lower()})")
    dv = np.diff(v)
    step_idx = int(np.argmin(dv))
    v_pre = float(v[step_idx])
    v_min = float(np.min(v[step_idx:]))
    droop = v_pre - v_min
    return {
        "check": "pdn_load_step",
        "v_pre_V": v_pre,
        "v_min_V": v_min,
        "droop_V": droop,
        "droop_mV": round(droop * 1e3, 3),
        "droop_limit_V": droop_limit_V,
        "overall": "OK" if droop <= droop_limit_V else "FAIL",
    }


def analyze_impedance(trace, node: str, *, z_limit_ohm: float = 0.1) -> dict:
    """|Z(f)| from injecting 1A: V(node) in volts == ohms. wrdata gives dB
    (vdb = 20log10|V|), so |Z| = 10**(dB/20)."""
    import numpy as np
    f = trace.col("time")                  # AC sweep var = frequency
    zdb = trace.col(f"vdb({node.lower()})")
    zmag = 10 ** (zdb / 20.0)
    peak_idx = int(np.argmax(zmag))
    return {
        "check": "pdn_impedance",
        "z_max_ohm": float(zmag[peak_idx]),
        "z_max_mohm": round(float(zmag[peak_idx]) * 1e3, 2),
        "f_at_z_max_Hz": float(f[peak_idx]),
        "z_limit_ohm": z_limit_ohm,
        "overall": "OK" if zmag[peak_idx] <= z_limit_ohm else "FAIL",
    }
