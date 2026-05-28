"""Normalize a vendor 2-pin passive `.SchLib` to the builder's vertical pin
convention so it drops into the hand-routed sheets unchanged.

Ultra-Librarian passive symbols draw the part HORIZONTALLY (pins on left/right,
asymmetric origin, vendor-specific pitch). Every sheet builder routes passives
to the VERTICAL hot-spots `(0, +/-100)` that the stock `R`/`C` symbols use
(see `symbols._add_passive`), so a vendor passive placed as-is lands rotated and
displaced and breaks the validated layout. This re-authors
`Parts Library/<MPN>/<MPN>.SchLib` as a 2-pin vertical passive (pin 1 top, pin 2
bottom, hot-spots at `(0, +/-100)`) while KEEPING the MPN-named symbol, its
device glyph (capacitor plates / resistor box), and its hidden metadata
parameters (manufacturer, MPN, datasheet, ...). Footprint pad mapping (pins
1/2) is untouched, so the `.PcbLib` linkage is unaffected.

    python -m test1.altium.normalize_passive             # all known vendor passives
    python -m test1.altium.normalize_passive <MPN> C     # one part, prefix C or R
"""

from __future__ import annotations

import sys
from pathlib import Path

from altium_monkey import (
    AltiumSchLib,
    PinElectrical,
    Rotation90,
    SchPointMils,
    make_sch_pin,
)

from . import glyphs
from .config import FONT_DEFAULT
from .symlib import schlib_path, symbol_summary

# UL boilerplate / placement-time fields not carried onto the re-authored symbol
# (Comment + Value are set per-instance at placement time from the netlist).
_DROP = {"Copyright", "Type", "Comment", "Value"}

# The committed vendor passives and their schematic designator prefix.
KNOWN: dict[str, str] = {
    "GRM21BR71A106KA73L": "C",   # 10 uF bulk MLCC
    "GRM155R70J105KA12D": "C",   # 1 uF mid MLCC
    "GRM155R71C104KA88D": "C",   # 100 nF HF MLCC
    "CRCW04020000Z0ED": "R",     # 0 ohm jumper
    "CR0402-FX-1002GLF": "R",    # 10 kohm pull
    "TNPW06035K11BEEA": "R",     # 5.11 kohm 0.1% sense
    "GRM155R71H103KA88D": "C",   # 10 nF HF (C12 — TPS7A8401A NR_SS)
    "GRM21BR61A226ME44L": "C",   # 22 uF bulk X5R 0805 (C13 — LDO OUT)
    "CR0402-FX-1001GLF": "R",    # 1 kohm series (R13 — LDO_PG)
    "CR0402-FX-2201GLF": "R",    # 2.2 kohm I2C pull-up (R60/R61)
}


def normalize(mpn: str, prefix: str) -> Path:
    """Re-author <MPN>.SchLib as a vertical 2-pin passive. Returns the path."""
    summ = symbol_summary(mpn)
    raw = summ.get("properties") or {}
    props = {k: v for k, v in raw.items()
             if k not in _DROP and str(v).strip() and str(v).strip() != k}
    desc = raw.get("Description", "")
    desc = "" if desc in ("", "Description") else str(desc)

    lib = AltiumSchLib()
    sym = lib.add_symbol(mpn, description=desc)
    # Pin geometry mirrors symbols._add_passive: hot-spots (connection points)
    # at (0, +/-100). The pin points OUTWARD and starts at the body edge (+/-70,
    # the resistor zig-zag extent — wider than the cap plates at +/-25), so its
    # connection end IS the outer tip and the pin line never runs THROUGH the
    # body glyph (a pin starting inside the zig-zag looks like a net crossing it).
    sym.add_pin(make_sch_pin(
        designator="1", name="", location_mils=SchPointMils.from_mils(0, 70),
        orientation=Rotation90.DEG_90, length_mils=30,
        electrical_type=PinElectrical.PASSIVE,
        name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT))
    sym.add_pin(make_sch_pin(
        designator="2", name="", location_mils=SchPointMils.from_mils(0, -70),
        orientation=Rotation90.DEG_270, length_mils=30,
        electrical_type=PinElectrical.PASSIVE,
        name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT))
    hs = {str(p.designator): (int(round(p.get_hot_spot().x_mils)),
                              int(round(p.get_hot_spot().y_mils))) for p in sym.pins}
    kind = glyphs.classify(prefix, {}, len(hs), 1)
    glyphs.draw_body(sym, kind, hs, {}, -1)
    sym.add_designator(f"{prefix}?", 100, 200)
    # Hidden metadata (manufacturer / MPN / datasheet); never drawn on the sheet.
    for key, val in props.items():
        sym.add_parameter(str(key), str(val), is_hidden=True)

    out = schlib_path(mpn)
    lib.to_schlib(out)
    return out


def main(argv: list[str]) -> int:
    if len(argv) == 2:
        items = [(argv[0], argv[1])]
    elif not argv:
        items = list(KNOWN.items())
    else:
        print("usage: python -m test1.altium.normalize_passive [<MPN> <C|R>]")
        return 2
    for mpn, prefix in items:
        out = normalize(mpn, prefix)
        print(f"normalized {mpn} ({prefix}) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
