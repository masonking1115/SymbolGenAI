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
    {"id": "power_stub_side", "severity": "WARNING", "scope": "sheet",
     "summary": "Supply-rail up-arrow has its net ABOVE the glyph (points up into "
                "the net instead of capping it from the top, off the net) — the "
                "rail mirror of ground_on_top"},
    {"id": "wire_through_body", "severity": "WARNING", "scope": "sheet",
     "summary": "Net wire crosses a component body instead of a pin end"},
    {"id": "pin_wire_crosses_body", "severity": "WARNING", "scope": "sheet",
     "summary": "A wire reaches a part's OWN pin by crossing the drawn symbol "
                "body (e.g. a gate wire cutting across a MOSFET glyph to a pin on "
                "the far side) — approach the pin from outside, not through it"},
    {"id": "off_center", "severity": "WARNING", "scope": "sheet",
     "summary": "Content bunched against an edge rather than centered"},
    {"id": "cramped_spacing", "severity": "WARNING", "scope": "sheet",
     "summary": "Two components closer than the min readable gap"},
    {"id": "decap_grouping", "severity": "WARNING", "scope": "sheet",
     "summary": "Same-rail decoupling cells (GND<->passive<->rail) clustered in "
                "one area but scattered instead of aligned into a neat bank"},
    {"id": "passive_declutter", "severity": "WARNING", "scope": "sheet",
     "summary": "Two aligned passives packed tighter than a readable pitch "
                "(cramped bank — space them out)"},
    {"id": "label_overlap", "severity": "WARNING", "scope": "sheet",
     "summary": "Two drawn text/label boxes overlap (unreadable glob) — port-to-port "
                "overlaps exempt (side-by-side layout like SCL/SDA is valid)"},
    {"id": "label_over_symbol", "severity": "WARNING", "scope": "sheet",
     "summary": "A label/port/value text box overlaps a component body"},
    {"id": "label_symbol_clearance", "severity": "WARNING", "scope": "sheet",
     "summary": "A PORT or text note sits flush against a component body (< min "
                "readable gap) — label bumps the symbol; measured against the "
                "true drawn body rect, not just the pin column. Aligned passive "
                "value labels (e.g. 0Ω jumper banks) are exempt"},
    {"id": "wire_through_port", "severity": "WARNING", "scope": "sheet",
     "summary": "A net wire crosses a port BODY (net travels through the port)"},
    {"id": "offpage_text", "severity": "WARNING", "scope": "sheet",
     "summary": "A drawn label/value/note/body box spills past the sheet border"},
    {"id": "wire_overlap", "severity": "WARNING", "scope": "sheet",
     "summary": "Collinear same-axis wires overlap (silent short)"},
    {"id": "stub_t_short", "severity": "ERROR", "scope": "sheet",
     "summary": "A power/port glyph SITS on the interior of an unrelated wire "
                "— Altium auto-junctions the T and silently shorts the rail "
                "to that wire. (Primary defense against the broader T-short "
                "class is now the validator's cross-net-contamination check "
                "in gen.validator._check_connectivity, added 2026-05-28; this "
                "lint catches a narrower geometric case as a secondary gate.)"},
    {"id": "shorted_component", "severity": "ERROR", "scope": "netlist",
     "summary": "A 2-terminal part (R/C/L/D, not DNP) has BOTH pins on the same "
                "net — shorted across itself, electrically a no-op. Enforced by "
                "the connectivity validator (gen.validator._check_shorted_"
                "components) from the YAML; catches e.g. a feed-forward cap placed "
                "across a strap whose two sides are the same node (FB tied to "
                "OUT). Listed here so the GUI checklist + closed-loop fix see it."},
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


def _check_power_stub_side(s):
    """A supply-rail power glyph (the up-arrow: +3V3/+VDDx/+VDDIO/...) must sit at
    the TOP of a short stub with the net BELOW it — it points UP, off the net,
    terminating the stub. Flag a rail whose net continues ABOVE the arrow tip
    (vertical wire material at the rail's column above its y): the arrow then sits
    ON / points INTO its own net instead of capping it from the top — the "PWR
    arrow overlapping the net, not facing up off it" defect.

    This is the rail mirror of ground_on_top (which guards the GND-down case); the
    two together require every power glyph to terminate its stub from the correct
    side. Auto-corrected post-build by shared.auto_fix_power (relocates the glyph
    to the clear end of its stub); flagged here when it can't be."""
    out = []
    for lb in s._labels:
        if lb.kind != "power" or lb.orientation is None:
            continue
        if "GND" in lb.name.upper():
            continue  # GND-down is ground_on_top's job
        x, y = lb.x, lb.y
        # Only meaningful for the conventional up-pointing rail (90deg). A rail
        # drawn sideways is power_orientation's concern, not this.
        if lb.orientation != 1:
            continue
        above = False
        for (a, b) in s._wires:
            if abs(a[0] - x) < _TOL and abs(b[0] - x) < _TOL:        # vertical at column x
                lo, hi = min(a[1], b[1]), max(a[1], b[1])
                if lo - _TOL <= y <= hi + _TOL and hi > y + _TOL:
                    above = True
        if above:
            out.append(LintIssue("WARNING", "power_stub_side",
                f"rail {lb.name!r} at ({x},{y}) has its net ABOVE the arrow (the "
                f"glyph points up INTO its net); place it at the TOP of the stub "
                f"so it points up OFF the net", [lb.name]))
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


# How far inside the DRAWN body a pin-terminating wire must travel before it
# counts as "crossing the symbol" rather than just touching the body edge at the
# pin. A pin sits on the body outline; a clean connection approaches from outside
# so the wire's interior stays out of the body. We inset the body by this much so
# a wire that merely grazes the edge to reach an edge-pin isn't flagged, but a
# wire running deep across the glyph (e.g. a gate wire crossing a MOSFET body to
# reach a pin on the far side) is.
_BODY_CROSS_INSET = 120  # mil (> 1 grid step / 2)


def _check_pin_wire_crosses_body(s):
    """A wire that TERMINATES on a part's own pin but reaches it by travelling
    THROUGH the part's drawn body — the "connected through the symbol" defect
    (e.g. a MOSFET whose gate-drive wire crosses the transistor glyph to land on
    a gate pin drawn on the far side). wire_through_body deliberately skips wires
    ending on the part's own pin (that's a legal connection); this catches the
    narrower case where that legal connection is drawn straight across the body
    instead of approaching the pin from outside.

    Measured against the TRUE drawn body (graphic_box) inset by
    _BODY_CROSS_INSET so a wire grazing the outline to reach an edge pin is fine;
    only a wire whose interior runs deep into the glyph is flagged. Applies to
    every component with a real body (transistors, ICs, op-amps), generalizing
    the user's MOSFET case."""
    out = []
    for (ref, unit), part in s._placed.items():
        if part.is_power or not part.pins:
            continue
        gb = getattr(part, "graphic_box", None)
        if not gb:
            continue  # need the true drawn rect; pin-extent can't tell body from pin
        inset = (gb[0] + _BODY_CROSS_INSET, gb[1] + _BODY_CROSS_INSET,
                 gb[2] - _BODY_CROSS_INSET, gb[3] - _BODY_CROSS_INSET)
        if inset[2] <= inset[0] or inset[3] <= inset[1]:
            continue  # body too small to have a meaningful interior
        own = {(round(px), round(py)) for (px, py) in part.pins.values()}
        for (a, b) in s._wires:
            ak, bk = (round(a[0]), round(a[1])), (round(b[0]), round(b[1]))
            ends_on_pin = ak in own or bk in own
            if not ends_on_pin:
                continue  # wire_through_body / bridged_drop handle pass-through wires
            if _seg_crosses_box(a, b, inset):
                out.append(LintIssue("WARNING", "pin_wire_crosses_body",
                    f"wire {a}->{b} reaches a {part.refdes} pin by crossing the "
                    f"symbol body {gb} (approach the pin from outside, not through "
                    f"the glyph)", [part.refdes]))
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


# --- decoupling-cluster grouping + passive declutter ------------------------
# A decoupling/bypass "cell" is a 2-pin passive (cap/resistor/inductor) whose two
# ends go to a power rail and to GND (or two rails) — i.e. it hangs between power
# symbols, carrying no signal. Several such cells for the SAME rail pair in one
# region read best ALIGNED in a neat row/column at a uniform pitch. These checks
# flag (a) same-rail decap cells clustered close but MISALIGNED (should be lined
# up) and (b) such cells packed tighter than a readable pitch.
DECAP_CLUSTER_RADIUS = 2500   # mil — cells within this of each other are "a group"
DECAP_ALIGN_TOL = 60          # mil — share a row/column if centers within this
DECAP_MIN_PITCH = 300         # mil — min center-to-center spacing in an aligned bank
PASSIVE_PREFIXES = ("C", "R", "L")


def _decap_cells(s):
    """[(refdes, cx, cy, frozenset(rails))] for each 2-pin passive whose BOTH pin
    nets terminate on power symbols (a pure decoupling/bypass/pull cell). rails is
    the set of rail names the cell bridges (e.g. {'+3V3','GND'}). Detected
    geometrically: a pin whose short stub ends at a power-glyph hot-spot."""
    pwr_at = {}
    for lb in s._labels:
        if lb.kind == "power":
            pwr_at.setdefault((round(lb.x), round(lb.y)), lb.name)

    def rail_reached_from(px, py):
        """Follow wires from pin (px,py); return a rail name if a short path of
        wires ends on a power glyph (<=2 hops), else None."""
        seen = {(round(px), round(py))}
        frontier = [(px, py)]
        for _hop in range(3):
            nxt = []
            for (cx, cy) in frontier:
                if (round(cx), round(cy)) in pwr_at:
                    return pwr_at[(round(cx), round(cy))]
                for (a, b) in s._wires:
                    for end, other in ((a, b), (b, a)):
                        if abs(end[0] - cx) < _TOL and abs(end[1] - cy) < _TOL:
                            ok = (round(other[0]), round(other[1]))
                            if ok not in seen:
                                seen.add(ok); nxt.append(other)
            frontier = nxt
        return None

    out = []
    for (ref, unit), p in s._placed.items():
        if p.is_power or len(p.pins) != 2:
            continue
        if not p.refdes[:1].upper() in PASSIVE_PREFIXES:
            continue
        rails = set()
        for (px, py) in p.pins.values():
            r = rail_reached_from(px, py)
            if r:
                rails.add(r)
        if len(rails) >= 2:   # both ends land on power -> a decoupling/bypass cell
            xs = [c[0] for c in p.pins.values()]; ys = [c[1] for c in p.pins.values()]
            out.append((p.refdes, sum(xs) / 2, sum(ys) / 2, frozenset(rails)))
    return out


def _check_decap_grouping(s):
    """Same-rail decoupling cells that sit close together (a cluster) but are NOT
    aligned into a neat row/column read as scattered. Flag a cluster of >=2 cells
    sharing a rail-pair, within DECAP_CLUSTER_RADIUS, whose centers neither share
    a row nor a column — they'd look tidier lined up at a uniform pitch (the
    user's "groups of GND->cap->PWR that could be neatly grouped" rule)."""
    out = []
    cells = _decap_cells(s)
    by_rail = {}
    for (ref, cx, cy, rails) in cells:
        by_rail.setdefault(rails, []).append((ref, cx, cy))
    for rails, group in by_rail.items():
        if len(group) < 2:
            continue
        # Build clusters of mutually-near cells (simple radius grouping).
        used = set()
        for i, (ri, xi, yi) in enumerate(group):
            if ri in used:
                continue
            cluster = [(ri, xi, yi)]
            for (rj, xj, yj) in group[i + 1:]:
                if rj in used:
                    continue
                if any(abs(xi - cx) <= DECAP_CLUSTER_RADIUS and
                       abs(yi - cy) <= DECAP_CLUSTER_RADIUS for (_, cx, cy) in cluster):
                    cluster.append((rj, xj, yj)); used.add(rj)
            if len(cluster) < 2:
                continue
            used.add(ri)
            xs = {round(c[1]) for c in cluster}; ys = {round(c[2]) for c in cluster}
            aligned_row = max(c[2] for c in cluster) - min(c[2] for c in cluster) <= DECAP_ALIGN_TOL
            aligned_col = max(c[1] for c in cluster) - min(c[1] for c in cluster) <= DECAP_ALIGN_TOL
            if not (aligned_row or aligned_col):
                refs = sorted(c[0] for c in cluster)
                out.append(LintIssue("WARNING", "decap_grouping",
                    f"{', '.join(refs)} are {('/'.join(sorted(rails)))} decoupling "
                    f"cells in one area but scattered (not aligned in a row/column); "
                    f"group them into a neat bank", refs))
    return out


def _check_passive_declutter(s):
    """Two aligned passives (same row or column) packed closer than
    DECAP_MIN_PITCH center-to-center read as cluttered/cramped — distinct from
    cramped_spacing (which measures body-edge gap between ANY parts); this guards
    the readable PITCH of a passive bank specifically (the user's "resistors
    placed too close to each other"). Only same-axis passive pairs are flagged so
    a legitimately dense but mixed cluster isn't penalized twice."""
    out = []
    passives = [(p.refdes, sum(c[0] for c in p.pins.values()) / 2,
                 sum(c[1] for c in p.pins.values()) / 2)
                for (_r, _u), p in s._placed.items()
                if not p.is_power and len(p.pins) == 2
                and p.refdes[:1].upper() in PASSIVE_PREFIXES]
    for i, (ra, xa, ya) in enumerate(passives):
        for (rb, xb, yb) in passives[i + 1:]:
            dx, dy = abs(xa - xb), abs(ya - yb)
            same_col = dx <= DECAP_ALIGN_TOL and 0 < dy < DECAP_MIN_PITCH
            same_row = dy <= DECAP_ALIGN_TOL and 0 < dx < DECAP_MIN_PITCH
            if same_col or same_row:
                d = dy if same_col else dx
                out.append(LintIssue("WARNING", "passive_declutter",
                    f"{ra} and {rb} are only {int(d)} mil apart center-to-center "
                    f"(<{DECAP_MIN_PITCH}); space the bank for readability",
                    [ra, rb]))
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
    """[(refdes, box)] drawn body box (inflated) for each real component.

    Prefers the true rendered graphical extent (PlacedPart.graphic_box, from
    altium_monkey's full_bounds_mils) which includes the symbol rectangle —
    important for single-column parts (e.g. FMC connectors) whose drawn body is
    offset to one side of the pin column, so a pin-only bbox understates the
    width and misses labels bumping the symbol. Falls back to pin extent."""
    out = []
    for (_ref, _u), p in s._placed.items():
        if p.is_power or not p.pins:
            continue
        gb = getattr(p, "graphic_box", None)
        bx0, by0, bx1, by1 = gb if gb else _part_bbox(p)
        out.append((p.refdes, (bx0 - _BODY_MARGIN, by0 - _BODY_MARGIN,
                               bx1 + _BODY_MARGIN, by1 + _BODY_MARGIN)))
    return out


def _check_label_overlap(s):
    """Two drawn text/label boxes overlap — the unreadable "glob" the user sees
    (e.g. a value Comment sitting under a port name, or two values colliding).
    Port-to-port overlaps are exempt: intentional side-by-side layout (e.g., SCL/SDA)
    is valid and readable; only flag when other label types collide.

    Power-to-power overlaps ARE flagged even when the two glyphs share a rail
    name: two same-rail power symbols placed too close (e.g. the VDDIO stubs on
    adjacent 200-mil-pitch chip pins) collide their rail-name text into an
    unreadable smear. They're electrically the same net, but the DRAWN text still
    overlaps — a real readability defect. (Net labels and value comments that
    repeat a name are still self-exempt: a duplicate net label is the same net
    drawn once, not two colliding glyphs.)"""
    out = []
    items = _label_boxes(s)
    for i, (ka, na, ba) in enumerate(items):
        for (kb, nb, bb) in items[i + 1:]:
            # Two power glyphs sharing a rail name still collide visually — keep them.
            same_label = (na == nb and ka == kb and ka != "power")
            if same_label:
                continue
            # Port-to-port overlaps are intentional layout (e.g., SCL/SDA side-by-side)
            if ka == "port" and kb == "port":
                continue
            if _overlap(ba, bb):
                glob = ("rail-name text collides" if ka == "power" and kb == "power"
                        else "unreadable glob")
                out.append(LintIssue("WARNING", "label_overlap",
                    f"{ka} {na!r} and {kb} {nb!r} drawn text overlap "
                    f"({glob} - space them apart)", [na, nb]))
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


# Minimum readable gap (mil) of TRUE clear space between a port/note box and a
# component's DRAWN body. Below this the label visibly bumps the symbol. Measured
# against the un-inflated graphic_box (half a 100-mil grid), so a label sitting a
# clean grid-step away is fine and only genuine near-touches are flagged.
LABEL_SYMBOL_CLEAR = 50


def _gap_between(a, b):
    """Shortest axis-aligned gap between two boxes; negative if they overlap."""
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    if dx == 0.0 and dy == 0.0:
        # boxes overlap on both axes -> overlapping; report negative penetration
        return -min(min(a[2], b[2]) - max(a[0], b[0]),
                    min(a[3], b[3]) - max(a[1], b[1]))
    return (dx * dx + dy * dy) ** 0.5


def _check_label_symbol_clearance(s):
    """A PORT or text NOTE box sits flush against (but not on top of) a component
    body — the "label bumps the symbol" case the eye catches as text crashing a
    symbol outline. Distinct from label_over_symbol (hard overlap): this catches
    near-zero clearance. Measured against the TRUE drawn body (graphic_box), so
    the FMC connectors' offset body rectangle is respected, not just their pin
    column.

    Scope: only port/text labels vs OTHER parts' bodies. A part's own value
    Comment, and value labels sitting in the regular gap of an aligned passive
    ladder (e.g. the FMC 0Ω jumper banks), are NOT flagged — a small value in a
    tidy, evenly-spaced bank reads fine and obstructs nothing. The defect we care
    about is a signal port/name colliding with a symbol it doesn't belong to."""
    out = []
    # Use TRUE drawn bodies (un-inflated) so the gap reported is real clear space.
    bodies = [(p.refdes, (p.graphic_box if getattr(p, "graphic_box", None)
                          else _part_bbox(p)))
              for (_r, _u), p in s._placed.items()
              if not p.is_power and p.pins]
    for (kind, name, lb) in _label_boxes(s):
        # Only ports and free text notes can "bump a symbol"; a part's value
        # Comment riding near an aligned passive bank is acceptable (user call).
        if kind not in ("port", "text"):
            continue
        for (refdes, bb) in bodies:
            if _overlap(lb, bb):
                continue  # hard overlap is reported by label_over_symbol
            g = _gap_between(lb, bb)
            if g < LABEL_SYMBOL_CLEAR:
                out.append(LintIssue("WARNING", "label_symbol_clearance",
                    f"{kind} {name!r} sits {g:.0f} mil from {refdes} body "
                    f"(< {LABEL_SYMBOL_CLEAR}-mil gap; label bumps the symbol - "
                    f"space it clear)", [name, refdes]))
    return out


def _check_wire_through_port(s):
    """A net wire passes THROUGH a port body (the net visibly travels across the
    port instead of terminating at it). Distinct from wire_through_label, which
    only catches the hot-spot point sitting mid-wire; this catches the body
    being impaled even when the wire correctly ends at the connection edge."""
    out = []
    for lb in s._labels:
        if lb.kind != "port":
            continue
        # Test the electrical body, not the text-expanded box: a long port name
        # renders centered text wider than the 700-mil body, overhanging the
        # connection edge — that text overhang is not the net impaling the body.
        body = getattr(lb, "body_box", None) or lb.box
        if not body:
            continue
        for (a, b) in s._wires:
            if _seg_crosses_box(a, b, body):
                out.append(LintIssue("WARNING", "wire_through_port",
                    f"port {lb.name!r} body is crossed by wire {a}->{b} (net runs "
                    f"through the port; place its body in the margin)", [lb.name]))
                break
    return out


def _check_offpage_text(s):
    """A drawn label/value/note box (or component body) spills past the sheet's
    USABLE area — the region inside Altium's border/reference-zone margin. Checks
    against the DECLARED paper size (s.paper), not auto-fitted. The bounds are
    Altium's real drawable frame (s._PAPER_MIL) inset by the border margin
    (s._PAPER_MARGIN), so content landing in the border or title-block zone is
    caught — not just content past the raw ISO page rectangle."""
    paper = s.paper  # Use declared paper, not auto-fitted
    W, H = s._PAPER_MIL.get(paper, (0, 0))
    if not W:
        return []
    m = getattr(s, "_PAPER_MARGIN", {}).get(paper, 0)
    lo_x, lo_y, hi_x, hi_y = m, m, W - m, H - m
    out = []
    items = [(k, n, b) for (k, n, b) in _label_boxes(s)]
    items += [("body", r, b) for (r, b) in _body_boxes(s)]
    for (kind, name, (x0, y0, x1, y1)) in items:
        if x0 < lo_x or y0 < lo_y or x1 > hi_x or y1 > hi_y:
            out.append(LintIssue("WARNING", "offpage_text",
                f"{kind} {name!r} box ({x0},{y0})..({x1},{y1}) spills past the "
                f"{paper} usable area ({lo_x},{lo_y})..({hi_x},{hi_y}) "
                f"[frame {W}x{H}, {m}-mil border]", [name]))
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


def _check_stub_t_short(s):
    """Catch the lane-vs-stub T-short class of bug. A power/port glyph's net
    point at (x, y) is usually the end of a short stub coming out of a
    horizontal or vertical lane. If that point lies on the INTERIOR of a
    DIFFERENT wire (not the stub itself), Altium auto-junctions the T and
    silently shorts the rail to that other wire. The connectivity validator
    misses this because its union-find joins matching endpoints, not
    endpoint-vs-interior contact.

    Concretely: for each power/port label at (x, y), find every wire whose
    interior (strictly between its two endpoints) passes through (x, y) on
    the same axis. Any such wire shorts this rail to the wire's net.

    Flagged the U41.OUTB→+3V3 short the Voltai review caught (2026-05-28)
    where build_bias.py's OUT_lane at y=11000 landed on the +3V3 power-port
    stub endpoints at (11200,11000) and (19200,11000)."""
    out = []
    for lb in s._labels:
        if lb.kind not in ("power", "port"):
            continue
        x, y = lb.x, lb.y
        for (a, b) in s._wires:
            # The stub OUT of the power port has (x, y) as one of its
            # endpoints — skip it. We only care about wires where (x, y) is
            # in the INTERIOR (strictly between endpoints).
            if (abs(a[0] - x) < _TOL and abs(a[1] - y) < _TOL) \
               or (abs(b[0] - x) < _TOL and abs(b[1] - y) < _TOL):
                continue
            # Vertical wire interior at column x?
            if abs(a[0] - b[0]) < _TOL and abs(a[0] - x) < _TOL:
                lo, hi = min(a[1], b[1]), max(a[1], b[1])
                if lo + _TOL < y < hi - _TOL:
                    out.append(LintIssue("ERROR", "stub_t_short",
                        f"{lb.kind} {lb.name!r} at ({x},{y}) T-shorts to a "
                        f"vertical wire interior {((a[0],a[1]),(b[0],b[1]))} "
                        f"— Altium auto-junctions this and bridges the nets",
                        [lb.name]))
            # Horizontal wire interior at row y?
            if abs(a[1] - b[1]) < _TOL and abs(a[1] - y) < _TOL:
                lo, hi = min(a[0], b[0]), max(a[0], b[0])
                if lo + _TOL < x < hi - _TOL:
                    out.append(LintIssue("ERROR", "stub_t_short",
                        f"{lb.kind} {lb.name!r} at ({x},{y}) T-shorts to a "
                        f"horizontal wire interior {((a[0],a[1]),(b[0],b[1]))} "
                        f"— Altium auto-junctions this and bridges the nets",
                        [lb.name]))
    return out


ALL_CHECKS = (_check_off_grid, _check_diagonal, _check_out_of_bounds,
              _check_component_overlap, _check_power_orientation,
              _check_visible_param_glob, _check_wire_through_label,
              _check_power_straddles_net, _check_stub_t_short,
              _check_ground_on_top, _check_power_stub_side,
              _check_wire_through_body,
              _check_pin_wire_crosses_body, _check_off_center,
              _check_cramped_spacing, _check_decap_grouping,
              _check_passive_declutter, _check_label_overlap,
              _check_label_over_symbol, _check_label_symbol_clearance,
              _check_wire_through_port,
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
