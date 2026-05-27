"""Re-draw committed per-MPN `.SchLib` bodies with standard schematic glyphs.

The migrated symbols all used a generic rectangle body (a capacitor looked like a
box, a MOSFET like a box, ...). This pass rebuilds each symbol with the SAME pins
(identical designator/name/electrical/location/orientation/length/owner, so the
electrical hot-spots — and therefore every builder's routing, the validator, and
the linter — are unchanged) but a conventional body glyph from `glyphs.py`.

Idempotent: re-running redraws from the current pins. Run after symbol migration:
    python -m test1.altium.restyle_symbols          # all parts
    python -m test1.altium.restyle_symbols 2N7002   # one MPN
"""

from __future__ import annotations

import sys

from altium_monkey import (
    AltiumSchLib,
    PinElectrical,
    Rotation90,
    SchPointMils,
    make_sch_pin,
)

from . import glyphs, kicad_glyph
from .config import FONT_DEFAULT
from .symlib import PARTS_LIB, schlib_path

# Active devices replicate their exact KiCad body when the archived .kicad_sym is
# available (passives keep the hand-drawn glyphs — the resistor must be a zig-zag,
# which KiCad does not use).
_KICAD_KINDS = {"mosfet", "opamp", "bjt", "diode"}
_ARCHIVE = PARTS_LIB.parent / "_archive_kicad" / "Parts Library"


def _prefix(sym) -> str:
    for d in getattr(sym, "designators", []) or []:
        t = (d.text or "").strip()
        if t:
            return t.rstrip("?0123456789") or t[:1]
    return "U"


def _desig_xy(sym) -> tuple[int, int]:
    for d in getattr(sym, "designators", []) or []:
        loc = getattr(d, "location", None)
        if loc is not None:
            try:
                return int(round(loc.x_mils)), int(round(loc.y_mils))
            except Exception:
                pass
    return 100, 200


def restyle_file(path) -> list[str]:
    """Rewrite one .SchLib in place; return the (kind) chosen per symbol."""
    names = AltiumSchLib.get_symbol_names(str(path))
    out = AltiumSchLib()
    report = []
    for nm in names:
        src = AltiumSchLib(str(path)).get_symbol(nm)
        if src is None:
            continue
        pc = int(getattr(src, "part_count", 1) or 1)
        new = out.add_symbol(nm, description=getattr(src, "description", "") or "")
        if pc > 1:
            new.set_part_count(pc)
        # 1) re-add pins identically (hot-spots preserved)
        for p in src.pins:
            owner = int(p.owner_part_id) if (pc > 1 and p.owner_part_id) else None
            new.add_pin(make_sch_pin(
                designator=str(p.designator), name=p.name or "",
                location_mils=SchPointMils.from_mils(int(round(p.x_mils)),
                                                     int(round(p.y_mils))),
                orientation=Rotation90(int(p.orientation)),
                length_mils=float(p.length_mils),
                electrical_type=PinElectrical(int(p.electrical)),
                owner_part_id=owner,
                name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT))
        # 2) draw the body glyph per unit, from the NEW pins' hot-spots
        prefix = _prefix(src)
        units = sorted({(int(p.owner_part_id) if p.owner_part_id else 1)
                        for p in new.pins})
        hs_by_unit, nmap_by_unit = {}, {}
        for u in units:
            upins = [p for p in new.pins
                     if (int(p.owner_part_id) if p.owner_part_id else 1) == u]
            hs, nmap = {}, {}
            for p in upins:
                h = p.get_hot_spot()
                hs[str(p.designator)] = (int(round(h.x_mils)), int(round(h.y_mils)))
                nmap[str(p.designator)] = p.name or ""
            hs_by_unit[u], nmap_by_unit[u] = hs, nmap
        # classify (first non-ic unit wins)
        kind = "ic"
        for u in units:
            k = glyphs.classify(prefix, nmap_by_unit[u], len(hs_by_unit[u]), pc)
            if k != "ic":
                kind = k
                break

        def owner_for(u):
            return u if pc > 1 else -1

        drawn = False
        if kind in _KICAD_KINDS:
            arch = _ARCHIVE / nm / f"{nm}.kicad_sym"
            if arch.exists() and kicad_glyph.available(str(arch)):
                drawn = kicad_glyph.draw_from_kicad(new, str(arch), hs_by_unit, owner_for)
        if not drawn:
            for u in units:
                glyphs.draw_body(new, kind, hs_by_unit[u], nmap_by_unit[u], owner_for(u))
        report.append(f"{nm}:{kind}{'(kicad)' if drawn else ''}")
        # 3) re-add designator + parameters
        dx, dy = _desig_xy(src)
        dtext = (src.designators[0].text if getattr(src, "designators", None) else f"{prefix}?")
        new.add_designator(dtext, dx, dy)
        for pa in getattr(src, "parameters", []) or []:
            if (pa.name or "").strip():
                new.add_parameter(pa.name, pa.text or "",
                                  is_hidden=bool(getattr(pa, "is_hidden", True)))
    out.to_schlib(str(path))
    return report


def main(argv: list[str]) -> int:
    if argv:
        mpns = argv
    else:
        mpns = sorted(d.name for d in PARTS_LIB.iterdir()
                      if d.is_dir() and schlib_path(d.name).exists())
    for mpn in mpns:
        p = schlib_path(mpn)
        if not p.exists():
            print(f"  {mpn:28} (no .SchLib, skipped)")
            continue
        rep = restyle_file(p)
        print(f"  {mpn:28} -> {', '.join(rep)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
