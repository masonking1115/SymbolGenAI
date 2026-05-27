"""Standard schematic body glyphs for the Altium symbol library.

The migrated symbols originally drew a generic rectangle body for EVERY part, so
a capacitor looked like a box, a MOSFET like a box, etc. These drawers replace
that rectangle with the conventional schematic shape for a device class, drawn
relative to the part's PIN HOT-SPOTS (the electrical connection points). The
pins themselves are added by the caller unchanged, so hot-spots — and therefore
every builder's net routing and the validator/linter — are untouched; only the
drawn body changes.

Each drawer takes:
  sym    — the AltiumSchLib symbol being authored,
  hs     — {designator: (x_mil, y_mil)} hot-spots for this unit's pins,
  names  — {designator: pin-name} (used to orient G/S/D, +IN/-IN/OUT, ...),
  owner  — owner_part_id for multi-unit parts (-1 for single-unit).
and draws ONLY body primitives (lines/arcs/polylines). It must not add pins.
"""

from __future__ import annotations

from altium_monkey import LineWidth

_LW = LineWidth.SMALL


def classify(prefix: str, names: dict[str, str], n_pins: int, n_units: int) -> str:
    """Infer device class from the designator prefix + pin names/counts."""
    pfx = (prefix or "").upper()
    p = pfx[:1]
    up = {(v or "").upper() for v in names.values()}
    # 3-terminal G/D/S -> MOSFET regardless of the (sometimes free-text)
    # designator prefix (e.g. "MOSFET?" rather than "Q?").
    if n_pins == 3 and {"G", "D", "S"}.issubset(up):
        return "mosfet"
    if "MOSFET" in pfx or "FET" in pfx:
        return "mosfet"
    if p == "C":
        return "capacitor"
    if p == "R":
        return "resistor"
    if p == "L":
        return "inductor"
    if p == "D":
        return "diode"
    if p == "Q":
        if {"G", "D", "S"} & up or any("GATE" in n for n in up):
            return "mosfet"
        return "bjt"
    # Op-amp: differential inputs (a +IN and a -IN) plus an OUT pin. Requiring
    # the explicit +/- naming avoids matching ordinary ICs that merely have
    # VIN/VOUT pins (e.g. a load switch).
    def _is_plus(n):
        return n.startswith("+") or n.startswith("+IN") or "NONINV" in n
    def _is_minus(n):
        return (n.startswith("-") and n != "-") or "-IN" in n or n.startswith("INV")
    if (any("OUT" in n for n in up) and any(_is_plus(n) for n in up)
            and any(_is_minus(n) for n in up) and n_pins <= 6):
        return "opamp"
    return "ic"


def _by_y(hs):
    """Return hot-spots sorted ascending by y -> (bottom, top)."""
    return sorted(hs.values(), key=lambda p: p[1])


def _by_x(hs):
    return sorted(hs.values(), key=lambda p: p[0])


def draw_capacitor(sym, hs, names, owner) -> None:
    """Two parallel plates with leads to each hot-spot (non-polarized cap)."""
    if len(hs) != 2:
        return draw_rectangle(sym, hs, names, owner)
    (bx, by), (tx, ty) = _by_y(hs)
    cx = (tx + bx) // 2
    cy = (ty + by) // 2
    gap = 25          # half the plate separation
    pw = 95           # plate half-width
    # plates
    sym.add_line(cx - pw, cy + gap, cx + pw, cy + gap, line_width=_LW, owner_part_id=owner)
    sym.add_line(cx - pw, cy - gap, cx + pw, cy - gap, line_width=_LW, owner_part_id=owner)
    # leads from each hot-spot to its plate
    sym.add_line(tx, ty, cx, cy + gap, line_width=_LW, owner_part_id=owner)
    sym.add_line(bx, by, cx, cy - gap, line_width=_LW, owner_part_id=owner)


def draw_resistor(sym, hs, names, owner) -> None:
    """US zig-zag resistor body (vertical) with leads to the hot-spots. The
    symbol is authored vertical; when a builder places it horizontally Altium
    rotates the whole glyph, so only the vertical form is needed here."""
    if len(hs) != 2:
        return draw_rectangle(sym, hs, names, owner)
    (bx, by), (tx, ty) = _by_y(hs)
    cx = (tx + bx) // 2
    top, bot = 70, -70        # zig-zag spans the body centre
    a = 45                    # zig amplitude (peak offset in x)
    n = 6                     # number of diagonal segments
    z = (top - bot) / n
    verts = [(cx, top)]
    for i in range(n - 1):
        verts.append((cx + (a if i % 2 == 0 else -a), top - (i + 1) * z))
    verts.append((cx, bot))
    sym.add_polyline([(int(x), int(y)) for x, y in verts],
                     line_width=_LW, owner_part_id=owner)
    # leads from each hot-spot to the zig-zag ends
    sym.add_line(tx, ty, cx, top, line_width=_LW, owner_part_id=owner)
    sym.add_line(bx, by, cx, bot, line_width=_LW, owner_part_id=owner)


def draw_inductor(sym, hs, names, owner) -> None:
    """Three series half-circle humps between the two hot-spots."""
    if len(hs) != 2:
        return draw_rectangle(sym, hs, names, owner)
    (bx, by), (tx, ty) = _by_y(hs)
    cx = (tx + bx) // 2
    span = 150        # total hump region (centered)
    r = span // 3 // 2
    sym.add_line(tx, ty, cx, span // 2, line_width=_LW, owner_part_id=owner)
    sym.add_line(bx, by, cx, -span // 2, line_width=_LW, owner_part_id=owner)
    y = span // 2 - r
    for _ in range(3):
        # half-circle bulging to +x (start at top of arc, sweep 180deg)
        sym.add_arc(cx, y, r, start_angle=270.0, end_angle=90.0,
                    line_width=_LW, owner_part_id=owner)
        y -= 2 * r


def draw_diode(sym, hs, names, owner) -> None:
    """Triangle + cathode bar (anode = higher pin, cathode = lower by default)."""
    if len(hs) != 2:
        return draw_rectangle(sym, hs, names, owner)
    (bx, by), (tx, ty) = _by_y(hs)
    cx = (tx + bx) // 2
    w = 70
    # anode (top) -> triangle pointing DOWN to the cathode bar
    sym.add_line(tx, ty, cx, 50, line_width=_LW, owner_part_id=owner)
    sym.add_polygon([(cx - w, 50), (cx + w, 50), (cx, -50)],
                    line_width=_LW, is_solid=False, owner_part_id=owner)
    sym.add_line(cx - w, -50, cx + w, -50, line_width=_LW, owner_part_id=owner)  # bar
    sym.add_line(bx, by, cx, -50, line_width=_LW, owner_part_id=owner)


def draw_mosfet(sym, hs, names, owner) -> None:
    """N-channel enhancement MOSFET: vertical channel bar, gate on the left,
    drain/source leads. Drawn from the G/S/D hot-spots."""
    by_name = {}
    for d, (x, y) in hs.items():
        nm = (names.get(d, "") or "").upper()
        if "G" in nm and "G" == nm[:1]:
            by_name["G"] = (x, y)
        elif nm.startswith("D"):
            by_name["D"] = (x, y)
        elif nm.startswith("S"):
            by_name["S"] = (x, y)
    if len(by_name) != 3:
        return draw_rectangle(sym, hs, names, owner)
    gx, gy = by_name["G"]
    dx, dy = by_name["D"]
    sx, sy = by_name["S"]
    chan_x = -50              # channel bar x (just right of the gate)
    # gate: horizontal lead in to a vertical gate bar
    sym.add_line(gx, gy, -150, gy, line_width=_LW, owner_part_id=owner)
    sym.add_line(-150, gy - 80, -150, gy + 80, line_width=_LW, owner_part_id=owner)
    # channel bar (vertical, broken into 3 segments is overkill — single bar)
    sym.add_line(chan_x, -90, chan_x, 90, line_width=_LW, owner_part_id=owner)
    # drain branch (top) and source branch (bottom)
    sym.add_line(dx, dy, dx, 60, line_width=_LW, owner_part_id=owner)
    sym.add_line(dx, 60, chan_x, 60, line_width=_LW, owner_part_id=owner)
    sym.add_line(sx, sy, sx, -60, line_width=_LW, owner_part_id=owner)
    sym.add_line(sx, -60, chan_x, -60, line_width=_LW, owner_part_id=owner)
    # channel mid connection to the bar
    sym.add_line(chan_x, 0, chan_x + 40, 0, line_width=_LW, owner_part_id=owner)


def draw_opamp(sym, hs, names, owner) -> None:
    """Triangle op-amp: inputs on the left (+/-), output at the apex (right)."""
    ins = sorted([(d, x, y) for d, (x, y) in hs.items()
                  if names.get(d, "").lstrip().startswith(("+", "-")) or "IN" in names.get(d, "").upper()],
                 key=lambda t: t[2])
    outs = [(d, x, y) for d, (x, y) in hs.items() if "OUT" in names.get(d, "").upper()]
    rails = [(d, x, y) for d, (x, y) in hs.items()
             if d not in {i[0] for i in ins} | {o[0] for o in outs}]
    if not ins or not outs:
        return draw_rectangle(sym, hs, names, owner)
    left_x = min(x for _, x, _ in ins)
    right_x = max(x for _, x, _ in outs)
    top = max(y for _, _, y in ins) + 100
    bot = min(y for _, _, y in ins) - 100
    apex_y = (top + bot) // 2
    bx = left_x + 100         # triangle left edge (in from the input hot-spots)
    ax = right_x - 100        # apex (toward the output)
    sym.add_polygon([(bx, top), (bx, bot), (ax, apex_y)],
                    line_width=_LW, is_solid=False, owner_part_id=owner)
    # input leads
    for _d, x, y in ins:
        sym.add_line(x, y, bx, y, line_width=_LW, owner_part_id=owner)
    # output lead
    for _d, x, y in outs:
        sym.add_line(ax, apex_y, x, y, line_width=_LW, owner_part_id=owner)
    # +/- markers near the inputs
    for _d, x, y in ins:
        nm = names.get(_d, "").lstrip()
        mx = bx + 45
        if nm.startswith("+") or nm.upper().startswith(("+IN", "NON")):
            sym.add_line(mx - 18, y, mx + 18, y, line_width=_LW, owner_part_id=owner)
            sym.add_line(mx, y - 18, mx, y + 18, line_width=_LW, owner_part_id=owner)
        elif nm.startswith("-"):
            sym.add_line(mx - 18, y, mx + 18, y, line_width=_LW, owner_part_id=owner)
    # power rails drop straight to the triangle edge
    for _d, x, y in rails:
        sym.add_line(x, y, x, apex_y if abs(y) > 200 else y, line_width=_LW, owner_part_id=owner)


def draw_rectangle(sym, hs, names, owner) -> None:
    """Generic IC / connector body: a rectangle just inside the pin hot-spots."""
    xs = [x for x, _ in hs.values()]
    ys = [y for _, y in hs.values()]
    if not xs:
        return
    pad = 0
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    # If all pins share an x (single column) give the box a sensible width.
    if x1 - x0 < 100:
        x0, x1 = x0 - 100, x1 + 100
    if y1 - y0 < 100:
        y0, y1 = y0 - 100, y1 + 100
    sym.add_rectangle(x0 + pad, y0 + pad, x1 - pad, y1 - pad,
                      line_width=_LW, is_solid=False, owner_part_id=owner)


DRAWERS = {
    "capacitor": draw_capacitor,
    "resistor": draw_resistor,
    "inductor": draw_inductor,
    "diode": draw_diode,
    "mosfet": draw_mosfet,
    "opamp": draw_opamp,
    "ic": draw_rectangle,
    "bjt": draw_rectangle,
}


def draw_body(sym, kind: str, hs, names, owner) -> None:
    DRAWERS.get(kind, draw_rectangle)(sym, hs, names, owner)
