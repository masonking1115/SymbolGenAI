"""Build every sheet of the design into Altium .SchDoc + SVG.

Runs each per-sheet builder (which validates against the reused gen.validator),
saves the .SchDoc + render, and reports the auto-selected sheet size. The
A4-preferred template (AltiumSheet) upgrades only the sheets that need more
room, so simple sheets stay A4 and dense ones (FMC) grow as required.
"""

from __future__ import annotations

from .build_bias import build_bias
from .build_bobcat import build_bobcat
from .build_connectors import build_connectors
from .build_eeprom import build_eeprom
from .build_fmc import build_fmc
from .build_power import build_power
from .config import OUT_DIR, RENDER_DIR

BUILDERS = {
    "eeprom": build_eeprom,
    "connectors": build_connectors,
    "power": build_power,
    "bias": build_bias,
    "fmc": build_fmc,
    "bobcat": build_bobcat,
}


def main() -> int:
    print(f"{'sheet':12} {'paper':6} {'parts':6} {'nets':5} {'bbox (min..max)':24} status")
    print("-" * 78)
    fails = 0
    for name, fn in BUILDERS.items():
        try:
            s, nl = fn()                      # validate() runs inside fn
            s.save(OUT_DIR / f"{name}.SchDoc")
            s.render_svg(RENDER_DIR / f"{name}.svg")
            minx, miny, maxx, maxy = s.content_bbox()
            paper = getattr(s, "_chosen_paper", "?")
            W, H = s._PAPER_MIL.get(paper, (0, 0))
            # Containment: all content within [0,W] x [0,H] of the page.
            contained = minx >= 0 and miny >= 0 and maxx <= W and maxy <= H
            status = "OK" if contained else "OUT OF BOUNDS"
            if not contained:
                fails += 1
            print(f"{name:12} {paper:6} {len(s._placed):<6} {len(nl.nets):<5} "
                  f"{f'({minx},{miny})..({maxx},{maxy})':24} {status}")
        except Exception as e:
            fails += 1
            print(f"{name:12} {'-':6} {'-':6} {'-':5} {'-':24} FAIL: {type(e).__name__}: {e}")
    print("-" * 78)
    print("all sheets validated + contained" if fails == 0 else f"{fails} sheet(s) FAILED/OOB")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
