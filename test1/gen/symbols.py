"""Symbol embedding, pin coordinate extraction, and standard-library inlines.

Two concerns live here:
1. Take a `<MPN>.kicad_sym` from `Parts Library/<MPN>/` and prepare it for
   embedding inside a schematic's `(lib_symbols …)` block — strip clauses
   that are valid in stand-alone .kicad_sym files but break on embed, rename
   the outer symbol + sub-units to `Lib:<MPN>`.
2. Provide a pin-coord lookup so layout code can ask "where does pin '14' of
   this lib_id land in world coords when placed at (X, Y, angle)?"

Standard symbols (R, C, GND, +3V3, generated rail variants) are inlined here
rather than pulled from a system KiCad lib — no runtime library lookup.
"""

from __future__ import annotations

import math
import re

from .config import PARTS_LIB


# ---------------------------------------------------------------------------
# S-expr parsing helpers
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


# ---------------------------------------------------------------------------
# Standard library symbols (R, C, power) embedded inline
# ---------------------------------------------------------------------------

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
    # Local axes (with the +y flip): u = local_x, v = -local_y
    u, v = local_x, -local_y
    rad = math.radians(at_angle)
    c, s = math.cos(rad), math.sin(rad)
    dx = u * c - v * s
    dy = u * s + v * c
    return (round(at_x + dx, 3), round(at_y + dy, 3))
