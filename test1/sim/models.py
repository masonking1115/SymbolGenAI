"""Behavioral SPICE models for the test1 active parts.

These are stand-ins, not vendor models — datasheet-derived enough to give
the AI/critic meaningful margin numbers, but they will NOT catch silicon-
level effects (saturation curves, charge injection, etc.). Replace with
vendor .lib files as they become available.

Each builder returns a SPICE subcircuit definition as a string. Node order
on the subcircuit line is documented at the top of each builder.
"""

from __future__ import annotations


def ldo_tps7a8401a() -> str:
    """TPS7A8401A — 1A ANY-OUT LDO, 3.3V in → programmable out.

    For the PoC we model:
      - An enable-gated output (EN > 1V → regulated; else 0).
      - Output voltage set by a control voltage on VSET node (0..1V mapped
        to 0.6..1.0V via behavioral source); for our setpoints we just pass
        in the desired output as a parameter via .param VOUT_SET.
      - Series output resistance (load regulation knob).
      - Quiescent current sink on IN.

    Subcircuit pins:  IN  OUT  EN  GND
    Parameters:       VOUT_SET (volts), DROPOUT (volts)
    """
    return r"""
* ---------- TPS7A8401A behavioral ----------
.subckt LDO_TPS7A8401A IN OUT EN GND PARAMS: VOUT_SET=1.8 DROPOUT=0.18 RO=0.005 TSS=100u LINE_REG=3e-5
* Enable comparator: 1 when EN > 1V, else 0
BEN  EN_GATE 0 V = u(V(EN)-1.0)
* Soft-start (NR_SS): RC ramp of SS toward the enable level (tau = TSS).
* Makes power-up + inrush physical instead of an instantaneous step; in DC
* the cap is open so SS settles exactly at the enable level (stable point).
BSSD SSD 0 V = V(EN_GATE)
RSS  SSD SS {TSS}
CSS  SS 0 1
* Headroom check: deliver min(VOUT_SET, V(IN)-DROPOUT), gated by soft-start.
* Finite line regulation: output drifts LINE_REG (V/V) with input vs the 3.3V
* nominal — so line_regulation has something real to measure (and can fail).
BHR  HEADROOM 0 V = V(IN) - DROPOUT
BVO  VOUT_TGT 0 V = min({VOUT_SET} + {LINE_REG}*(V(IN)-3.3), V(HEADROOM)) * V(EN_GATE) * min(1, max(0, V(SS)))
* Output stage: target voltage through small series R (load reg)
EOUT OUT_INT GND VOUT_TGT 0 1
RO   OUT_INT OUT {RO}
* Quiescent current on IN (~250µA typ)
IQ   IN GND DC 250u
.ends LDO_TPS7A8401A
""".strip()


def load_switch_tps22916() -> str:
    """TPS22916 — 5.5V/2A load switch, 38mΩ Rdson, controlled turn-on slew.

    The real part ramps its output (slew control) to limit inrush into the
    downstream caps. Modeled as a pass source whose output = VIN scaled by a
    soft-start ramp (RC, tau=TRISE), then Rdson to the output node — so the
    Rdson voltage drop under load is preserved while the turn-on is rate-
    limited. A hard SW element would (falsely) slam discharged caps and show
    tens of amps of inrush.

    Subcircuit pins:  VIN  VOUT  EN  GND
    """
    return r"""
* ---------- TPS22916 behavioral (slew-controlled) ----------
.subckt SW_TPS22916 VIN VOUT EN GND PARAMS: RDSON=0.1 TRISE=200u
* Enable → soft-start ramp SS: 0->1 over TRISE (RC; settles at 1 in DC)
BENT ENT 0 V = u(V(EN)-1.0)
RSS  ENT SS {TRISE}
CSS  SS 0 1
* Slew-limited pass: VOUT follows VIN*SS through Rdson (drop = I*Rdson)
BPASS VO_INT 0 V = V(VIN) * min(1, max(0, V(SS)))
RON   VO_INT VOUT {RDSON}
.ends SW_TPS22916
""".strip()


def current_sink(name: str = "ISINK") -> str:
    """A PWL-controlled current sink for load-step transients.

    Subcircuit pins:  NODE  GND
    Parameters:       I_BASE (A), I_STEP (A), T_STEP (s), T_RISE (s)
    """
    return rf"""
* ---------- Programmable current sink ----------
.subckt {name} NODE GND PARAMS: I_BASE=0.01 I_STEP=0.1 T_STEP=1m T_RISE=1u
BISRC NODE GND I = {{I_BASE}} + {{I_STEP}} * u(time - {{T_STEP}}) * min(1, (time-{{T_STEP}})/{{T_RISE}})
.ends {name}
""".strip()


def opa2388() -> str:
    """OPA2388 — zero-drift precision RRIO op-amp (single-pole behavioral).

    Single dominant pole sets GBW; output is rail-to-rail clamped with a
    finite output resistance. A capacitive load (e.g. a MOSFET gate) on the
    output forms a second pole, so closed-loop peaking / phase margin shows
    up naturally — which is what the stability sim looks for.

    NOT modeled: input voltage-noise density / 1-f corner (needs the
    datasheet noise curve), CMRR, and real offset distribution. So this is
    fine for bias accuracy / stability / settling, but a `.noise` run on it
    would be meaninglessly quiet.

    Pins:  OUT INP INN VCC VEE
    Params: AOL (V/V), GBW (Hz), VOS (V)
    """
    return r"""
* ---------- OPA2388 behavioral op-amp ----------
.subckt OPA2388 OUT INP INN VCC VEE PARAMS: AOL=3e6 GBW=10e6 VOS=15e-6
* gm input stage (gm=1mA/V); R1 sets DC gain (AOL=gm*R1); C1 sets pole (GBW=gm/2*pi*C1)
BGM  0 INT I = 1e-3*(V(INP)-V(INN)+{VOS})
R1   INT 0 {AOL/1e-3}
C1   INT 0 {1e-3/(2*3.141592653589793*GBW)}
* rail-to-rail clamped output buffer + output resistance
BOUT OUTB 0 V = max(min(V(INT), V(VCC)-0.02), V(VEE)+0.02)
ROUT OUTB OUT 50
.ends OPA2388
""".strip()


def mosfet_models() -> str:
    """Level-1 MOSFET .model cards for the bias pass element + isolator.

    Behavioral-grade — VTO/KP picked so the parts conduct the µA-to-mA bias
    currents in saturation with the gate drive the loop provides. In a
    feedback V-to-I the op-amp loop (not the FET) sets the accuracy, so the
    exact silicon params only affect loop dynamics, not the DC current.
    """
    return r"""
* ---------- MOSFET models (level 1, behavioral-grade) ----------
* PMZ1200: VGS(th) typ -0.7V, Ciss ~43pF (datasheet) — gate caps split CGSO/CGDO.
* 2N7002: VGS(th) 1-2.5V. Earlier CGSO=1n was ~25x too large and softened the
* op-amp loop's gate-load pole; corrected to datasheet-scale capacitance.
.model PMOS_PMZ1200 PMOS (VTO=-0.7 KP=0.2 LAMBDA=0.01 CGSO=30p CGDO=12p)
.model NMOS_2N7002  NMOS (VTO=1.6  KP=0.15 LAMBDA=0.01 CGSO=20p CGDO=6p)
""".strip()


def all_models() -> str:
    """LDO-rail model set (preamble for ldo_rail decks)."""
    return "\n\n".join([
        ldo_tps7a8401a(),
        load_switch_tps22916(),
        current_sink(),
    ])


def opa_models() -> str:
    """Bias-loop model set (preamble for opa_bias decks)."""
    return "\n\n".join([opa2388(), mosfet_models()])
