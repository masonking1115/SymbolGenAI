"""gen — KiCad schematic generator package for test1.

Layered split so per-session edits load minimal context:
  config.py        — constants, paths, uid(), SHEET_*, LA_ASSIGN, footprints
  symbols.py       — symbol embedding (clause-strip, sub-unit rename),
                     pin coord extraction, pin_world transform
  shared.py        — Sheet container, primitives (wire/junction/labels/
                     no_connect), place(), power_at(), sheet_block()
  build_<sheet>.py — one builder per child sheet, plus build_root
"""

from .build_bias import build_bias
from .build_bobcat import build_bobcat
from .build_connectors import build_connectors
from .build_eeprom import build_eeprom
from .build_fmc import build_fmc
from .build_power import build_power
from .build_root import build_root

__all__ = [
    "build_bias",
    "build_bobcat",
    "build_connectors",
    "build_eeprom",
    "build_fmc",
    "build_power",
    "build_root",
]
