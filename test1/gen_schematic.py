#!/usr/bin/env python3
"""
KiCad schematic generator for test1 (Bobcat carrier board).

Emits a hierarchical KiCad project at test1/kicad/:
  test1.kicad_pro                — project file with sheets array
  test1.kicad_sch                — root sheet (sheet blocks only)
  fmc.kicad_sch                  — VITA 57.1 LPC connector
  power.kicad_sch                — TPS7A8401A LDO + load switch
  bobcat.kicad_sch               — Bobcat DUT + decoupling + isolators
  eeprom.kicad_sch               — 24AA08 I2C EEPROM
  bias.kicad_sch                 — MCP4728 + OPA2388 + PMOS bias generators
  connectors.kicad_sch           — SMAs + GPIO header + GND clips

UUIDs are derived deterministically from a project namespace so re-runs
produce stable files (good for git diffs).
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent
PARTS_LIB = PROJECT_DIR / "Parts Library"
OUT_DIR = PROJECT_DIR / "kicad"
RENDER_DIR = OUT_DIR / "render"
PROJECT_NAME = "test1"
SCH_VERSION = "20250114"
GENERATOR = "eeschema"
GENERATOR_VERSION = "10.99"
KICAD_CLI = "/Users/masonking/Downloads/kicad/build/kicad/KiCad.app/Contents/MacOS/kicad-cli"

# Deterministic UUIDs derived from a project-local namespace.
_NS = uuid.UUID("11111111-2222-3333-4444-555555555555")
def uid(name: str) -> str:
    return str(uuid.uuid5(_NS, name))

ROOT_UUID = uid("root")
SHEET_NAMES = ["fmc", "power", "bobcat", "eeprom", "bias", "connectors"]
SHEET_UUIDS = {name: uid(f"sheet_{name}") for name in SHEET_NAMES}
SHEET_TITLES = {
    "fmc": "FMC Connector",
    "power": "Power",
    "bobcat": "Bobcat DUT",
    "eeprom": "EEPROM",
    "bias": "Bias Generators",
    "connectors": "Connectors / Breakouts",
}

# Page numbers: root=1, children in declared order
PAGE_NUMBERS = {"root": "1"}
for i, n in enumerate(SHEET_NAMES, start=2):
    PAGE_NUMBERS[n] = str(i)

# ---------------------------------------------------------------------------
# Symbol library loader
# ---------------------------------------------------------------------------

def _find_matching_paren(text: str, open_idx: int) -> int:
    """Given the index of an '(' in text, return the index of its matching ')'."""
    depth = 0
    for i in range(open_idx, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced parens")


def _read_symbol_file(dir_name: str) -> tuple[str, str]:
    """Read PARTS_LIB/<dir_name>/<dir_name>.kicad_sym; return (inner_symbol_name, file_text)."""
    path = PARTS_LIB / dir_name / f"{dir_name}.kicad_sym"
    text = path.read_text()
    # The file's outer wrapper is (kicad_symbol_lib ...); the first (symbol "X"
    # inside it is the top-level definition. Symbol name may differ from
    # the directory name (e.g. dashes vs underscores).
    m = re.search(r'\(symbol\s+"([^"]+)"', text)
    if m is None:
        raise ValueError(f"no (symbol ...) block in {path}")
    return m.group(1), text


def _strip_clause(block: str, clause_name: str) -> str:
    """Remove every (clause_name ...) sub-expression from block."""
    out = []
    i = 0
    while i < len(block):
        marker = f"({clause_name}"
        idx = block.find(marker, i)
        if idx < 0:
            out.append(block[i:])
            break
        # Verify the next char is whitespace or ')' (not a longer identifier)
        nxt = block[idx + len(marker) : idx + len(marker) + 1]
        if nxt and nxt not in " \t\n)":
            out.append(block[i : idx + 1])
            i = idx + 1
            continue
        out.append(block[i:idx])
        end = _find_matching_paren(block, idx)
        # Also swallow leading whitespace before the clause for cleanliness
        # (find start of line if the clause is alone on its line)
        i = end + 1
    return "".join(out)


def extract_symbol_block(dir_name: str, lib_prefix: str = "Lib") -> str:
    """
    Extract the top-level (symbol "X" ...) block from PARTS_LIB/<dir_name>/
    and rename it to (symbol "<lib_prefix>:<dir_name>" ...) for embedding.
    The internal X (which may differ from dir_name) is replaced so the
    lib_id we use in schematics matches the directory name 1:1.

    KiCad's .kicad_sym files include metadata clauses (do_not_autoplace,
    show_name, in_pos_files, duplicate_pin_numbers_are_jumpers, …) that are
    valid in the symbol-library context but *not* inside a schematic's
    (lib_symbols …). We strip those.
    """
    inner, text = _read_symbol_file(dir_name)
    m = re.search(rf'\(symbol\s+"{re.escape(inner)}"', text)
    start = m.start()
    end = _find_matching_paren(text, start)
    block = text[start : end + 1]
    block = re.sub(
        rf'\(symbol\s+"{re.escape(inner)}"',
        f'(symbol "{lib_prefix}:{dir_name}"',
        block,
        count=1,
    )
    # Sub-units MUST have stems matching the OUTER name (post-colon), but
    # without the lib prefix. e.g. outer "Lib:24AA08-I-SN" → sub-units
    # "24AA08-I-SN_0_1", not "24AA08-I_SN_0_1" (the raw .kicad_sym stem).
    if inner != dir_name:
        block = block.replace(f'(symbol "{inner}_', f'(symbol "{dir_name}_')

    # These property clauses are valid in .kicad_sym files but cause a parse
    # failure inside a schematic's (lib_symbols …) on this KiCad build.
    for clause in ("do_not_autoplace", "show_name"):
        block = _strip_clause(block, clause)
    return block


# Standard KiCad library symbols (R, C, L, power) — embedded inline rather than
# pulled from disk so we don't depend on system KiCad libs. These match the
# stock Device:R, Device:C, Device:L, power:GND, power:+3V3 definitions.
# Pin coords are from the upstream KiCad symbol library.

STD_SYMBOLS: dict[str, str] = {
    # Resistor — vertical, pins at (0, +2.54) and (0, -2.54), body span y ±1.016.
    "Device:R": '''(symbol "Device:R"
    (pin_numbers (hide yes))
    (pin_names (offset 0))
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at -1.778 0 90) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Description" "Resistor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (symbol "R_0_1"
      (rectangle (start -1.016 -2.54) (end 1.016 2.54)
        (stroke (width 0.254) (type default)) (fill (type none)))
    )
    (symbol "R_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 1.27)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))
    )
  )''',
    # Capacitor — non-polarized, vertical, pins at (0, +3.81) and (0, -3.81).
    "Device:C": '''(symbol "Device:C"
    (pin_numbers (hide yes))
    (pin_names (offset 0.254))
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (property "Reference" "C" (at 0.635 2.54 0) (effects (font (size 1.27 1.27))))
    (property "Value" "C" (at 0.635 -2.54 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at 0.9652 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Description" "Unpolarized capacitor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (symbol "C_0_1"
      (polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762))
        (stroke (width 0.508) (type default)) (fill (type none)))
      (polyline (pts (xy -2.032 0.762) (xy 2.032 0.762))
        (stroke (width 0.508) (type default)) (fill (type none)))
    )
    (symbol "C_1_1"
      (pin passive line (at 0 3.81 270) (length 2.794)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 2.794)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))
    )
  )''',
    # power:GND — triangle pointing down, single pin at origin (0,0).
    "power:GND": '''(symbol "power:GND"
    (power)
    (pin_names (offset 0) (hide yes))
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (property "Reference" "#PWR" (at 0 -6.35 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "GND" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Description" "Power symbol — GND" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (symbol "GND_0_1"
      (polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27))
        (stroke (width 0) (type default)) (fill (type none)))
    )
    (symbol "GND_1_1"
      (pin power_in line (at 0 0 270) (length 0) (hide yes)
        (name "GND" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
    )
  )''',
    # power:+3V3 — arrow pointing up, pin at origin.
    "power:+3V3": '''(symbol "power:+3V3"
    (power)
    (pin_names (offset 0) (hide yes))
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (property "Reference" "#PWR" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "+3V3" (at 0 3.556 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Description" "Power symbol — +3V3" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (symbol "+3V3_0_1"
      (polyline (pts (xy -0.762 1.27) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))
      (polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))
      (polyline (pts (xy 0 2.54) (xy 0.762 1.27)) (stroke (width 0) (type default)) (fill (type none)))
    )
    (symbol "+3V3_1_1"
      (pin power_in line (at 0 0 90) (length 0) (hide yes)
        (name "+3V3" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
    )
  )''',
}

# Generic-rail variants — reuse +3V3 geometry, just relabel.
def _power_rail_symbol(net_name: str) -> str:
    """Create a power: symbol for a named rail (e.g. +VDDD) using +3V3 shape."""
    safe = net_name  # keep exact net name in the symbol id
    return f'''(symbol "power:{safe}"
    (power)
    (pin_names (offset 0) (hide yes))
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (property "Reference" "#PWR" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "{safe}" (at 0 3.556 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Description" "Power symbol — {safe}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (symbol "{safe}_0_1"
      (polyline (pts (xy -0.762 1.27) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))
      (polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))
      (polyline (pts (xy 0 2.54) (xy 0.762 1.27)) (stroke (width 0) (type default)) (fill (type none)))
    )
    (symbol "{safe}_1_1"
      (pin power_in line (at 0 0 90) (length 0) (hide yes)
        (name "{safe}" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
    )
  )'''


# Power rails used in this design (besides GND and +3V3).
EXTRA_RAILS = ["+VDDD", "+VDDA1", "+VDDA2", "+VDDIO", "+VADJ"]
for _r in EXTRA_RAILS:
    STD_SYMBOLS[f"power:{_r}"] = _power_rail_symbol(_r)


# ---------------------------------------------------------------------------
# Pin coordinate extraction
# ---------------------------------------------------------------------------

# Cache: lib_id -> {pin_number: (name, local_x, local_y, angle_deg)}
_PIN_CACHE: dict[str, dict[str, tuple[str, float, float, int]]] = {}

# Hand-coded pin tables for embedded STD_SYMBOLS (R/C/L/power).
# Format: {pin_number: (name, local_x, local_y, angle_deg)}
_STD_PINS: dict[str, dict[str, tuple[str, float, float, int]]] = {
    "Device:R":   {"1": ("~", 0, 3.81, 270), "2": ("~", 0, -3.81, 90)},
    "Device:C":   {"1": ("~", 0, 3.81, 270), "2": ("~", 0, -3.81, 90)},
    "power:GND":  {"1": ("GND", 0, 0, 270)},
    "power:+3V3": {"1": ("+3V3", 0, 0, 90)},
}
for _r in EXTRA_RAILS:
    _STD_PINS[f"power:{_r}"] = {"1": (_r, 0, 0, 90)}


def parse_pins(lib_id: str) -> dict[str, tuple[str, float, float, int]]:
    """Return {pin_number: (name, local_x, local_y, angle_deg)} for a symbol."""
    if lib_id in _PIN_CACHE:
        return _PIN_CACHE[lib_id]
    if lib_id in _STD_PINS:
        _PIN_CACHE[lib_id] = _STD_PINS[lib_id]
        return _STD_PINS[lib_id]

    if ":" not in lib_id:
        raise ValueError(f"Unknown lib_id {lib_id}")
    _, mpn = lib_id.split(":", 1)
    text = (PARTS_LIB / mpn / f"{mpn}.kicad_sym").read_text()

    pins: dict[str, tuple[str, float, float, int]] = {}
    # Each pin: (pin TYPE shape (at X Y A) (length L) (name "N" ...) ... (number "N" ...))
    pin_pat = re.compile(r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)')
    name_pat = re.compile(r'\(name\s+"([^"]+)"')
    number_pat = re.compile(r'\(number\s+"([^"]+)"')

    # Walk the file, finding each (pin ...) block by paren matching.
    for m in pin_pat.finditer(text):
        start = text.rfind("(pin", 0, m.end())
        end = _find_matching_paren(text, start)
        block = text[start:end + 1]
        x = float(m.group(1)); y = float(m.group(2)); a = int(m.group(3))
        nm = name_pat.search(block)
        nu = number_pat.search(block)
        if nm and nu:
            pins[nu.group(1)] = (nm.group(1), x, y, a)
    _PIN_CACHE[lib_id] = pins
    return pins


def pin_world(at_x: float, at_y: float, at_angle: int,
              local_x: float, local_y: float) -> tuple[float, float]:
    """Compute a pin's world coordinate given the symbol's placement.

    Symbol local +y is UP in editor view but +y is DOWN in the schematic file,
    so local y is negated. Symbol rotation rotates pin offsets too.
    """
    import math
    # Local axes (with the +y flip): u = local_x, v = -local_y
    u, v = local_x, -local_y
    rad = math.radians(at_angle)
    c, s = math.cos(rad), math.sin(rad)
    dx = u * c - v * s
    dy = u * s + v * c
    return (round(at_x + dx, 3), round(at_y + dy, 3))


# ---------------------------------------------------------------------------
# Schematic builder
# ---------------------------------------------------------------------------

@dataclass
class Sheet:
    """Accumulates s-expression fragments for a single .kicad_sch file."""
    name: str           # short name used in filename
    uuid: str           # sheet uuid
    page: str           # page number (string)
    title: str = ""     # title block title
    paper: str = "A3"

    _lib_symbols: dict[str, str] = field(default_factory=dict)
    _content: list[str] = field(default_factory=list)
    _refdes_seen: set[str] = field(default_factory=set)

    def embed_symbol(self, lib_id: str) -> None:
        """Ensure a symbol definition is embedded in lib_symbols. Idempotent."""
        if lib_id in self._lib_symbols:
            return
        if lib_id in STD_SYMBOLS:
            self._lib_symbols[lib_id] = STD_SYMBOLS[lib_id]
            return
        # custom: "Lib:<MPN>"
        if ":" in lib_id:
            _, mpn = lib_id.split(":", 1)
            self._lib_symbols[lib_id] = extract_symbol_block(mpn, lib_prefix="Lib")
            return
        raise ValueError(f"Unknown symbol {lib_id} — not in STD_SYMBOLS and no library prefix")

    def add(self, sexpr: str) -> None:
        self._content.append(sexpr)

    def render(self) -> str:
        body = "\n".join(self._lib_symbols.values())
        content = "\n".join(self._content)
        return f'''(kicad_sch
  (version {SCH_VERSION})
  (generator "{GENERATOR}")
  (generator_version "{GENERATOR_VERSION}")
  (uuid "{self.uuid}")
  (paper "{self.paper}")
  (title_block
    (title "{self.title}")
    (date "")
    (rev "1")
  )
  (lib_symbols
{body}
  )
{content}
  (sheet_instances
    (path "/" (page "{self.page}"))
  )
)
'''


# ---------------------------------------------------------------------------
# Primitive emitters
# ---------------------------------------------------------------------------

def wire(x1, y1, x2, y2) -> str:
    return (f'  (wire (pts (xy {x1} {y1}) (xy {x2} {y2})) '
            f'(stroke (width 0) (type default)) (uuid "{uid(f"wire_{x1}_{y1}_{x2}_{y2}")}"))')

def junction(x, y) -> str:
    return (f'  (junction (at {x} {y}) (diameter 0) (color 0 0 0 0) '
            f'(uuid "{uid(f"junc_{x}_{y}")}"))')

def label(net: str, x, y, angle: int = 0, justify: str = "left bottom") -> str:
    return (f'  (label "{net}" (at {x} {y} {angle}) '
            f'(effects (font (size 1.27 1.27)) (justify {justify})) '
            f'(uuid "{uid(f"label_{net}_{x}_{y}")}"))')

def hier_label(net: str, shape: str, x, y, angle: int = 0,
               justify: str = "left") -> str:
    return (f'  (hierarchical_label "{net}" (shape {shape}) (at {x} {y} {angle}) '
            f'(effects (font (size 1.27 1.27)) (justify {justify})) '
            f'(uuid "{uid(f"hlabel_{net}_{x}_{y}")}"))')

def no_connect(x, y) -> str:
    return f'  (no_connect (at {x} {y}) (uuid "{uid(f"nc_{x}_{y}")}"))'


# ---------------------------------------------------------------------------
# Symbol placement
# ---------------------------------------------------------------------------

def _ref_value_positions(lib_id: str, x: float, y: float, angle: int
                         ) -> tuple[tuple[float, float], tuple[float, float]]:
    """Choose non-overlapping Reference/Value positions per skill layout rules."""
    if lib_id in ("Device:R", "Device:C", "Device:L"):
        if angle in (0, 180):  # vertical body
            return ((x + 2.54, y - 1.27), (x + 2.54, y + 1.27))
        else:                  # horizontal
            return ((x, y - 3.81), (x, y + 3.81))
    if lib_id.startswith("power:"):
        # Power symbols suppress Reference; Value is visible above the arrow/triangle.
        return ((x, y - 6.35), (x, y - 3.81))
    # IC: pick a safe spot above the implied symbol body. Real distance depends
    # on body height — we use a conservative offset that won't overlap typical bodies.
    return ((x, y - 5.08), (x, y + 5.08))


def place(sheet: Sheet, lib_id: str, ref: str, value: str,
          x: float, y: float, angle: int = 0,
          footprint: str = "") -> dict[str, tuple[float, float]]:
    """
    Embed a symbol if needed, emit an instance, and return {pin_number: (wx, wy)}.

    Caller wires by pin number. For passives, both pin numbers are valid;
    for ICs use the pin number from parse_pins().
    """
    sheet.embed_symbol(lib_id)
    pins = parse_pins(lib_id)

    # Hide reference for power symbols (they use "#PWR..." per KiCad convention).
    is_power = lib_id.startswith("power:")
    if is_power:
        # Use a unique #PWR ref per instance — KiCad expects them to be unique
        ref_actual = f"#PWR{uid(f'{sheet.name}_{x}_{y}_{value}')[:8].replace('-', '')}"
    else:
        ref_actual = ref
        if ref in sheet._refdes_seen:
            raise ValueError(f"duplicate refdes {ref} on sheet {sheet.name}")
        sheet._refdes_seen.add(ref)

    (xr, yr), (xv, yv) = _ref_value_positions(lib_id, x, y, angle)

    pin_uuids = "\n".join(
        f'    (pin "{num}" (uuid "{uid(f"pin_{sheet.name}_{ref_actual}_{num}")}"))'
        for num in pins
    )

    ref_effects = " (effects (font (size 1.27 1.27)) (hide yes))" if is_power else " (effects (font (size 1.27 1.27)))"
    value_effects = " (effects (font (size 1.27 1.27)))"

    instance_uuid = uid(f"inst_{sheet.name}_{ref_actual}")
    block = f'''  (symbol
    (lib_id "{lib_id}")
    (at {x} {y} {angle})
    (unit 1) (in_bom yes) (on_board yes) (dnp no)
    (uuid "{instance_uuid}")
    (property "Reference" "{ref_actual}" (at {xr} {yr} 0){ref_effects})
    (property "Value" "{value}" (at {xv} {yv} 0){value_effects})
    (property "Footprint" "{footprint}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
{pin_uuids}
    (instances
      (project "{PROJECT_NAME}"
        (path "/{ROOT_UUID}/{sheet.uuid}" (reference "{ref_actual}") (unit 1)))))'''
    sheet.add(block)

    # Compute world coords per pin.
    out: dict[str, tuple[float, float]] = {}
    for num, (_nm, lx, ly, _la) in pins.items():
        out[num] = pin_world(x, y, angle, lx, ly)
    return out


def power_at(sheet: Sheet, rail: str, x: float, y: float, angle: int = 0
             ) -> tuple[float, float]:
    """Place a power symbol of the given rail (e.g. '+3V3', 'GND') at (x,y).

    Returns the pin world coord (which equals (x,y) since all power-symbol
    pins live at the symbol origin).
    """
    lib_id = f"power:{rail}"
    place(sheet, lib_id, "#PWR", rail, x, y, angle)
    return (x, y)


# ---------------------------------------------------------------------------
# Sheet block (parent embeds child)
# ---------------------------------------------------------------------------

@dataclass
class SheetPin:
    name: str
    direction: str   # input/output/bidirectional/tri_state/passive
    side: str        # left/right — which edge of the sheet box
    offset: float    # offset along that edge from top of box, in mm


def sheet_block(child_name: str, child_uuid: str, page: str,
                x: float, y: float, w: float, h: float,
                pins: list[SheetPin]) -> str:
    pin_blocks = []
    for p in pins:
        if p.side == "left":
            px, py, angle = x, y + p.offset, 180
        elif p.side == "right":
            px, py, angle = x + w, y + p.offset, 0
        else:
            raise ValueError(f"unsupported side {p.side!r}")
        pin_blocks.append(
            f'    (pin "{p.name}" {p.direction} (at {px} {py} {angle}) '
            f'(effects (font (size 1.27 1.27)) (justify {"right" if p.side == "right" else "left"})) '
            f'(uuid "{uid(f"sheetpin_{child_name}_{p.name}")}"))'
        )
    pins_str = "\n".join(pin_blocks)
    sheetname_y = y - 0.5
    sheetfile_y = y + h + 0.5
    return f'''  (sheet
    (at {x} {y}) (size {w} {h})
    (stroke (width 0.1524) (type solid))
    (fill (color 0 0 0 0.0000))
    (uuid "{child_uuid}")
    (property "Sheetname" "{SHEET_TITLES[child_name]}" (at {x} {sheetname_y} 0)
      (effects (font (size 1.524 1.524)) (justify left bottom)))
    (property "Sheetfile" "{child_name}.kicad_sch" (at {x} {sheetfile_y} 0)
      (effects (font (size 1.524 1.524)) (justify left top)))
{pins_str}
    (instances (project "{PROJECT_NAME}" (path "/{ROOT_UUID}" (page "{page}"))))

  )'''


# ---------------------------------------------------------------------------
# Root sheet
# ---------------------------------------------------------------------------

def build_root() -> Sheet:
    s = Sheet(name="root", uuid=ROOT_UUID, page=PAGE_NUMBERS["root"],
              title=f"{PROJECT_NAME} — Bobcat Carrier (root)")

    # 6 sheet blocks in a 2x3 grid, A3 paper (420 x 297 mm usable ~ 400 x 280).
    # Each block 95 mm wide, 60 mm tall, spaced 15 mm apart.
    W, H = 100, 65
    GAP_X, GAP_Y = 25, 30
    X0, Y0 = 30, 35

    layout = [
        ("fmc",        (X0,                 Y0)),
        ("power",      (X0 + W + GAP_X,     Y0)),
        ("bobcat",     (X0 + 2*(W+GAP_X),   Y0)),
        ("eeprom",     (X0,                 Y0 + H + GAP_Y)),
        ("bias",       (X0 + W + GAP_X,     Y0 + H + GAP_Y)),
        ("connectors", (X0 + 2*(W+GAP_X),   Y0 + H + GAP_Y)),
    ]

    # Crossing-signal pin lists per child (parent's view).
    # These describe what nets exit/enter each sheet at the root level.
    # Directions are from the CHILD's perspective: input = into child, output = out of child.
    sheet_pins = {
        "fmc": [
            SheetPin("VADJ",         "output", "right",  5),
            SheetPin("SCL",          "bidirectional", "right", 10),
            SheetPin("SDA",          "bidirectional", "right", 15),
            SheetPin("LDO_EN",       "input",  "right", 25),
            SheetPin("LDO_PG",       "output", "right", 30),
            SheetPin("LSW_EN",       "input",  "right", 35),
            SheetPin("RESET_N",      "bidirectional", "right", 45),
            SheetPin("CS_L",         "input",  "right", 50),
            SheetPin("SCLK",         "input",  "right", 55),
            SheetPin("MOSI",         "input",  "right", 60),
            SheetPin("MISO",         "output", "right", 5 + 60),  # falls past box if too many — adjust later
        ],
        "power": [
            SheetPin("VADJ",   "input",  "left",  5),
            SheetPin("LDO_EN", "output", "left",  15),
            SheetPin("LDO_PG", "input",  "left",  20),
            SheetPin("LSW_EN", "output", "left",  25),
        ],
        "bobcat": [
            SheetPin("CS_L",        "output", "left",  5),
            SheetPin("SCLK",        "output", "left", 10),
            SheetPin("MOSI",        "output", "left", 15),
            SheetPin("MISO",        "input",  "left", 20),
            SheetPin("RESET_N",     "output", "left", 25),
            SheetPin("SPI_DMODE",   "output", "left", 30),
            SheetPin("BIAS0",       "input",  "right",  5),
            SheetPin("BIAS1",       "input",  "right", 10),
            SheetPin("CLK_OUT0",    "output", "right", 20),
            SheetPin("CLK_OUT1",    "output", "right", 25),
            SheetPin("CLK_OUT2",    "output", "right", 30),
            SheetPin("CLK_OUT3",    "output", "right", 35),
            SheetPin("GPIO0",       "output", "right", 45),
            SheetPin("GPIO1",       "output", "right", 50),
            SheetPin("GPIO2",       "output", "right", 55),
            SheetPin("GPIO3",       "output", "right", 60),
        ],
        "eeprom": [
            SheetPin("SCL", "bidirectional", "left", 10),
            SheetPin("SDA", "bidirectional", "left", 15),
        ],
        "bias": [
            SheetPin("SCL",   "bidirectional", "left",  5),
            SheetPin("SDA",   "bidirectional", "left", 10),
            SheetPin("BIAS0", "output",        "right", 5),
            SheetPin("BIAS1", "output",        "right", 10),
        ],
        "connectors": [
            SheetPin("CLK_OUT0", "input", "left",  5),
            SheetPin("CLK_OUT1", "input", "left", 10),
            SheetPin("CLK_OUT2", "input", "left", 15),
            SheetPin("CLK_OUT3", "input", "left", 20),
            SheetPin("GPIO0",    "input", "left", 30),
            SheetPin("GPIO1",    "input", "left", 35),
            SheetPin("GPIO2",    "input", "left", 40),
            SheetPin("GPIO3",    "input", "left", 45),
        ],
    }

    for child, (sx, sy) in layout:
        s.add(sheet_block(child, SHEET_UUIDS[child], PAGE_NUMBERS[child],
                          sx, sy, W, H, sheet_pins[child]))

    return s


# ---------------------------------------------------------------------------
# Child sheet: EEPROM (24AA08-I-SN, I²C)
# ---------------------------------------------------------------------------

def build_eeprom() -> Sheet:
    """24AA08-I-SN I²C EEPROM. Address pins to GND (slot 000), WP to GND,
    0.1 µF decoupling on VCC, 2.2 kΩ I²C pull-ups on SCL/SDA."""
    s = Sheet(name="eeprom", uuid=SHEET_UUIDS["eeprom"],
              page=PAGE_NUMBERS["eeprom"],
              title=f"{PROJECT_NAME} — EEPROM (24AA08 I²C)")

    SOIC_FP = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    C0402 = "Capacitor_SMD:C_0402_1005Metric"
    R0402 = "Resistor_SMD:R_0402_1005Metric"

    # --- U1: 24AA08 at (100, 120). Body x ∈ [100, 176.2], y ∈ [120, 127.62].
    # Pin world coords at angle 0:
    #   1 A_0 (100, 120)        5 SDA (176.2, 127.62)
    #   2 A_1 (100, 122.54)     6 SCL (176.2, 125.08)
    #   3 A_2 (100, 125.08)     7 WP  (176.2, 122.54)
    #   4 VSS (100, 127.62)     8 VCC (176.2, 120)
    place(s, "Lib:24AA08-I-SN", "U1", "24AA08", 100, 120, footprint=SOIC_FP)

    # --- Left side: pins 1-4 to GND (address slot 000 + VSS) ---
    for y in (120, 122.54, 125.08, 127.62):
        s.add(wire(100, y, 92.71, y))
        power_at(s, "GND", 92.71, y, angle=270)

    # --- Right side: organized into three vertical lanes, well-spaced ---
    # Lane 1 (x=184.15, +7.95 mm right of chip): VCC rail + WP→GND
    # Lane 2 (x=200.66, +24.46 mm right): decoupling cap C1
    # Lane 3 (x=215.9, +39.7 mm right): I²C pull-ups R1 (SCL), R2 (SDA)

    # +3V3 rail runs horizontally at y = 105.41 (14.59 mm above chip top)
    RAIL_Y = 105.41
    GND_RAIL_Y = 142.24  # 14.62 mm below chip bottom

    # Pin 8 VCC → up to +3V3 rail
    s.add(wire(176.2, 120, 184.15, 120))
    s.add(wire(184.15, 120, 184.15, RAIL_Y))

    # Pin 7 WP → down to GND (separate column, not stacked with VCC)
    s.add(wire(176.2, 122.54, 189.23, 122.54))
    s.add(wire(189.23, 122.54, 189.23, GND_RAIL_Y))
    power_at(s, "GND", 189.23, GND_RAIL_Y)

    # Pin 6 SCL → horizontal bus, extends past both pull-ups to hier label.
    SCL_LABEL_X = 237.49
    SDA_LABEL_X = 237.49
    s.add(wire(176.2, 125.08, SCL_LABEL_X, 125.08))
    s.add(hier_label("SCL", "bidirectional", SCL_LABEL_X, 125.08, angle=0))

    # Pin 5 SDA → horizontal bus, ditto
    s.add(wire(176.2, 127.62, SDA_LABEL_X, 127.62))
    s.add(hier_label("SDA", "bidirectional", SDA_LABEL_X, 127.62, angle=0))

    # --- C1: decoupling cap. Place at (200.66, 116.84) so pins land on grid.
    # Pin 1 (top, +3V3) at (200.66, 113.03); pin 2 (bot, GND) at (200.66, 120.65).
    place(s, "Device:C", "C1", "0.1uF", 200.66, 116.84, footprint=C0402)
    s.add(wire(200.66, 113.03, 200.66, RAIL_Y))           # top to +3V3 rail
    s.add(wire(200.66, 120.65, 200.66, GND_RAIL_Y))       # bottom to GND rail
    power_at(s, "GND", 200.66, GND_RAIL_Y)

    # --- R1 (SCL pull-up): vertical, placed well above the SCL line so the
    # body doesn't crowd C1 or R2.
    # Place at (215.9, 113.03). Pin 1 (top, +3V3) at (215.9, 109.22); pin 2
    # (bot) at (215.9, 116.84). Then route pin 2 down to SCL line at y=125.08.
    place(s, "Device:R", "R1", "2.2k", 215.9, 113.03, footprint=R0402)
    s.add(wire(215.9, 109.22, 215.9, RAIL_Y))             # to +3V3 rail
    s.add(wire(215.9, 116.84, 215.9, 125.08))             # down to SCL
    s.add(junction(215.9, 125.08))

    # --- R2 (SDA pull-up): same column-spacing rule. Place at (228.6, 113.03)
    # — 12.7 mm right of R1 — so the value labels don't crowd.
    place(s, "Device:R", "R2", "2.2k", 228.6, 113.03, footprint=R0402)
    s.add(wire(228.6, 109.22, 228.6, RAIL_Y))
    s.add(wire(228.6, 116.84, 228.6, 127.62))
    s.add(junction(228.6, 127.62))

    # --- +3V3 rail: one horizontal wire tying VCC, C1, R1, R2 together ---
    s.add(wire(184.15, RAIL_Y, 228.6, RAIL_Y))
    # Junctions where verticals tap the rail
    for x in (200.66, 215.9):
        s.add(junction(x, RAIL_Y))
    # +3V3 power symbol — its pin sits at the symbol origin, so place AT the
    # rail (its triangle extends upward in editor view = lower y on screen)
    power_at(s, "+3V3", 228.6, RAIL_Y)

    return s

def project_json() -> str:
    sheets = [f'    ["{ROOT_UUID}", ""]']
    for n in SHEET_NAMES:
        sheets.append(f'    ["{SHEET_UUIDS[n]}", "{SHEET_TITLES[n]}"]')
    sheets_str = ",\n".join(sheets)
    return f'''{{
  "meta": {{
    "filename": "{PROJECT_NAME}.kicad_pro",
    "version": 3
  }},
  "schematic": {{
    "legacy_lib_dir": "",
    "legacy_lib_list": []
  }},
  "sheets": [
{sheets_str}
  ],
  "text_variables": {{}}
}}
'''


def root_sheet_instances() -> str:
    """Override the default single-sheet instances block in root."""
    lines = [f'    (path "/" (page "{PAGE_NUMBERS["root"]}"))']
    for n in SHEET_NAMES:
        lines.append(
            f'    (path "/{SHEET_UUIDS[n]}" (page "{PAGE_NUMBERS[n]}"))'
        )
    return "  (sheet_instances\n" + "\n".join(lines) + "\n  )"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(sch_path: Path) -> tuple[bool, str]:
    """Run kicad-cli sch export svg as a parse check."""
    cmd = [KICAD_CLI, "sch", "export", "svg",
           "--output", str(RENDER_DIR),
           str(sch_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False, f"kicad-cli not at {KICAD_CLI}"
    ok = (r.returncode == 0) and "Done" in (r.stdout + r.stderr)
    return ok, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)

    # Project file
    (OUT_DIR / f"{PROJECT_NAME}.kicad_pro").write_text(project_json())
    print(f"wrote {PROJECT_NAME}.kicad_pro")

    # Root sheet — override the trailing single-page sheet_instances with multi-page
    root = build_root()
    root_text = root.render()
    root_text = root_text.replace(
        f'  (sheet_instances\n    (path "/" (page "{PAGE_NUMBERS["root"]}"))\n  )',
        root_sheet_instances(),
    )
    root_path = OUT_DIR / f"{PROJECT_NAME}.kicad_sch"
    root_path.write_text(root_text)
    print(f"wrote {root_path.name}")

    # Real child sheets (filled-in) override stubs.
    real_builders = {
        "eeprom": build_eeprom,
    }
    for n in SHEET_NAMES:
        cpath = OUT_DIR / f"{n}.kicad_sch"
        if n in real_builders:
            cpath.write_text(real_builders[n]().render())
            print(f"wrote {n}.kicad_sch")
        else:
            stub = Sheet(name=n, uuid=SHEET_UUIDS[n], page=PAGE_NUMBERS[n],
                         title=f"{PROJECT_NAME} — {SHEET_TITLES[n]}").render()
            cpath.write_text(stub)
            print(f"wrote {n}.kicad_sch (stub)")

    # Validate root + every child
    failures = 0
    for path in [root_path] + [OUT_DIR / f"{n}.kicad_sch" for n in SHEET_NAMES]:
        ok, msg = validate(path)
        flag = "OK " if ok else "FAIL"
        print(f"  [{flag}] {path.name}: {msg.splitlines()[-1] if msg else ''}")
        if not ok:
            failures += 1
            print(msg)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
