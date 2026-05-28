"""Author the discrete MOSFET symbols (2N7002 N-channel, PMZ1200UPEYL P-channel)
as proper enhancement MOSFETs WITH an integrated body diode, in the library's
standard line style.

Why this is its own module: the migrated/committed `<MPN>.SchLib` drew a bare
box-ish body, and the build only MERGES committed symbols (it never re-runs the
glyph drawers on them), so the only way to fix a committed symbol is to
re-author the file. We preserve each part's EXACT pin interface (G left, D top,
S bottom — same hot-spots, orientations, lengths) and its existing metadata, so
the change propagates automatically on the next `build_project` (the merged
`out/lib/parts.SchLib` rebuilds when a source is newer) WITHOUT disturbing any
sheet's routing, validator, or linter.

N vs P differs only in the substrate-arrow direction and the body-diode
polarity:
  - N-channel: substrate arrow points INTO the channel; body diode conducts
    source->drain (anode = source/bottom, cathode = drain/top).
  - P-channel: substrate arrow points OUT of the channel; body diode conducts
    drain->source (anode = drain/top, cathode = source/bottom).

    python -m test1.altium.author_mosfets            # both
    python -m test1.altium.author_mosfets 2N7002     # one
"""

from __future__ import annotations

import sys

from altium_monkey import (
    AltiumSchLib,
    LineWidth,
    PinElectrical,
    Rotation90,
    SchPointMils,
    make_sch_pin,
)

from .config import FONT_DEFAULT
from .symlib import schlib_path, symbol_name, symbol_summary

_LW = LineWidth.SMALL          # matches glyphs.py body style

# The two committed discrete MOSFETs and their channel polarity.
CHANNEL = {"2N7002": "n", "PMZ1200UPEYL": "p"}

# UL/boilerplate params not carried onto the re-authored symbol (the value is
# shown via the per-instance Comment at placement time).
_DROP = {"Copyright", "Type", "Comment", "Value"}

_ORIENT = {0: Rotation90.DEG_0, 1: Rotation90.DEG_90,
           2: Rotation90.DEG_180, 3: Rotation90.DEG_270}


def _draw_body(sym, channel: str) -> None:
    """Enhancement MOSFET (channel 'n'|'p') with body diode, inside a circle.

    Drawn from the pin inner ends: gate (-300,0), drain (0,300), source
    (0,-300) — matching the committed pin geometry.
    """
    L = lambda x1, y1, x2, y2: sym.add_line(x1, y1, x2, y2, line_width=_LW, owner_part_id=-1)

    # Gate: lead in to a vertical gate electrode bar.
    L(-300, 0, -170, 0)
    L(-170, -120, -170, 120)

    # Channel: three enhancement-mode segments (broken bar) right of the gate.
    L(-110, 60, -110, 120)     # top (drain) segment
    L(-110, -30, -110, 30)     # middle (substrate) segment
    L(-110, -120, -110, -60)   # bottom (source) segment

    # Drain rail (top) + contact from the top channel segment.
    L(0, 300, 0, 90)
    L(-110, 90, 0, 90)

    # Source rail (bottom, extended to the substrate axis) + contact.
    L(0, -300, 0, 0)
    L(-110, -90, 0, -90)

    # Substrate connection + channel-type arrow.
    L(0, 0, -110, 0)
    if channel == "n":
        # arrow points INTO the channel (toward the gate, -x)
        L(-110, 0, -88, 14)
        L(-110, 0, -88, -14)
    else:
        # arrow points OUT of the channel (toward the source rail, +x)
        L(-30, 0, -52, 14)
        L(-30, 0, -52, -14)

    # Body diode on the right rail between drain (top) and source (bottom).
    L(0, 180, 130, 180)        # tap off drain rail
    L(130, 180, 130, 50)       # upper lead
    L(130, -50, 130, -180)     # lower lead
    L(0, -180, 130, -180)      # tap off source rail
    if channel == "n":
        # anode = source (bottom) -> cathode = drain (top): triangle apex UP
        sym.add_polygon([(80, -50), (180, -50), (130, 50)],
                        line_width=_LW, is_solid=False, owner_part_id=-1)
        L(80, 50, 180, 50)     # cathode bar (drain/top side)
    else:
        # anode = drain (top) -> cathode = source (bottom): triangle apex DOWN
        sym.add_polygon([(80, 50), (180, 50), (130, -50)],
                        line_width=_LW, is_solid=False, owner_part_id=-1)
        L(80, -50, 180, -50)   # cathode bar (source/bottom side)

    # Enclosing circle (two semicircles — full-circle arcs render unreliably).
    sym.add_arc(0, 0, 270, start_angle=0.0, end_angle=180.0, line_width=_LW, owner_part_id=-1)
    sym.add_arc(0, 0, 270, start_angle=180.0, end_angle=360.0, line_width=_LW, owner_part_id=-1)


def build(mpn: str) -> "object":
    """Re-author <MPN>.SchLib preserving its pins + metadata, with a proper
    channel-correct MOSFET-with-body-diode body."""
    channel = CHANNEL[mpn]
    src_name = symbol_name(mpn) or mpn
    src = AltiumSchLib(schlib_path(mpn)).get_symbol(src_name)
    # Snapshot the existing pins so the electrical interface is byte-identical.
    pins = [(p.designator, p.name, int(p.x_mils), int(p.y_mils),
             _ORIENT[int(p.orientation)], int(p.length_mils)) for p in src.pins]
    raw = symbol_summary(mpn).get("properties") or {}
    props = {k: v for k, v in raw.items()
             if k not in _DROP and str(v).strip() and str(v).strip() != k}
    desc = str(raw.get("Description", "") or getattr(src, "description", "") or "")

    lib = AltiumSchLib()
    sym = lib.add_symbol(mpn, description=desc)
    for desig, name, x, y, orient, length in pins:
        sym.add_pin(make_sch_pin(
            designator=desig, name=name,
            location_mils=SchPointMils.from_mils(x, y),
            orientation=orient, length_mils=length,
            electrical_type=PinElectrical.PASSIVE,
            name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT))
    _draw_body(sym, channel)
    sym.add_designator("Q?", 100, 200)
    for key, val in props.items():
        sym.add_parameter(str(key), str(val), is_hidden=True)
    out = schlib_path(mpn)
    lib.to_schlib(out)
    return out


def main(argv: list[str]) -> int:
    mpns = argv if argv else list(CHANNEL)
    for mpn in mpns:
        if mpn not in CHANNEL:
            print(f"unknown MOSFET {mpn!r}; known: {', '.join(CHANNEL)}")
            return 2
        out = build(mpn)
        print(f"authored {mpn} ({CHANNEL[mpn].upper()}-channel + body diode) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
