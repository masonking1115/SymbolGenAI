"""Symbol authoring + placement — the Altium replacement for gen/symbols.py.

In the KiCad backend, symbols.py parsed pin geometry out of a `.kicad_sym`
text file (`parse_pins`) and computed world coordinates by hand (`pin_world`),
because KiCad schematics embed each symbol's definition inline.

Altium inverts this: a placed component carries live pin records whose
hot-spots are already in world (sheet) coordinates. So this module shrinks to
two jobs:
  1. author `.SchLib` symbols (the equivalent of generating a `.kicad_sym`),
  2. place a symbol on a sheet and hand back {designator: (x_mil, y_mil)} so
     builders can wire pins parametrically — the same contract `place()`
     returned on the KiCad side.
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

from .config import FONT_DEFAULT


# KiCad lib_id -> authored SchLib symbol name. The netlist YAML speaks KiCad
# lib_ids; the Altium backend authors equivalently-pinned SchLib symbols.
LIBID_TO_SYMBOL = {
    "Device:R": "R",
    "Device:C": "C",
    "Lib:24AA08-I-SN": "24AA08-I-SN",
}


def _add_passive(lib, name: str, designator_prefix: str) -> None:
    """Author a 2-pin vertical passive: pin 1 on top, pin 2 on bottom. The drawn
    body uses the conventional glyph for the device class (a capacitor renders as
    plates, a resistor as an IEC box) instead of a generic rectangle. Pin
    hot-spots stay at (0, +/-100) so every builder's routing is unchanged; the
    pins point OUTWARD and start at the body edge (+/-70, the resistor zig-zag
    extent — wider than the cap plates at +/-25) so their connection end IS the
    outer tip and the pin line never runs THROUGH the body glyph (a pin starting
    inside the zig-zag looks like a net crossing the resistor)."""
    from . import glyphs
    sym = lib.add_symbol(name, description=f"Generic {name}")
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
    kind = glyphs.classify(designator_prefix, {}, len(hs), 1)
    glyphs.draw_body(sym, kind, hs, {}, -1)
    sym.add_designator(f"{designator_prefix}?", 100, 200)


def pin_world_coords(component) -> dict[str, tuple[int, int]]:
    """Return {designator: (x_mil, y_mil)} for a placed component's pins.

    This is the Altium analogue of KiCad `pin_world()`. Altium already stores
    pin hot-spots in sheet coordinates once a component is placed, so we just
    read them back instead of re-deriving from local coords + rotation.
    """
    out: dict[str, tuple[int, int]] = {}
    for pin in component.pins:
        hs = pin.get_hot_spot()
        out[str(pin.designator)] = (int(round(hs.x_mils)), int(round(hs.y_mils)))
    return out
