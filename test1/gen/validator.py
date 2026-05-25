"""Strict netlist-vs-layout connectivity validator.

Given a built `Sheet` and a `Netlist` loaded from netlist/<sheet>.yaml, this
module walks the layout's wire graph (wires + junctions + pin coords +
labels + power-symbol placements) to determine which connected component
each pin lies in and what name(s) that component carries (from labels and
power symbols). Then for every YAML net member, it checks the member's
component is named the YAML net's name.

Failure modes caught:
- Part in YAML not placed in layout (or vice-versa)               → inventory error
- Net member listed in YAML but the layout never wired the pin    → unnamed-component error
- Pin wired to the wrong net (e.g. SCL crossed with SDA)          → wrong-name error
- Bridged nets (two YAML nets sharing one component by accident)  → wrong-name error on one side

Failure modes NOT caught (yet):
- Diagonal wires (this codebase doesn't use them; segment-on-point only handles H/V)
- Multi-unit symbols sharing one refdes — Sheet._placed overwrites; Phase C will extend.
- Stray pins not listed in any YAML net (warn-only candidate for later).
"""

from __future__ import annotations

from .netlist import Net, Netlist, parse_member
from .shared import Sheet


_COORD_TOL = 0.005       # mm — float-equality slack for coord matching


class ValidationError(Exception):
    """Raised when the layout fails to satisfy the netlist."""


# ---------------------------------------------------------------------------
# Union-Find for coord-based connectivity
# ---------------------------------------------------------------------------

class _UF:
    def __init__(self) -> None:
        self.parent: dict = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            return x
        # Iterative find with path compression
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, x, y) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


def _K(x: float, y: float) -> tuple[float, float]:
    """Coord key — round to 3 decimals to dodge float noise."""
    return (round(x, 3), round(y, 3))


def _on_segment(px: float, py: float,
                ax: float, ay: float,
                bx: float, by: float,
                tol: float = _COORD_TOL) -> bool:
    """True if (px, py) lies on the orthogonal segment (a)→(b)."""
    if abs(ax - bx) < tol:                                # vertical
        return (abs(px - ax) < tol
                and min(ay, by) - tol <= py <= max(ay, by) + tol)
    if abs(ay - by) < tol:                                # horizontal
        return (abs(py - ay) < tol
                and min(ax, bx) - tol <= px <= max(ax, bx) + tol)
    return False                                          # diagonal — not used


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate(sheet: Sheet, netlist: Netlist) -> None:
    """Run inventory + connectivity checks. Raises ValidationError on failure."""
    errors: list[str] = []
    errors.extend(_check_inventory(sheet, netlist))
    errors.extend(_check_connectivity(sheet, netlist))
    if errors:
        raise ValidationError(
            f"Validation failed for sheet '{netlist.sheet}':\n  - "
            + "\n  - ".join(errors)
        )


# ---------------------------------------------------------------------------
# Inventory: YAML parts ↔ sheet.placed (excluding auto-generated #PWR refs)
# ---------------------------------------------------------------------------

def _check_inventory(sheet: Sheet, netlist: Netlist) -> list[str]:
    """Check (refdes, unit) parity between YAML declaration and the placed
    layout. Multi-unit parts declare a list of units; the layout must place
    each one."""
    placed_pairs: set[tuple[str, int]] = {
        (ref, unit) for (ref, unit) in sheet._placed if not ref.startswith("#PWR")
    }
    declared_pairs: set[tuple[str, int]] = set()
    for refdes, part in netlist.parts.items():
        for u in part.units:
            declared_pairs.add((refdes, u))
    errors: list[str] = []
    missing_in_layout = declared_pairs - placed_pairs
    missing_in_yaml = placed_pairs - declared_pairs
    if missing_in_layout:
        errors.append(
            f"declared in YAML but not placed in layout: "
            f"{sorted(_fmt_pair(p) for p in missing_in_layout)}"
        )
    if missing_in_yaml:
        errors.append(
            f"placed in layout but not declared in YAML: "
            f"{sorted(_fmt_pair(p) for p in missing_in_yaml)}"
        )
    return errors


def _fmt_pair(p: tuple[str, int]) -> str:
    """Pretty-print a (refdes, unit) for error messages."""
    ref, unit = p
    return ref if unit == 1 else f"{ref}:u{unit}"


# ---------------------------------------------------------------------------
# Connectivity: build coord graph, name each component, check YAML net members
# ---------------------------------------------------------------------------

def _build_graph(sheet: Sheet) -> _UF:
    """Build a Union-Find on coord nodes from the sheet's wires, junctions,
    pins, labels, and power-symbol pins.

    Junction semantics here match modern KiCad eeschema (≥ v6): a wire
    endpoint that lands on another wire's interior is implicitly connected
    (T-intersection). The explicit (junction) marker is required only at
    points where three or more wires meet and no wire actually ENDS at the
    interior point (rare; we accept either).
    """
    uf = _UF()

    # 1) Wires: each segment unifies its two endpoints.
    for (a, b) in sheet._wires:
        uf.union(_K(*a), _K(*b))

    # 1b) T-intersections: a wire endpoint lying on ANOTHER wire's interior
    #     is auto-connected (per KiCad eeschema's implicit junction rule).
    endpoints: set[tuple[float, float]] = set()
    for (a, b) in sheet._wires:
        endpoints.add(_K(*a))
        endpoints.add(_K(*b))
    for ep in endpoints:
        ex, ey = ep
        for (ax, ay), (bx, by) in sheet._wires:
            a_k, b_k = _K(ax, ay), _K(bx, by)
            if ep == a_k or ep == b_k:
                continue
            if _on_segment(ex, ey, ax, ay, bx, by):
                uf.union(ep, a_k)

    # 2) Junctions on a wire's interior: unify the junction with the wire's
    #    endpoint (transitively reaches the other endpoint).
    for jx, jy in sheet._junctions:
        jk = _K(jx, jy)
        uf.find(jk)  # ensure node exists
        for (ax, ay), (bx, by) in sheet._wires:
            if _on_segment(jx, jy, ax, ay, bx, by):
                uf.union(jk, _K(ax, ay))

    # 3) Pins (including power-symbol pins): unify each pin coord with any wire
    #    endpoint or interior at that coord.
    for _key, part in sheet._placed.items():
        for _pin_num, (px, py) in part.pins.items():
            pk = _K(px, py)
            uf.find(pk)
            for (ax, ay), (bx, by) in sheet._wires:
                if _on_segment(px, py, ax, ay, bx, by):
                    uf.union(pk, _K(ax, ay))

    # 4) Labels: ensure the label's coord is a node (it's typically a wire
    #    endpoint already, so this just guarantees presence in the UF).
    for lbl in sheet._labels:
        lk = _K(lbl.x, lbl.y)
        uf.find(lk)
        for (ax, ay), (bx, by) in sheet._wires:
            if _on_segment(lbl.x, lbl.y, ax, ay, bx, by):
                uf.union(lk, _K(ax, ay))

    return uf


def _name_components(sheet: Sheet, uf: _UF) -> dict[tuple, set[str]]:
    """Return {component_root: {net_name, …}} accumulated from every label
    anchor and every power-symbol pin on the sheet."""
    names: dict[tuple, set[str]] = {}
    for lbl in sheet._labels:
        root = uf.find(_K(lbl.x, lbl.y))
        names.setdefault(root, set()).add(lbl.name)
    for _key, part in sheet._placed.items():
        if part.is_power:
            (px, py) = part.pins["1"]
            root = uf.find(_K(px, py))
            names.setdefault(root, set()).add(part.power_rail)
    return names


def _check_connectivity(sheet: Sheet, netlist: Netlist) -> list[str]:
    uf = _build_graph(sheet)
    comp_names = _name_components(sheet, uf)

    errors: list[str] = []
    for net_name, net in netlist.nets.items():
        # Resolve each member to its connected-component root. Collect errors
        # for unknown refdes/pins inline; everything else feeds the name &
        # connectivity checks below.
        roots: list[tuple[str, tuple[float, float], object]] = []
        for member in net.members:
            try:
                refdes, unit, pin_num = parse_member(member)
            except ValueError as e:
                errors.append(f"net '{net_name}': {e}")
                continue
            part = sheet._placed.get((refdes, unit))
            if part is None:
                # Try to give a useful hint if the refdes is known under a
                # different unit (typo on the `:uN` suffix).
                other_units = sorted(
                    u for (r, u) in sheet._placed if r == refdes
                )
                hint = f" (placed units: {other_units})" if other_units else ""
                errors.append(
                    f"net '{net_name}': member '{member}' references "
                    f"undeclared/unplaced {_fmt_pair((refdes, unit))}{hint}"
                )
                continue
            if pin_num not in part.pins:
                errors.append(
                    f"net '{net_name}': pin '{pin_num}' not found on "
                    f"{_fmt_pair((refdes, unit))} (known pins: {sorted(part.pins.keys())})"
                )
                continue
            (px, py) = part.pins[pin_num]
            root = uf.find(_K(px, py))
            roots.append((member, (px, py), root))

        if net.net_type == "internal":
            # All members must be in ONE connected component; no name check.
            distinct = {r for _, _, r in roots}
            if len(distinct) > 1:
                groups: dict[object, list[str]] = {}
                for m, _, r in roots:
                    groups.setdefault(r, []).append(m)
                errors.append(
                    f"internal net '{net_name}': members split across "
                    f"{len(distinct)} components: "
                    + " vs ".join(repr(g) for g in groups.values())
                )
        else:
            # power / hier / global — each member must be in a component whose
            # name set contains the YAML net name.
            for member, (px, py), root in roots:
                names = comp_names.get(root, set())
                if net_name not in names:
                    if not names:
                        errors.append(
                            f"net '{net_name}': member '{member}' at ({px}, {py}) is in an "
                            f"UNNAMED component — no label or power symbol reaches this pin"
                        )
                    else:
                        errors.append(
                            f"net '{net_name}': member '{member}' at ({px}, {py}) is in a "
                            f"component named {sorted(names)} — expected '{net_name}'"
                        )
    return errors
