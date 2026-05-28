"""Layout linter for the Altium backend — the mil/Altium analogue of
gen/layout_lint.py.

Advisory style/quality checks on a built AltiumSheet (the strict connectivity
validator in gen.validator stays the hard gate). Operates on the same
duck-typed records the validator uses (_wires/_junctions/_placed/_labels), in
mils on a 100-mil grid.

Two entry points, both gated in build_project.py on every generation:
  - lint(sheet)         — per-sheet checks below, registered in ALL_CHECKS.
  - lint_library(path)  — per-symbol library checks (see that function), e.g.
                          pin_name_overlap WARNING (body too narrow for its pin
                          names, so left/right names collide inside the symbol).

Sheet checks (highest value first):
  off_grid          ERROR   pin/wire endpoint not on the 100-mil grid
  diagonal_wire     ERROR   non-orthogonal wire (breaks H/V routing)
  out_of_bounds     ERROR   content past the sheet border
  component_overlap ERROR   two parts' pin-extent boxes overlap (drawn on top)
  power_orientation WARNING power port rotated against convention (GND must
                            point down 270deg, supply rails up 90deg)
  visible_param_glob WARNING component has a VISIBLE metadata parameter
                            (Footprint/Datasheet/MPN/...) — stacks at the part
                            origin into an unreadable text "glob"; hide it
  wire_through_label WARNING a port/power symbol sits MID-wire (the net travels
                            through it) instead of terminating it
  ground_on_top     WARNING a GND symbol sits ABOVE its net (wire drops down to
                            it) — GND belongs at the bottom, pointing down
  wire_through_body WARNING a net wire crosses a component body instead of
                            tapping a pin END
  off_center        WARNING sheet content is bunched against an edge rather than
                            centered on the page
  cramped_spacing   WARNING two components sit closer than the min readable gap
  label_overlap     WARNING two drawn text/label boxes overlap (unreadable
                            "glob" — value text under a port name, etc.)
  label_over_symbol WARNING a label/port/value text box overlaps a component
                            body (text or port drawn on top of a symbol)
  wire_through_port WARNING a net wire crosses a port BODY (net travels through
                            the port; its body should sit in the margin)
  offpage_text      WARNING a drawn label/value/note/body box spills past the
                            sheet border (text clipped at the page edge)
  wire_overlap      WARNING collinear same-axis wires overlap (silent short)
  bridged_drop      WARNING wire interior crosses a third part's pin (bridge)
  duplicate_wire    INFO    identical segment drawn twice
  redundant_junction INFO   junction with <3 segments / on a pin (cosmetic)
"""

from __future__ import annotations

from dataclasses import dataclass, field

GRID = 100
_TOL = 1.0   # mil


# Authoritative rule registry — the single source of truth for "what the linter
# checks". The per-sheet checks below and the GUI rule list both derive from
# this, so adding a rule here (and its _check_*) is all that's needed to surface
# it everywhere. scope: "sheet" (per-SchDoc) or "library" (per-symbol).
RULES: list[dict] = [
    {"id": "off_grid", "severity": "ERROR", "scope": "sheet",
     "summary": "Pin/wire endpoint off the 100-mil grid"},
    {"id": "diagonal_wire", "severity": "ERROR", "scope": "sheet",
     "summary": "Non-orthogonal (diagonal) wire"},
    {"id": "out_of_bounds", "severity": "ERROR", "scope": "sheet",
     "summary": "Content extends past the sheet border"},
    {"id": "component_overlap", "severity": "ERROR", "scope": "sheet",
     "summary": "Two component pin-boxes overlap (drawn on top)"},
    {"id": "power_orientation", "severity": "WARNING", "scope": "sheet",
     "summary": "Power port rotated against convention (GND down, rails up)"},
    {"id": "visible_param_glob", "severity": "WARNING", "scope": "sheet",
     "summary": "Visible metadata parameter stacks into a text glob"},
    {"id": "wire_through_label", "severity": "WARNING", "scope": "sheet",
     "summary": "Port/power hot-spot sits mid-wire instead of terminating it"},
    {"id": "power_straddles_net", "severity": "WARNING", "scope": "sheet",
     "summary": "Power/port glyph straddles the net (net runs through it) instead "
                "of sitting off to the side and terminating a stub"},
    {"id": "ground_on_top", "severity": "WARNING", "scope": "sheet",
     "summary": "GND symbol sits above its net (should hang at the bottom)"},
    {"id": "wire_through_body", "severity": "WARNING", "scope": "sheet",
     "summary": "Net wire crosses a component body instead of a pin end"},
    {"id": "off_center", "severity": "WARNING", "scope": "sheet",
     "summary": "Content bunched against an edge rather than centered"},
    {"id": "cramped_spacing", "severity": "WARNING", "scope": "sheet",
     "summary": "Two components closer than the min readable gap"},
    {"id": "label_overlap", "severity": "WARNING", "scope": "sheet",
     "summary": "Two drawn text/label boxes overlap (unreadable glob)"},
    {"id": "label_over_symbol", "severity": "WARNING", "scope": "sheet",
     "summary": "A label/port/value text box overlaps a component body"},
    {"id": "wire_through_port", "severity": "WARNING", "scope": "sheet",
     "summary": "A net wire crosses a port BODY (net travels through the port)"},
    {"id": "offpage_text", "severity": "WARNING", "scope": "sheet",
     "summary": "A drawn label/value/note/body box spills past the sheet border"},
    {"id": "wire_overlap", "severity": "WARNING", "scope": "sheet",
     "summary": "Collinear same-axis wires overlap (silent short)"},
    {"id": "bridged_drop", "severity": "WARNING", "scope": "sheet",
     "summary": "Wire interior crosses a third part's pin (possible bridge)"},
    {"id": "duplicate_wire", "severity": "INFO", "scope": "sheet",
     "summary": "Identical wire segment drawn twice"},
    {"id": "redundant_junction", "severity": "INFO", "scope": "sheet",
     "summary": "Junction with <3 segments / on a pin (cosmetic)"},
    {"id": "pin_name_overlap", "severity": "WARNING", "scope": "library",
     "summary": "Symbol body too narrow — opposing pin names collide"},
]


@dataclass
class LintIssue:
    severity: str
    rule: str
    message: str
    refs: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.severity:7s} {self.rule:18s} {self.message}"


def _part_bbox(part):
    xs = [p[0] for p in part.pins.values()]
    ys = [p[1] for p in part.pins.values()]
    if not xs:
        return (part.x, part.y, part.x, part.y)
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a, b):
    return (a[0] < b[2] - _TOL and a[2] > b[0] + _TOL
            and a[1] < b[3] - _TOL and a[3] > b[1] + _TOL)


def _off_grid(v):
    return abs(round(v / GRID) * GRID - v) > _TOL


def _check_off_grid(s):
    out = []
    for (ref, unit), p in s._placed.items():
        for num, (px, py) in p.pins.items():
            if _off_grid(px) or _off_grid(py):
                out.append(LintIssue("ERROR", "off_grid",
                    f"{ref} pin {num} at ({px},{py}) off 100-mil grid", [ref]))
    for i, (a, b) in enumerate(s._wires):
        for (x, y) in (a, b):
            if _off_grid(x) or _off_grid(y):
                out.append(LintIssue("ERROR", "off_grid",
                    f"wire endpoint ({x},{y}) off 100-mil grid"))
    return out


def _check_diagonal(s):
    return [LintIssue("ERROR", "diagonal_wire", f"wire {a}->{b} is diagonal")
            for (a, b) in s._wires
            if abs(a[0]-b[0]) > _TOL and abs(a[1]-b[1]) > _TOL]


def _check_out_of_bounds(s):
    minx, miny, maxx, maxy = s.content_bbox()
    paper = getattr(s, "_chosen_paper", None) or s._fit_paper()
    W, H = s._PAPER_MIL.get(paper, (0, 0))
    out = []
    if minx < 0 or miny < 0 or maxx > W or maxy > H:
        out.append(LintIssue("ERROR", "out_of_bounds",
            f"content ({minx},{miny})..({maxx},{maxy}) exceeds {paper} page (0,0)..({W},{H})"))
    return out


def _check_component_overlap(s):
    out = []
    parts = [(k, p, _part_bbox(p)) for k, p in s._placed.items() if not p.is_power]
    for i, (ka, pa, ba) in enumerate(parts):
        for (kb, pb, bb) in parts[i+1:]:
            if pa.refdes == pb.refdes:
                continue
            if _overlap(ba, bb):
                out.append(LintIssue("ERROR", "component_overlap",
                    f"{pa.refdes} and {pb.refdes} pin-boxes overlap", [pa.refdes, pb.refdes]))
    return out


def _check_duplicate_wire(s):
    seen = {}
    for (a, b) in s._wires:
        key = tuple(sorted([(round(a[0]), round(a[1])), (round(b[0]), round(b[1]))]))
        seen[key] = seen.get(key, 0) + 1
    return [LintIssue("INFO", "duplicate_wire", f"segment {k} drawn {n}x")
            for k, n in seen.items() if n > 1]


def _check_wire_overlap(s):
    out, H, V = [], [], []
    for (a, b) in s._wires:
        if abs(a[1]-b[1]) < _TOL and abs(a[0]-b[0]) > _TOL:
            H.append((round(a[1]), min(a[0], b[0]), max(a[0], b[0])))
        elif abs(a[0]-b[0]) < _TOL and abs(a[1]-b[1]) > _TOL:
            V.append((round(a[0]), min(a[1], b[1]), max(a[1], b[1])))
    for arr, ax in ((H, "y"), (V, "x")):
        for i, (c1, lo1, hi1) in enumerate(arr):
            for (c2, lo2, hi2) in arr[i+1:]:
                if c1 != c2:
                    continue
                lo, hi = max(lo1, lo2), min(hi1, hi2)
                if hi - lo > _TOL and not (lo1 == lo2 and hi1 == hi2):
                    out.append(LintIssue("WARNING", "wire_overlap",
                        f"collinear wires overlap at {ax}={c1} range [{lo},{hi}] (silent short)"))
    return out


def _check_bridged_drop(s):
    out = []
    pin_at = {}
    for (ref, unit), p in s._placed.items():
        for num, (px, py) in p.pins.items():
            pin_at.setdefault((round(px), round(py)), []).append((p.refdes, num, p.is_power))
    # Named-rail endpoints: a wire ending at a power/net label is a named net,
    # so parts tapping its interior are legitimate decoupling/rail taps, not
    # bridges. Skip those wires (mirrors gen.layout_lint's power-pin skip).
    label_at = {(round(l.x), round(l.y)) for l in s._labels}
    for (a, b) in s._wires:
        ak, bk = (round(a[0]), round(a[1])), (round(b[0]), round(b[1]))
        if ak in label_at or bk in label_at:
            continue
        ends = {r for (r, _, _) in pin_at.get(ak, [])} | {r for (r, _, _) in pin_at.get(bk, [])}
        if not ends:
            continue
        for pk, occ in pin_at.items():
            if pk in (ak, bk):
                continue
            on = False
            if abs(a[0]-b[0]) < _TOL and abs(pk[0]-a[0]) < _TOL:
                on = min(a[1], b[1]) + _TOL < pk[1] < max(a[1], b[1]) - _TOL
            elif abs(a[1]-b[1]) < _TOL and abs(pk[1]-a[1]) < _TOL:
                on = min(a[0], b[0]) + _TOL < pk[0] < max(a[0], b[0]) - _TOL
            if not on:
                continue
            for (r, num, isp) in occ:
                if r not in ends and not isp:
                    out.append(LintIssue("WARNING", "bridged_drop",
                        f"wire {a}->{b} interior crosses {r} pin {num} at {pk} (possible bridge)", [r]))
    return out


# Component parameters that may legitimately be drawn on the sheet. Everything
# else (Footprint/Datasheet/MPN/Manufacturer/Value/...) is metadata and must be
# hidden — a visible parameter renders at the part origin and, with several
# present, stacks into an unreadable text "glob". The displayed value rides on
# the component Comment (set in shared.place), so even Value stays hidden.
_VISIBLE_PARAM_OK = {"comment"}


def _check_visible_param_glob(s):
    """Flag placed-component parameters that are visible but shouldn't be drawn.

    Reads the sheet's actual objects (shared.AltiumSheet keeps the live
    AltiumSchDoc in `.doc`); a non-hidden AltiumSchParameter with text whose
    name isn't whitelisted is metadata that will render as a text glob."""
    doc = getattr(s, "doc", None)
    if doc is None:
        return []
    from collections import Counter
    bad = Counter()
    for o in getattr(doc, "objects", []):
        if type(o).__name__ != "AltiumSchParameter":
            continue
        if getattr(o, "is_hidden", False):
            continue
        name = (getattr(o, "name", "") or "").strip()
        text = (getattr(o, "text", "") or "").strip()
        if not text or name.lower() in _VISIBLE_PARAM_OK:
            continue
        # Skip the sheet's own document parameters (CurrentDate/Author/...),
        # which are template fields, not component metadata.
        if getattr(o, "owner_index", 0) in (0, -1) and name in _SHEET_DOC_PARAMS:
            continue
        bad[name] += 1
    return [LintIssue("WARNING", "visible_param_glob",
                      f"{n} component(s) show parameter {name!r} as drawn text "
                      f"(metadata should be hidden — only the Comment/value is drawn)",
                      [name])
            for name, n in sorted(bad.items())]


_SHEET_DOC_PARAMS = {
    "CurrentTime", "CurrentDate", "Time", "Date", "DocumentFullPathAndName",
    "DocumentName", "ModifiedDate", "ApprovedBy", "CheckedBy", "Author",
    "CompanyName", "DrawnBy", "Engineer", "Organization", "Address1",
    "Address2", "Address3", "Address4", "Title", "Revision", "SheetNumber",
    "SheetTotal", "Rule", "ImagePath", "PCBConfiguration", "VariantName",
}

_ORI_DEG = {0: 0, 1: 90, 2: 180, 3: 270}


def _check_power_orientation(s):
    """Power ports must follow schematic convention so the glyph reads right in
    Altium: GROUND-family points DOWN (270deg) and supply rails point UP
    (90deg). A sideways port (the default 0deg = east) looks rotated."""
    out = []
    for lb in s._labels:
        if lb.kind != "power" or lb.orientation is None:
            continue
        is_gnd = "GND" in lb.name.upper()
        want = 3 if is_gnd else 1                       # 270deg down / 90deg up
        if lb.orientation != want:
            got = _ORI_DEG.get(lb.orientation, lb.orientation)
            need = _ORI_DEG[want]
            kind = "ground" if is_gnd else "rail"
            out.append(LintIssue("WARNING", "power_orientation",
                f"{lb.name} power port at ({lb.x},{lb.y}) is {got}deg; "
                f"{kind} should point {'down' if is_gnd else 'up'} ({need}deg)",
                [lb.name]))
    return out


# --- layout-quality checks (general placement/routing conventions) ----------
MIN_SYMBOL_GAP = 200     # mil — min clear gap between two component pin-boxes
OFF_CENTER_FRAC = 0.18   # content center may stray this fraction of page size
_BODY_MARGIN = 60        # mil — inflate thin (2-pin) part boxes for crossing test


def _seg_is_point_interior(p, a, b):
    """True if axis-aligned segment a->b passes THROUGH point p (p on the
    segment, strictly between the endpoints)."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs(ax - bx) < _TOL and abs(px - ax) < _TOL:          # vertical
        return min(ay, by) + _TOL < py < max(ay, by) - _TOL
    if abs(ay - by) < _TOL and abs(py - ay) < _TOL:          # horizontal
        return min(ax, bx) + _TOL < px < max(ax, bx) - _TOL
    return False


def _point_on_seg(p, a, b):
    """True if point p lies on axis-aligned segment a->b (endpoints included)."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs(ax - bx) < _TOL:
        return abs(px - ax) < _TOL and min(ay, by) - _TOL <= py <= max(ay, by) + _TOL
    if abs(ay - by) < _TOL:
        return abs(py - ay) < _TOL and min(ax, bx) - _TOL <= px <= max(ax, bx) + _TOL
    return False


def _seg_crosses_box(a, b, box):
    """True if axis-aligned segment a->b passes through the interior of box
    (minx,miny,maxx,maxy)."""
    minx, miny, maxx, maxy = box
    (ax, ay), (bx, by) = a, b
    if abs(ax - bx) < _TOL:                                  # vertical at x=ax
        lo, hi = min(ay, by), max(ay, by)
        return (minx + _TOL < ax < maxx - _TOL
                and max(lo, miny) < min(hi, maxy) - _TOL)
    if abs(ay - by) < _TOL:                                  # horizontal at y=ay
        lo, hi = min(ax, bx), max(ax, bx)
        return (miny + _TOL < ay < maxy - _TOL
                and max(lo, minx) < min(hi, maxx) - _TOL)
    return False


def _check_wire_through_label(s):
    """A port/power symbol must TERMINATE a wire, not sit in its middle. (Net
    labels may ride a wire to name it, so they're exempt.)"""
    out = []
    for lb in s._labels:
        if lb.kind not in ("port", "power"):
            continue
        p = (lb.x, lb.y)
        if any(_seg_is_point_interior(p, a, b) for (a, b) in s._wires):
            out.append(LintIssue("WARNING", "wire_through_label",
                f"{lb.kind} {lb.name!r} at {p} sits mid-wire (net travels through "
                f"it; it should terminate the wire)", [lb.name]))
    return out


def _check_power_straddles_net(s):
    """A power/port glyph must sit OFF TO THE SIDE of the net and terminate it,
    not straddle it. Flag a power/port whose connection point has the net
    continuing past it on BOTH sides of an axis (vertical wire above AND below,
    or horizontal wire left AND right) — i.e. the net runs THROUGH the glyph.
    The fix is to feed the port from one side via a short stub (see
    shared.power_at(stub=...)). Broader than wire_through_label, which only sees
    a point in the interior of a single segment; this also catches a point where
    two collinear segments meet."""
    out = []
    for lb in s._labels:
        if lb.kind not in ("power", "port"):
            continue
        x, y = lb.x, lb.y
        up = down = left = right = False
        for (a, b) in s._wires:
            if abs(a[0] - x) < _TOL and abs(b[0] - x) < _TOL:        # vertical at column x
                lo, hi = min(a[1], b[1]), max(a[1], b[1])
                if lo - _TOL <= y <= hi + _TOL:
                    up |= hi > y + _TOL
                    down |= lo < y - _TOL
            if abs(a[1] - y) < _TOL and abs(b[1] - y) < _TOL:        # horizontal at row y
                lo, hi = min(a[0], b[0]), max(a[0], b[0])
                if lo - _TOL <= x <= hi + _TOL:
                    right |= hi > x + _TOL
                    left |= lo < x - _TOL
        if (up and down) or (left and right):
            out.append(LintIssue("WARNING", "power_straddles_net",
                f"{lb.kind} {lb.name!r} at ({x},{y}) straddles the net (it runs "
                f"through the glyph); feed it from one side so it terminates a stub",
                [lb.name]))
    return out


def _check_ground_on_top(s):
    """A GND symbol should sit at the BOTTOM of its connection (wire enters from
    above). Flag a GND power port whose every attached wire drops downward."""
    out = []
    for lb in s._labels:
        if lb.kind != "power" or "GND" not in lb.name.upper():
            continue
        p = (lb.x, lb.y)
        ys = []
        for (a, b) in s._wires:
            for end, other in ((a, b), (b, a)):
                if abs(end[0] - p[0]) < _TOL and abs(end[1] - p[1]) < _TOL:
                    ys.append(other[1])
        if ys and all(y < p[1] - _TOL for y in ys):
            out.append(LintIssue("WARNING", "ground_on_top",
                f"GND {lb.name!r} at {p} sits above its net (wire drops to it); "
                f"GND belongs at the bottom, pointing down", [lb.name]))
    return out


def _check_wire_through_body(s):
    """A net should tap a pin END, not cross a component body. Flag a wire whose
    interior passes through a part's (inflated) pin-box without ending on one of
    that part's pins."""
    out = []
    for (ref, unit), part in s._placed.items():
        if part.is_power or not part.pins:
            continue
        bx0, by0, bx1, by1 = _part_bbox(part)
        box = (bx0 - _BODY_MARGIN, by0 - _BODY_MARGIN,
               bx1 + _BODY_MARGIN, by1 + _BODY_MARGIN)
        pins = list(part.pins.values())
        own = {(round(px), round(py)) for (px, py) in pins}
        for (a, b) in s._wires:
            if (round(a[0]), round(a[1])) in own or (round(b[0]), round(b[1])) in own:
                continue  # wire ends on this part's pin
            if any(_point_on_seg(pin, a, b) for pin in pins):
                continue  # wire taps a pin in passing (legit rail/T-tap)
            if _seg_crosses_box(a, b, box):
                out.append(LintIssue("WARNING", "wire_through_body",
                    f"wire {a}->{b} crosses {part.refdes} body (route the net to a "
                    f"pin end, not through the symbol)", [part.refdes]))
                break
    return out


def _check_off_center(s):
    """Content should be centered on the sheet, not bunched against an edge."""
    minx, miny, maxx, maxy = s.content_bbox()
    if maxx <= minx:
        return []
    paper = getattr(s, "_chosen_paper", None) or s._fit_paper()
    W, H = s._PAPER_MIL.get(paper, (0, 0))
    if not W:
        return []
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    if abs(cx - W / 2) > W * OFF_CENTER_FRAC or abs(cy - H / 2) > H * OFF_CENTER_FRAC:
        return [LintIssue("WARNING", "off_center",
            f"content center ({int(cx)},{int(cy)}) is far from page center "
            f"({int(W/2)},{int(H/2)}) on {paper}; center the layout")]
    return []


def _check_cramped_spacing(s):
    """Two components closer than MIN_SYMBOL_GAP (but not overlapping — that's
    component_overlap) read as cluttered."""
    out = []
    parts = [(k, p, _part_bbox(p)) for k, p in s._placed.items() if not p.is_power]
    for i, (ka, pa, ba) in enumerate(parts):
        for (kb, pb, bb) in parts[i + 1:]:
            if pa.refdes == pb.refdes:
                continue
            sepx = max(ba[0] - bb[2], bb[0] - ba[2])   # >0 ⇒ separated in x
            sepy = max(ba[1] - bb[3], bb[1] - ba[3])
            close = ((sepx <= 0 and 0 < sepy < MIN_SYMBOL_GAP)
                     or (sepy <= 0 and 0 < sepx < MIN_SYMBOL_GAP))
            if close:
                gap = sepy if sepx <= 0 else sepx
                out.append(LintIssue("WARNING", "cramped_spacing",
                    f"{pa.refdes} and {pb.refdes} are only {int(gap)} mil apart "
                    f"(<{MIN_SYMBOL_GAP}); add spacing", [pa.refdes, pb.refdes]))
    return out


# --- geometric text/label extent checks -------------------------------------
# The records above gave ports/power/net/note labels and component value
# Comments a real rendered bounding box (shared.LabelRec.box / PlacedPart.
# comment_box). These checks treat drawn TEXT as the 2-D object it actually is
# instead of a dimensionless point, so they catch the failures a point model
# misses: text "globs" (overlapping labels), a component drawn on top of a
# port, a wire impaling a port body, and text spilling off the page.

def _label_boxes(s):
    """[(kind, name, box)] for every drawn label/note + component value text."""
    out = []
    for lb in s._labels:
        if lb.box:
            out.append((lb.kind, lb.name, lb.box))
    for (_ref, _u), p in s._placed.items():
        if p.comment_box:
            out.append(("value", p.refdes, p.comment_box))
    return out


def _body_boxes(s):
    """[(refdes, box)] pin-extent body box (inflated) for each real component."""
    out = []
    for (_ref, _u), p in s._placed.items():
        if p.is_power or not p.pins:
            continue
        bx0, by0, bx1, by1 = _part_bbox(p)
        out.append((p.refdes, (bx0 - _BODY_MARGIN, by0 - _BODY_MARGIN,
                               bx1 + _BODY_MARGIN, by1 + _BODY_MARGIN)))
    return out


def _check_label_overlap(s):
    """Two drawn text/label boxes overlap — the unreadable "glob" the user sees
    (e.g. a value Comment sitting under a port name, or two values colliding)."""
    out = []
    items = _label_boxes(s)
    for i, (ka, na, ba) in enumerate(items):
        for (kb, nb, bb) in items[i + 1:]:
            if na == nb and ka == kb:
                continue
            if _overlap(ba, bb):
                out.append(LintIssue("WARNING", "label_overlap",
                    f"{ka} {na!r} and {kb} {nb!r} drawn text overlap "
                    f"(unreadable glob - space them apart)", [na, nb]))
    return out


def _check_label_over_symbol(s):
    """A label/port/value text box overlaps a COMPONENT body — e.g. a resistor
    drawn on top of a port, or a port body landing across a chip/cap."""
    out = []
    bodies = _body_boxes(s)
    for (kind, name, lb) in _label_boxes(s):
        for (refdes, bb) in bodies:
            if kind == "value" and name == refdes:
                continue  # a part's own value sits just above its body
            if _overlap(lb, bb):
                out.append(LintIssue("WARNING", "label_over_symbol",
                    f"{kind} {name!r} overlaps {refdes} body "
                    f"(text/port drawn on top of a symbol - move it clear)",
                    [name, refdes]))
    return out


def _check_wire_through_port(s):
    """A net wire passes THROUGH a port body (the net visibly travels across the
    port instead of terminating at it). Distinct from wire_through_label, which
    only catches the hot-spot point sitting mid-wire; this catches the body
    being impaled even when the wire correctly ends at the connection edge."""
    out = []
    for lb in s._labels:
        if lb.kind != "port" or not lb.box:
            continue
        for (a, b) in s._wires:
            if _seg_crosses_box(a, b, lb.box):
                out.append(LintIssue("WARNING", "wire_through_port",
                    f"port {lb.name!r} body is crossed by wire {a}->{b} (net runs "
                    f"through the port; place its body in the margin)", [lb.name]))
                break
    return out


def _check_offpage_text(s):
    """A drawn label/value/note box (or component body) spills past the sheet
    border — its text is clipped at the page edge."""
    paper = getattr(s, "_chosen_paper", None) or s._fit_paper()
    W, H = s._PAPER_MIL.get(paper, (0, 0))
    if not W:
        return []
    out = []
    items = [(k, n, b) for (k, n, b) in _label_boxes(s)]
    items += [("body", r, b) for (r, b) in _body_boxes(s)]
    for (kind, name, (x0, y0, x1, y1)) in items:
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
            out.append(LintIssue("WARNING", "offpage_text",
                f"{kind} {name!r} box ({x0},{y0})..({x1},{y1}) spills past the "
                f"{paper} page (0,0)..({W},{H})", [name]))
    return out


def _check_redundant_junction(s):
    out = []
    pins = {(round(px), round(py)) for _, p in s._placed.items() for (px, py) in p.pins.values()}
    for (jx, jy) in s._junctions:
        jk = (round(jx), round(jy))
        if jk in pins:
            out.append(LintIssue("INFO", "redundant_junction", f"junction {jk} on a pin (auto-connected)"))
            continue
        seg = 0
        for (a, b) in s._wires:
            if (round(a[0]), round(a[1])) == jk or (round(b[0]), round(b[1])) == jk:
                seg += 1
            elif abs(a[0]-b[0]) < _TOL and abs(jx-a[0]) < _TOL and min(a[1], b[1]) < jy < max(a[1], b[1]):
                seg += 2
            elif abs(a[1]-b[1]) < _TOL and abs(jy-a[1]) < _TOL and min(a[0], b[0]) < jx < max(a[0], b[0]):
                seg += 2
        if seg < 3:
            out.append(LintIssue("INFO", "redundant_junction", f"junction {jk}: only {seg} segment(s)"))
    return out


ALL_CHECKS = (_check_off_grid, _check_diagonal, _check_out_of_bounds,
              _check_component_overlap, _check_power_orientation,
              _check_visible_param_glob, _check_wire_through_label,
              _check_power_straddles_net,
              _check_ground_on_top, _check_wire_through_body, _check_off_center,
              _check_cramped_spacing, _check_label_overlap,
              _check_label_over_symbol, _check_wire_through_port,
              _check_offpage_text, _check_wire_overlap, _check_bridged_drop,
              _check_duplicate_wire, _check_redundant_junction)


def lint(sheet):
    out = []
    for c in ALL_CHECKS:
        out.extend(c(sheet))
    return out


def lint_library(lib_path):
    """Symbol-library checks (general case), complementing the per-sheet ones.

    pin_name_overlap: a symbol whose body is too narrow for its pin names —
    a long left name and a long right name on the same row render inward and
    collide (the cramped-EEPROM case). Caught here so ANY symbol added to the
    design (migrated, AI-generated, or hand-built) is flagged before it reaches
    a sheet. WARNING — readability, not connectivity.
    """
    from collections import defaultdict

    from altium_monkey import AltiumSchLib

    from .units import PIN_NAME_GAP_MIL, min_half_x_for_names, text_width_mil

    out = []
    for nm in AltiumSchLib.get_symbol_names(lib_path):
        sym = AltiumSchLib(lib_path).get_symbol(nm)
        if sym is None:
            continue
        by_unit = defaultdict(list)
        for p in sym.pins:
            by_unit[int(p.owner_part_id or 1)].append(p)
        for unit, ps in sorted(by_unit.items()):
            half = max((abs(p.x_mils) for p in ps), default=0)
            if half <= 0:
                continue
            rows = defaultdict(lambda: [0.0, 0.0])
            for p in ps:
                side = 0 if p.x_mils < 0 else 1
                rows[round(p.y_mils)][side] = max(
                    rows[round(p.y_mils)][side], text_width_mil(p.name or ""))
            for y, (lw, rw) in rows.items():
                if lw + rw + PIN_NAME_GAP_MIL > 2 * half + _TOL:
                    need = min_half_x_for_names(
                        [p.name for p in ps if p.x_mils < 0],
                        [p.name for p in ps if p.x_mils > 0], base=int(half))
                    out.append(LintIssue("WARNING", "pin_name_overlap",
                        f"symbol {nm!r}{f' unit {unit}' if len(by_unit) > 1 else ''}: "
                        f"pin names overlap (body half_x={int(half)}, need {need})",
                        [nm]))
                    break
    return out


def counts(issues):
    d = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for i in issues:
        d[i.severity] = d.get(i.severity, 0) + 1
    return d


def print_report(name, issues):
    c = counts(issues)
    if sum(c.values()) == 0:
        print(f"[{name}] layout-lint: clean")
        return c
    print(f"[{name}] layout-lint: {c['ERROR']} ERROR, {c['WARNING']} WARNING, {c['INFO']} INFO")
    order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    for i in sorted(issues, key=lambda i: (order[i.severity], i.rule)):
        print(f"  {i}")
    return c


def main() -> int:
    from .build_all import BUILDERS
    total = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for name, fn in BUILDERS.items():
        s, _nl = fn()
        c = print_report(name, lint(s))
        for k in total:
            total[k] += c[k]
    print("-" * 50)
    print(f"TOTAL: {total['ERROR']} ERROR, {total['WARNING']} WARNING, {total['INFO']} INFO")
    return 1 if total["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
