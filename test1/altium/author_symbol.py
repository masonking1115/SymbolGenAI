"""Author a native Altium `<MPN>.SchLib` from a JSON pin-spec.

This is the generation-time counterpart to `symlib.read_pins`: an AI (or a
human) describes a part's pins in a small, reviewable JSON file, and this
module lays them out on a clean 100-mil grid and writes the committed
`Parts Library/<MPN>/<MPN>.SchLib`. No KiCad anywhere in the loop.

Pin-spec schema (`<MPN>.pinspec.json`)::

    {
      "mpn": "TPS7A8401A",
      "description": "150 mA LDO, optional free text",
      "reference": "U",                 # designator prefix (U/R/C/J/Q/...)
      "properties": {                    # -> Altium component parameters
        "Value": "TPS7A8401ARGRR",
        "Footprint": "RGR0020A",
        "Datasheet": "https://www.ti.com/lit/gpn/tps7a84a",
        "Manufacturer": "Texas Instruments",
        "MPN": "TPS7A8401ARGRR"
      },
      "units": [
        {"unit": 1, "pins": [
          {"number": "1", "name": "IN",  "type": "power_in",  "side": "left"},
          {"number": "5", "name": "OUT", "type": "output",    "side": "right"},
          ...
        ]}
      ]
    }

`type`  ∈ input|output|bidirectional|passive|power_in|power_out|
          tri_state|open_collector|open_emitter   (KiCad-style names; mapped to
          the nearest Altium PinElectrical).
`side`  ∈ left|right|top|bottom   (which body edge the pin sits on).
A single-unit part may omit "units" and provide a top-level "pins" list.
"""

from __future__ import annotations

import json
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
from .symlib import PARTS_LIB, schlib_path
from .units import min_half_x_for_names

PITCH = 200          # mil between pins on a side
PIN_LEN = 200        # mil

_ETYPE = {
    "input": PinElectrical.INPUT,
    "output": PinElectrical.OUTPUT,
    "bidirectional": PinElectrical.IO,
    "io": PinElectrical.IO,
    "passive": PinElectrical.PASSIVE,
    "power_in": PinElectrical.POWER,
    "power_out": PinElectrical.POWER,
    "power": PinElectrical.POWER,
    "tri_state": PinElectrical.HIZ,
    "hiz": PinElectrical.HIZ,
    "open_collector": PinElectrical.OPEN_COLLECTOR,
    "open_emitter": PinElectrical.OPEN_EMITTER,
    "no_connect": PinElectrical.PASSIVE,
    "unspecified": PinElectrical.PASSIVE,
}
_ORIENT = {"left": Rotation90.DEG_180, "right": Rotation90.DEG_0,
           "top": Rotation90.DEG_90, "bottom": Rotation90.DEG_270}
_SIDE_KEY = {"left": "L", "right": "R", "top": "T", "bottom": "B"}


def _r100(v: float) -> int:
    return int(round(v / 100.0) * 100)


def _author_unit(sym, pins: list[dict], owner: int, prefix: str = "U") -> None:
    """Lay one unit's pins on-grid, grouped by their declared side, then draw the
    conventional body glyph for the device class (capacitor plates, resistor
    zig-zag, MOSFET, op-amp triangle, ...) instead of a generic rectangle."""
    sides: dict[str, list[dict]] = {"L": [], "R": [], "T": [], "B": []}
    for p in pins:
        side = _SIDE_KEY.get(str(p.get("side", "left")).lower(), "L")
        sides[side].append(p)

    nL, nR, nT, nB = (len(sides[s]) for s in "LRTB")
    half_x = max(300, _r100((max(nT, nB, 1) / 2) * PITCH + PITCH))
    half_y = max(300, _r100((max(nL, nR, 1) / 2) * PITCH + PITCH))
    # Widen so left/right pin names don't collide inside the body.
    half_x = max(half_x, min_half_x_for_names(
        [str(p.get("name", "")) for p in sides["L"]],
        [str(p.get("name", "")) for p in sides["R"]]))

    def emit(side: str):
        lst = sides[side]
        n = len(lst)
        for i, p in enumerate(lst):
            off = int(((n - 1) / 2 - i) * PITCH)
            if side == "L":
                loc = (-half_x, off)
                orient = _ORIENT["left"]
            elif side == "R":
                loc = (half_x, off)
                orient = _ORIENT["right"]
            elif side == "T":
                loc = (-off, half_y)
                orient = _ORIENT["top"]
            else:
                loc = (-off, -half_y)
                orient = _ORIENT["bottom"]
            nm = str(p.get("name", "") or "")
            sym.add_pin(make_sch_pin(
                designator=str(p["number"]),
                name=("" if nm in ("~", "") else nm),
                location_mils=SchPointMils.from_mils(*loc),
                orientation=orient, length_mils=PIN_LEN,
                electrical_type=_ETYPE.get(str(p.get("type", "passive")).lower(),
                                           PinElectrical.PASSIVE),
                name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT,
                owner_part_id=(owner if owner != -1 else None)))

    for s in "LRTB":
        emit(s)

    # Body glyph from the device class (falls back to a rectangle for ICs).
    from . import glyphs
    hs, nmap = {}, {}
    for p in sym.pins:
        if owner not in (-1, None) and p.owner_part_id not in (owner, None):
            continue
        h = p.get_hot_spot()
        hs[str(p.designator)] = (int(round(h.x_mils)), int(round(h.y_mils)))
        nmap[str(p.designator)] = p.name or ""
    n_units = int(getattr(sym, "part_count", 1) or 1)
    kind = glyphs.classify(prefix, nmap, len(hs), n_units)
    if kind == "ic":
        sym.add_rectangle(-half_x, -half_y, half_x, half_y, owner_part_id=owner)
    else:
        glyphs.draw_body(sym, kind, hs, nmap, owner)


def _normalize_units(spec: dict) -> list[tuple[int, list[dict]]]:
    if spec.get("units"):
        units = [(int(u.get("unit", i + 1)), list(u.get("pins", [])))
                 for i, u in enumerate(spec["units"])]
    else:
        units = [(1, list(spec.get("pins", [])))]
    return [(u, pins) for u, pins in units if pins]


def build_from_spec(spec: dict, out_path: Path | None = None) -> Path:
    """Author <MPN>.SchLib from a pin-spec dict. Returns the written path."""
    mpn = spec["mpn"]
    out_path = out_path or schlib_path(mpn)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    units = _normalize_units(spec)
    if not units:
        raise ValueError(f"pin-spec for {mpn} has no pins")

    lib = AltiumSchLib()
    sym = lib.add_symbol(mpn, description=spec.get("description", ""))
    multi = len(units) > 1
    if multi:
        sym.set_part_count(len(units))
    # Designator prefix from "reference" (U/R/C/J/Q/...), default U.
    ref = re.sub(r"\d+$", "", str(spec.get("reference", "U")).strip()) or "U"
    for unit, pins in units:
        _author_unit(sym, pins, owner=(unit if multi else -1), prefix=ref)
    sym.add_designator(f"{ref}?", 0, 0)
    # Component parameters (Value/Footprint/Datasheet/Manufacturer/MPN/...) are
    # HIDDEN metadata — kept in the Properties dialog, never drawn on the sheet
    # (visible params stack at the origin into a text "glob"). The value is
    # shown via the component Comment at placement time.
    for key, val in (spec.get("properties") or {}).items():
        if str(val).strip():
            sym.add_parameter(str(key), str(val), is_hidden=True)
    lib.to_schlib(out_path)
    return out_path


def build_from_file(mpn: str) -> Path:
    """Read Parts Library/<MPN>/<MPN>.pinspec.json and author the .SchLib."""
    spec_path = PARTS_LIB / mpn / f"{mpn}.pinspec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"no pin-spec at {spec_path}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec.setdefault("mpn", mpn)
    return build_from_spec(spec)


def build_from_clone(mpn: str, source_mpn: str) -> Path:
    """Author <MPN>.SchLib by CLONING an existing sibling part's .SchLib —
    GEOMETRY-IDENTICAL (same pin coordinates, body, pitch), only the part
    identity swapped.

    Why this exists: the sheet builders (altium/build_<sheet>.py) route a part's
    pins at coordinates calibrated to that part's EXACT symbol geometry. A symbol
    re-authored from a pin-spec lands its pins on a clean 200-mil grid, which may
    NOT match a hand-tuned sibling — placing the regenerated part then shifts pin
    positions and shorts/splits nets. For a same-package value swap (e.g. one
    0603 thin-film resistor value to another), the correct move is to copy the
    sibling's .SchLib verbatim and only rename the symbol identity. Component
    *values* live in the netlist (netlist/*.yaml `value:`), not the symbol, so no
    value field needs patching here.

    The symbol identity appears in TWO encodings inside the .SchLib (an OLE
    compound file): the canonical symbol name is a UTF-16LE entry in the OLE
    storage directory (what `get_symbol_names` reads), and the same string also
    appears in `|`-delimited ASCII records (LibRef0, LibReference, DesignItemId,
    the symbol-name Text). We rewrite BOTH. A length-equal rename (typical for a
    same-series swap, e.g. TNPW0603xxxxBEEA → 16 chars either way) is fully
    offset-safe in the OLE directory; an unequal-length rename would shift the
    UTF-16 directory entry, so we refuse it and tell the caller to use a
    pin-spec instead.
    """
    src_path = schlib_path(source_mpn)
    if not src_path.exists():
        raise FileNotFoundError(f"clone source .SchLib not found: {src_path}")
    src_b = source_mpn.encode("latin1")
    new_b = mpn.encode("latin1")
    src_u16 = source_mpn.encode("utf-16-le")
    new_u16 = mpn.encode("utf-16-le")
    data = src_path.read_bytes()
    if src_b not in data or src_u16 not in data:
        raise ValueError(
            f"source .SchLib {source_mpn!r} not found in both ASCII + UTF-16 "
            "forms; cannot clone-rename safely")
    if len(src_b) != len(new_b):
        # Unequal length would move the UTF-16 OLE directory entry (the byte
        # offsets that index the storage are length-sensitive). Don't risk
        # corruption — the caller should author from a pin-spec for this part.
        raise ValueError(
            f"clone requires equal-length MPNs (OLE directory is offset-"
            f"sensitive): {source_mpn!r} ({len(source_mpn)}) vs {mpn!r} "
            f"({len(mpn)}). Author from a pin-spec instead.")
    data = data.replace(src_u16, new_u16).replace(src_b, new_b)
    out_path = schlib_path(mpn)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    # Verify the clone parses and exposes exactly the renamed symbol.
    names = AltiumSchLib.get_symbol_names(out_path)
    if names != [mpn]:
        raise RuntimeError(
            f"clone wrote {out_path} but symbol names = {names} (expected "
            f"[{mpn!r}])")
    return out_path


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m test1.altium.author_symbol <MPN> "
              "[--clone-from <SOURCE_MPN>]", file=sys.stderr)
        return 2
    mpn = argv[0]
    clone_from: str | None = None
    if "--clone-from" in argv:
        i = argv.index("--clone-from")
        if i + 1 >= len(argv):
            print("--clone-from requires a SOURCE_MPN", file=sys.stderr)
            return 2
        clone_from = argv[i + 1]

    if clone_from:
        out = build_from_clone(mpn, clone_from)
        from .symlib import read_pins
        pins = read_pins(mpn)
        print(f"Wrote {out} — symbol {mpn!r} CLONED from {clone_from!r} "
              f"({len(pins)} pins, geometry-identical)")
    else:
        out = build_from_file(mpn)
        from .symlib import read_pins
        pins = read_pins(mpn)
        units = sorted({u for *_, u in pins.values()})
        extra = f", {len(units)} units" if len(units) > 1 else ""
        print(f"Wrote {out} — symbol {mpn!r} ({len(pins)} pins{extra})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
