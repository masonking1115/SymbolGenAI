"""One-shot: rewrite Parts Library/Bobcat/Bobcat.SchLib so its pin NAMES render
at the readable sheet-default size instead of the tiny size they showed as —
"the text in bobcat is not renderable in the png" the user flagged.

ROOT CAUSE (subtle): the source Bobcat pins used a CUSTOM font referenced by
`name_settings.font_id` (id 2 = Arial 10 in the *source* library). But
`AltiumSchLib.merge` (used by build_symbols to build out/lib/parts.SchLib) does
NOT remap per-symbol font_ids when it merges font tables — the merged table's
id 2 ends up as a tiny Courier-New-5 (won by another part's table), while the
Bobcat pins still point at id 2. So on the assembled sheet the names rendered at
Courier-5. Bumping the *source* font size is futile: merge overwrites what id 2
means.

THE FIX: author the pins in **DEFAULT font mode** (no explicit name_font →
`font_mode=0`, `font_id=None`). DEFAULT-mode names render at the schematic's
standard pin-name size and DON'T depend on the font table, so they survive the
merge bug intact — exactly how the UL-imported parts that render fine (MCP4728,
OPA2388, TPS7A8401A, ...) are authored. The result is clean, readable Bobcat pin
names like every other IC on the sheet.

(The same latent merge-font bug affects the passives / MOSFET symbols that still
use CUSTOM id 2; they happen to be 2-pin parts with short, still-legible names,
so this targeted fix addresses the part the user flagged. A general fix would be
to re-author every CUSTOM-font part in DEFAULT mode, or fix merge upstream.)

Pin GEOMETRY (designators, hot-spots, sides, electrical types, owner part) and
the body rectangle are preserved EXACTLY — only the font MODE changes — so every
builder that routes from Bobcat pin hot-spots is byte-for-byte unaffected (zero
risk to connectivity/placement). Also repairs the mojibake em-dash in the
description.

Re-runnable and idempotent. The merge in build_symbols picks it up automatically
because it rewrites the committed source .SchLib (newer mtime than the merged
parts.SchLib). Run:
    python -m test1.altium._fix_bobcat_pinfont
"""

from __future__ import annotations

from altium_monkey import (
    AltiumSchLib,
    PinElectrical,
    SchPointMils,
    make_sch_pin,
)

from .symlib import schlib_path

HALF_X = 1400   # body unchanged
HALF_Y = 1500


def rewrite() -> str:
    src = schlib_path("Bobcat")
    old = AltiumSchLib(str(src)).get_symbol("Bobcat")
    if old is None:
        raise RuntimeError("Bobcat symbol not found")

    # Repair the description's corrupted em-dash (cp1252 mojibake) if present.
    desc = (old.description or "")
    desc = desc.replace("â€”", "-").replace("â€”", "-")

    lib = AltiumSchLib()
    sym = lib.add_symbol("Bobcat", description=desc)

    # Re-emit every pin with IDENTICAL geometry but an explicit readable font.
    # Use x_mils/y_mils (the body-edge ANCHOR in mils) — NOT p.location, whose
    # CoordPoint is in 10-mil internal units. from_mils(x_mils,y_mils) reproduces
    # the original hot-spot exactly (verified pin-by-pin).
    for p in old.pins:
        x, y = int(round(p.x_mils)), int(round(p.y_mils))
        sym.add_pin(make_sch_pin(
            designator=str(p.designator),
            name=str(p.name or ""),
            location_mils=SchPointMils.from_mils(x, y),
            orientation=p.orientation,
            length_mils=float(p.length_mils),
            electrical_type=(p.electrical if isinstance(p.electrical, PinElectrical)
                             else PinElectrical.PASSIVE),
            name_visible=bool(p.show_name),
            designator_visible=bool(p.show_designator),
            hidden=bool(p.is_hidden),
            owner_part_id=(int(p.owner_part_id) if p.owner_part_id else None),
            # No name_font/designator_font -> DEFAULT font mode (font_id=None),
            # which renders at the readable sheet-default pin size and is immune
            # to the merge font-table scramble (see module docstring).
        ))

    sym.add_rectangle(-HALF_X, -HALF_Y, HALF_X, HALF_Y, owner_part_id=-1)
    sym.add_designator("U?", 0, 0)

    # Preserve hidden metadata parameters (Value/Footprint/MPN/...) so the part
    # stays fully specified; they remain hidden (never drawn).
    for prm in getattr(old, "parameters", []) or []:
        name = getattr(prm, "name", None)
        val = getattr(prm, "text", None) or getattr(prm, "value", None)
        if name and val:
            sym.add_parameter(str(name), str(val), is_hidden=True)

    lib.to_schlib(str(src))
    return str(src)


def main() -> int:
    path = rewrite()
    sym = AltiumSchLib(path).get_symbol("Bobcat")
    # font_id the names now reference (resolved against the lib font table below).
    fids = {p.name_settings.font_id for p in sym.pins if p.name_settings}
    fonts = AltiumSchLib(path).font_manager.fonts
    used = {fid: fonts.get(fid) for fid in fids}
    print(f"Rewrote {path}: {len(sym.pins)} pins; name font(s) -> {used}")
    # Confirm the larger names don't collide (library-scope linter rule).
    from .layout_lint import lint_library
    issues = lint_library(path)
    if issues:
        print("  pin_name_overlap WARNINGS:")
        for i in issues:
            print("   ", i)
    else:
        print("  pin_name_overlap: clean (no opposing-name collisions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
