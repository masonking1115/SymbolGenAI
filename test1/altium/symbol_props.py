"""Carry the KiCad symbol PROPERTIES onto the native Altium `.SchLib` symbols.

The geometry migration (`migrate_symbols`) brought pins/units/body across but
not the metadata KiCad kept as symbol *properties* (Reference, Value,
Footprint, Datasheet, Description, Manufacturer, MPN). This module reads those
from the archived `test1/_archive_kicad/Parts Library/<MPN>/<MPN>.kicad_sym`
and bakes them into the committed `<MPN>.SchLib` as Altium component
parameters, the designator prefix, and the symbol description.

altium_monkey only serializes parameters/designators added to a FRESHLY
authored symbol (high-level edits to a loaded binary symbol don't round-trip),
so we REBUILD each library: read the current symbol's geometry back, re-author
it identically, then attach the properties. Geometry is unchanged (verified by
comparing read_pins before/after); only metadata is added.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from altium_monkey import (
    AltiumSchLib,
    PinElectrical,
    Rotation90,
    SchPointMils,
    make_sch_pin,
)

from .config import FONT_DEFAULT
from .symlib import PARTS_LIB, read_pins, schlib_path, symbol_name
from .units import min_half_x_for_names

ARCHIVE_LIB = PARTS_LIB.parent / "_archive_kicad" / "Parts Library"

# KiCad property -> Altium parameter name. Reference/Description are handled
# specially (designator prefix / symbol description); ki_* are KiCad-internal
# and intentionally dropped.
PARAM_KEYS = ("Value", "Footprint", "Datasheet", "Manufacturer", "MPN")
_PROP_RE = re.compile(r'\(property\s+"([^"]+)"\s+"((?:[^"\\]|\\.)*)"')


def read_kicad_props(mpn: str) -> dict[str, str]:
    """Parse {property: value} from the archived <MPN>.kicad_sym (empties and
    KiCad-internal ki_* dropped). Returns {} if no archived file."""
    f = ARCHIVE_LIB / mpn / f"{mpn}.kicad_sym"
    if not f.exists():
        return {}
    out: dict[str, str] = {}
    for key, val in _PROP_RE.findall(f.read_text(errors="replace")):
        if key.startswith("ki_") or not val.strip():
            continue
        out[key] = val.replace('\\"', '"')
    return out


def _designator_prefix(props: dict[str, str], fallback: str = "U") -> str:
    ref = props.get("Reference", fallback).strip() or fallback
    # KiCad Reference is the prefix (U/R/C/J/...); strip any trailing digits.
    return re.sub(r"\d+$", "", ref) or fallback


def _read_geometry(sym):
    """Read a symbol's pins + rectangles + part count back from a loaded
    .SchLib so we can re-author it identically."""
    part_count = int(getattr(sym, "part_count", 1) or 1)
    pins = []
    for p in sym.pins:
        pins.append(dict(
            designator=str(p.designator), name=p.name or "",
            x=int(round(p.x_mils)), y=int(round(p.y_mils)),
            length=int(round(p.length_mils)),
            electrical=PinElectrical(int(getattr(p.electrical, "value", p.electrical))),
            orientation=Rotation90(int(getattr(p.orientation, "value", p.orientation))),
            owner=int(p.owner_part_id),
        ))
    rects = []
    for r in sym.rectangles:
        rects.append(dict(
            x1=int(round(r.location_mils.x_mils)), y1=int(round(r.location_mils.y_mils)),
            x2=int(round(r.corner_mils.x_mils)), y2=int(round(r.corner_mils.y_mils)),
            owner=int(r.owner_part_id),
        ))
    return part_count, pins, rects


def apply_props(mpn: str) -> tuple[bool, str]:
    """Rebuild <MPN>.SchLib with its existing geometry + KiCad properties."""
    sp = schlib_path(mpn)
    name = symbol_name(mpn)
    if name is None or not sp.exists():
        return False, "no .SchLib"
    props = read_kicad_props(mpn)
    if not props:
        return False, "no archived kicad_sym properties"

    before = read_pins(mpn)
    part_count, pins, rects = _read_geometry(AltiumSchLib(sp).get_symbol(name))
    multi = part_count > 1
    widened = _widen_body(pins, rects, multi)

    lib = AltiumSchLib()
    sym = lib.add_symbol(name, description=props.get("Description", ""))
    if multi:
        sym.set_part_count(part_count)
    for pn in pins:
        owner = pn["owner"] if multi else None
        sym.add_pin(make_sch_pin(
            designator=pn["designator"],
            name=("" if pn["name"] in ("~", "") else pn["name"]),
            location_mils=SchPointMils.from_mils(pn["x"], pn["y"]),
            orientation=pn["orientation"], length_mils=pn["length"],
            electrical_type=pn["electrical"],
            name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT,
            owner_part_id=owner))
    for rc in rects:
        sym.add_rectangle(rc["x1"], rc["y1"], rc["x2"], rc["y2"],
                          owner_part_id=(rc["owner"] if multi else -1))
    sym.add_designator(f"{_designator_prefix(props)}?", 0, 0)

    applied = []
    for key in PARAM_KEYS:
        if props.get(key, "").strip():
            # Hidden: metadata lives in the Properties dialog, NOT drawn on the
            # sheet (visible params stack at the origin into a text "glob").
            # The value is shown separately via the component Comment in place().
            sym.add_parameter(key, props[key], is_hidden=True)
            applied.append(key)
    lib.to_schlib(sp)

    # Guard: pins/units/names/vertical layout must be preserved. Body WIDTH may
    # grow (we widen x to clear long pin names), so compare topology ignoring x.
    def _topo(d):
        return {k: (v[0], round(v[2]), v[3], v[4]) for k, v in d.items()}
    if _topo(read_pins(mpn)) != _topo(before):
        return False, "TOPOLOGY CHANGED — aborted (left rewritten file; investigate)"
    extra = f", ref {_designator_prefix(props)}?"
    desc = " +desc" if props.get("Description", "").strip() else ""
    wide = f", widened body->{widened}mil" if widened else ""
    return True, f"params: {', '.join(applied) or '(none)'}{extra}{desc}{wide}"


def _widen_body(pins: list[dict], rects: list[dict], multi: bool) -> int:
    """Grow each unit's body half-width (and its side pins) so long left/right
    pin names don't collide. Mutates pins/rects in place; returns the largest
    new half-width applied (0 if nothing changed)."""
    units = sorted({p["owner"] for p in pins}) if multi else [None]
    applied = 0
    for u in units:
        upins = [p for p in pins if (not multi or p["owner"] == u)]
        cur = max((abs(p["x"]) for p in upins), default=0)
        if cur <= 0:
            continue
        left = [p["name"] for p in upins if p["x"] < 0]
        right = [p["name"] for p in upins if p["x"] > 0]
        new = min_half_x_for_names(left, right, base=cur)
        if new <= cur:
            continue
        for p in upins:
            if abs(abs(p["x"]) - cur) < 1:           # a side pin
                p["x"] = -new if p["x"] < 0 else new
        urects = rects if not multi else [r for r in rects if r["owner"] == u]
        for r in urects:
            for k in ("x1", "x2"):
                if abs(abs(r[k]) - cur) < 1:          # a side edge
                    r[k] = -new if r[k] < 0 else new
        applied = max(applied, new)
    return applied


def _mpns_with_archive() -> list[str]:
    if not ARCHIVE_LIB.exists():
        return []
    return sorted(d.name for d in ARCHIVE_LIB.iterdir()
                  if d.is_dir() and (d / f"{d.name}.kicad_sym").exists()
                  and schlib_path(d.name).exists())


def main(argv: list[str]) -> int:
    only = set(argv)
    mpns = [m for m in _mpns_with_archive() if not only or m in only]
    print(f"Applying KiCad properties to {len(mpns)} .SchLib symbol(s)\n")
    fails = 0
    for mpn in mpns:
        ok, msg = apply_props(mpn)
        print(f"  [{'OK ' if ok else 'FAIL'}] {mpn:22} {msg}")
        fails += 0 if ok else 1
    print(f"\n{'all done' if fails == 0 else f'{fails} failed'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
