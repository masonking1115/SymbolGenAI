"""Multi-sheet netlist view — convenience queries for rules.py.

`gen/netlist.py` loads one YAML at a time. The review pipeline almost
always wants the full picture: "which sheet has the pull-down on net X?",
"what nets does refdes R22 belong to?". This module loads every YAML
once and exposes those queries.

This is the only place review/ code reaches into gen/. Keeping the
import direction one-way (review → gen) means the build doesn't depend
on the review pipeline.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))  # so `from gen import netlist` works

from gen import netlist as _gen_netlist  # noqa: E402
from gen.config import SHEET_NAMES  # noqa: E402


@dataclass
class NetMember:
    sheet: str
    net: str
    refdes: str
    unit: int
    pin: str


@dataclass
class NetlistView:
    by_sheet: dict[str, _gen_netlist.Netlist] = field(default_factory=dict)

    # Reverse index: refdes -> list[NetMember] across all sheets.
    _ref_to_nets: dict[str, list[NetMember]] = field(default_factory=dict)
    # Net name -> all members anywhere (a power/global net may span sheets).
    _net_members: dict[str, list[NetMember]] = field(default_factory=dict)

    def part(self, refdes: str) -> tuple[str, _gen_netlist.Part] | None:
        """Return (sheet, Part) for the first sheet declaring this refdes."""
        for sheet_name, nl in self.by_sheet.items():
            if refdes in nl.parts:
                return sheet_name, nl.parts[refdes]
        return None

    def nets_with_member(self, refdes: str, pin: str | None = None) -> list[NetMember]:
        rows = self._ref_to_nets.get(refdes, [])
        if pin is None:
            return list(rows)
        return [r for r in rows if r.pin == pin]

    def members(self, net_name: str) -> list[NetMember]:
        return list(self._net_members.get(net_name, []))

    def parts_with_value(self, value_predicate) -> list[tuple[str, str, _gen_netlist.Part]]:
        """Return [(sheet, refdes, Part), …] where value_predicate(value) is truthy."""
        out: list[tuple[str, str, _gen_netlist.Part]] = []
        for sheet_name, nl in self.by_sheet.items():
            for refdes, part in nl.parts.items():
                if value_predicate(part.value):
                    out.append((sheet_name, refdes, part))
        return out


def load_all() -> NetlistView:
    view = NetlistView()
    for name in SHEET_NAMES:
        view.by_sheet[name] = _gen_netlist.load_netlist(name)
    # Build reverse indices.
    for sheet_name, nl in view.by_sheet.items():
        for net_name, net in nl.nets.items():
            for member in net.members:
                refdes, unit, pin = _gen_netlist.parse_member(member)
                rec = NetMember(sheet=sheet_name, net=net_name,
                                refdes=refdes, unit=unit, pin=pin)
                view._ref_to_nets.setdefault(refdes, []).append(rec)
                view._net_members.setdefault(net_name, []).append(rec)
    return view
