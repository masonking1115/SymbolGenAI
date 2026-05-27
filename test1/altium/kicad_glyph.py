"""Import a symbol body shape from an archived KiCad `.kicad_sym` and draw it
into an Altium symbol, mapped onto the Altium pin hot-spots.

Used for the active devices (MOSFET, op-amp, BJT, diode) so they look exactly
like the original KiCad symbols (gate/channel/arrow, op-amp triangle with +/-,
...). Passives keep the hand-drawn glyphs in `glyphs.py` (the resistor must be a
US zig-zag, which the KiCad library does NOT use).

Approach: parse the KiCad graphic primitives (mm) and pin connection points by
pin number, then solve an axis-aligned affine (KiCad mm -> Altium mil) from the
pin-number correspondences so every graphic endpoint lands exactly on the
matching Altium pin. Pins themselves are never touched, so hot-spots — and the
whole downstream pipeline — are unchanged.
"""

from __future__ import annotations

from altium_monkey import LineWidth

_LW = LineWidth.SMALL


# --- tiny S-expression parser ------------------------------------------------
def _parse_sexpr(text: str):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    buf.append(text[j + 1]); j += 2
                else:
                    buf.append(text[j]); j += 1
            tokens.append('"' + "".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in " \t\r\n()":
                j += 1
            tokens.append(text[i:j])
            i = j

    pos = 0

    def build():
        nonlocal pos
        node = []
        assert tokens[pos] == "("
        pos += 1
        while tokens[pos] != ")":
            if tokens[pos] == "(":
                node.append(build())
            else:
                node.append(tokens[pos]); pos += 1
        pos += 1
        return node

    out = []
    while pos < len(tokens):
        if tokens[pos] == "(":
            out.append(build())
        else:
            pos += 1
    return out[0] if out else []


def _f(x):
    return float(x)


def _head(node):
    return node[0] if node and isinstance(node[0], str) else None


def _find_all(node, tag):
    return [c for c in node if isinstance(c, list) and _head(c) == tag]


def _find(node, tag):
    for c in node:
        if isinstance(c, list) and _head(c) == tag:
            return c
    return None


def _fill_solid(prim) -> bool:
    f = _find(prim, "fill")
    if not f:
        return False
    t = _find(f, "type")
    return bool(t and t[1] in ("outline", "background", "color"))


def _pts(prim):
    p = _find(prim, "pts")
    out = []
    if p:
        for xy in _find_all(p, "xy"):
            out.append((_f(xy[1]), _f(xy[2])))
    return out


def parse_symbol(path) -> dict:
    """Return {'pins': {unit: {number: (x,y)}}, 'graphics': {unit: [prim,...]}}.

    unit 0 holds the symbol's common graphics/pins (shown on every part).
    prim is one of:
      ('poly', [(x,y)...], solid_bool)
      ('circle', cx, cy, r)
      ('rect', x1, y1, x2, y2, solid_bool)
      ('arc', [(x,y)...3], solid_bool)     # start, mid, end
    """
    root = _parse_sexpr(open(path, encoding="utf-8").read())
    top = _find(root, "symbol")
    pins: dict[int, dict] = {}
    gfx: dict[int, list] = {}
    for sub in _find_all(top, "symbol"):
        name = sub[1].lstrip('"')
        # name = "<base>_<unit>_<style>"
        parts = name.rsplit("_", 2)
        try:
            unit = int(parts[1])
        except (IndexError, ValueError):
            unit = 0
        gl = gfx.setdefault(unit, [])
        pl = pins.setdefault(unit, {})
        for prim in sub:
            if not isinstance(prim, list):
                continue
            h = _head(prim)
            if h == "polyline":
                gl.append(("poly", _pts(prim), _fill_solid(prim)))
            elif h == "rectangle":
                s = _find(prim, "start"); e = _find(prim, "end")
                if s and e:
                    gl.append(("rect", _f(s[1]), _f(s[2]), _f(e[1]), _f(e[2]),
                               _fill_solid(prim)))
            elif h == "circle":
                c = _find(prim, "center"); r = _find(prim, "radius")
                if c and r:
                    gl.append(("circle", _f(c[1]), _f(c[2]), _f(r[1])))
            elif h == "arc":
                a = [_find(prim, k) for k in ("start", "mid", "end")]
                if all(a):
                    gl.append(("arc", [(_f(p[1]), _f(p[2])) for p in a],
                               _fill_solid(prim)))
            elif h == "pin":
                at = _find(prim, "at")
                num = _find(prim, "number")
                if at and num:
                    pl[num[1].lstrip('"')] = (_f(at[1]), _f(at[2]))
    return {"pins": pins, "graphics": gfx}


def _fit(ks, as_):
    """Least-squares 1-D affine a = s*k + t. Returns (s, t) or None if degenerate."""
    n = len(ks)
    if n == 0:
        return None
    sk = sum(ks); sa = sum(as_); skk = sum(k * k for k in ks)
    ska = sum(k * a for k, a in zip(ks, as_))
    denom = n * skk - sk * sk
    if abs(denom) < 1e-9:           # all k equal -> no scale info on this axis
        return None
    s = (n * ska - sk * sa) / denom
    t = (sa - s * sk) / n
    return s, t


def available(path) -> bool:
    try:
        return bool(parse_symbol(path)["graphics"])
    except Exception:
        return False


def draw_from_kicad(sym, path, hs_by_unit: dict, owner_for_unit) -> bool:
    """Draw the KiCad body into `sym` for each Altium unit, mapped onto that
    unit's Altium hot-spots `hs_by_unit[u] = {number: (x_mil, y_mil)}`.
    Returns True on success, False if the affine could not be solved."""
    data = parse_symbol(path)
    kpins, kgfx = data["pins"], data["graphics"]
    any_drawn = False
    for u, hs in hs_by_unit.items():
        # KiCad pins for this unit + the common (unit 0) pins.
        kp = dict(kpins.get(0, {}))
        kp.update(kpins.get(u, {}))
        pairs = [(kp[num], hs[num]) for num in hs if num in kp]
        if len(pairs) < 2:
            return False
        fx = _fit([k[0] for k, _ in pairs], [a[0] for _, a in pairs])
        fy = _fit([k[1] for k, _ in pairs], [a[1] for _, a in pairs])
        if not fx or not fy:
            return False
        sx, tx = fx
        sy, ty = fy

        def T(p):
            return (int(round(sx * p[0] + tx)), int(round(sy * p[1] + ty)))

        owner = owner_for_unit(u)
        prims = list(kgfx.get(0, [])) + list(kgfx.get(u, []))
        for pr in prims:
            kind = pr[0]
            if kind == "poly":
                verts = [T(p) for p in pr[1]]
                if len(verts) < 2:
                    continue
                if pr[2] and len(verts) >= 3:
                    sym.add_polygon(verts, line_width=_LW, is_solid=True, owner_part_id=owner)
                elif len(verts) == 2:
                    sym.add_line(*verts[0], *verts[1], line_width=_LW, owner_part_id=owner)
                else:
                    sym.add_polyline(verts, line_width=_LW, owner_part_id=owner)
            elif kind == "rect":
                (x1, y1) = T((pr[1], pr[2])); (x2, y2) = T((pr[3], pr[4]))
                sym.add_rectangle(x1, y1, x2, y2, line_width=_LW,
                                  is_solid=pr[5], owner_part_id=owner)
            elif kind == "circle":
                cx, cy = T((pr[1], pr[2]))
                rx, ry = abs(int(round(sx * pr[3]))), abs(int(round(sy * pr[3])))
                if max(rx, ry) < 25:        # KiCad junction dot -> skip
                    continue
                sym.add_ellipse(cx, cy, rx, ry, line_width=_LW,
                                is_solid=False, owner_part_id=owner)
            elif kind == "arc":
                verts = [T(p) for p in pr[1]]   # approximate arc by its 3 points
                sym.add_polyline(verts, line_width=_LW, owner_part_id=owner)
            any_drawn = True
    return any_drawn
