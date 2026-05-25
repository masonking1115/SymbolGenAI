"""Sheet container + all emission primitives that builders call.

This is the layer between config/symbols and the per-sheet builders. A
builder constructs a `Sheet`, then accumulates s-expr fragments by calling
`wire()`, `junction()`, `label()`, `hier_label()`, `global_label()`,
`no_connect()`, `place()`, `power_at()`, and `sheet_block()`. `Sheet.render()`
produces the full file text.

`place()` is the workhorse: it embeds the symbol's lib_symbol definition on
demand, emits the placed instance, returns `{pin_number: (world_x, world_y)}`
so subsequent wire/junction calls can address pins parametrically. Multi-unit
support honors KiCad's unit-0 = "common to all units" convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import (
    GENERATOR,
    GENERATOR_VERSION,
    PROJECT_NAME,
    ROOT_UUID,
    SCH_VERSION,
    SHEET_TITLES,
    uid,
)
from .symbols import STD_SYMBOLS, extract_symbol_block, parse_pins, pin_world


# ---------------------------------------------------------------------------
# Structured records — populated as the Sheet is built so the validator in
# gen/validator.py can walk the connectivity graph without re-parsing s-expr.
# ---------------------------------------------------------------------------

@dataclass
class PlacedPart:
    refdes: str
    lib_id: str
    value: str
    x: float
    y: float
    angle: int
    unit: int
    pins: dict[str, tuple[float, float]]   # pin_number -> (world_x, world_y)
    dnp: bool = False
    is_power: bool = False
    power_rail: str = ""                    # rail name (e.g. "+3V3") if is_power


@dataclass
class LabelRec:
    kind: str          # "label" | "hier_label" | "global_label"
    name: str
    x: float
    y: float


# Regex parsers used by Sheet.add() to record wires/junctions/labels/no_connects
# from the emitted s-expr fragment. Format is stable in this codebase.
_RE_WIRE = re.compile(r"\(wire\s+\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\)")
_RE_JUNC = re.compile(r"\(junction\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)")
_RE_NC = re.compile(r"\(no_connect\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)")
_RE_LABEL = re.compile(r'\((label|hierarchical_label|global_label)\s+"([^"]+)".*?\(at\s+([-\d.]+)\s+([-\d.]+)')


# ---------------------------------------------------------------------------
# Sheet container
# ---------------------------------------------------------------------------

@dataclass
class Sheet:
    """Accumulates s-expression fragments for a single .kicad_sch file.

    In addition to the emitted s-expr strings, Sheet records structured data
    (placed parts, wires, junctions, labels, no_connects) so the strict
    validator can walk the connectivity graph without re-parsing s-expr.
    """
    name: str           # short name used in filename
    uuid: str           # sheet uuid
    page: str           # page number (string)
    title: str = ""     # title block title
    paper: str = "A3"

    _lib_symbols: dict[str, str] = field(default_factory=dict)
    _content: list[str] = field(default_factory=list)
    _refdes_seen: set[str] = field(default_factory=set)

    # Structured records (mirror of _content for validator consumption).
    # _placed is keyed by (refdes, unit) so multi-unit symbols (OPA2388 unit
    # 1+2, ASP-134606 4 units) store each unit's pin coords separately.
    # Use _placed_by_ref() if you only have the refdes and want any unit.
    _placed: dict[tuple[str, int], PlacedPart] = field(default_factory=dict)
    _wires: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)
    _junctions: list[tuple[float, float]] = field(default_factory=list)
    _labels: list[LabelRec] = field(default_factory=list)
    _no_connects: list[tuple[float, float]] = field(default_factory=list)

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
        """Append an s-expr fragment and parse it into structured records.

        Wires, junctions, labels, and no_connects are extracted by regex. The
        emit format from gen.shared is stable; if a future change to the emit
        functions reshapes the fragment, the regex below needs to keep pace.
        """
        self._content.append(sexpr)
        stripped = sexpr.lstrip()
        if stripped.startswith("(wire "):
            m = _RE_WIRE.search(stripped)
            if m:
                self._wires.append((
                    (float(m.group(1)), float(m.group(2))),
                    (float(m.group(3)), float(m.group(4))),
                ))
        elif stripped.startswith("(junction "):
            m = _RE_JUNC.search(stripped)
            if m:
                self._junctions.append((float(m.group(1)), float(m.group(2))))
        elif stripped.startswith("(no_connect "):
            m = _RE_NC.search(stripped)
            if m:
                self._no_connects.append((float(m.group(1)), float(m.group(2))))
        elif (stripped.startswith("(label ")
              or stripped.startswith("(hierarchical_label ")
              or stripped.startswith("(global_label ")):
            m = _RE_LABEL.search(stripped)
            if m:
                kind_map = {
                    "label": "label",
                    "hierarchical_label": "hier_label",
                    "global_label": "global_label",
                }
                self._labels.append(LabelRec(
                    kind=kind_map[m.group(1)],
                    name=m.group(2),
                    x=float(m.group(3)),
                    y=float(m.group(4)),
                ))

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


def global_label(net: str, shape: str, x, y, angle: int = 0,
                 justify: str = "left") -> str:
    """Global label — ties by name across all sheets without needing a parent
    pin declaration. Use for project-wide nets (SCL/SDA, deferred LA-bank
    signals) where a hier_label would force redundant parent-pin plumbing."""
    return (f'  (global_label "{net}" (shape {shape}) (at {x} {y} {angle}) '
            f'(effects (font (size 1.27 1.27)) (justify {justify})) '
            f'(uuid "{uid(f"glabel_{net}_{x}_{y}")}"))')


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
          footprint: str = "", unit: int = 1,
          dnp: bool = False) -> dict[str, tuple[float, float]]:
    """
    Embed a symbol if needed, emit an instance, and return {pin_number: (wx, wy)}.

    For multi-unit symbols (e.g. OPA2388 dual op-amp), pass unit=2, 3, … to
    instantiate other units. Only the named unit's pins (plus shared-power
    pins assigned to unit 1) are wired by the returned coord map.

    dnp=True marks the instance Do Not Populate at the s-expr level. Use this
    instead of putting " DNP" in the Value field so downstream BOM/PnP tools
    read a machine-readable status.
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
    dnp_flag = "yes" if dnp else "no"
    block = f'''  (symbol
    (lib_id "{lib_id}")
    (at {x} {y} {angle})
    (unit {unit}) (in_bom yes) (on_board yes) (dnp {dnp_flag})
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

    # Record structured placement for the validator (gen/validator.py).
    # Keyed by (refdes, unit) so multi-unit symbols (e.g. OPA2388 unit 1+2,
    # ASP-134606 J1 units 1..4) each retain their own pin map.
    sheet._placed[(ref_actual, unit)] = PlacedPart(
        refdes=ref_actual,
        lib_id=lib_id,
        value=value,
        x=x, y=y, angle=angle, unit=unit,
        pins=out,
        dnp=dnp,
        is_power=is_power,
        power_rail=value if is_power else "",
    )
    return out


def place_from_netlist(sheet: "Sheet", netlist, refdes: str,
                       x: float, y: float, angle: int = 0,
                       unit: int = 1,
                       ) -> dict[str, tuple[float, float]]:
    """Place a part whose lib_id / value / footprint / dnp come from the YAML
    netlist. The layout file picks (x, y, angle) and (for multi-unit symbols)
    the `unit` to instantiate; everything else is read from netlist/<sheet>.yaml.

    For multi-unit parts, call once per declared unit. The validator's
    inventory check verifies every declared unit is placed.
    """
    p = netlist.parts[refdes]
    if unit not in p.units:
        raise ValueError(
            f"place_from_netlist: {refdes} unit {unit} not in YAML's units "
            f"{p.units} (declared in netlist/{netlist.sheet}.yaml)"
        )
    return place(sheet, p.lib_id, p.refdes, p.value,
                 x, y, angle=angle,
                 footprint=p.footprint, unit=unit, dnp=p.dnp)


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
# Cluster helpers — bake skill Rules 7 & 8 into reusable calls
# ---------------------------------------------------------------------------

def gnd_bus(sheet: Sheet,
            pins: list[tuple[float, float]],
            rail_x: float,
            gnd_extra: float = 5.08,
            ) -> tuple[float, float]:
    """Bus a column of pins to a vertical GND rail terminated by ONE power:GND.

    Implements skill Rule 7 (GND symbol clustering): instead of dropping one
    power:GND per pin, fan stubs from each pin into a common rail and drop a
    single GND at the bottom.

    Args:
        sheet:    target Sheet
        pins:     list of world-coord pin positions to bus together
        rail_x:   x-coordinate of the vertical rail (should clear all pin x's)
        gnd_extra: how far below the lowest pin the GND symbol sits

    Returns the (x, y) where the GND symbol was placed.

    Junctions are dropped at every interior tap (i.e. every pin except the
    topmost and bottommost) since 3 wires meet there: the stub coming in,
    and the two rail segments above/below.
    """
    if not pins:
        raise ValueError("gnd_bus: pins list is empty")
    sorted_pins = sorted(pins, key=lambda p: p[1])
    top_y = sorted_pins[0][1]
    bot_y = sorted_pins[-1][1]

    for (px, py) in sorted_pins:
        sheet.add(wire(px, py, rail_x, py))

    if len(sorted_pins) >= 2:
        sheet.add(wire(rail_x, top_y, rail_x, bot_y))

    # Interior junctions (skip endpoints — the rail terminates there).
    for (_, py) in sorted_pins[1:-1]:
        sheet.add(junction(rail_x, py))

    gnd_y = bot_y + gnd_extra
    sheet.add(wire(rail_x, bot_y, rail_x, gnd_y))
    power_at(sheet, "GND", rail_x, gnd_y)
    return (rail_x, gnd_y)


def decoupling_cluster(sheet: Sheet,
                       netlist,
                       cap_refs: list[str],
                       rail: str,
                       rail_x: float,
                       rail_y: float,
                       spacing: float = 7.62,
                       gnd_extra: float = 5.08,
                       ) -> tuple[float, float]:
    """Lay out a horizontal row of decoupling caps sharing one rail above and
    ONE power:GND below. Implements skill Rule 8 (decoupling-cap cluster).

    Caps are placed vertically (pin 1 on top → rail, pin 2 on bottom → GND).
    `cap_refs` are looked up in the YAML netlist for lib_id/value/footprint.
    The caller wires the rail back to the chip's supply pin themselves — this
    helper only owns the cap row.

    Args:
        sheet:     target Sheet
        netlist:   loaded Netlist (for place_from_netlist)
        cap_refs:  ordered list of cap refdes (left-to-right placement)
        rail:      rail name (e.g. "+3V3") — only used for the optional comment;
                   no power symbol is dropped on the rail end (caller wires it
                   to the chip)
        rail_x:    x of the LEFTMOST cap (the rail extends right from here)
        rail_y:    y of the rail line (pin 1 of each cap sits ON this y)
        spacing:   horizontal gap between cap centers (default 7.62 = 3 grid)
        gnd_extra: how far below the cap row the GND symbol sits

    Returns (rail_left_x, rail_right_x) so the caller can extend the rail to
    the chip's VCC pin (typically with one extra wire segment).
    """
    if not cap_refs:
        raise ValueError("decoupling_cluster: cap_refs is empty")

    # Device:C pin 1 is at local (0, +3.81) → world (cx, cy - 3.81) at angle 0.
    # So to land pin 1 ON rail_y, cy = rail_y + 3.81.
    cy = rail_y + 3.81
    gnd_y = rail_y + 7.62 + gnd_extra        # 7.62 = cap pin-to-pin span

    xs = [rail_x + i * spacing for i in range(len(cap_refs))]

    for (cx, ref) in zip(xs, cap_refs):
        place_from_netlist(sheet, netlist, ref, x=cx, y=cy)

    # Top rail across pin-1's of every cap (skip if only one cap — pin 1 is
    # already on rail_y, no rail wire needed; caller adds the connection).
    if len(xs) > 1:
        sheet.add(wire(xs[0], rail_y, xs[-1], rail_y))
        for cx in xs[1:-1]:
            sheet.add(junction(cx, rail_y))

    # Bottom rail across pin-2's of every cap, plus stubs down to gnd_y at the
    # rightmost cap only. Single shared GND symbol per Rule 7.
    pin2_y = rail_y + 7.62
    if len(xs) > 1:
        sheet.add(wire(xs[0], pin2_y, xs[-1], pin2_y))
        for cx in xs[1:-1]:
            sheet.add(junction(cx, pin2_y))
    sheet.add(wire(xs[-1], pin2_y, xs[-1], gnd_y))
    power_at(sheet, "GND", xs[-1], gnd_y)

    return (xs[0], xs[-1])


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
