"""Boundary-stub library.

A *boundary stub* is the SPICE stand-in for everything outside the slice
of circuit currently being simulated. When we cut the schematic at a
hier-label / power net, each cut edge needs something on the far side:
a source for incoming rails/signals, a load for outgoing ones.

These are deliberately small and readable. Each stub is a dataclass with
an `.emit()` method returning SPICE text. The deck builder loops over a
block's boundary assignments (see blocks.yaml), instantiates the named
stub with the given params, and concatenates the emitted SPICE.

Parameters are filled from datasheets (cheap default) or, later, from an
auto-extracted envelope of a prior sim of the source block. The shapes
here don't change; only the parameters do.

Naming convention: every stub names its SPICE elements with the boundary
node as a suffix so two stubs on different nets never collide.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RailIn:
    """Incoming supply rail: finite-impedance source + optional ripple.

    Covers: +3V3 from the FMC carrier, or any regulated rail entering the
    block from upstream. R_src models connector + trace resistance so the
    block sees realistic rail sag under load.
    """
    node: str
    V: float = 3.3
    R_src: float = 0.020
    ripple_mV: float = 0.0
    ripple_hz: float = 100e3

    def emit(self) -> str:
        sin = (f" AC 1 SIN({self.V} {self.ripple_mV/1000:.4g} {self.ripple_hz:.4g})"
               if self.ripple_mV else " AC 1")
        return (f"V{self.node}_SRC {self.node}_RAW 0 DC {self.V}{sin}\n"
                f"R{self.node}_SRC {self.node}_RAW {self.node} {self.R_src:.4g}")


@dataclass
class RailOut:
    """Downstream load on a rail this block generates.

    Covers: +VDDIO / +VDDD / +VDDA* loads (the Bobcat side). base current
    plus an optional step for load-transient tests. Edge time matters for
    droop, so it's exposed.

    A constant-current load is the right model once the rail is up (op-point,
    load-step), but it's unphysical *during* power-up — a current sink would
    try to pull I_base even at 0V and drag the node negative before the rail
    comes alive. For sequencing tests set R_load instead, so the current
    naturally tracks the rising rail (I = V/R).
    """
    node: str
    I_base: float = 0.010
    I_step: float = 0.0
    t_step: float = 500e-6
    edge: float = 100e-9
    R_load: float | None = None

    def emit(self) -> str:
        if self.R_load is not None:
            return f"R{self.node}_LOAD {self.node} 0 {self.R_load:.4g}"
        if self.I_step:
            return (f"B{self.node}_LOAD {self.node} 0 "
                    f"I={self.I_base:.4g} + {self.I_step:.4g}"
                    f"*u(time-{self.t_step:.4g})"
                    f"*min(1,(time-{self.t_step:.4g})/{self.edge:.4g})")
        return f"I{self.node}_LOAD {self.node} 0 DC {self.I_base:.4g}"


@dataclass
class DigitalDrive:
    """A digital control input driven from outside (FPGA via FMC).

    Covers: LDO_EN, LSW_EN, LDO_SET_* selects. Clean ramp from 0 to V_hi at
    t_on. For a static-high enable, leave t_on at 0.
    """
    node: str
    V_hi: float = 3.3
    t_on: float = 100e-6
    edge: float = 1e-6

    def emit(self) -> str:
        if self.t_on <= 0:
            return f"V{self.node}_DRV {self.node} 0 DC {self.V_hi}"
        return (f"V{self.node}_DRV {self.node} 0 "
                f"PWL(0 0 {self.t_on:.4g} 0 {self.t_on+self.edge:.4g} {self.V_hi})")


@dataclass
class DigitalOut:
    """A digital output we only observe (open-drain PG, CLK_OUT*, etc.).

    Nothing to source — high-Z. The deck builder is expected to add a
    `wrdata` probe on this node. An optional pull resistor models the
    external pull on open-drain outputs like LDO_PG.
    """
    node: str
    pull_to: str | None = None   # e.g. "V3V3"; None = no external pull
    R_pull: float = 10e3

    def emit(self) -> str:
        if self.pull_to:
            return f"R{self.node}_PULL {self.node} {self.pull_to} {self.R_pull:.4g}"
        return f"* monitor-only boundary on {self.node} (high-Z)"


@dataclass
class AnalogInRC:
    """Slow analog input with finite slew (single-pole RC).

    Covers: a DAC/reference feeding the block where ramp rate matters.
    tau = R * C. Drive V can be made a PWL externally for step tests.
    """
    node: str
    V: float = 1.0
    R: float = 1e3
    C: float = 100e-12

    def emit(self) -> str:
        return (f"V{self.node}_SRC {self.node}_RAW 0 DC {self.V}\n"
                f"R{self.node}_SRC {self.node}_RAW {self.node} {self.R:.4g}\n"
                f"C{self.node}_SRC {self.node} 0 {self.C:.4g}")


@dataclass
class AnalogOutLoad:
    """R||C load standing in for a downstream analog input.

    Covers: BIAS0/BIAS1 into the Bobcat bias pins. R_load sets the DC
    operating current; C_load sets the settling pole the driver sees.
    """
    node: str
    R_load: float = 10e3
    C_load: float = 10e-12

    def emit(self) -> str:
        return (f"R{self.node}_LD {self.node} 0 {self.R_load:.4g}\n"
                f"C{self.node}_LD {self.node} 0 {self.C_load:.4g}")


# Registry so blocks.yaml can reference stubs by name. The deck builder
# does STUB_REGISTRY[name](node=net, **params).emit().
STUB_REGISTRY: dict[str, type] = {
    "RailIn": RailIn,
    "RailOut": RailOut,
    "DigitalDrive": DigitalDrive,
    "DigitalOut": DigitalOut,
    "AnalogInRC": AnalogInRC,
    "AnalogOutLoad": AnalogOutLoad,
}


def emit_stub(name: str, node: str, params: dict | None = None) -> str:
    """Instantiate a stub by name and return its SPICE text."""
    if name not in STUB_REGISTRY:
        raise KeyError(f"unknown stub {name!r}; known: {sorted(STUB_REGISTRY)}")
    return STUB_REGISTRY[name](node=node, **(params or {})).emit()
