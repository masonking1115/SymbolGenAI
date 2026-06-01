#!/usr/bin/env python3
"""Fault-injection self-test — proves each sim has teeth.

A passing sim on a good design is worthless if it can't FAIL on a broken one.
This suite, for each gated sim, runs the NOMINAL design (expect PASS) and a
DELIBERATELY BROKEN variant (expect FAIL), and reports TEETH=yes only if the
verdict actually flips. Run it whenever the models or analyzers change:

    python3 test1/sim/fault_injection.py        # exit 0 iff every gate has teeth

Faults are injected by transforming the generated SPICE deck (or the cap
list), so they break the *design under test*, not the analyzer.

Sims with no fault case are listed explicitly as KNOWN-LIMITATION (they pass
by construction of the behavioral model — e.g. they need vendor data to fail
meaningfully). That's surfaced, not hidden.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test1.sim.decks import ldo_rail as L, opa_bias as B, pdn as P
from test1.sim.runner import run_deck


def _verdict(analysis) -> str:
    return (analysis or {}).get("overall", "ERR")


# --- nominal + faulted runners, returning the analysis "overall" verdict ----

def ldo_op(vout_set=1.8):
    deck, _ = L.build_deck(mode="op", vout_set=vout_set)
    return _verdict(L.analyze_op_point(run_deck(deck).op_point, vout_set=vout_set))

def _force_param(deck: str, model: str, param: str, value: str) -> str:
    """Force a param on the model INSTANCE line (starts with X) to `value`,
    whether or not it's already set. Must not touch the `.subckt` definition
    default — the instance value overrides it, so patching the def is a no-op."""
    out = []
    for line in deck.splitlines():
        if line.lstrip().startswith("X") and model in line:
            if re.search(rf"\b{param}=\S+", line):
                line = re.sub(rf"\b{param}=\S+", f"{param}={value}", line)
            elif "PARAMS:" in line:
                line = line.replace("PARAMS:", f"PARAMS: {param}={value}", 1)
            else:
                line = f"{line} PARAMS: {param}={value}"
        out.append(line)
    return "\n".join(out)


def ldo_line(line_reg=None):
    deck, specs = L.build_deck(mode="line_reg", vout_set=1.8)
    if line_reg is not None:
        deck = _force_param(deck, "LDO_TPS7A8401A", "LINE_REG", str(line_reg))
    res = run_deck(deck, trace_specs=specs)
    return _verdict(L.analyze_line_regulation(res.traces["line_reg"]))

def ldo_setpoint(setpoints=None):
    return _verdict(L.simulate_setpoint_coverage(setpoints))

def opa_dc(vos=None):
    deck, specs = B.build_deck(mode="dc_sweep")
    if vos is not None:
        deck = _force_param(deck, "OPA2388", "VOS", str(vos))
    res = run_deck(deck, trace_specs=specs)
    return _verdict(B.analyze_dc_sweep(res.traces["dc_sweep"]))

def opa_por(dac=None):
    # The DAC POR code is the SOLE off-by-default mechanism now (no isolation
    # FET — deck topology). Fault: DAC not at its safe full-scale code → the
    # PMOS turns partly on and bias leaks into the DUT at power-on.
    deck, specs = B.build_deck(mode="por")
    if dac is not None:
        deck = deck.replace("VDAC VDAC 0 DC 3.3", f"VDAC VDAC 0 DC {dac}")
    return _verdict(B.analyze_por(run_deck(deck, trace_specs=specs).op_point))

def pdn_loadstep(block="vddio_pdn", node="VDDIO", n_caps=None):
    orig = P._rail_caps
    if n_caps is not None:
        P._rail_caps = lambda rail, sheets: orig(rail, sheets)[:n_caps]
    try:
        deck, specs = P.build_deck(block_id=block, mode="load_step")
        res = run_deck(deck, trace_specs=specs)
        return _verdict(P.analyze_load_step(res.traces["pdn_load_step"], node))
    finally:
        P._rail_caps = orig


# --- the suite --------------------------------------------------------------
# Each: (label, nominal_fn, faulted_fn, fault_description)
CASES = [
    ("ldo_rail / dc_op_point",
     lambda: ldo_op(1.8), lambda: ldo_op(3.5),
     "setpoint 3.5V > Vin-dropout (3.1V) — violates headroom"),
    ("ldo_rail / line_regulation",
     lambda: ldo_line(), lambda: ldo_line(0.1),
     "line regulation degraded to 100mV/V"),
    ("ldo_rail / setpoint_coverage",
     lambda: ldo_setpoint(), lambda: ldo_setpoint([0.8, 3.2]),
     "a 3.2V setpoint with only 0.1V headroom"),
    ("opa_bias / dc_sweep (V-to-I accuracy)",
     lambda: opa_dc(), lambda: opa_dc("5m"),
     "op-amp input offset 15uV -> 5mV"),
    ("opa_bias / por_failsafe",
     lambda: opa_por(), lambda: opa_por(dac=1.0),
     "DAC not at safe full-scale code at POR -> PMOS partly on, bias leaks"),
    ("vddio_pdn / transient_load_step",
     lambda: pdn_loadstep("vddio_pdn", "VDDIO"),
     lambda: pdn_loadstep("vddio_pdn", "VDDIO", n_caps=1),
     "decoupling bank stripped from 6 caps to 1"),
    ("vddd_pdn / transient_load_step",
     lambda: pdn_loadstep("vddd_pdn", "VDDD"),
     lambda: pdn_loadstep("vddd_pdn", "VDDD", n_caps=1),
     "decoupling bank stripped to 1 cap"),
]

# Sims that pass by construction of the behavioral model — documented, not hidden.
KNOWN_LIMITATIONS = [
    ("ldo_rail / transient_powerup", "ordering is set by the modeled FPGA enable timing (stimulus), not autonomous"),
    ("opa_bias / ac_stability", "single-pole behavioral op-amp; margin reflects assumed GBW/poles, not silicon"),
    ("opa_bias / transient_settling", "same as ac_stability — dynamics are model parameters"),
    ("*_pdn / ac_pdn_impedance", "anti-resonance peak set by board L_src (layout); needs PCB extraction"),
]


def main() -> int:
    print("FAULT-INJECTION SELF-TEST — does each sim actually have teeth?\n")
    print(f"{'sim gate':42} {'nominal':8} {'faulted':8} teeth")
    print("-" * 72)
    all_teeth = True
    for label, nom_fn, fault_fn, desc in CASES:
        nom = nom_fn()
        flt = fault_fn()
        teeth = (nom == "OK" and flt == "FAIL")
        all_teeth = all_teeth and teeth
        mark = "YES" if teeth else "*** NO ***"
        print(f"{label:42} {nom:8} {flt:8} {mark}")
        print(f"{'':42} fault: {desc}")
    print("-" * 72)
    print("\nKNOWN LIMITATIONS (pass by model construction — need vendor/PCB data to fail):")
    for label, why in KNOWN_LIMITATIONS:
        print(f"  - {label}: {why}")
    print()
    if all_teeth:
        print("RESULT: every gated sim flips PASS->FAIL on a real defect. Teeth confirmed.")
    else:
        print("RESULT: *** at least one gated sim did NOT flip — it lacks teeth. ***")
    return 0 if all_teeth else 1


if __name__ == "__main__":
    sys.exit(main())
