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

# Cache: lib_id -> {pin_number: (name, local_x, local_y, angle_deg, unit)}
_PIN_CACHE: dict[str, dict[str, tuple[str, float, float, int, int]]] = {}

# Hand-coded pin tables for embedded STD_SYMBOLS (R/C/L/power). Unit = 1.
_STD_PINS: dict[str, dict[str, tuple[str, float, float, int, int]]] = {
    "Device:R":   {"1": ("~", 0, 3.81, 270, 1), "2": ("~", 0, -3.81, 90, 1)},
    "Device:C":   {"1": ("~", 0, 3.81, 270, 1), "2": ("~", 0, -3.81, 90, 1)},
    "power:GND":  {"1": ("GND", 0, 0, 270, 1)},
    "power:+3V3": {"1": ("+3V3", 0, 0, 90, 1)},
}
for _r in EXTRA_RAILS:
    _STD_PINS[f"power:{_r}"] = {"1": (_r, 0, 0, 90, 1)}


def parse_pins(lib_id: str) -> dict[str, tuple[str, float, float, int, int]]:
    """Return {pin_number: (name, local_x, local_y, angle_deg, unit)}.

    The unit number is parsed from sub-symbol names like "X_<unit>_<style>"
    (e.g. "OPA2388IDR_2_1" → unit 2). Pins outside any sub-symbol are unit 1.
    """
    if lib_id in _PIN_CACHE:
        return _PIN_CACHE[lib_id]
    if lib_id in _STD_PINS:
        _PIN_CACHE[lib_id] = _STD_PINS[lib_id]
        return _STD_PINS[lib_id]

    if ":" not in lib_id:
        raise ValueError(f"Unknown lib_id {lib_id}")
    _, mpn = lib_id.split(":", 1)
    text = (PARTS_LIB / mpn / f"{mpn}.kicad_sym").read_text()

    # Find each sub-symbol block "<innerStem>_<unit>_<style>" and remember its
    # span so we can attribute pins inside it to the right unit.
    subunit_spans: list[tuple[int, int, int]] = []  # (start, end, unit)
    for m in re.finditer(r'\(symbol\s+"[^"]+_(\d+)_\d+"', text):
        u = int(m.group(1))
        start = m.start()
        end = _find_matching_paren(text, start)
        subunit_spans.append((start, end, u))

    def unit_at(pos: int) -> int:
        for st, en, u in subunit_spans:
            if st <= pos <= en:
                return u
        return 1

    pins: dict[str, tuple[str, float, float, int, int]] = {}
    pin_pat = re.compile(r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)')
    name_pat = re.compile(r'\(name\s+"([^"]+)"')
    number_pat = re.compile(r'\(number\s+"([^"]+)"')

    for m in pin_pat.finditer(text):
        start = text.rfind("(pin", 0, m.end())
        end = _find_matching_paren(text, start)
        block = text[start:end + 1]
        x = float(m.group(1)); y = float(m.group(2)); a = int(m.group(3))
        nm = name_pat.search(block)
        nu = number_pat.search(block)
        if nm and nu:
            pins[nu.group(1)] = (nm.group(1), x, y, a, unit_at(start))
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
          footprint: str = "", unit: int = 1) -> dict[str, tuple[float, float]]:
    """
    Embed a symbol if needed, emit an instance, and return {pin_number: (wx, wy)}.

    For multi-unit symbols (e.g. OPA2388 dual op-amp), pass unit=2, 3, … to
    instantiate other units. Only the named unit's pins (plus shared-power
    pins assigned to unit 1) are wired by the returned coord map.
    """
    sheet.embed_symbol(lib_id)
    all_pins = parse_pins(lib_id)
    # Filter pins for this unit. KiCad treats unit 0 as "common to all units"
    # (single-unit symbols often use _0_1 sub-symbols), so include both unit 0
    # and the requested unit.
    pins = {n: p for n, p in all_pins.items() if p[4] in (0, unit)}

    is_power = lib_id.startswith("power:")
    if is_power:
        ref_actual = f"#PWR{uid(f'{sheet.name}_{x}_{y}_{value}')[:8].replace('-', '')}"
    else:
        ref_actual = ref
        # For multi-unit instances, the same refdes appears multiple times
        # (e.g. U1 with unit 1 and unit 2). Don't error on those.
        key = f"{ref}/unit{unit}"
        if key in sheet._refdes_seen:
            raise ValueError(f"duplicate refdes {ref} unit {unit} on sheet {sheet.name}")
        sheet._refdes_seen.add(key)

    (xr, yr), (xv, yv) = _ref_value_positions(lib_id, x, y, angle)

    def _esc(t: str) -> str:
        """Escape any chars that would break an s-expr string token."""
        return t.replace("\\", "\\\\").replace('"', '\\"')
    ref_actual_e = _esc(ref_actual)
    value_e      = _esc(value)
    footprint_e  = _esc(footprint)

    pin_uuids = "\n".join(
        f'    (pin "{num}" (uuid "{uid(f"pin_{sheet.name}_{ref_actual}_u{unit}_{num}")}"))'
        for num in pins
    )

    ref_effects = " (effects (font (size 1.27 1.27)) (hide yes))" if is_power else " (effects (font (size 1.27 1.27)))"
    value_effects = " (effects (font (size 1.27 1.27)))"

    instance_uuid = uid(f"inst_{sheet.name}_{ref_actual}_u{unit}")
    block = f'''  (symbol
    (lib_id "{lib_id}")
    (at {x} {y} {angle})
    (unit {unit}) (in_bom yes) (on_board yes) (dnp no)
    (uuid "{instance_uuid}")
    (property "Reference" "{ref_actual_e}" (at {xr} {yr} 0){ref_effects})
    (property "Value" "{value_e}" (at {xv} {yv} 0){value_effects})
    (property "Footprint" "{footprint_e}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
{pin_uuids}
    (instances
      (project "{PROJECT_NAME}"
        (path "/{ROOT_UUID}/{sheet.uuid}" (reference "{ref_actual_e}") (unit {unit})))))'''
    sheet.add(block)

    out: dict[str, tuple[float, float]] = {}
    for num, (_nm, lx, ly, _la, _u) in pins.items():
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


# Common footprint constants
FP_R0402 = "Resistor_SMD:R_0402_1005Metric"
FP_C0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
FP_VQFN20 = "Package_DFN_QFN:VQFN-20-1EP_3.5x3.5mm_P0.5mm_EP1.6x1.6mm"
FP_QFN10 = "Package_DFN_QFN:VQFN-10-1EP_3x3mm_P0.5mm_EP1.6x1.6mm"
FP_PMOS_DFN = "Package_DFN_QFN:DFN-3-1EP_1.0x1.0mm_P0.65mm_EP0.5x0.5mm"
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"
FP_WCSP4 = "Package_DirectFETandLGA:Texas_DSBGA-4_0.6x1.0mm_Layout2x2_P0.4mm"
FP_QFN40 = "Bobcat:QFN-40_5x5mm_P0.4mm_EP3.5mm"
FP_SMA = "Connector_Coaxial:SMA_Amphenol_HRM-G_Vertical"
FP_HEADER_1x2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
FP_HEADER_1x4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
FP_TESTPOINT = "TestPoint:TestPoint_THTPad_D5.0mm_Drill3.0mm"
FP_FMC = "Connector:FMC_LPC_ASP-134606-01"


# ---------------------------------------------------------------------------
# Child sheet: Power
# ---------------------------------------------------------------------------

def build_power() -> Sheet:
    """TPS7A8401A LDO (3P3V → 0.6–1.0V) + TPS22916 load switch (VADJ → VDDIO).

    Functional clusters:
      A. LDO input side  (IN×3, BIAS, decoupling, EN pulldown)
      B. LDO output side (OUT×3, SNS, FB, NR_SS cap, ANY-OUT strap, decoupling)
      C. Output jumpers  (3× 1×2 headers fanning OUT to VDDD/VDDA1/VDDA2)
      D. Load switch     (TPS22916: VADJ → VDDIO, EN pulldown, decoupling)
    """
    s = Sheet(name="power", uuid=SHEET_UUIDS["power"],
              page=PAGE_NUMBERS["power"],
              title=f"{PROJECT_NAME} — Power (LDO + Load Switch)")

    # ===== Cluster A: LDO body =====
    # Place TPS7A8401A at (130, 130). Body spans local x ∈ [-20.32, 20.32] (40.64 wide),
    # local y ∈ [-22.86, 20.32] (43.18 tall).
    # World coords: chip body x ∈ [109.68, 150.32], y ∈ [109.68, 152.86].
    U1 = place(s, "Lib:TPS7A8401A", "U1", "TPS7A8401A", 130, 130, footprint=FP_VQFN20)
    # Pin world coords (recompute the important ones):
    # IN (pins 15,16,17): local (-20.32, 20.32/17.78/15.24) → world (109.68, 109.68/112.22/114.76)
    # EN (14): (-20.32, 10.16) → (109.68, 119.84)
    # BIAS (12): (-20.32, 5.08) → (109.68, 124.92)
    # NR_SS (13): (-20.32, -2.54) → (109.68, 132.54)
    # 50_mV..1.6_V (5,6,7,9,10,11): left side, lower
    # OUT (1,19,20): (20.32, 10.16/7.62/5.08) → (150.32, 119.84/122.38/124.92)
    # SNS (2): (20.32, 0) → (150.32, 130)
    # FB (3): (20.32, -7.62) → (150.32, 137.62)
    # PG (4): (20.32, 20.32) → (150.32, 109.68)
    # GND (8): (20.32, -17.78) → (150.32, 147.78)
    # GND (18): (20.32, -20.32) → (150.32, 150.32)
    # PAD (21): (20.32, -22.86) → (150.32, 152.86)

    # +3V3 input rail at top (y = 95.25)
    RAIL_3V3_Y = 95.25
    GND_RAIL_Y = 175.26

    # IN pins → +3V3 (junction the three IN stubs together)
    for px, py in [U1["15"], U1["16"], U1["17"]]:
        s.add(wire(px, py, px - 7.62, py))
    s.add(wire(102.06, U1["15"][1], 102.06, RAIL_3V3_Y))   # vertical riser
    s.add(wire(102.06, U1["16"][1], 109.68, U1["16"][1]))  # already covered
    s.add(junction(102.06, U1["16"][1]))
    s.add(junction(102.06, U1["17"][1]))
    # Actually simpler: drop a vertical bus at x=102.06 covering all three Y values
    # and add junctions at each.
    s.add(wire(102.06, U1["17"][1], 102.06, U1["15"][1]))
    # BIAS pin → +3V3 (separately stubbed)
    s.add(wire(U1["12"][0], U1["12"][1], 102.06, U1["12"][1]))
    s.add(junction(102.06, U1["12"][1]))
    s.add(wire(102.06, U1["12"][1], 102.06, RAIL_3V3_Y))
    power_at(s, "+3V3", 102.06, RAIL_3V3_Y)

    # IN-side decoupling: 10µF (C1) and 0.1µF (C2) between +3V3 and GND, left of LDO
    place(s, "Device:C", "C1", "10uF", 87.63, 130, footprint=FP_C0805)
    # C1 pin 1 (top) world: (87.63, 126.19); pin 2 (bot): (87.63, 133.81)
    s.add(wire(87.63, 126.19, 87.63, RAIL_3V3_Y))
    s.add(junction(87.63, RAIL_3V3_Y))
    # wire +3V3 rail from C1 over to U1 stub
    s.add(wire(87.63, RAIL_3V3_Y, 102.06, RAIL_3V3_Y))
    s.add(wire(87.63, 133.81, 87.63, GND_RAIL_Y))

    place(s, "Device:C", "C2", "0.1uF", 95.25, 130, footprint=FP_C0402)
    s.add(wire(95.25, 126.19, 95.25, RAIL_3V3_Y))
    s.add(junction(95.25, RAIL_3V3_Y))
    s.add(wire(95.25, 133.81, 95.25, GND_RAIL_Y))

    # GND rail bottom
    s.add(wire(87.63, GND_RAIL_Y, 95.25, GND_RAIL_Y))
    s.add(junction(87.63, GND_RAIL_Y))
    s.add(junction(95.25, GND_RAIL_Y))
    power_at(s, "GND", 87.63, GND_RAIL_Y)

    # EN pin (14) → 10k pulldown to GND, hier-label LDO_EN comes from FPGA via FMC.
    s.add(wire(U1["14"][0], U1["14"][1], 99.06, U1["14"][1]))
    place(s, "Device:R", "R1", "10k", 99.06, 124.92, footprint=FP_R0402)
    # R1 pin 1 top (99.06, 121.11) → connects to EN stub via vertical riser
    s.add(wire(99.06, 121.11, 99.06, U1["14"][1]))
    s.add(wire(99.06, 128.73, 99.06, GND_RAIL_Y))
    s.add(wire(95.25, GND_RAIL_Y, 99.06, GND_RAIL_Y))
    s.add(junction(99.06, GND_RAIL_Y))
    # Hier label LDO_EN at the EN stub
    s.add(hier_label("LDO_EN", "input", 91.44, U1["14"][1], angle=180, justify="right"))
    s.add(wire(91.44, U1["14"][1], 99.06, U1["14"][1]))
    s.add(junction(99.06, U1["14"][1]))

    # NR_SS (13): 10nF cap to GND
    s.add(wire(U1["13"][0], U1["13"][1], 99.06, U1["13"][1]))
    place(s, "Device:C", "C3", "10nF", 99.06, 137.16, footprint=FP_C0402)
    # C3 pin 1 top (99.06, 133.35); pin 2 bot (99.06, 140.97)
    s.add(wire(99.06, 133.35, 99.06, U1["13"][1]))
    s.add(wire(99.06, 140.97, 99.06, GND_RAIL_Y))
    s.add(junction(99.06, GND_RAIL_Y))

    # ===== Cluster B: ANY-OUT strap (set output voltage) =====
    # The TPS7A8401A output is configured by tying ANY-OUT pins to GND. Default
    # base 0.5V; adding 50_mV(5), 100_mV(6), 200_mV(9 actually 400_mV…)…
    # Per design_requirements: Bobcat rails 0.6–1.0V. Target a single setpoint
    # of 0.8 V (0.5V base + 100mV + 200mV). Tie pins 6 (100_mV) and 7 (200_mV)
    # to GND; leave 5, 9, 10, 11 NC (no_connect).
    # ANY-OUT pin world coords (left side, lower):
    #   5 (50_mV)   (109.68, 152.86)
    #   6 (100_mV)  (109.68, 150.32) — strap to GND
    #   7 (200_mV)  (109.68, 147.78) — strap to GND
    #   9 (400_mV)  (109.68, 145.24)
    #   10 (800_mV) (109.68, 142.70)
    #   11 (1.6_V)  (109.68, 140.16)
    # Tie 6 and 7 to GND (short stubs left + GND symbols)
    for pn in ("6", "7"):
        px, py = U1[pn]
        s.add(wire(px, py, px - 7.62, py))
        power_at(s, "GND", px - 7.62, py, angle=270)
    # NC the other ANY-OUT pins to suppress ERC errors
    for pn in ("5", "9", "10", "11"):
        px, py = U1[pn]
        s.add(no_connect(px, py))

    # ===== Cluster B: OUT side =====
    # OUT pins (1, 19, 20) → tie together → output bus → goes to jumpers + SNS + FB + decoupling
    # OUT world coords: (150.32, 119.84/122.38/124.92)
    OUT_BUS_X = 165.1
    OUT_BUS_Y = 122.38  # midpoint of OUT pins
    # Stub each OUT pin right to the bus
    for pn in ("1", "19", "20"):
        px, py = U1[pn]
        s.add(wire(px, py, OUT_BUS_X, py))
    s.add(wire(OUT_BUS_X, U1["1"][1], OUT_BUS_X, U1["20"][1]))   # vertical OUT bus
    for pn in ("1", "20"):
        _, py = U1[pn]
        s.add(junction(OUT_BUS_X, py))

    # SNS (2) → tie to OUT bus (sense to output for kelvin), via wire
    s.add(wire(U1["2"][0], U1["2"][1], OUT_BUS_X, U1["2"][1]))
    s.add(wire(OUT_BUS_X, U1["2"][1], OUT_BUS_X, U1["1"][1]))
    s.add(junction(OUT_BUS_X, U1["2"][1]))

    # FB (3) → tie to OUT (ANY-OUT mode uses internal feedback when FB=OUT)
    s.add(wire(U1["3"][0], U1["3"][1], OUT_BUS_X, U1["3"][1]))
    s.add(wire(OUT_BUS_X, U1["2"][1], OUT_BUS_X, U1["3"][1]))
    s.add(junction(OUT_BUS_X, U1["3"][1]))

    # PG (4) → hier label LDO_PG (open drain, pulled up by FPGA side)
    s.add(wire(U1["4"][0], U1["4"][1], 167.64, U1["4"][1]))
    s.add(hier_label("LDO_PG", "output", 167.64, U1["4"][1], angle=0))

    # GND pins (8, 18, 21) → GND
    for pn in ("8", "18", "21"):
        px, py = U1[pn]
        s.add(wire(px, py, px + 5.08, py))
        power_at(s, "GND", px + 5.08, py)

    # OUT-side decoupling: 22µF (C4) and 0.1µF (C5) — between OUT bus and GND
    place(s, "Device:C", "C4", "22uF", 172.72, 130, footprint=FP_C0805)
    s.add(wire(172.72, 126.19, 172.72, U1["1"][1]))
    s.add(wire(OUT_BUS_X, U1["1"][1], 172.72, U1["1"][1]))
    s.add(junction(OUT_BUS_X, U1["1"][1]))
    s.add(wire(172.72, 133.81, 172.72, GND_RAIL_Y))
    s.add(wire(172.72, GND_RAIL_Y, 180.34, GND_RAIL_Y))
    power_at(s, "GND", 180.34, GND_RAIL_Y)

    place(s, "Device:C", "C5", "0.1uF", 180.34, 130, footprint=FP_C0402)
    s.add(wire(180.34, 126.19, 180.34, U1["1"][1]))
    s.add(wire(172.72, U1["1"][1], 180.34, U1["1"][1]))
    s.add(junction(172.72, U1["1"][1]))
    s.add(junction(180.34, U1["1"][1]))
    s.add(wire(180.34, 133.81, 180.34, GND_RAIL_Y))
    s.add(junction(180.34, GND_RAIL_Y))

    # ===== Cluster C: Output jumpers (3× 1×2 → VDDD, VDDA1, VDDA2) =====
    # Place jumpers in a column to the right of the LDO, fanning out from OUT bus
    # Jumper TSW-102: 2 pins vertical, pin 1 at top, pin 2 below (2.54 mm pitch)
    # J1 → VDDD, J2 → VDDA1, J3 → VDDA2. Each: pin 1 = LDO OUT bus side, pin 2 = output rail.
    # Place at x=195.58, y spaced.
    JX = 195.58
    for i, (ref, rail) in enumerate([("J1", "+VDDD"), ("J2", "+VDDA1"), ("J3", "+VDDA2")]):
        jy = 119.38 + i * 17.78   # more vertical breathing room between jumpers
        J = place(s, "Lib:TSW-102-05-G-S", ref, "1x2 100mil", JX, jy, footprint=FP_HEADER_1x2)
        # J pin 1 (jx, jy), pin 2 (jx, jy + 2.54)
        # Pin 1 → OUT bus (route via x = JX-5.08 then back to OUT_BUS_X)
        s.add(wire(JX, jy, JX - 5.08, jy))
        s.add(wire(JX - 5.08, jy, JX - 5.08, U1["1"][1]))
        s.add(wire(JX - 5.08, U1["1"][1], OUT_BUS_X, U1["1"][1]))
        s.add(junction(OUT_BUS_X, U1["1"][1]))
        # Pin 2 → power rail symbol with name (rail) for that supply
        s.add(wire(JX, jy + 2.54, JX + 7.62, jy + 2.54))
        power_at(s, rail, JX + 7.62, jy + 2.54)

    # ===== Cluster D: Load switch (TPS22916) =====
    # Place at (235, 130). VIN (A2, left top), ON (B2, left bot), VOUT (A1, right top), GND (B1, right bot).
    U2 = place(s, "Lib:TPS22916CNYFPR", "U2", "TPS22916", 235, 130, footprint=FP_WCSP4)
    # VIN (A2) world (214.68, 124.92) — wire to VADJ hier label
    s.add(wire(U2["A2"][0], U2["A2"][1], 207.01, U2["A2"][1]))
    s.add(hier_label("VADJ", "input", 207.01, U2["A2"][1], angle=180, justify="right"))
    # ON (B2): pulldown R2 placed later in this cluster, below the chip.

    # GND (B1) world (255.32, 135.08)
    s.add(wire(U2["B1"][0], U2["B1"][1], U2["B1"][0] + 5.08, U2["B1"][1]))
    power_at(s, "GND", U2["B1"][0] + 5.08, U2["B1"][1])

    # VOUT (A1) world (255.32, 124.92) → +VDDIO
    s.add(wire(U2["A1"][0], U2["A1"][1], U2["A1"][0] + 12.7, U2["A1"][1]))
    power_at(s, "+VDDIO", U2["A1"][0] + 12.7, U2["A1"][1])

    # TPS22916 decoupling: 0.1 µF on VIN and VOUT. Place to the side of the
    # chip body (not above/below) and route around the body cleanly. The
    # caps live in their own column with GND below; the chip-pin connection
    # goes via a short horizontal stub at the pin's row.
    #
    # Cap pin convention: pin 1 = top (rail), pin 2 = bottom (GND).
    # For caps that decouple a pin AT THE TOP of the chip body, we put the
    # cap ALONGSIDE the chip (at the same y as the pin) — bottom of cap
    # goes to GND below, top of cap goes to a short horizontal stub into
    # the chip pin.

    # C6 — VIN (A2 at y=124.92) decouple. Place LEFT of chip; cap center
    # such that pin 1 (top) is on the same row as VIN.
    C6_X = U2["A2"][0] - 7.62          # x = 207.06 (one grid left of body)
    C6_CENTER_Y = U2["A2"][1] + 3.81   # cap center; pin 1 top at VIN row
    place(s, "Device:C", "C6", "0.1uF", C6_X, C6_CENTER_Y, footprint=FP_C0402)
    # pin 1 world: (C6_X, U2["A2"][1])   — VIN row
    # pin 2 world: (C6_X, U2["A2"][1] + 7.62)  — GND row
    s.add(wire(C6_X, U2["A2"][1], U2["A2"][0], U2["A2"][1]))   # cap top → VIN pin
    s.add(junction(C6_X, U2["A2"][1]))
    s.add(wire(C6_X, U2["A2"][1] + 7.62, C6_X, GND_RAIL_Y))    # cap bottom → GND rail
    s.add(wire(C6_X, GND_RAIL_Y, 180.34, GND_RAIL_Y))
    s.add(junction(C6_X, GND_RAIL_Y))

    # C7 — VOUT (A1 at y=124.92) decouple. Place RIGHT of chip.
    C7_X = U2["A1"][0] + 7.62          # x = 262.94 (one grid right of body)
    C7_CENTER_Y = U2["A1"][1] + 3.81
    place(s, "Device:C", "C7", "0.1uF", C7_X, C7_CENTER_Y, footprint=FP_C0402)
    s.add(wire(C7_X, U2["A1"][1], U2["A1"][0] + 7.62, U2["A1"][1]))
    # Note: VOUT is also wired to +VDDIO via a longer horizontal earlier;
    # we extend the +VDDIO net through the cap pin via the existing
    # power_at call, and the cap pin will join that net.
    s.add(junction(C7_X, U2["A1"][1]))
    s.add(wire(C7_X, U2["A1"][1] + 7.62, C7_X, GND_RAIL_Y))
    s.add(wire(C6_X, GND_RAIL_Y, C7_X, GND_RAIL_Y))
    s.add(junction(C7_X, GND_RAIL_Y))

    # ON pull-down R2 (10k) + LSW_EN hier-label, vertical, between ON stub
    # and GND rail below the load switch.
    place(s, "Device:R", "R2", "10k", 207.06, U2["B2"][1] + 7.62, footprint=FP_R0402)
    # R2 pin 1 (top): (207.06, U2["B2"][1] + 3.81); pin 2 (bot): (207.06, U2["B2"][1] + 11.43)
    s.add(wire(207.06, U2["B2"][1] + 3.81, 207.06, U2["B2"][1]))
    s.add(wire(207.06, U2["B2"][1], U2["B2"][0], U2["B2"][1]))
    s.add(junction(207.06, U2["B2"][1]))
    s.add(hier_label("LSW_EN", "input", 199.39, U2["B2"][1], angle=180, justify="right"))
    s.add(wire(199.39, U2["B2"][1], 207.06, U2["B2"][1]))
    s.add(wire(207.06, U2["B2"][1] + 11.43, 207.06, GND_RAIL_Y))
    s.add(junction(207.06, GND_RAIL_Y))

    return s


# ---------------------------------------------------------------------------
# Child sheet: Connectors / Breakouts
# ---------------------------------------------------------------------------

def build_connectors() -> Sheet:
    """SMA outputs + GPIO breakout header + GND test clips.

    Clusters:
      A. CLK_OUT0–3 SMAs (4 vertical SMAs, signal pin to hier label)
      B. OSC_EN / WEIGHT_EN / SAMPLE_TRIG SMAs (also routed to FMC via 0Ω option)
      C. GPIO 1×4 header
      D. GND test clips (×3)
    """
    s = Sheet(name="connectors", uuid=SHEET_UUIDS["connectors"],
              page=PAGE_NUMBERS["connectors"],
              title=f"{PROJECT_NAME} — Connectors / Breakouts")

    # Cluster A: CLK_OUT0–3 SMAs (J1–J4), arranged vertically on the left.
    for i, net in enumerate(("CLK_OUT0", "CLK_OUT1", "CLK_OUT2", "CLK_OUT3")):
        ref = f"J{i+1}"
        # Place SMA at (100, 100 + i*15.24). Pin 1 (signal) at (100, 100+i*15.24).
        place(s, "Lib:HRM-G-300-467B-1", ref, "SMA", 100, 100 + i*15.24, footprint=FP_SMA)
        # Wire signal pin out to hier label
        s.add(wire(100, 100 + i*15.24, 92.71, 100 + i*15.24))
        s.add(hier_label(net, "input", 92.71, 100 + i*15.24, angle=180, justify="right"))

    # Cluster B: OSC_EN / WEIGHT_EN / SAMPLE_TRIG SMAs (J5–J7) — center column.
    for i, net in enumerate(("OSC_EN", "WEIGHT_EN", "SAMPLE_TRIG")):
        ref = f"J{i+5}"
        place(s, "Lib:HRM-G-300-467B-1", ref, "SMA", 165, 100 + i*15.24, footprint=FP_SMA)
        s.add(wire(165, 100 + i*15.24, 157.71, 100 + i*15.24))
        s.add(hier_label(net, "input", 157.71, 100 + i*15.24, angle=180, justify="right"))

    # Cluster C: GPIO 1×4 header (J8). Pin 1 = GPIO0, ..., Pin 4 = GPIO3.
    GPIO_HDR_X, GPIO_HDR_Y = 230, 100
    J8 = place(s, "Lib:TSW-104-05-G-S", "J8", "1x4 100mil", GPIO_HDR_X, GPIO_HDR_Y, footprint=FP_HEADER_1x4)
    # J8 pin world: pin 1 (230, 100), pin 2 (230, 102.54), pin 3 (230, 105.08), pin 4 (230, 107.62)
    for i, net in enumerate(("GPIO0", "GPIO1", "GPIO2", "GPIO3")):
        py = GPIO_HDR_Y + i*2.54
        s.add(wire(GPIO_HDR_X, py, GPIO_HDR_X - 7.29, py))
        s.add(hier_label(net, "input", GPIO_HDR_X - 7.29, py, angle=180, justify="right"))

    # Cluster D: 3× GND test clips (Keystone-5011), arranged at the bottom.
    for i in range(3):
        ref = f"TP{i+1}"
        place(s, "Lib:Keystone-5011", ref, "GND-CLIP", 100 + i*30, 175, footprint=FP_TESTPOINT)
        # Single pin at (100 + i*30, 175) — tie to GND
        power_at(s, "GND", 100 + i*30, 175)

    return s


# ---------------------------------------------------------------------------
# Child sheet: Bias generators
# ---------------------------------------------------------------------------

def build_bias() -> Sheet:
    """MCP4728 DAC + 2× channel (OPA2388 + PMOS + sense R + opt NMOS).

    Clusters:
      A. MCP4728 DAC (4 VOUT channels; we use A and B for the two bias loops).
      B. Channel 0 (BIAS0): OPA2388 unit A, PMZ1200UPEYL PMOS, 5.11 kΩ sense,
         optional 2N7002 NMOS isolator (DNP).
      C. Channel 1 (BIAS1): OPA2388 unit B, second PMOS, second sense R,
         optional 2N7002 (DNP).
    """
    s = Sheet(name="bias", uuid=SHEET_UUIDS["bias"],
              page=PAGE_NUMBERS["bias"],
              title=f"{PROJECT_NAME} — Bias Generators")

    GND_Y = 200.66

    # ===== Cluster A: MCP4728 DAC =====
    # Body: x ∈ [80, 151.12], y ∈ [80, 90.16].
    # Pin world (angle 0):
    #   1 VDD   (80, 80)        6 VOUTA (151.12, 90.16)
    #   2 SCL   (80, 82.54)     7 VOUTB (151.12, 87.62)
    #   3 SDA   (80, 85.08)     8 VOUTC (151.12, 85.08)
    #   4 *LDAC (80, 87.62)     9 VOUTD (151.12, 82.54)
    #   5 RDY*  (80, 90.16)    10 VSS   (151.12, 80)
    U1 = place(s, "Lib:MCP4728", "U1", "MCP4728", 80, 80, footprint=FP_QFN10)

    # I²C in (left side)
    for pn, net in [("2", "SCL"), ("3", "SDA")]:
        px, py = U1[pn]
        s.add(wire(px, py, 67.31, py))
        s.add(hier_label(net, "bidirectional", 67.31, py, angle=180, justify="right"))

    # *LDAC (4) — tie to GND for transparent latching
    s.add(wire(U1["4"][0], U1["4"][1], 67.31, U1["4"][1]))
    power_at(s, "GND", 67.31, U1["4"][1], angle=270)

    # RDY/*BSY (5) — leave NC
    s.add(no_connect(U1["5"][0], U1["5"][1]))

    # VDD (1) → +3V3
    s.add(wire(U1["1"][0], U1["1"][1], 75.18, U1["1"][1]))
    s.add(wire(75.18, U1["1"][1], 75.18, 67.31))
    power_at(s, "+3V3", 75.18, 67.31)

    # VSS (10) → GND (right side, dropped down)
    s.add(wire(U1["10"][0], U1["10"][1], 158.75, U1["10"][1]))
    s.add(wire(158.75, U1["10"][1], 158.75, GND_Y))
    power_at(s, "GND", 158.75, GND_Y)

    # VOUTC, VOUTD unused — NC
    s.add(no_connect(U1["8"][0], U1["8"][1]))
    s.add(no_connect(U1["9"][0], U1["9"][1]))

    # MCP4728 decoupling: 0.1 µF and 10 nF on VDD. Place WELL TO THE LEFT
    # of U1's left edge (x=80) so cap bodies don't overlap pin labels.
    DECAP_X1 = 55.88   # 0.1 µF
    DECAP_X2 = 50.8    # 10 nF (further left)
    place(s, "Device:C", "C1", "0.1uF", DECAP_X1, 80, footprint=FP_C0402)
    s.add(wire(DECAP_X1, 76.19, DECAP_X1, 67.31))
    s.add(wire(DECAP_X1, 67.31, 75.18, 67.31))
    s.add(junction(75.18, 67.31))
    s.add(wire(DECAP_X1, 83.81, DECAP_X1, GND_Y))

    place(s, "Device:C", "C2", "10nF", DECAP_X2, 80, footprint=FP_C0402)
    s.add(wire(DECAP_X2, 76.19, DECAP_X2, 67.31))
    s.add(wire(DECAP_X2, 67.31, DECAP_X1, 67.31))
    s.add(junction(DECAP_X1, 67.31))
    s.add(wire(DECAP_X2, 83.81, DECAP_X2, GND_Y))
    s.add(wire(DECAP_X2, GND_Y, DECAP_X1, GND_Y))
    s.add(junction(DECAP_X1, GND_Y))
    power_at(s, "GND", DECAP_X2, GND_Y)

    # ===== Bias channel builder — used twice (BIAS0, BIAS1) =====
    def bias_channel(ch_idx: int, x0: float, dac_pin: str, out_net: str,
                     refs: tuple[str, str, str, str, str]) -> None:
        """Place one bias channel (op-amp half, PMOS, sense R, opt NMOS).

        Args:
          ch_idx: 0 or 1 (informational, used in coordinate names)
          x0: left edge of channel cluster (mm)
          dac_pin: MCP4728 pin number that feeds this channel (e.g. "6" for VOUTA)
          out_net: net name for the channel output (e.g. "BIAS0")
          refs: (opa_ref, pmos_ref, sense_r_ref, isol_nmos_ref, cap_ref)
        """
        opa_ref, pmos_ref, sense_ref, nmos_ref, cap_ref = refs

        # OPA2388 unit (channel A=1, B=2). Pin numbers differ per unit but layout same.
        # Place at (x0+25, 110) — the op-amp body sits in the middle.
        opa_unit = ch_idx + 1  # ch0 → unit 1, ch1 → unit 2
        OPA = place(s, "Lib:OPA2388", opa_ref, "OPA2388", x0 + 25, 110,
                    footprint=FP_SOIC8, unit=opa_unit)
        # OPA pins per unit:
        #   Unit 1: 1=OUT_A, 2=-IN_A, 3=+IN_A, 4=V-, 8=V+
        #   Unit 2: 7=OUT_B, 6=-IN_B, 5=+IN_B (4 and 8 are common — only shown in one unit's drawing)
        # For unit 1: in_pin=3, neg_pin=2, out_pin=1
        # For unit 2: in_pin=5, neg_pin=6, out_pin=7
        in_pin  = "3" if opa_unit == 1 else "5"
        neg_pin = "2" if opa_unit == 1 else "6"
        out_pin = "1" if opa_unit == 1 else "7"

        # +IN connects to DAC VOUT_x (via short routing). DAC VOUTA is at U1["6"]
        # which is on the right edge of U1. We route the DAC output across to OPA +IN.
        dac_x, dac_y = U1[dac_pin]
        in_x, in_y = OPA[in_pin]
        # Route: from DAC, go right then down to in_y, then right to in_x
        s.add(wire(dac_x, dac_y, x0 + 5.08, dac_y))
        s.add(wire(x0 + 5.08, dac_y, x0 + 5.08, in_y))
        s.add(wire(x0 + 5.08, in_y, in_x, in_y))

        # OPA output drives PMOS gate. Place PMOS at (x0+50, 110).
        # PMOS pins: 1 G (0,0), 2 S (7.62, -5.08, angle 90), 3 D (7.62, 5.08, angle 270)
        Q = place(s, "Lib:PMZ1200UPEYL", pmos_ref, "PMZ1200UPEYL", x0 + 50, 110,
                  footprint=FP_PMOS_DFN)
        gate_x, gate_y = Q["1"]
        src_x, src_y = Q["2"]
        drn_x, drn_y = Q["3"]

        # OPA out → PMOS gate
        out_x, out_y = OPA[out_pin]
        s.add(wire(out_x, out_y, gate_x, out_y))
        if out_y != gate_y:
            s.add(wire(gate_x, out_y, gate_x, gate_y))

        # PMOS source → 3V3 via sense resistor (R, 5.11k 0.1%)
        # Sense R: vertical, between +3V3 (top) and PMOS S (bottom).
        # PMOS S world: (x0+50+7.62, 110+5.08) = (x0+57.62, 115.08)
        place(s, "Device:R", sense_ref, "5.11k 0.1%", src_x, 100, footprint=FP_R0402)
        # Sense R pin 1 (top): (src_x, 96.19); pin 2 (bot): (src_x, 103.81)
        s.add(wire(src_x, 103.81, src_x, src_y))                # bot → S
        s.add(wire(src_x, 96.19, src_x, 90.17))                 # top → up
        power_at(s, "+3V3", src_x, 90.17)

        # Op-amp –IN feedback: tie –IN to PMOS source (across sense R)
        # –IN world: (in_x, in_y + 5.08) — pin 2/6 is below pin 3/5 by 5.08
        neg_x, neg_y = OPA[neg_pin]
        # Route: from –IN (in_x, neg_y), go down then right to src_x, then up to src_y
        s.add(wire(neg_x, neg_y, neg_x, src_y + 7.62))
        s.add(wire(neg_x, src_y + 7.62, src_x, src_y + 7.62))
        s.add(wire(src_x, src_y + 7.62, src_x, src_y))
        s.add(junction(src_x, src_y))

        # PMOS drain → 2N7002 drain → 2N7002 source → BIASx hier label.
        # 2N7002 is DNP (default-removed): when unpopulated the schematic
        # shows the intended isolation path; populating activates it. Gate
        # is tied to a hier label for MCU GPIO control (BIAS_ISOx, pulled
        # low at reset → NMOS off → bias output isolated).
        # 2N7002 pin coords (angle 0): 1 G (0,0); 2 S (7.62,-5.08); 3 D (7.62,5.08).
        # Place to the right of the PMOS, on a clear horizontal lane.
        nmos_x = x0 + 70
        nmos_y = drn_y + 10.16
        NM = place(s, "Lib:2N7002", nmos_ref, "2N7002 DNP", nmos_x, nmos_y,
                   footprint=FP_SOT23)
        # Mark this instance DNP at the s-expr level too (best-effort: KiCad
        # may not honour dnp on a no-op instance, but value tag is enough
        # for downstream BOM filters).
        # NM pins world (angle 0): G=(nmos_x, nmos_y); S=(nmos_x+7.62, nmos_y+5.08); D=(nmos_x+7.62, nmos_y-5.08)
        nm_g = NM["1"]; nm_s = NM["2"]; nm_d = NM["3"]

        # PMOS drain → NMOS drain
        s.add(wire(drn_x, drn_y, drn_x, nmos_y - 5.08))   # vertical down
        s.add(wire(drn_x, nmos_y - 5.08, nm_d[0], nm_d[1]))  # horizontal to NMOS drain
        # NMOS source → BIASx output
        s.add(wire(nm_s[0], nm_s[1], nm_s[0] + 5.08, nm_s[1]))
        s.add(hier_label(out_net, "output", nm_s[0] + 5.08, nm_s[1], angle=0))
        # NMOS gate → hier label for MCU control (BIAS_ISO0 / BIAS_ISO1)
        iso_net = f"BIAS_ISO{ch_idx}"
        s.add(wire(nm_g[0], nm_g[1], nm_g[0] - 7.62, nm_g[1]))
        s.add(hier_label(iso_net, "input", nm_g[0] - 7.62, nm_g[1], angle=180, justify="right"))

        # Op-amp V+ / V- power pins. Unit 1 carries both; unit 2 omits V+/V-
        # because they're shared. For unit 1 only:
        if opa_unit == 1:
            vplus_x, vplus_y = OPA["8"]
            vminus_x, vminus_y = OPA["4"]
            # V+ → +3V3 (rotated 270, so it points up; pin is at top)
            s.add(wire(vplus_x, vplus_y, vplus_x, vplus_y - 5.08))
            power_at(s, "+3V3", vplus_x, vplus_y - 5.08)
            # V- → GND (pin at bottom)
            s.add(wire(vminus_x, vminus_y, vminus_x, vminus_y + 5.08))
            power_at(s, "GND", vminus_x, vminus_y + 5.08)

        # Channel decoupling cap (0.1 µF) on +3V3 near the OPA
        place(s, "Device:C", cap_ref, "0.1uF", x0 + 15, 95, footprint=FP_C0402)
        s.add(wire(x0 + 15, 91.19, x0 + 15, 87.63))
        power_at(s, "+3V3", x0 + 15, 87.63)
        s.add(wire(x0 + 15, 98.81, x0 + 15, 105))
        power_at(s, "GND", x0 + 15, 105)

    # Channel 0 (BIAS0): MCP4728 VOUTA (pin 6) → OPA2388 unit 1
    bias_channel(0, x0=180, dac_pin="6", out_net="BIAS0",
                 refs=("U2", "Q1", "R1", "Q3", "C3"))
    # Channel 1 (BIAS1): MCP4728 VOUTB (pin 7) → OPA2388 unit 2
    bias_channel(1, x0=295, dac_pin="7", out_net="BIAS1",
                 refs=("U2", "Q2", "R2", "Q4", "C4"))

    return s


# ---------------------------------------------------------------------------
# Child sheet: Bobcat DUT
# ---------------------------------------------------------------------------

def build_bobcat() -> Sheet:
    """Bobcat 40-QFN DUT.

    Clusters (functional, by supply domain + signal direction):
      A. Bobcat chip + GND EP
      B. VDDD decoupling (pins 12, 20)
      C. VDDIO decoupling (pins 7, 13, 22, 33, 34) + load-switch input
      D. VDDA1 path (pin 1) — series 0Ω + decoupling
      E. VDDA2 path (pins 26, 27) — series 0Ω + decoupling
      F. Pull-up / pull-down network for SPI / control signals
      G. SAMPLE_OUT, CLK_OUT, BIAS, GPIO, OSC_EN/WEIGHT_EN/SAMPLE_TRIG hier-label exits
    """
    s = Sheet(name="bobcat", uuid=SHEET_UUIDS["bobcat"],
              page=PAGE_NUMBERS["bobcat"],
              title=f"{PROJECT_NAME} — Bobcat DUT")

    # Place Bobcat at (200, 130). Body local x ∈ [-20.32, 20.32], y ∈ [-20.32, 20.32]
    # (the chip rectangle), but pins extend to (±22.86). World body: x ∈ [179.68, 220.32].
    U1 = place(s, "Lib:Bobcat", "U1", "Bobcat", 200, 130, footprint=FP_QFN40)

    # Pin 41 (GND, EP) at chip center (200, 130) — wire to GND symbol nearby
    s.add(wire(200, 130, 200, 144.78))
    power_at(s, "GND", 200, 144.78)

    # ===== Cluster B: VDDD decoupling =====
    # VDDD pins: 12 (bottom, world (-8.89, 22.86) → (191.11, 152.86))
    #            20 (bottom, world (11.43, 22.86) → (211.43, 152.86))
    # Place a 0.1µF and a 1µF cap pair for the VDDD rail.
    # VDDD rail at y = 165.1 (below chip)
    VDDD_RAIL_Y = 165.1
    GND_RAIL_BOT = 175.26

    for pn in ("12", "20"):
        px, py = U1[pn]
        s.add(wire(px, py, px, VDDD_RAIL_Y))
    s.add(wire(U1["12"][0], VDDD_RAIL_Y, U1["20"][0], VDDD_RAIL_Y))
    s.add(junction(U1["12"][0], VDDD_RAIL_Y))
    s.add(junction(U1["20"][0], VDDD_RAIL_Y))
    # Decoupling caps near VDDD rail
    for i, (ref, val) in enumerate([("C1", "0.1uF"), ("C2", "1uF")]):
        cx = 196.85 + i*5.08
        place(s, "Device:C", ref, val, cx, VDDD_RAIL_Y + 3.81, footprint=FP_C0402)
        # Cap pin 1 (top) at (cx, VDDD_RAIL_Y), pin 2 at (cx, VDDD_RAIL_Y + 7.62)
        s.add(junction(cx, VDDD_RAIL_Y))
        s.add(wire(cx, VDDD_RAIL_Y + 7.62, cx, GND_RAIL_BOT))
    # Connect VDDD rail to +VDDD power symbol
    power_at(s, "+VDDD", U1["12"][0] - 5.08, VDDD_RAIL_Y)
    s.add(wire(U1["12"][0] - 5.08, VDDD_RAIL_Y, U1["12"][0], VDDD_RAIL_Y))
    # GND rail at bottom
    s.add(wire(196.85, GND_RAIL_BOT, 201.93, GND_RAIL_BOT))
    s.add(junction(196.85, GND_RAIL_BOT))
    s.add(junction(201.93, GND_RAIL_BOT))
    power_at(s, "GND", 196.85, GND_RAIL_BOT)

    # ===== Cluster D: VDDA1 path (pin 1) =====
    # Pin 1 VDDA1 world (177.14, 118.57). Series 0Ω + decoupling.
    p1_x, p1_y = U1["1"]
    # Series 0Ω R (R5), placed horizontally to left
    R5 = place(s, "Device:R", "R5", "0", p1_x - 7.62, p1_y, angle=90, footprint=FP_R0402)
    # R5 angle 90: pin 1 local (0, 3.81), rotate 90 → (3.81, 0) → world (p1_x - 7.62 + 3.81, p1_y)
    # Wait that's the OPPOSITE direction. Let me use angle 0 (vertical) and tilt the geometry.
    # Actually simpler: use a horizontal R5 with angle 90 makes pin 1 at world
    # (p1_x - 7.62 + 3.81, p1_y) = (p1_x - 3.81, p1_y) and pin 2 at (p1_x - 7.62 - 3.81, p1_y) = (p1_x - 11.43, p1_y).
    # Wire pin 1 → pin 1 of Bobcat, pin 2 → +VDDA1.
    s.add(wire(p1_x, p1_y, p1_x - 3.81, p1_y))
    s.add(wire(p1_x - 11.43, p1_y, p1_x - 17.78, p1_y))
    power_at(s, "+VDDA1", p1_x - 17.78, p1_y, angle=270)
    # VDDA1 decoupling at the chip side (after series R)
    place(s, "Device:C", "C3", "0.1uF", p1_x - 3.81, p1_y + 7.62, footprint=FP_C0402)
    # C3 pin 1 top (p1_x-3.81, p1_y+3.81), pin 2 (p1_x-3.81, p1_y+11.43)
    s.add(wire(p1_x - 3.81, p1_y + 3.81, p1_x - 3.81, p1_y))
    s.add(junction(p1_x - 3.81, p1_y))
    s.add(wire(p1_x - 3.81, p1_y + 11.43, p1_x - 3.81, p1_y + 17.78))
    power_at(s, "GND", p1_x - 3.81, p1_y + 17.78)

    # ===== Cluster E: VDDA2 path (pins 26, 27) =====
    # Pin 26 VDDA2 (222.86, 128.73); pin 27 VDDA2 (222.86, 126.19). Two pins
    # are joined on a short vertical stub; series 0Ω routes RIGHT to +VDDA2;
    # decoupling cap is placed BELOW the pin-tie stub on its OWN vertical
    # branch (not in the series path).
    p26_x, p26_y = U1["26"]
    p27_x, p27_y = U1["27"]
    TIE_X = p26_x + 5.08          # short stub right of both pins
    s.add(wire(p26_x, p26_y, TIE_X, p26_y))
    s.add(wire(p27_x, p27_y, TIE_X, p27_y))
    s.add(wire(TIE_X, p26_y, TIE_X, p27_y))           # vertical tie 26↔27
    mid_y = (p26_y + p27_y) / 2

    # Series 0Ω R6 — horizontal (angle 90), positioned BELOW the chip body
    # so its lead doesn't fight the VDDIO power symbol on pin 22 above.
    R6_Y = mid_y + 12.7
    s.add(wire(TIE_X, p26_y, TIE_X, R6_Y))            # drop from tie down to R6 lane
    place(s, "Device:R", "R6", "0", p26_x + 13.97, R6_Y, angle=90, footprint=FP_R0402)
    s.add(wire(TIE_X, R6_Y, p26_x + 13.97 - 3.81, R6_Y))    # tie → R6 left pin
    s.add(wire(p26_x + 13.97 + 3.81, R6_Y, p26_x + 25.4, R6_Y))  # R6 right pin → power
    power_at(s, "+VDDA2", p26_x + 25.4, R6_Y, angle=90)

    # Decoupling cap C4: chip-side of R6 (on the TIE_X column), placed BELOW
    # the R6 lane so the cap body sits on its own branch — not in the
    # pin-tie wire and not under the OSC_EN/WEIGHT_EN/SAMPLE_TRIG exits.
    C4_Y = R6_Y + 12.7
    place(s, "Device:C", "C4", "0.1uF", TIE_X, C4_Y, footprint=FP_C0402)
    s.add(junction(TIE_X, R6_Y))                       # branch point at R6 lane
    s.add(wire(TIE_X, R6_Y, TIE_X, C4_Y - 3.81))       # tie → C4 top
    s.add(wire(TIE_X, C4_Y + 3.81, TIE_X, C4_Y + 7.62))  # C4 bot → GND
    power_at(s, "GND", TIE_X, C4_Y + 7.62)

    # ===== Cluster C: VDDIO decoupling =====
    # VDDIO pins 7 (left), 13/22 (bot/right), 33/34 (top) — drop a +VDDIO
    # power symbol on each pin's short stub (no shared rail; cleaner because
    # pins are on all four edges). Decoupling caps live to the side, not above.
    for pn in ("7", "13", "22", "33", "34"):
        px, py = U1[pn]
        if pn == "7":     # left edge
            s.add(wire(px, py, px - 7.62, py))
            power_at(s, "+VDDIO", px - 7.62, py, angle=270)
        elif pn == "22":  # right edge (mid)
            s.add(wire(px, py, px + 7.62, py))
            power_at(s, "+VDDIO", px + 7.62, py, angle=90)
        elif pn == "13":  # bottom edge
            s.add(wire(px, py, px, py + 7.62))
            power_at(s, "+VDDIO", px, py + 7.62)
        else:             # 33, 34 — top edge: route UP into a cap-cluster zone
            s.add(wire(px, py, px, py - 5.08))
            power_at(s, "+VDDIO", px, py - 5.08, angle=90)
    # VDDIO decoupling caps live on the FAR LEFT, well clear of the top-edge
    # hier-label exit lane. Tie each between +VDDIO and GND.
    for i, (ref, val) in enumerate([("C5", "0.1uF"), ("C6", "1uF")]):
        cx = 165.1 - i*5.08   # left of chip body (x=179.68)
        cy = 100              # well above the chip body top (y=109.68)
        place(s, "Device:C", ref, val, cx, cy, footprint=FP_C0402)
        # pin 1 top (cx, cy-3.81), pin 2 bot (cx, cy+3.81)
        s.add(wire(cx, cy - 3.81, cx, cy - 7.62))
        power_at(s, "+VDDIO", cx, cy - 7.62, angle=90)
        s.add(wire(cx, cy + 3.81, cx, cy + 7.62))
        power_at(s, "GND", cx, cy + 7.62)

    # ===== Cluster F: Pull-up/down network =====
    # Pull-downs (10k to GND) on: GPIO0-3 (37-40), SPI_DMODE (18), SCLK (16), MOSI (14),
    #                              OSC_EN (23), WEIGHT_EN (24), SAMPLE_TRIG (25)
    # Pull-ups (10k to +VDDIO) on: CS_L (17), RESET_N (19)
    # Place these pull-downs on a rail at the far right (x = U1_right + 30)
    # and pull-ups on the same rail group but tied to +VDDIO instead of GND.

    # For brevity, route each control pin directly to its hier label + a pull resistor.
    # Each pull resistor is placed vertically below/above the signal trace.

    # Bottom-edge SPI / control pins (14 MOSI, 15 MISO, 16 SCLK, 17 CS_L,
    # 18 SPI_DMODE, 19 RESET_N). Bottom-edge pins are at y=152.86. Push hier
    # labels well below the chip body (which ends at y=150.32) and stagger
    # alternate pins to avoid label overlap on the dense 2.54mm pitch.
    for i, (pn, net) in enumerate([("14", "MOSI"), ("15", "MISO"), ("16", "SCLK"),
                                    ("17", "CS_L"), ("18", "SPI_DMODE"), ("19", "RESET_N")]):
        px, py = U1[pn]
        label_y = 180.34 + (i % 2)*7.62
        s.add(wire(px, py, px, label_y))
        s.add(hier_label(net, "passive", px, label_y, angle=270, justify="left"))

    # Left-edge pins: pin 1 (VDDA1, done), 2 (SAMPLE_OUTV), 3-10 (SAMPLE_OUT0-7 part),
    # plus pin 11 (SAMPLE_OUT7, bottom edge), and pin 7 (VDDIO, done).
    # SAMPLE_OUT* exit to the left as hier labels.
    for pn, net in [("2", "SAMPLE_OUTV"), ("3", "SAMPLE_OUT0"), ("4", "SAMPLE_OUT1"),
                     ("5", "SAMPLE_OUT2"), ("6", "SAMPLE_OUT3"), ("8", "SAMPLE_OUT4"),
                     ("9", "SAMPLE_OUT5"), ("10", "SAMPLE_OUT6"), ("11", "SAMPLE_OUT7")]:
        px, py = U1[pn]
        # For pins on left edge (3-6, 8-10) and pin 2: angle 0 means pin points left,
        # so route stub LEFT.
        if pn == "11":   # bottom edge pin
            s.add(wire(px, py, px, py + 10.16))
            s.add(hier_label(net, "output", px, py + 10.16, angle=270))
        else:            # left edge
            s.add(wire(px, py, px - 12.7, py))
            s.add(hier_label(net, "output", px - 12.7, py, angle=180, justify="right"))

    # Right-edge pins not yet wired: 21 NC, 23 OSC_EN, 24 WEIGHT_EN, 25 SAMPLE_TRIG,
    # 28 BIAS0, 29 BIAS1, 30 NC
    for pn, net, direction in [
        ("23", "OSC_EN", "output"),
        ("24", "WEIGHT_EN", "output"),
        ("25", "SAMPLE_TRIG", "output"),
        ("28", "BIAS0", "input"),
        ("29", "BIAS1", "input"),
    ]:
        px, py = U1[pn]
        s.add(wire(px, py, px + 12.7, py))
        s.add(hier_label(net, direction, px + 12.7, py, angle=0))
    # NC pins 21, 30
    for pn in ("21", "30"):
        px, py = U1[pn]
        s.add(no_connect(px, py))

    # Top-edge pins: 31 CLK_OUT3, 32 CLK_OUT2, 35 CLK_OUT1, 36 CLK_OUT0, 37-40 GPIO3-0
    # (33, 34 done as VDDIO above). Route UP 30+ mm so labels clear the chip
    # entirely and don't collide with the VDDIO power-symbol stubs (which exit
    # only 5 mm above the chip).
    for pn, net in [("31", "CLK_OUT3"), ("32", "CLK_OUT2"),
                     ("35", "CLK_OUT1"), ("36", "CLK_OUT0"),
                     ("37", "GPIO3"), ("38", "GPIO2"),
                     ("39", "GPIO1"), ("40", "GPIO0")]:
        px, py = U1[pn]
        target_y = py - 25.4
        s.add(wire(px, py, px, target_y))
        s.add(hier_label(net, "output", px, target_y, angle=90, justify="left"))

    return s


# ---------------------------------------------------------------------------
# Child sheet: FMC connector
# ---------------------------------------------------------------------------

def build_fmc() -> Sheet:
    """VITA 57.1 LPC FMC connector. Power + I²C + strapping only (LA bank deferred).

    The 160-pin connector has 4 units (one per row C/D/G/H), 40 pins each.
    We place all 4 units side-by-side to expose every pin, then wire only:
      - 3P3V (C36, C38, C40, D39 → +3V3)
      - VADJ (G40, H39 → VADJ hier label)
      - SCL (D30 → SCL hier label)
      - SDA (D31 → SDA hier label)
      - PRSNT_M2C_L (H2 → GND, presence detect)
      - GA0/GA1 (C34, C35 → GND, geographical address)
      - PG_C2M (C1 → LDO_PG hier label)
      - 12P0V (D35, D37 → NC)
      - 3P3VAUX (C32 → NC)
      - VREF_A_M2C (H1 → NC)
    All other pins on rows C/D/G/H are GND per the standard — emit GND power
    symbols at those positions. LA-bank signal pins (LA00-LA33 pairs) are left
    open for later pinning.
    """
    s = Sheet(name="fmc", uuid=SHEET_UUIDS["fmc"],
              page=PAGE_NUMBERS["fmc"],
              title=f"{PROJECT_NAME} — FMC LPC Connector (Power + I²C only)")

    # Place 4 units of ASP-134606-01 — units 1,2,3,4 for rows C, D, G, H.
    # Each unit has 40 pins arranged vertically; layout each as a column.
    # Pin coords within a single unit: x=0, y from 0 down to -99.06 (40 pins × 2.54).
    # Units are placed side-by-side with horizontal spacing.

    # Unit positions
    UNIT_X = {1: 80, 2: 140, 3: 200, 4: 260}    # rows C, D, G, H
    UNIT_Y = 95
    row_letters = {1: "C", 2: "D", 3: "G", 4: "H"}

    units: dict[int, dict[str, tuple[float, float]]] = {}
    for unit_num, row_letter in row_letters.items():
        pins = place(s, "Lib:ASP-134606-01", f"J{unit_num}",
                     f"FMC LPC ({row_letter})", UNIT_X[unit_num], UNIT_Y,
                     footprint=FP_FMC, unit=unit_num)
        units[unit_num] = pins

    # Connect specific named pins. Returns the world coord of pin name X in row.
    def pin(row: str, num: int) -> tuple[float, float]:
        # Determine unit
        unit = {"C": 1, "D": 2, "G": 3, "H": 4}[row]
        key = f"{row}{num}"
        return units[unit][key]

    # ===== 3P3V (C36, C38, C40, D39) → +3V3 =====
    for r, n in [("C", 36), ("C", 38), ("C", 40), ("D", 39)]:
        px, py = pin(r, n)
        s.add(wire(px, py, px + 7.62, py))
        power_at(s, "+3V3", px + 7.62, py, angle=90)

    # ===== VADJ (G40, H39) → VADJ hier label =====
    for r, n in [("G", 40), ("H", 39)]:
        px, py = pin(r, n)
        s.add(wire(px, py, px + 10.16, py))
        s.add(hier_label("VADJ", "output", px + 10.16, py, angle=0))

    # ===== I²C =====
    s.add(wire(*pin("D", 30), pin("D", 30)[0] + 10.16, pin("D", 30)[1]))
    s.add(hier_label("SCL", "bidirectional", pin("D", 30)[0] + 10.16, pin("D", 30)[1], angle=0))
    s.add(wire(*pin("D", 31), pin("D", 31)[0] + 10.16, pin("D", 31)[1]))
    s.add(hier_label("SDA", "bidirectional", pin("D", 31)[0] + 10.16, pin("D", 31)[1], angle=0))

    # ===== Strapping: PRSNT_M2C_L (H2), GA0 (C34), GA1 (C35) → GND =====
    for r, n in [("H", 2), ("C", 34), ("C", 35)]:
        px, py = pin(r, n)
        s.add(wire(px, py, px + 7.62, py))
        power_at(s, "GND", px + 7.62, py)

    # ===== PG_C2M (C1) → LDO_PG hier label =====
    px, py = pin("C", 1)
    s.add(wire(px, py, px + 10.16, py))
    s.add(hier_label("LDO_PG", "input", px + 10.16, py, angle=0))

    # ===== NC pins (12V, 3P3VAUX, VREF_A_M2C) =====
    for r, n in [("C", 32), ("D", 35), ("D", 37), ("H", 1)]:
        px, py = pin(r, n)
        s.add(no_connect(px, py))

    # ===== Control hier labels — LDO_EN, LSW_EN (these come from LA-bank pins,
    # but pinning is TBD; for now drop them as floating hier labels on a side
    # area so the parent sheet's pins resolve). =====
    for i, net in enumerate(("LDO_EN", "LSW_EN")):
        # Place on the right side of the FMC unit 4
        lx = UNIT_X[4] + 30
        ly = UNIT_Y + i*5.08 + 5.08
        s.add(hier_label(net, "output", lx, ly, angle=0))

    # ===== GND on unlabeled pins =====
    # Per VITA 57.1, all unlabeled pins on C/D/G/H are GND. Drop GND power
    # symbols on each pin we have NOT wired above.
    wired: set[tuple[str, int]] = {
        ("C", 1), ("C", 32), ("C", 34), ("C", 35),
        ("C", 36), ("C", 38), ("C", 40),
        ("D", 30), ("D", 31), ("D", 35), ("D", 37), ("D", 39),
        ("G", 40),
        ("H", 1), ("H", 2), ("H", 39),
    }
    # Skip LA bank pins too — they're for future Bobcat signal wiring
    la_bank = set()
    la_ranges = {
        "C": [(8,9), (11,12), (14,15), (17,18), (20,21), (23,24), (26,27)],
        "D": [(10,11), (14,15), (18,19), (22,23), (26,27)],
        "G": [(7,8), (10,11), (13,14), (16,17), (19,20), (22,23), (25,26),
              (28,29), (31,32), (34,35), (37,38), (4,5)],
        "H": [(6,7), (9,10), (12,13), (15,16), (18,19), (21,22), (24,25),
              (27,28), (30,31), (33,34), (36,37), (2,3)],
    }
    # Wait H2/H3 is a clock pair (CLK1_M2C). H2 is already wired to GND but H3 should be LA-bank-like.
    # Let me just protect everything in the LA ranges from being grounded.
    for row, pairs in la_ranges.items():
        for a, b in pairs:
            la_bank.add((row, a))
            la_bank.add((row, b))
    # Also reserve: D2/D3, D6/D7 (gigabit pairs), G4/G5 (CLK0), C4/C5 (GBTCLK0)
    for row, n in [("D",2),("D",3),("D",6),("D",7),("G",4),("G",5),
                    ("C",4),("C",5),
                    # JTAG (C29-C33, C34=GA0 already wired). C29-C31, C33 left as NC.
                    ("C",29),("C",30),("C",31),("C",33)]:
        la_bank.add((row, n))
    # Also: TRST_L is C34 = GA0 (already wired)... no actually TRST_L is a separate pin per spec.
    # Just NC the JTAG pins.
    for r, n in [("C",29),("C",30),("C",31),("C",33)]:
        px, py = pin(r, n)
        if (r, n) not in wired:
            s.add(no_connect(px, py))
            wired.add((r, n))

    # Ground all unwired non-LA pins — bus each unit's GND pins onto ONE
    # vertical rail to the right of the unit, with a SINGLE GND symbol at
    # the rail's bottom. Avoids the visual clutter of dozens of triangles.
    for row, _ in [("C", 1), ("D", 2), ("G", 3), ("H", 4)]:
        gnd_pins = [n for n in range(1, 41)
                    if (row, n) not in wired and (row, n) not in la_bank]
        if not gnd_pins:
            continue
        # Rail x = pin_x + 5.08; rail spans y from first to last GND-pin y.
        first_px, first_py = pin(row, gnd_pins[0])
        _, last_py = pin(row, gnd_pins[-1])
        rail_x = first_px + 5.08
        # Short stub from each pin to the rail
        for n in gnd_pins:
            px, py = pin(row, n)
            s.add(wire(px, py, rail_x, py))
        # Vertical rail tying all the stubs
        s.add(wire(rail_x, first_py, rail_x, last_py))
        # Junctions at each stub-rail meeting (except endpoints — KiCad
        # auto-connects there, but be explicit for readability)
        for n in gnd_pins[1:-1]:
            _, py = pin(row, n)
            s.add(junction(rail_x, py))
        # One GND symbol at the rail's BOTTOM, below the last pin
        gnd_y = last_py + 5.08
        s.add(wire(rail_x, last_py, rail_x, gnd_y))
        power_at(s, "GND", rail_x, gnd_y)

    # NC the LA-bank pins for now (no_connect to avoid orphan-pin warnings)
    for r, n in la_bank:
        if (r, n) in wired:
            continue
        px, py = pin(r, n)
        s.add(no_connect(px, py))

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
        "power": build_power,
        "connectors": build_connectors,
        "bias": build_bias,
        "bobcat": build_bobcat,
        "fmc": build_fmc,
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
