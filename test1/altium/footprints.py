"""Footprint authoring — Altium replacement for the KiCad `.pretty` libraries.

Gate 0 only needs to prove the PcbLib authoring path round-trips, so this
synthesises a couple of simple SMD footprints (an 0402 passive and an SOIC-8)
without 3D models. The full port would translate the FP_* constants in
gen/config.py into a complete PcbLib.
"""

from __future__ import annotations

from pathlib import Path

from altium_monkey import AltiumPcbLib, PadShape, PcbLayer


def author_footprint_lib(out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lib = AltiumPcbLib()

    # 0402 two-pad passive.
    c0402 = lib.add_footprint("C0402", height="22mil", description="Capacitor 0402")
    for des, x in (("1", -19.7), ("2", 19.7)):
        c0402.add_pad(designator=des, position_mils=(x, 0.0),
                      width_mils=20.0, height_mils=24.0,
                      layer=PcbLayer.TOP, shape=PadShape.RECTANGLE)

    # SOIC-8: 2 rows of 4, 50 mil pitch, ~150 mil row spacing.
    soic = lib.add_footprint("SOIC8", height="69mil", description="SOIC-8")
    for i in range(4):
        y = 75.0 - i * 50.0
        soic.add_pad(designator=str(i + 1), position_mils=(-110.0, y),
                     width_mils=60.0, height_mils=24.0,
                     layer=PcbLayer.TOP, shape=PadShape.RECTANGLE)
    for i in range(4):
        y = -75.0 + i * 50.0
        soic.add_pad(designator=str(i + 5), position_mils=(110.0, y),
                     width_mils=60.0, height_mils=24.0,
                     layer=PcbLayer.TOP, shape=PadShape.RECTANGLE)

    lib.save(out_path)
    return out_path
