"""One-time migration: legacy `<MPN>.kicad_sym` -> native `<MPN>.SchLib`.

For every MPN the design references (plus any MPN dir that still ships a
`.kicad_sym`), author the committed `Parts Library/<MPN>/<MPN>.SchLib` using the
existing, render-fidelity-tuned layout in `translate.translate_symbol`. After
this runs once, the `.kicad_sym` files are no longer in any runtime path and
can be archived; symbols are authored/edited via `author_symbol` from then on.

Idempotent: re-running simply rewrites the .SchLib files.

NOTE: this migration has already been run; the legacy `.kicad_sym` inputs now
live under `test1/_archive_kicad/Parts Library/`. To re-run, restore them to
`Parts Library/<MPN>/<MPN>.kicad_sym` first (parse_pins reads that path).
"""

from __future__ import annotations

import re
import sys

from altium_monkey import (
    AltiumSchLib,
    PinElectrical,
    Rotation90,
    SchPointMils,
    make_sch_pin,
)

from .build_symbols import libid_map
from .config import FONT_DEFAULT
from .symlib import PARTS_LIB, read_pins, schlib_path
from .translate import translate_symbol


def _passive_ref(mpn: str) -> str | None:
    """If the MPN's .kicad_sym is a generic passive (no parseable pin geometry,
    KiCad Reference 'R' or 'C'), return that reference letter, else None."""
    f = PARTS_LIB / mpn / f"{mpn}.kicad_sym"
    if not f.exists():
        return None
    m = re.search(r'\(property\s+"Reference"\s+"([RC])"', f.read_text(errors="replace"))
    return m.group(1) if m else None


def _author_passive(mpn: str, ref: str) -> None:
    """Author a compact 2-pin passive (pin 1 top, pin 2 bottom) named <MPN>,
    matching symbols._add_passive geometry."""
    lib = AltiumSchLib()
    sym = lib.add_symbol(mpn, description=f"Generic {ref} ({mpn})")
    sym.add_rectangle(-50, -100, 50, 100)
    sym.add_pin(make_sch_pin(
        designator="1", name="", location_mils=SchPointMils.from_mils(0, 300),
        orientation=Rotation90.DEG_270, length_mils=200,
        electrical_type=PinElectrical.PASSIVE,
        name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT))
    sym.add_pin(make_sch_pin(
        designator="2", name="", location_mils=SchPointMils.from_mils(0, -300),
        orientation=Rotation90.DEG_90, length_mils=200,
        electrical_type=PinElectrical.PASSIVE,
        name_font=FONT_DEFAULT, designator_font=FONT_DEFAULT))
    sym.add_designator(f"{ref}?", 100, 200)
    out = schlib_path(mpn)
    out.parent.mkdir(parents=True, exist_ok=True)
    lib.to_schlib(out)


def _custom_mpns() -> list[str]:
    """MPNs to migrate: every Lib: part the netlists use, plus any other MPN
    directory that still has a per-MPN .kicad_sym (so the GUI library stays
    complete, not just the parts wired into a sheet)."""
    mpns = {lid.split(":", 1)[1] for lid in libid_map() if lid.startswith("Lib:")}
    if PARTS_LIB.exists():
        for d in PARTS_LIB.iterdir():
            if d.is_dir() and (d / f"{d.name}.kicad_sym").exists():
                mpns.add(d.name)
    return sorted(mpns)


def migrate_one(mpn: str) -> tuple[bool, str]:
    try:
        lib = AltiumSchLib()
        translate_symbol(lib, mpn)        # reads <mpn>.kicad_sym via parse_pins
        out = schlib_path(mpn)
        out.parent.mkdir(parents=True, exist_ok=True)
        lib.to_schlib(out)
        pins = read_pins(mpn)             # verify it reads back
        units = sorted({u for *_, u in pins.values()})
        extra = f", {len(units)} units" if len(units) > 1 else ""
        return True, f"{len(pins)} pins{extra}"
    except Exception as e:                # noqa: BLE001 — translate couldn't parse
        ref = _passive_ref(mpn)
        if ref:                           # generic R/C passive -> author one
            try:
                _author_passive(mpn, ref)
                return True, f"2 pins (generic {ref})"
            except Exception as e2:       # noqa: BLE001
                return False, f"passive author failed: {e2}"
        return False, str(e)


def main(argv: list[str]) -> int:
    only = set(argv)
    mpns = [m for m in _custom_mpns() if not only or m in only]
    print(f"Migrating {len(mpns)} symbol(s) -> per-MPN .SchLib\n")
    fails = 0
    for mpn in mpns:
        ok, msg = migrate_one(mpn)
        print(f"  [{'OK ' if ok else 'FAIL'}] {mpn:22} {msg}")
        fails += 0 if ok else 1
    print(f"\n{'all migrated' if fails == 0 else f'{fails} failed'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
