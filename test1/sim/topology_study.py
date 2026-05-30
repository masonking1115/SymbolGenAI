#!/usr/bin/env python3
"""Bias-loop TOPOLOGY trade study (throwaway experiment, not wired into review).

The production opa_bias loop (single-supply OPA2388 servoing a high-side PMOS,
I = (3.3 - V_DAC)/R_sense) cannot reach the 0-640 µA spec: near full scale the
op-amp output (the PMOS gate) must swing toward/below GND, but a single-supply
RRIO part bottoms out ~20 mV above its V-, so the loop rails at ~484 µA (75% of
range). Lowering R_sense rescales the current but knocks the 320 µA nominal point
off and doesn't change the railing fraction.

This script models the candidate FIXES in SPICE and measures each against the
three acceptance numbers, reusing the SAME behavioral models as production
(models.opa_models) and the SAME ngspice runner, so the comparison is apples to
apples with the validated baseline:

    1. Regulated full-scale ceiling   >= 640 µA   (the headline failure)
    2. Current at the 320 µA nominal   within 1%   (with BIAS0 held at 0.5 V)
    3. PMOS pass-element drain          >= 0.5 V    (DUT compliance headroom)

Candidates:
  baseline  — single-supply OPA2388, R=5.11k (the as-built design, for reference)
  opt_a     — Option A: add a small NEGATIVE op-amp rail (V- = -0.5 V) so the
              gate can swing below GND; everything else identical, R=5.11k.
  opt_b     — Option B: op-amp servos a LOW-SIDE NMOS across a low-side sense R
              (op-amp output swings UP — no headroom problem on a single supply),
              and a PMOS current mirror reflects that current to the high-side
              BIAS0 output. Introduces mirror matching as a new error term.

Run:  python -m test1.sim.topology_study
"""

from __future__ import annotations

import numpy as np

from .models import opa_models
from .runner import run_deck

VDD = 3.3
R_SENSE = 5110.0
NOMINAL_A = 320e-6
COMPLIANCE_V = 0.5
SPEC_FS_A = 640e-6
ERR_LIMIT = 0.01

# DC sweep grid for V_DAC. Finer than production (0.01 V) so the nominal-point
# pick isn't a grid artifact — we want the topology verdict, not a sweep-step one.
SWEEP = "dc VDAC 0 3.3 0.01"


def _ideal(v_dac: float, r: float = R_SENSE) -> float:
    return max(0.0, (VDD - v_dac) / r)


# ---------------------------------------------------------------------------
# Deck builders. Each holds BIAS0 at the 0.5 V DUT compliance point (the honest
# load) and writes i(vsns_bias), v(biasd) [PMOS drain], v(opaout) so we can score
# the regulated ceiling, nominal current, and drain headroom in one sweep.

def _baseline_deck(*, vee: float = 0.0, r: float = R_SENSE) -> str:
    """Single-supply (vee=0) or negative-rail (vee<0) high-side PMOS loop.
    Option A is just this with vee=-0.5."""
    return f"""* topology study — high-side PMOS loop (vee={vee})
{opa_models()}

VV3V3 V3V3 0 DC {VDD}
VVEE  VEE  0 DC {vee}
VDAC  VDAC 0 DC 0
* OPA2388: OUT=OPAOUT +IN=VDAC -IN=VSENSE V+=V3V3 V-=VEE
XOPA OPAOUT VDAC VSENSE V3V3 VEE OPA2388
* PMOS pass element: D=BIASD G=OPAOUT S=VSENSE  (body to V3V3)
MQ40 BIASD OPAOUT VSENSE V3V3 PMOS_PMZ1200
* sense R: VSENSE -> +3V3 (feedback samples VSENSE)
RSENSE VSENSE V3V3 {r:.6g}
* 2N7002 isolator (gate held on): D=BIASD G=ISO S=BIASO
VISO ISO 0 DC {VDD}
MQ42 BIASD ISO BIASO 0 NMOS_2N7002
* ammeter into the BIAS output node
VSNS_BIAS BIASO BIAS0 0
* DUT compliance: hold BIAS0 at 0.5 V
VBIASCOMP BIAS0 0 DC {COMPLIANCE_V}

.control
{SWEEP}
wrdata study.dat i(vsns_bias) v(biasd) v(opaout) v(vsense)
.endc
.end
""".strip()


def _mirror_deck(*, r: float = R_SENSE) -> str:
    """Option B — low-side NMOS sense + PMOS current mirror.

    The op-amp servos a low-side NMOS so that V(across low-side R) = V_ref, with
    V_ref = (VDD - V_DAC) (so the same DAC code → same target current, inverse
    map preserved). The op-amp output swings UP from GND — no single-supply
    headroom problem. The reference-leg current is mirrored by a matched PMOS
    pair to the high-side output into BIAS0.

    I_ref = (VDD - V_DAC)/R. The mirror copies I_ref to the output leg; matching
    error (KP/area mismatch, Early effect) is the new accuracy term — modeled
    here with IDENTICAL mirror FETs (best case) so we measure the topology's
    headroom first; a mismatch sweep is the obvious follow-up.
    """
    return f"""* topology study — Option B: low-side sense + PMOS current mirror
{opa_models()}

VV3V3 V3V3 0 DC {VDD}
VDAC  VDAC 0 DC 0
* Inverse map preserved: target current I_ref = (VDD - V_DAC)/R, programmed as a
* reference voltage VREF = (VDD - V_DAC) across a GROUND-referenced sense R so the
* op-amp output swings UP (single-supply friendly).
BVREF VREF 0 V = {VDD} - V(VDAC)
* Op-amp servos NMOS gate so V(RS_top)=VREF; NMOS sinks I_ref=VREF/R through RS.
* OUT=NG +IN=VREF -IN=RST
XOPA NG VREF RST V3V3 0 OPA2388
RS    RST 0 {r:.6g}
* The NMOS sinks I_ref; its drain pulls current through the mirror DIODE leg.
* Mirror reference: PMOS diode MPREF (gate=drain=MGATE), source=VDD. The NMOS
* drain ties to MGATE, so I(MPREF) = I_ref and MGATE self-biases.
MNLS  MGATE NG RST 0 NMOS_2N7002
MPREF MGATE MGATE V3V3 V3V3 PMOS_PMZ1200
* Mirror output: MPOUT gate=MGATE, source=VDD -> copies I_ref to BIASD.
MPOUT BIASD MGATE V3V3 V3V3 PMOS_PMZ1200
* isolator + ammeter into BIAS0 (held at 0.5 V compliance)
VISO ISO 0 DC {VDD}
MQ42 BIASD ISO BIASO 0 NMOS_2N7002
VSNS_BIAS BIASO BIAS0 0
VBIASCOMP BIAS0 0 DC {COMPLIANCE_V}

.control
{SWEEP}
wrdata study.dat i(vsns_bias) v(biasd) v(ng) v(rst)
.endc
.end
""".strip()


# ---------------------------------------------------------------------------

def _score(trace, r: float = R_SENSE) -> dict:
    """Compute the three acceptance numbers from a swept trace.
    Regulated = op-amp output off both rails (its swing isn't pinned)."""
    v_dac = trace.col("time")               # DC sweep var
    i_meas = trace.col("i(vsns_bias)")
    biasd = trace.col("v(biasd)")
    # Pick the railing detector by what the deck wrote.
    swing = None
    for name in ("v(opaout)", "v(ng)"):
        if name in trace.columns:
            swing = trace.col(name)
            break
    ideal = np.array([_ideal(v, r) for v in v_dac])

    # Regulated band: where the controlling op-amp output is off both rails.
    # For the high-side loop the rail floor is the (possibly negative) VEE; we
    # detect railing as "output not pinned" via small slope of measured vs ideal.
    # Simplest robust proxy: regulated where measured tracks ideal within 5%.
    with np.errstate(divide="ignore", invalid="ignore"):
        track_err = np.where(ideal > 1e-9, np.abs(i_meas - ideal) / ideal, 1.0)
    regulated = track_err < 0.05

    i_max_reg = float(np.max(i_meas[regulated])) if regulated.any() else 0.0

    # current at the nominal operating point
    v_nom = VDD - NOMINAL_A * r
    j = int(np.argmin(np.abs(v_dac - v_nom)))
    i_at_nom = float(i_meas[j])
    nom_err = abs(i_at_nom - NOMINAL_A) / NOMINAL_A

    # worst tracking error over the regulated band
    worst = float(np.max(track_err[regulated])) if regulated.any() else 1.0

    # drain headroom over the regulated band (must stay >= 0.5 V)
    drain_min = float(np.min(biasd[regulated])) if regulated.any() else float("nan")

    return {
        "full_scale_ideal_uA": round(VDD / r * 1e6, 1),
        "i_max_regulated_uA": round(i_max_reg * 1e6, 1),
        "reaches_640uA": i_max_reg >= SPEC_FS_A,
        "i_at_nominal_uA": round(i_at_nom * 1e6, 2),
        "nominal_err_pct": round(nom_err * 100, 3),
        "nominal_ok": nom_err <= ERR_LIMIT,
        "worst_reg_err_pct": round(worst * 100, 3),
        "pmos_drain_min_V": None if np.isnan(drain_min) else round(drain_min, 4),
        "drain_ok": (not np.isnan(drain_min)) and drain_min >= COMPLIANCE_V,
    }


# Exact vector list each deck's `wrdata` writes, in order (these become the
# Trace column names — must match the wrdata line or _read_wrdata mislabels).
_VECS = {
    "baseline": ["i(vsns_bias)", "v(biasd)", "v(opaout)", "v(vsense)"],
    "mirror":   ["i(vsns_bias)", "v(biasd)", "v(ng)", "v(rst)"],
}


def _run(name: str, deck: str, vecs: list[str], r: float = R_SENSE) -> dict:
    res = run_deck(deck, trace_specs={"study": vecs})
    if not res.traces or "study" not in res.traces:
        return {"name": name, "error": (res.stderr or "no trace")[:400]}
    s = _score(res.traces["study"], r)
    s["name"] = name
    return s


# (build_fn, vectors, R_sense) per candidate. The headline experiment is the
# R_sense reduction — the TRUE binding constraint is the I*R_sense voltage budget
# (640µA needs 3.27V across 5.11k, leaving nothing for PMOS V_SD + the 0.5V DUT),
# NOT op-amp swing. So lowering R is the physics fix; the negative rail (Option A)
# can't help because the limit is downstream of the gate. Option B trades the
# budget for mirror matching. We also show 5.11k+neg-rail to PROVE it doesn't help.
CANDIDATES = {
    "baseline single-supply 5.11k":        (lambda: _baseline_deck(vee=0.0), _VECS["baseline"], 5110.0),
    "Option A neg-rail (V-=-1.0V) 5.11k":  (lambda: _baseline_deck(vee=-1.0), _VECS["baseline"], 5110.0),
    "R-fix 3.65k single-supply":           (lambda: _baseline_deck(vee=0.0, r=3650.0), _VECS["baseline"], 3650.0),
    "R-fix 3.32k single-supply":           (lambda: _baseline_deck(vee=0.0, r=3320.0), _VECS["baseline"], 3320.0),
    "Option B mirror 3.65k":               (lambda: _mirror_deck(r=3650.0), _VECS["mirror"], 3650.0),
}


def main() -> int:
    print("Bias-loop topology trade study — acceptance: FS>=640µA, nom 320µA±1%, drain>=0.5V")
    print("(root cause: 640µA across R_sense must fit in 3.3V minus the 0.5V DUT compliance + pass-device headroom)\n")
    rows = []
    for name, (build, vecs, r) in CANDIDATES.items():
        rows.append(_run(name, build(), vecs, r))
    hdr = f"{'topology':<42} {'FS_ideal':>9} {'i_max_reg':>10} {'>=640?':>7} {'i@nom':>9} {'nom_err':>8} {'drain_min':>10} {'VERDICT':>8}"
    print(hdr)
    print("-" * len(hdr))
    for s in rows:
        if "error" in s:
            print(f"{s['name']:<42}  ERROR: {s['error']}")
            continue
        ok = s["reaches_640uA"] and s["nominal_ok"] and s["drain_ok"]
        verdict = "PASS" if ok else "fail"
        print(f"{s['name']:<42} {s['full_scale_ideal_uA']:>8.0f}u "
              f"{s['i_max_regulated_uA']:>9.1f}u {('yes' if s['reaches_640uA'] else 'no'):>7} "
              f"{s['i_at_nominal_uA']:>8.1f}u {s['nominal_err_pct']:>7.2f}% "
              f"{(str(s['pmos_drain_min_V'])+'V'):>10} {verdict:>8}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
