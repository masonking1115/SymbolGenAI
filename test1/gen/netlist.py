"""Netlist loader — parses netlist/<sheet>.yaml into typed Python objects.

The YAML is the declarative source of truth for a sheet's parts and nets.
Layout (positions + wire routing) stays in gen/build_<sheet>.py. The validator
in gen/validator.py cross-checks that the layout's wire graph matches the
nets declared here.

Schema (per sheet):

    parts:
      <REFDES>:
        lib_id: <lib_id>           # required, e.g. "Device:R" or "Lib:24AA08-I-SN"
        value: <str>               # required, e.g. "10k" or "MCP4728"
        footprint: <str>           # optional but recommended
        dnp: <bool>                # optional, default false
        unit: <int>                # optional, default 1 (for multi-unit symbols)
        notes: <str>               # optional, design-intent commentary

    nets:
      <NET_NAME>:
        type: power | hier | global    # required
        direction: input | output | bidirectional | tri_state | passive
                                       # required for hier/global; omitted for power
        members: [<REFDES>.<PIN>, ...] # pin references; e.g. ["U30.8", "C30.1"]

Net types:
  power    — net is tied by power-symbol name across all sheets (GND, +3V3, …).
             Members may end up in different connected components on the sheet;
             each component just needs to be NAMED the same as the YAML net.
  hier     — net crosses the parent/child sheet boundary via a hier_label.
  global   — net spans 2+ sheets via global_label.
  internal — net is local-to-sheet AND unlabeled (e.g. an LDO OUT bus that
             only connects pins via wires, without an explicit label). All
             members must be in one connected component; no name check is
             performed. Use this to make every connectable pin reachable
             from the netlist YAML (so strict validation has full coverage).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

NETLIST_DIR = Path(__file__).resolve().parent.parent / "netlist"


@dataclass
class Part:
    refdes: str
    lib_id: str
    value: str
    footprint: str = ""
    dnp: bool = False
    units: list[int] = field(default_factory=lambda: [1])
    notes: str = ""


def parse_member(token: str) -> tuple[str, int, str]:
    """Parse a net-member reference.

    "U30.6"      → ("U30", 1, "6")
    "U41:u2.7"   → ("U41", 2, "7")     # multi-unit: explicit unit
    "J1:u3.G16"  → ("J1", 3, "G16")    # multi-unit + alpha pin name

    The right-most `.` separates the pin number; an optional `:uN` segment
    in the refdes part selects a non-default unit.
    """
    if "." not in token:
        raise ValueError(f"member {token!r} missing '.PIN' suffix")
    head, pin = token.rsplit(".", 1)
    if ":u" in head:
        refdes, unit_str = head.split(":u", 1)
        try:
            unit = int(unit_str)
        except ValueError:
            raise ValueError(f"member {token!r}: unit {unit_str!r} is not an int")
        return refdes, unit, pin
    return head, 1, pin


@dataclass
class Net:
    name: str
    net_type: str            # "power" | "hier" | "global"
    direction: str = ""      # "input" | "output" | "bidirectional" | "tri_state" | "passive"
    members: list[str] = field(default_factory=list)   # ["U30.8", "C30.1", …]


@dataclass
class Netlist:
    sheet: str
    parts: dict[str, Part]
    nets: dict[str, Net]

    def part(self, refdes: str) -> Part:
        return self.parts[refdes]


def load_netlist(sheet_name: str) -> Netlist:
    """Load and parse netlist/<sheet_name>.yaml."""
    path = NETLIST_DIR / f"{sheet_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"netlist not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}

    parts: dict[str, Part] = {}
    for ref, attrs in (data.get("parts") or {}).items():
        if not isinstance(attrs, dict):
            raise ValueError(f"{path}: parts.{ref} must be a mapping, got {type(attrs).__name__}")
        if "lib_id" not in attrs or "value" not in attrs:
            raise ValueError(f"{path}: parts.{ref} requires both lib_id and value")
        # `units` is a list of placed-unit indices. Default to [1] for single-
        # unit parts (and for the legacy `unit: N` scalar field, kept for
        # backward compat with existing YAMLs).
        if "units" in attrs:
            units_list = attrs["units"]
            if not isinstance(units_list, list) or not all(isinstance(u, int) for u in units_list):
                raise ValueError(f"{path}: parts.{ref}.units must be a list of ints")
            units = list(units_list)
        else:
            units = [int(attrs.get("unit", 1))]
        parts[ref] = Part(
            refdes=ref,
            lib_id=attrs["lib_id"],
            value=str(attrs["value"]),
            footprint=attrs.get("footprint", ""),
            dnp=bool(attrs.get("dnp", False)),
            units=units,
            notes=attrs.get("notes", "") or "",
        )

    nets: dict[str, Net] = {}
    valid_types = {"power", "hier", "global", "internal"}
    valid_dirs = {"input", "output", "bidirectional", "tri_state", "passive", ""}
    for name, attrs in (data.get("nets") or {}).items():
        if not isinstance(attrs, dict):
            raise ValueError(f"{path}: nets.{name} must be a mapping, got {type(attrs).__name__}")
        ntype = attrs.get("type")
        if ntype not in valid_types:
            raise ValueError(f"{path}: nets.{name}.type must be one of {valid_types}, got {ntype!r}")
        direction = attrs.get("direction", "")
        if direction not in valid_dirs:
            raise ValueError(f"{path}: nets.{name}.direction must be one of {valid_dirs}, got {direction!r}")
        if ntype in ("hier", "global") and not direction:
            raise ValueError(f"{path}: nets.{name} type={ntype!r} requires a direction")
        members = attrs.get("members") or []
        if not isinstance(members, list):
            raise ValueError(f"{path}: nets.{name}.members must be a list")
        for m in members:
            if not isinstance(m, str) or "." not in m:
                raise ValueError(f"{path}: nets.{name}: invalid member {m!r}; expected REFDES.PIN")
        nets[name] = Net(name=name, net_type=ntype, direction=direction, members=list(members))

    return Netlist(sheet=sheet_name, parts=parts, nets=nets)
