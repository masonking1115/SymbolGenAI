"""KiCad .kicad_sym -> Altium .SchLib translator.

MIGRATION-ONLY as of the Altium-native symbol cutover. Symbols are now
committed as per-MPN `Parts Library/<MPN>/<MPN>.SchLib` (the source of truth,
read by symlib / placed by build_symbols). This module is no longer in the
build or GUI path — it is invoked only by `migrate_symbols.py` to (re)author a
.SchLib from the legacy `.kicad_sym`, which now live under
`test1/_archive_kicad/Parts Library/`. New symbols are authored from a JSON
pin-spec by `author_symbol.py`, not here.

Generates one SchLib covering every part the design uses, so the per-sheet
builders can place real components instead of hand-authored stand-ins.

Faithfulness contract: pin NUMBERS and pin SIDES come from the canonical
`Parts Library/<MPN>/<MPN>.kicad_sym` (via the shared gen.symbols.parse_pins).
Exact pin COORDINATES are NOT preserved — they don't need to be, because the
Altium builders route from the hot-spots returned by place(). Instead pins are
auto-laid on a clean 100-mil grid, grouped by the side the KiCad symbol put
them on, so every symbol is on-grid, collision-free, and readable.

Multi-unit parts (FMC ASP-134606 = 4 units, OPA2388 = 2) use Altium part_count
+ per-pin owner_part_id; place(..., part_id=u) instantiates one unit.
"""

from __future__ import annotations

from pathlib import Path

from altium_monkey import (
    AltiumSchLib,
    PinElectrical,
    Rotation90,
    SchPointMils,
    make_sch_pin,
)

from ..gen.symbols import parse_pins
from .config import FONT_DEFAULT
from .units import min_half_x_for_names

PITCH = 200          # mil between pins on a side (2 grid — roomy, parity-safe)
PIN_LEN = 200        # mil

# KiCad lib_id -> SchLib symbol name. Custom parts keep their MPN; stock R/C
# get short names. Built lazily from the netlists by build_symbols.py.
_ORIENT = {"L": Rotation90.DEG_180, "R": Rotation90.DEG_0,
           "T": Rotation90.DEG_90, "B": Rotation90.DEG_270}


def _side(dx: float, dy: float) -> str:
    """Classify a pin to a body side from its offset to the symbol centroid.
    Convention-free (uses coordinate signs, not KiCad's pin-angle), so it can't
    be tripped up by the angle interpretation."""
    if abs(dx) >= abs(dy):
        return "L" if dx < 0 else "R"
    return "T" if dy > 0 else "B"


def _author_unit(sym, unit_pins: dict, owner: int) -> None:
    """Lay out one unit's pins (dict num -> (name, lx, ly, angle)) on-grid."""
    cx = sum(p[1] for p in unit_pins.values()) / len(unit_pins)
    cy = sum(p[2] for p in unit_pins.values()) / len(unit_pins)

    xs = [p[1] for p in unit_pins.values()]
    ys = [p[2] for p in unit_pins.values()]
    xspread, yspread = max(xs) - min(xs), max(ys) - min(ys)

    sides: dict[str, list[tuple[str, str, float, float]]] = {"L": [], "R": [], "T": [], "B": []}
    items = [(num, name, lx, ly) for num, (name, lx, ly, _a) in unit_pins.items()]
    if len(items) >= 3 and xspread < 1.0:
        # Single vertical column (e.g. an FMC/header connector): KiCad draws all
        # pins stacked on one side, not split into two rows. Put them all on the
        # LEFT so the symbol reads as a tall connector, matching KiCad.
        sides["L"] = items
    elif len(items) >= 3 and yspread < 1.0:
        # Single horizontal row -> all on the bottom edge.
        sides["B"] = items
    else:
        for it in items:
            sides[_side(it[2] - cx, it[3] - cy)].append(it)

    # Order pins along each edge as the KiCad symbol had them.
    sides["L"].sort(key=lambda t: -t[3])   # top (high y) first
    sides["R"].sort(key=lambda t: -t[3])
    sides["T"].sort(key=lambda t: t[2])    # left (low x) first
    sides["B"].sort(key=lambda t: t[2])

    nL, nR, nT, nB = (len(sides[s]) for s in "LRTB")
    half_x = max(300, _r100((max(nT, nB, 1) / 2) * PITCH + PITCH))
    half_y = max(300, _r100((max(nL, nR, 1) / 2) * PITCH + PITCH))
    # Widen so left/right pin names don't collide inside the body.
    half_x = max(half_x, min_half_x_for_names(
        [it[1] for it in sides["L"]], [it[1] for it in sides["R"]]))

    def emit(side: str):
        lst = sides[side]
        n = len(lst)
        for i, (num, name, _lx, _ly) in enumerate(lst):
            off = int(((n - 1) / 2 - i) * PITCH)        # centered, on 100-grid
            if side == "L":
                loc = (-half_x, off)
            elif side == "R":
                loc = (half_x, off)
            elif side == "T":
                loc = (-off, half_y)
            else:
                loc = (-off, -half_y)
            sym.add_pin(make_sch_pin(
                designator=num, name=("" if name in ("~", "") else name),
                location_mils=SchPointMils.from_mils(*loc),
                orientation=_ORIENT[side], length_mils=PIN_LEN,
                electrical_type=PinElectrical.PASSIVE,
                name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT,
                owner_part_id=(owner if owner != -1 else None)))

    for s in "LRTB":
        emit(s)
    sym.add_rectangle(-half_x, -half_y, half_x, half_y, owner_part_id=owner)


def _r100(v: float) -> int:
    return int(round(v / 100.0) * 100)


def translate_symbol(lib: AltiumSchLib, mpn: str, symbol_name: str | None = None) -> str:
    """Translate Parts Library/<mpn>/<mpn>.kicad_sym into a SchLib symbol.
    Returns the authored symbol name."""
    name = symbol_name or mpn
    pins = parse_pins(f"Lib:{mpn}")     # {num: (name, lx, ly, angle, unit)}
    if not pins:
        raise ValueError(f"no pins parsed for {mpn}")

    units = sorted({p[4] for p in pins.values()})
    sym = lib.add_symbol(name, description=f"Translated from {mpn}.kicad_sym")
    multi = len(units) > 1
    if multi:
        sym.set_part_count(len(units))

    for u in units:
        unit_pins = {num: (nm, lx, ly, ang)
                     for num, (nm, lx, ly, ang, pu) in pins.items() if pu == u}
        _author_unit(sym, unit_pins, owner=(u if multi else -1))

    sym.add_designator("U?", 0, 0)
    return name
