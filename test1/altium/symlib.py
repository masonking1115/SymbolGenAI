"""Native Altium symbol source-of-truth helpers.

The project's committed symbols are now per-MPN Altium libraries:
`Parts Library/<MPN>/<MPN>.SchLib`, each holding ONE symbol named exactly
`<MPN>`. This module is the single place that knows that convention and reads
those files back through altium_monkey — the Altium-native replacement for
`gen.symbols.parse_pins` (which parsed `.kicad_sym` text).

Nothing here writes symbols; authoring lives in `author_symbol.py` (from a
JSON pin-spec), or a `.SchLib` is installed directly from Ultra Librarian.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from altium_monkey import AltiumSchLib, PinElectrical

from .config import ALTIUM_DIR

# Parts Library lives next to the altium/ package (test1/Parts Library).
PARTS_LIB = ALTIUM_DIR.parent / "Parts Library"

# Altium has a single POWER electrical type; KiCad (and the GUI) distinguish
# power_in/power_out. We surface POWER as "power_in" — the common case for IC
# supply/ground pins — since the binary carries no in/out bit to recover.
ETYPE_NAME: dict[PinElectrical, str] = {
    PinElectrical.INPUT: "input",
    PinElectrical.OUTPUT: "output",
    PinElectrical.IO: "bidirectional",
    PinElectrical.PASSIVE: "passive",
    PinElectrical.POWER: "power_in",
    PinElectrical.HIZ: "tri_state",
    PinElectrical.OPEN_COLLECTOR: "open_collector",
    PinElectrical.OPEN_EMITTER: "open_emitter",
}


def schlib_path(mpn: str) -> Path:
    """Path to the committed per-MPN symbol library (may not exist)."""
    return PARTS_LIB / mpn / f"{mpn}.SchLib"


def has_symbol(mpn: str) -> bool:
    return schlib_path(mpn).exists()


# Open + parse each .SchLib AT MOST ONCE per (mpn, file mtime). symbol_name,
# read_pins, and _summary all funnel through here, so a build that touches a
# part 5×—or verify_coverage walking every net-member pin—re-parses the file 0
# extra times. mtime keying means a regenerated/swapped library is still picked
# up on the next call. (Previously each of those helpers re-opened the file.)
@lru_cache(maxsize=None)
def _load_schlib(mpn: str, mtime: float) -> AltiumSchLib | None:
    p = schlib_path(mpn)
    if not p.exists():
        return None
    try:
        return AltiumSchLib(p)
    except Exception:
        return None


def _schlib(mpn: str) -> AltiumSchLib | None:
    """Cached parsed library for an MPN (None if absent/unparseable)."""
    p = schlib_path(mpn)
    if not p.exists():
        return None
    return _load_schlib(mpn, p.stat().st_mtime)


@lru_cache(maxsize=None)
def _symbol_names(mpn: str, mtime: float) -> tuple[str, ...]:
    """Memoized symbol-name list (get_symbol_names is a static path call)."""
    try:
        return tuple(AltiumSchLib.get_symbol_names(schlib_path(mpn)))
    except Exception:
        return ()


def symbol_name(mpn: str) -> str | None:
    """The symbol name to look up inside the MPN's library. By construction we
    author it as exactly `<MPN>`, but fall back to the first symbol present so a
    hand-built library with a vendor-internal name still resolves."""
    p = schlib_path(mpn)
    if not p.exists():
        return None
    names = _symbol_names(mpn, p.stat().st_mtime)
    if not names:
        return None
    return mpn if mpn in names else names[0]


def read_pins(mpn: str) -> dict[str, tuple[str, float, float, int, int]]:
    """Return {designator: (name, x_mils, y_mils, angle_deg, unit)} for the
    MPN's symbol — the Altium-native analogue of gen.symbols.parse_pins.

    angle_deg is derived from the pin orientation (0/90/180/270). unit is the
    Altium owner_part_id (1-based; 1 for single-unit parts).
    """
    lib = _schlib(mpn)
    name = symbol_name(mpn)
    if lib is None or name is None:
        return {}
    sym = lib.get_symbol(name)
    if sym is None:
        return {}
    out: dict[str, tuple[str, float, float, int, int]] = {}
    for pin in sym.pins:
        angle = int(getattr(pin.orientation, "value", 0)) * 90
        nm = pin.name or ""
        out[str(pin.designator)] = (
            nm, float(pin.x_mils), float(pin.y_mils), angle,
            int(pin.owner_part_id or 1),
        )
    return out


@lru_cache(maxsize=None)
def _summary(mpn: str, mtime: float) -> dict:
    """Parsed symbol summary, memoised on (mpn, file mtime) so repeated GUI
    reads are cheap but a regenerated library is picked up."""
    name = symbol_name(mpn)
    lib = _schlib(mpn)
    if name is None or lib is None:
        return {}
    sym = lib.get_symbol(name)
    if sym is None:
        return {}
    props: dict[str, str] = {}
    for prm in getattr(sym, "parameters", []) or []:
        k = getattr(prm, "name", None)
        v = getattr(prm, "text", None)
        if k and v:
            props[str(k)] = str(v)
    desc = getattr(sym, "description", "") or ""
    if desc and "Description" not in props:
        props["Description"] = desc
    pins = []
    units: set[int] = set()
    for pin in sym.pins:
        unit = int(pin.owner_part_id or 1)
        units.add(unit)
        pins.append({
            "number": str(pin.designator),
            "name": pin.name or "~",
            "etype": ETYPE_NAME.get(pin.electrical, "unspecified"),
            "x": float(pin.x_mils),
            "y": float(pin.y_mils),
            "rotation": int(getattr(pin.orientation, "value", 0)) * 90,
            "unit": unit,
        })
    # Sort like the KiCad GUI did: left pins first, then right, by number.
    pins.sort(key=lambda d: (
        0 if d["x"] < 0 else 1 if d["x"] > 0 else 2,
        int(d["number"]) if d["number"].isdigit() else 9999,
    ))
    return {
        "name": name,
        "mpn": mpn,
        "properties": props,
        "pins": pins,
        "pin_count": len(pins),
        "unit_names": [f"{name}_unit{u}" for u in sorted(units)] if len(units) > 1 else [],
    }


def symbol_summary(mpn: str) -> dict:
    """GUI-shaped summary {name, mpn, pins[], pin_count, unit_names[]} or {}."""
    p = schlib_path(mpn)
    if not p.exists():
        return {}
    return _summary(mpn, p.stat().st_mtime)
