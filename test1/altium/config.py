"""Project-wide constants for the Altium backend.

Mirror of gen/config.py, retargeted from KiCad to Altium. Paths, the default
fonts, and power-rail style mapping live here so builders pull them via
`from .config import ...` exactly as the KiCad side does.

What changed vs gen/config.py:
  - No KICAD_CLI / SCH_VERSION / GENERATOR triple — Altium rendering is the
    in-process `AltiumSchDoc.to_svg()`, not an external CLI.
  - File-format UUID plumbing (ROOT_UUID, sheet UUIDs, the deterministic uid()
    helper) is gone: altium_monkey assigns object IDs internally on save.
  - Footprint constants become PcbLib/footprint names, not KiCad lib_ids.
"""

from __future__ import annotations

from pathlib import Path

from altium_monkey import PowerObjectStyle, SchFontSpec

PROJECT_DIR = Path(__file__).resolve().parent.parent     # test1/
ALTIUM_DIR = PROJECT_DIR / "altium"
OUT_DIR = ALTIUM_DIR / "out"                              # generated .SchDoc/.SchLib/.PcbLib
RENDER_DIR = OUT_DIR / "render"                           # generated .svg
LIB_DIR = OUT_DIR / "lib"                                 # authored libraries

PROJECT_NAME = "test1"

# Default fonts — one place so every primitive renders consistently, the way
# the KiCad side hard-codes (size 1.27 1.27) everywhere.
FONT_DEFAULT = SchFontSpec(name="Arial", size=10)
FONT_NOTE = SchFontSpec(name="Arial", size=9)

# Rail name -> Altium power-port glyph. KiCad used a power: symbol per rail;
# Altium encodes the glyph as a style on a single power-port object.
POWER_STYLE = {
    "GND": PowerObjectStyle.GND_POWER,
    "AGND": PowerObjectStyle.GND_SIGNAL,
    "PGND": PowerObjectStyle.GND_POWER,
    # Everything else (rails like +3V3, +1V8, VDDIO) renders as an arrow.
}


def power_style_for(rail: str) -> PowerObjectStyle:
    return POWER_STYLE.get(rail, PowerObjectStyle.ARROW)
