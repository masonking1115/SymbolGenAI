"""Layout linter — non-fatal style/formatting checks on a built Sheet.

Complements gen/validator.py:
  - validator.py    → connectivity correctness (must pass; raises on fail)
  - layout_lint.py  → visual / placement quality (advisory; warnings only)

Backs the rules in .claude/skills/kicad-circuit-from-topology.md §Layout:
  Rule 1 (spacing)    → bbox_overlap, bbox_too_close
  Rule 2 (labels)     → refval_on_body, label_on_body
  Rule 5 (routing)    → diagonal_wire, wire_through_body, duplicate_wire,
                        redundant_junction
  Rule 7 (GND clust.) → dense_gnd_cluster

Run it after validate() in each build_<sheet>.py, or globally from
gen_schematic.py against every Sheet. Issues are returned as a list; nothing
raises. Severity is advisory — ERROR means "looks broken", WARNING means
"violates a written rule", INFO means "candidate for consolidation".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .shared import PlacedPart, Sheet
from .symbols import parse_pins


_TOL = 0.01            # mm — float-equality slack
_MIN_GAP = 2.54        # mm — Rule 1 adjacent-component minimum
_GND_CLUSTER_RADIUS = 15.0   # mm — radius for dense_gnd_cluster INFO
_GND_CLUSTER_THRESHOLD = 3   # symbols within radius → flag


# ---------------------------------------------------------------------------
# Issue record
# ---------------------------------------------------------------------------

@dataclass
class LintIssue:
    severity: str          # "ERROR" | "WARNING" | "INFO"
    rule: str              # short id, e.g. "bbox_overlap"
    message: str
    refs: list[str] = field(default_factory=list)   # involved refdes / coords

    def __str__(self) -> str:
        return f"{self.severity:7s} {self.rule:22s} {self.message}"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _part_bbox(part: PlacedPart) -> tuple[float, float, float, float]:
    """Return a conservative (min_x, min_y, max_x, max_y) "no-go" box for the part.

    Power symbols are tiny — fixed box around the pin.
    Device:R/C/L bodies are SHORT relative to their pin span (cap plates at
    y±0.762, resistor body at y±2.54 vs pins at y±3.81). Using pin-extent
    here flags wires that pass BETWEEN the pins as wire_through_body false
    positives. Use the actual body extent instead.
    For ICs the pin-extent bbox is an outer bound on the body.
    """
    if part.is_power:
        return (part.x - 1.27, part.y - 2.0, part.x + 1.27, part.y + 2.0)
    if part.lib_id in ("Device:R", "Device:L"):
        # Body: x ∈ [-1.016, 1.016], y ∈ [-2.54, 2.54] (local).
        bx, by = 1.016, 2.54
    elif part.lib_id == "Device:C":
        # Body (just the two plates): x ∈ [-2.032, 2.032], y ∈ [-0.762, 0.762].
        bx, by = 2.032, 0.762
    else:
        if not part.pins:
            return (part.x, part.y, part.x, part.y)
        xs = [px for (px, _) in part.pins.values()]
        ys = [py for (_, py) in part.pins.values()]
        return (min(xs), min(ys), max(xs), max(ys))
    # For passives, rotation swaps x/y body extents.
    if part.angle in (90, 270):
        bx, by = by, bx
    return (part.x - bx, part.y - by, part.x + bx, part.y + by)


def _bbox_overlap(a: tuple[float, float, float, float],
                  b: tuple[float, float, float, float]) -> bool:
    """True if two axis-aligned bboxes share interior area (touching edges → False)."""
    return (a[0] < b[2] - _TOL and a[2] > b[0] + _TOL
            and a[1] < b[3] - _TOL and a[3] > b[1] + _TOL)


def _bbox_gap(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float]) -> float:
    """Min orthogonal distance between two non-overlapping bboxes (0 if touching)."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    if dx == 0.0 and dy == 0.0:
        return 0.0
    if dx == 0.0:
        return dy
    if dy == 0.0:
        return dx
    return (dx * dx + dy * dy) ** 0.5


def _point_in_bbox(x: float, y: float,
                   bbox: tuple[float, float, float, float]) -> bool:
    return (bbox[0] + _TOL < x < bbox[2] - _TOL
            and bbox[1] + _TOL < y < bbox[3] - _TOL)


def _segment_enters_bbox(x1: float, y1: float, x2: float, y2: float,
                         bbox: tuple[float, float, float, float]) -> bool:
    """True if an orthogonal wire segment enters the bbox's interior.

    A segment that merely touches the boundary (e.g. terminates on the box
    edge at a pin coord) does not count — only interior intersection.
    """
    minx, miny, maxx, maxy = bbox
    if abs(x1 - x2) < _TOL:                       # vertical
        if not (minx + _TOL < x1 < maxx - _TOL):
            return False
        seg_lo, seg_hi = min(y1, y2), max(y1, y2)
        return seg_lo < maxy - _TOL and seg_hi > miny + _TOL
    if abs(y1 - y2) < _TOL:                       # horizontal
        if not (miny + _TOL < y1 < maxy - _TOL):
            return False
        seg_lo, seg_hi = min(x1, x2), max(x1, x2)
        return seg_lo < maxx - _TOL and seg_hi > minx + _TOL
    return False                                  # diagonal — separate rule


def _ref_value_anchors(part: PlacedPart) -> tuple[tuple[float, float],
                                                  tuple[float, float]]:
    """Replicate shared._ref_value_positions() for the linter.

    These are the world-coord anchors KiCad uses to render the Reference and
    Value text of a placed symbol. If an anchor lands inside another part's
    bbox, the text will collide with that part visually.
    """
    x, y, angle, lib_id = part.x, part.y, part.angle, part.lib_id
    if lib_id in ("Device:R", "Device:C", "Device:L"):
        if angle in (0, 180):
            return ((x + 2.54, y - 1.27), (x + 2.54, y + 1.27))
        return ((x, y - 3.81), (x, y + 3.81))
    if lib_id.startswith("power:"):
        return ((x, y - 6.35), (x, y - 3.81))
    return ((x, y - 5.08), (x, y + 5.08))


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_diagonal_wires(sheet: Sheet) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for (a, b) in sheet._wires:
        if abs(a[0] - b[0]) > _TOL and abs(a[1] - b[1]) > _TOL:
            issues.append(LintIssue(
                "ERROR", "diagonal_wire",
                f"wire {a}→{b} is diagonal (Rule 5: orthogonal only)",
                [f"{a}->{b}"],
            ))
    return issues


def _check_bbox_overlap_and_spacing(sheet: Sheet) -> list[LintIssue]:
    """Pairwise bbox check — Rule 1 (component spacing).

    Power-symbol pairs are excluded: clustering GNDs/rails near each other is
    normal and gets its own dense_gnd_cluster INFO check instead.

    Pairs of the same 2-pin passive (Device:C-Device:C, Device:R-Device:R) get
    a relaxed gap threshold — decoupling-cap rows and pull-down banks (per
    Rule 8) intentionally pack at 5.08 mm pitch, which yields ~1 mm body gap.
    """
    issues: list[LintIssue] = []
    parts = [p for p in sheet._placed.values() if not p.is_power]
    bbs = [(p, _part_bbox(p)) for p in parts]
    seen: set[tuple[str, str]] = set()
    for i, (pa, ba) in enumerate(bbs):
        for (pb, bb) in bbs[i + 1:]:
            if pa.refdes == pb.refdes:
                continue
            key = tuple(sorted((f"{pa.refdes}:u{pa.unit}", f"{pb.refdes}:u{pb.unit}")))
            if key in seen:
                continue
            seen.add(key)
            if _bbox_overlap(ba, bb):
                issues.append(LintIssue(
                    "ERROR", "bbox_overlap",
                    f"{pa.refdes}:u{pa.unit} and {pb.refdes}:u{pb.unit} "
                    f"bounding boxes overlap",
                    [pa.refdes, pb.refdes],
                ))
                continue
            min_gap = _MIN_GAP
            if (pa.lib_id == pb.lib_id
                    and pa.lib_id in ("Device:C", "Device:R", "Device:L")):
                min_gap = 1.0   # array/row pattern
            gap = _bbox_gap(ba, bb)
            if gap < min_gap - _TOL:
                issues.append(LintIssue(
                    "WARNING", "bbox_too_close",
                    f"{pa.refdes}:u{pa.unit} ↔ {pb.refdes}:u{pb.unit} "
                    f"gap {gap:.2f} mm (Rule 1: ≥ {min_gap:.2f} mm)",
                    [pa.refdes, pb.refdes],
                ))
    return issues


def _check_wire_through_body(sheet: Sheet) -> list[LintIssue]:
    """Rule 5 last clause — no net passes through a component body."""
    issues: list[LintIssue] = []
    for (a, b) in sheet._wires:
        for part in sheet._placed.values():
            if part.is_power:
                continue
            bbox = _part_bbox(part)
            if not _segment_enters_bbox(a[0], a[1], b[0], b[1], bbox):
                continue
            # If either endpoint is one of THIS part's pins, the wire is the
            # part's own stub — fine.
            pin_keys = {(round(px, 3), round(py, 3)) for (px, py) in part.pins.values()}
            if ((round(a[0], 3), round(a[1], 3)) in pin_keys
                    or (round(b[0], 3), round(b[1], 3)) in pin_keys):
                continue
            issues.append(LintIssue(
                "WARNING", "wire_through_body",
                f"wire {a}→{b} passes through {part.refdes}:u{part.unit} "
                f"without terminating on one of its pins",
                [part.refdes],
            ))
    return issues


# 2-pin passives have pins on OPPOSITE sides of the body (body sits between
# the two pins), so the notion of "wire exits away from body" doesn't apply
# — a wire from one pin going toward the other pin's side isn't a bug, just
# routing efficiency. Skip these from the wire_into_body check.
_PASSIVES_TWO_PIN = frozenset({"Device:R", "Device:C", "Device:L"})


def _check_wire_into_body(sheet: Sheet) -> list[LintIssue]:
    """Rule 5b — wires must exit on the pin-protrusion side (away from body).

    Complements _check_wire_through_body: bbox-based detection fails for
    one-sided symbols (single-edge connectors like FMC ASP-134606, SMAs,
    headers like TSW-102) because all pins live on one local x or y line,
    making the pin-extent bbox degenerate. This check uses the pin ANGLE —
    the unambiguous source of truth for which side of the body the pin
    protrudes from.

    World-direction-into-body computation:
      editor_dir = {0: (+x), 90: (+y editor=-y world), 180: (-x), 270: (-y editor=+y world)}
      world_dir  = (editor.x, -editor.y)                        # flip y
      rotated    = rotate world_dir by placement_angle (world CCW)
    """
    issues: list[LintIssue] = []
    pin_dir_at: dict[tuple[float, float], list[tuple[PlacedPart, str, tuple[float, float]]]] = {}
    for part in sheet._placed.values():
        if part.is_power or part.lib_id in _PASSIVES_TWO_PIN:
            continue
        try:
            local_pins = parse_pins(part.lib_id)
        except Exception:
            continue
        for pin_num, (px, py) in part.pins.items():
            info = local_pins.get(pin_num)
            if info is None:
                continue
            local_angle = info[3] % 360
            into_body = _into_body_world(local_angle, part.angle)
            k = (round(px, 3), round(py, 3))
            pin_dir_at.setdefault(k, []).append((part, pin_num, into_body))

    for (a, b) in sheet._wires:
        for endpoint, other in ((a, b), (b, a)):
            ek = (round(endpoint[0], 3), round(endpoint[1], 3))
            if ek not in pin_dir_at:
                continue
            for (part, pin_num, into_body) in pin_dir_at[ek]:
                wdx, wdy = other[0] - endpoint[0], other[1] - endpoint[1]
                # Dot product > 0 → wire heads INTO the body.
                if into_body[0] * wdx + into_body[1] * wdy > _TOL:
                    issues.append(LintIssue(
                        "WARNING", "wire_into_body",
                        f"wire from {part.refdes}:u{part.unit} pin {pin_num} at "
                        f"{endpoint} heads INTO the body (body dir {into_body}) "
                        f"toward {other} — wires must exit on pin-protrusion side",
                        [part.refdes],
                    ))
    return issues


def _into_body_world(local_angle: int, placement_angle: int) -> tuple[float, float]:
    """Compute the world-frame unit vector pointing from the pin's outer
    endpoint INTO the body, accounting for the placement rotation."""
    import math
    editor_dirs = {0: (1.0, 0.0), 90: (0.0, 1.0),
                   180: (-1.0, 0.0), 270: (0.0, -1.0)}
    ex, ey = editor_dirs.get(local_angle % 360, (0.0, 0.0))
    wx, wy = ex, -ey                          # flip y to world frame
    rad = math.radians(placement_angle)
    c, s = math.cos(rad), math.sin(rad)
    return (round(wx * c - wy * s, 3), round(wx * s + wy * c, 3))


def _check_bridged_drop_column(sheet: Sheet) -> list[LintIssue]:
    """Catch the bobcat-OWT failure mode: a long signal wire whose interior
    passes through a different part's pin coord, silently bridging two nets.

    The strict netlist validator does NOT catch this because both pin coords
    end up in the same connected component which still carries each net's
    name (the per-member name-in-set check passes).

    Heuristic: a wire whose BOTH endpoints are at distinct parts' pin coords
    (i.e. a signal connection between two parts) AND whose INTERIOR contains
    the pin coord of a THIRD part is suspect. Legitimate cap-on-rail patterns
    typically have at least one endpoint on a power-symbol pin or wire-only
    endpoint, so they don't trigger this rule.
    """
    issues: list[LintIssue] = []
    pin_at: dict[tuple[float, float], list[tuple[str, int, str]]] = {}
    power_pin_coords: set[tuple[float, float]] = set()
    for part in sheet._placed.values():
        for pin_num, (px, py) in part.pins.items():
            k = (round(px, 3), round(py, 3))
            pin_at.setdefault(k, []).append((part.refdes, part.unit, pin_num))
            if part.is_power:
                power_pin_coords.add(k)

    for (a, b) in sheet._wires:
        ak = (round(a[0], 3), round(a[1], 3))
        bk = (round(b[0], 3), round(b[1], 3))
        # Skip rail wires (one endpoint on a power symbol pin) — caps on
        # rails legitimately tap the rail interior; not a bridge.
        if ak in power_pin_coords or bk in power_pin_coords:
            continue
        a_parts = {(r, u) for (r, u, _) in pin_at.get(ak, [])}
        b_parts = {(r, u) for (r, u, _) in pin_at.get(bk, [])}
        if not a_parts or not b_parts:
            continue
        # Wire endpoints sit on pins of two different parts → "signal wire."
        if not (a_parts - b_parts) and not (b_parts - a_parts):
            continue
        endpoint_parts = a_parts | b_parts
        for (pk, occupants) in pin_at.items():
            if pk == ak or pk == bk:
                continue
            on_interior = False
            if abs(a[0] - b[0]) < _TOL:    # vertical wire
                if abs(pk[0] - a[0]) < _TOL and (
                    min(a[1], b[1]) + _TOL < pk[1] < max(a[1], b[1]) - _TOL):
                    on_interior = True
            elif abs(a[1] - b[1]) < _TOL:  # horizontal wire
                if abs(pk[1] - a[1]) < _TOL and (
                    min(a[0], b[0]) + _TOL < pk[0] < max(a[0], b[0]) - _TOL):
                    on_interior = True
            if not on_interior:
                continue
            for (r, u, pn) in occupants:
                if (r, u) in endpoint_parts:
                    continue
                issues.append(LintIssue(
                    "WARNING", "bridged_drop",
                    f"wire {a}→{b} interior passes through {r}:u{u} pin {pn} "
                    f"at {pk} — likely silent bridge between nets",
                    [r],
                ))
    return issues


def _check_label_on_body(sheet: Sheet) -> list[LintIssue]:
    """Rule 2 — labels (incl. hier/global) must not anchor inside a symbol bbox."""
    issues: list[LintIssue] = []
    parts = list(sheet._placed.values())
    bbs = [(p, _part_bbox(p)) for p in parts if not p.is_power]
    for lbl in sheet._labels:
        for (p, bb) in bbs:
            if _point_in_bbox(lbl.x, lbl.y, bb):
                issues.append(LintIssue(
                    "WARNING", "label_on_body",
                    f"{lbl.kind} '{lbl.name}' at ({lbl.x}, {lbl.y}) anchors "
                    f"inside {p.refdes}:u{p.unit}'s body",
                    [lbl.name, p.refdes],
                ))
    return issues


def _check_refval_on_body(sheet: Sheet) -> list[LintIssue]:
    """Rule 2 — a part's Reference/Value text anchor must not land inside another
    part's bbox. (The shared._ref_value_positions() helper picks them relative
    to the part's own body, so the only failure is collision with a neighbor.)"""
    issues: list[LintIssue] = []
    parts = list(sheet._placed.values())
    bbs = [(p, _part_bbox(p)) for p in parts]
    for owner in parts:
        if owner.is_power:
            continue   # power-symbol Value text is short and lives on the rail
        ref_xy, val_xy = _ref_value_anchors(owner)
        for (other, bb) in bbs:
            if other is owner:
                continue
            if other.refdes == owner.refdes:
                continue   # same multi-unit part
            for tag, (lx, ly) in (("Reference", ref_xy), ("Value", val_xy)):
                if _point_in_bbox(lx, ly, bb):
                    issues.append(LintIssue(
                        "WARNING", "refval_on_body",
                        f"{owner.refdes}:u{owner.unit} {tag} anchor "
                        f"({lx}, {ly}) lands inside {other.refdes}:u{other.unit}'s body",
                        [owner.refdes, other.refdes],
                    ))
    return issues


def _check_dense_gnd_cluster(sheet: Sheet) -> list[LintIssue]:
    """Rule 7 — many GND power symbols in a small area suggests they should be
    bussed onto one rail with a single GND terminator."""
    issues: list[LintIssue] = []
    gnds = [p for p in sheet._placed.values()
            if p.is_power and p.power_rail == "GND"]
    if len(gnds) < _GND_CLUSTER_THRESHOLD:
        return issues
    flagged: set[int] = set()
    for i, a in enumerate(gnds):
        if i in flagged:
            continue
        neighbors = [a]
        for j, b in enumerate(gnds):
            if j == i:
                continue
            if ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5 <= _GND_CLUSTER_RADIUS:
                neighbors.append(b)
        if len(neighbors) >= _GND_CLUSTER_THRESHOLD:
            for n in neighbors:
                flagged.add(gnds.index(n))
            cx = sum(n.x for n in neighbors) / len(neighbors)
            cy = sum(n.y for n in neighbors) / len(neighbors)
            issues.append(LintIssue(
                "INFO", "dense_gnd_cluster",
                f"{len(neighbors)} GND symbols within {_GND_CLUSTER_RADIUS:.0f} mm "
                f"of ({cx:.1f}, {cy:.1f}) — candidate for gnd_bus() consolidation",
                [f"{n.refdes}@({n.x},{n.y})" for n in neighbors],
            ))
    return issues


def _check_duplicate_wires(sheet: Sheet) -> list[LintIssue]:
    """Two wire segments with identical (or reversed) endpoints — redundant."""
    issues: list[LintIssue] = []
    seen: dict[tuple[tuple[float, float], tuple[float, float]], int] = {}
    for (a, b) in sheet._wires:
        a_k = (round(a[0], 3), round(a[1], 3))
        b_k = (round(b[0], 3), round(b[1], 3))
        key = tuple(sorted([a_k, b_k]))
        seen[key] = seen.get(key, 0) + 1
    for key, count in seen.items():
        if count > 1:
            issues.append(LintIssue(
                "INFO", "duplicate_wire",
                f"wire {key[0]}→{key[1]} drawn {count} times (redundant)",
                [],
            ))
    return issues


def _check_wire_overlap(sheet: Sheet) -> list[LintIssue]:
    """Parallel wires on the same axis with overlapping ranges = silent short.

    Two horizontal wires at the same y with overlapping x ranges are merged
    by KiCad into one electrical net; same for two vertical wires at the same
    x. The strict netlist validator does NOT catch this when the merged nets
    each still see their own name on the bridged component — same blind spot
    as bridged_drop. This check geometrically catches the pattern.

    Excludes exact duplicates (handled by _check_duplicate_wires).
    """
    issues: list[LintIssue] = []
    horizontals: list[tuple[float, float, float, tuple, tuple]] = []
    verticals: list[tuple[float, float, float, tuple, tuple]] = []
    for (a, b) in sheet._wires:
        if abs(a[1] - b[1]) < _TOL and abs(a[0] - b[0]) > _TOL:
            horizontals.append((round(a[1], 3), min(a[0], b[0]), max(a[0], b[0]), a, b))
        elif abs(a[0] - b[0]) < _TOL and abs(a[1] - b[1]) > _TOL:
            verticals.append((round(a[0], 3), min(a[1], b[1]), max(a[1], b[1]), a, b))

    def _emit(axis_label, c1, c2, axis_val, lo, hi, a1, b1, a2, b2):
        # Skip exact duplicates — covered by duplicate_wire.
        if c1 == c2 and abs(lo - hi) < _TOL:
            return None
        issues.append(LintIssue(
            "WARNING", "wire_overlap",
            f"{axis_label} wires overlap at {axis_label[0]}={axis_val}: "
            f"{a1}→{b1} and {a2}→{b2} share range [{lo:.2f}, {hi:.2f}] — "
            f"KiCad will electrically merge these (silent short)",
            [],
        ))

    for i, (y1, x1_lo, x1_hi, a1, b1) in enumerate(horizontals):
        for (y2, x2_lo, x2_hi, a2, b2) in horizontals[i + 1:]:
            if abs(y1 - y2) > _TOL:
                continue
            lo, hi = max(x1_lo, x2_lo), min(x1_hi, x2_hi)
            if hi - lo > _TOL:
                _emit("horizontal", (x1_lo, x1_hi), (x2_lo, x2_hi), y1, lo, hi, a1, b1, a2, b2)

    for i, (x1, y1_lo, y1_hi, a1, b1) in enumerate(verticals):
        for (x2, y2_lo, y2_hi, a2, b2) in verticals[i + 1:]:
            if abs(x1 - x2) > _TOL:
                continue
            lo, hi = max(y1_lo, y2_lo), min(y1_hi, y2_hi)
            if hi - lo > _TOL:
                _emit("vertical", (y1_lo, y1_hi), (y2_lo, y2_hi), x1, lo, hi, a1, b1, a2, b2)

    return issues


def _check_redundant_junctions(sheet: Sheet) -> list[LintIssue]:
    """A (junction) marker is required where 3+ wire *segments* meet AND the
    point isn't already a pin endpoint (KiCad auto-junctions on pins).

    Counting rule:
      - wire ENDS at P              → 1 segment
      - wire passes THROUGH P       → 2 segments (above + below the tap)

    So at the "T" of one stub hitting a passing-through rail, the rail
    contributes 2 segments and the stub contributes 1 → 3 total → junction
    is NEEDED. The check only flags junctions that fall below 3 segments and
    are not on a pin coord.
    """
    issues: list[LintIssue] = []
    # Pre-compute pin coord set so we can skip junctions placed on a pin.
    pin_coords: set[tuple[float, float]] = set()
    for part in sheet._placed.values():
        for (px, py) in part.pins.values():
            pin_coords.add((round(px, 3), round(py, 3)))

    for (jx, jy) in sheet._junctions:
        jk = (round(jx, 3), round(jy, 3))
        if jk in pin_coords:
            issues.append(LintIssue(
                "INFO", "redundant_junction",
                f"junction at ({jx}, {jy}) sits on a pin — KiCad auto-connects",
                [f"({jx},{jy})"],
            ))
            continue
        segments = 0
        for (a, b) in sheet._wires:
            at_a = abs(a[0] - jx) < _TOL and abs(a[1] - jy) < _TOL
            at_b = abs(b[0] - jx) < _TOL and abs(b[1] - jy) < _TOL
            if at_a or at_b:
                segments += 1
                continue
            # interior — counts as 2 segments meeting at P
            if abs(a[0] - b[0]) < _TOL:                   # vertical wire
                if (abs(jx - a[0]) < _TOL
                        and min(a[1], b[1]) + _TOL < jy < max(a[1], b[1]) - _TOL):
                    segments += 2
            elif abs(a[1] - b[1]) < _TOL:                 # horizontal wire
                if (abs(jy - a[1]) < _TOL
                        and min(a[0], b[0]) + _TOL < jx < max(a[0], b[0]) - _TOL):
                    segments += 2
        if segments < 3:
            issues.append(LintIssue(
                "INFO", "redundant_junction",
                f"junction at ({jx}, {jy}) has only {segments} wire segment(s) "
                f"meeting here — KiCad doesn't need a junction",
                [f"({jx},{jy})"],
            ))
    return issues


def _check_vertical_label(sheet: Sheet) -> list[LintIssue]:
    """Labels (global/hier/local) should be horizontal (angle 0 or 180), not
    vertical (90/270). Vertical labels stack illegibly and visually appear to
    have a wire flowing through them. Place horizontal labels OFF TO THE SIDE
    at the end of a horizontal wire branch."""
    issues: list[LintIssue] = []
    for lbl in sheet._labels:
        if lbl.angle in (90, 270):
            issues.append(LintIssue(
                "WARNING", "vertical_label",
                f"{lbl.kind} '{lbl.name}' at ({lbl.x}, {lbl.y}) is vertical "
                f"(angle={lbl.angle}); rotate to angle=0 or 180 and route the "
                f"wire so the label sits at a horizontal endpoint",
                [lbl.name],
            ))
    return issues


def _check_wire_through_label(sheet: Sheet) -> list[LintIssue]:
    """A label must sit at a wire ENDPOINT, never on a wire's interior. If a
    wire passes through the label anchor, the wire visually flows through the
    label box — route the label onto its own short branch instead."""
    issues: list[LintIssue] = []
    for lbl in sheet._labels:
        for (a, b) in sheet._wires:
            if abs(a[0] - b[0]) < _TOL:        # vertical wire
                if (abs(lbl.x - a[0]) < _TOL
                        and min(a[1], b[1]) + _TOL < lbl.y < max(a[1], b[1]) - _TOL):
                    issues.append(LintIssue(
                        "WARNING", "wire_through_label",
                        f"{lbl.kind} '{lbl.name}' at ({lbl.x}, {lbl.y}) sits on "
                        f"a vertical wire's interior {a}–{b}; place the label "
                        f"at an endpoint or branch it off horizontally",
                        [lbl.name],
                    ))
            elif abs(a[1] - b[1]) < _TOL:      # horizontal wire
                if (abs(lbl.y - a[1]) < _TOL
                        and min(a[0], b[0]) + _TOL < lbl.x < max(a[0], b[0]) - _TOL):
                    issues.append(LintIssue(
                        "WARNING", "wire_through_label",
                        f"{lbl.kind} '{lbl.name}' at ({lbl.x}, {lbl.y}) sits on "
                        f"a horizontal wire's interior {a}–{b}; place the label "
                        f"at an endpoint or branch it off vertically",
                        [lbl.name],
                    ))
    return issues


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

ALL_CHECKS = (
    _check_diagonal_wires,
    _check_bbox_overlap_and_spacing,
    _check_wire_through_body,
    _check_wire_into_body,
    _check_bridged_drop_column,
    _check_wire_overlap,
    _check_label_on_body,
    _check_refval_on_body,
    _check_vertical_label,
    _check_wire_through_label,
    _check_dense_gnd_cluster,
    _check_duplicate_wires,
    _check_redundant_junctions,
)


def lint(sheet: Sheet) -> list[LintIssue]:
    """Run every layout check on the sheet. Returns the flat issue list."""
    issues: list[LintIssue] = []
    for check in ALL_CHECKS:
        issues.extend(check(sheet))
    return issues


def severity_counts(issues: list[LintIssue]) -> dict[str, int]:
    out = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for i in issues:
        out[i.severity] = out.get(i.severity, 0) + 1
    return out


def print_report(sheet_name: str, issues: list[LintIssue]) -> None:
    counts = severity_counts(issues)
    if sum(counts.values()) == 0:
        print(f"[{sheet_name}] layout-lint: clean")
        return
    print(f"[{sheet_name}] layout-lint: "
          f"{counts['ERROR']} ERROR, {counts['WARNING']} WARNING, "
          f"{counts['INFO']} INFO")
    order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    for issue in sorted(issues, key=lambda i: (order[i.severity], i.rule)):
        print(f"  {issue}")
