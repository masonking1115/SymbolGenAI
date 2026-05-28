"""Sheet container + emission primitives — Altium replacement for gen/shared.py.

`AltiumSheet` wraps an `AltiumSchDoc` and exposes the same primitive verbs the
KiCad `Sheet` did — `wire`, `junction`, `net_label`, `port`, `power_at`,
`no_connect`, `text`, `place`, `sheet_symbol` — so per-sheet builders can be
ported with minimal change. As on the KiCad side, it also accumulates
structured records (placed parts, wires, labels) so the connectivity validator
can walk the graph without re-parsing the saved file.

Coordinates are in mils throughout (see units.py). `place()` returns
{designator: (x_mil, y_mil)} just like the KiCad version returned
{pin_number: (world_x, world_y)}.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from altium_monkey import (
    AltiumSchDoc,
    ColorValue,
    LineWidth,
    PortIOType,
    PortStyle,
    SchHorizontalAlign,
    SchPointMils,
    SheetStyle,
    TextJustification,
    TextOrientation,
    SchRectMils,
    SchSheetEntryIOType,
    SchSheetSymbolType,
    SheetEntrySide,
    make_sch_file_name,
    make_sch_junction,
    make_sch_net_label,
    make_sch_no_erc,
    make_sch_port,
    make_sch_power_port,
    make_sch_sheet_entry,
    make_sch_sheet_name,
    make_sch_sheet_symbol,
    make_sch_text_string,
    make_sch_wire,
)

from .config import FONT_DEFAULT, FONT_NOTE, power_style_for
from .symbols import pin_world_coords

_BLACK = ColorValue.from_hex("#000000")
_NET_BLUE = ColorValue.from_hex("#000080")
_PWR_RED = ColorValue.from_hex("#800000")

# Rendered text height (mil) for label/note/value glyphs at FONT_DEFAULT size 10
# (~100 mil tall); used to give labels a real bounding box for overlap checks.
_TEXT_H_MIL = 90


def _text_box(x: int, y: int, text: str, align: str = "left",
              h: int = _TEXT_H_MIL) -> tuple[int, int, int, int]:
    """Axis-aligned bbox (page mils) of `text` drawn at anchor (x,y).

    `align` is the horizontal anchor: 'left' (text grows +x), 'center', or
    'right' (text grows -x). The baseline sits near (x,y); we straddle it
    vertically by h/2 so a glyph slightly above/below a wire still registers."""
    from .units import text_width_mil
    w = int(round(text_width_mil(text or "")))
    if align == "center":
        x0, x1 = x - w // 2, x + w // 2
    elif align == "right":
        x0, x1 = x - w, x
    else:
        x0, x1 = x, x + w
    return (x0, y - h // 2, x1, y + h // 2)


# --- build-time centering offset --------------------------------------------
# Builders lay out in "logical" mils starting near the origin. To CENTER a
# sheet on its page we re-run the builder with a uniform (dx,dy) offset that
# every emit/record applies, so connectivity (offset-invariant) is untouched
# but the whole drawing shifts. place() returns LOGICAL pin coords (offset
# removed) so builders can keep chaining pins into wires without double-shift.
_BUILD_OFFSET: tuple[int, int] = (0, 0)


def set_build_offset(dx: int, dy: int) -> None:
    global _BUILD_OFFSET
    _BUILD_OFFSET = (int(dx), int(dy))


# NOTE on attribute names: the structured records below use the SAME
# underscore-prefixed names the KiCad gen/validator.py duck-types on
# (`_wires`, `_junctions`, `_placed`, `_labels`). That lets us reuse the exact
# same strict connectivity validator for the Altium backend — identical logic
# == true functional parity. PlacedPart mirrors gen/shared.py's fields the
# validator reads (`pins`, `is_power`, `power_rail`, `unit`).
@dataclass
class PlacedPart:
    refdes: str
    symbol: str
    value: str
    x: int
    y: int
    pins: dict[str, tuple[int, int]]
    unit: int = 1
    is_power: bool = False
    power_rail: str = ""
    # Rendered value-Comment text box (page mils) so the linter can detect the
    # value text colliding with ports/other text (the "22uF LDO_PG 0.1uF" glob).
    comment_box: tuple[int, int, int, int] | None = None


@dataclass
class LabelRec:
    kind: str   # "net" | "port" | "power" | "text"
    name: str
    x: int
    y: int
    orientation: int | None = None   # power ports: 0/1/2/3 (=0/90/180/270 deg)
    # Rendered extent (page mils) of the drawn glyph+text. For ports this is the
    # port BODY (which extends away from the connection point) — the linter uses
    # it to catch wires impaling the body and bodies colliding with other items.
    box: tuple[int, int, int, int] | None = None
    # The underlying doc object, kept for cosmetic "text" notes so auto_fix_text
    # can reposition them after the build (other kinds carry connectivity).
    obj: object | None = None


@dataclass
class AltiumSheet:
    """Accumulates objects for a single .SchDoc plus validator-facing records."""

    name: str
    title: str = ""
    paper: str = "A4"          # sheet template size; A4 fits the per-sheet layouts
    doc: AltiumSchDoc = field(default_factory=AltiumSchDoc)

    # Validator-facing records (names match gen/validator.py's duck-typing).
    _placed: dict[tuple[str, int], PlacedPart] = field(default_factory=dict)
    _wires: list[tuple[tuple[int, int], tuple[int, int]]] = field(default_factory=list)
    _junctions: list[tuple[int, int]] = field(default_factory=list)
    _labels: list[LabelRec] = field(default_factory=list)
    _no_connects: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Capture the active build offset at construction (see set_build_offset).
        self._ox, self._oy = _BUILD_OFFSET

    def _t(self, x: int, y: int) -> tuple[int, int]:
        """Logical -> emitted (page) coords."""
        return (x + self._ox, y + self._oy)

    # --- connectivity primitives ------------------------------------------
    def wire(self, x1: int, y1: int, x2: int, y2: int) -> None:
        x1, y1 = self._t(x1, y1)
        x2, y2 = self._t(x2, y2)
        self.doc.add_object(make_sch_wire(
            points_mils=[SchPointMils.from_mils(x1, y1), SchPointMils.from_mils(x2, y2)],
            color=_NET_BLUE, line_width=LineWidth.SMALL,
        ))
        self._wires.append(((x1, y1), (x2, y2)))

    def junction(self, x: int, y: int) -> None:
        """Record a junction. NOTE: real Altium DROPS altium_monkey junction
        objects on load (upstream write bug — see verify/FINDINGS.md), so this
        dot is cosmetic in altium_monkey's SVG only. Electrical connectivity in
        Altium relies on T-intersections (auto-junctioned) + pin endpoints; the
        layout must never route a 4-way crossing. We still record the junction
        for our own validator's connectivity graph."""
        x, y = self._t(x, y)
        self.doc.add_object(make_sch_junction(location_mils=SchPointMils.from_mils(x, y)))
        self._junctions.append((x, y))

    def net_label(self, net: str, x: int, y: int,
                  orientation: TextOrientation = TextOrientation.DEGREES_0) -> None:
        x, y = self._t(x, y)
        self.doc.add_object(make_sch_net_label(
            location_mils=SchPointMils.from_mils(x, y), text=net,
            font=FONT_DEFAULT, color=_NET_BLUE, orientation=orientation,
            justification=TextJustification.BOTTOM_LEFT, mirrored=False,
        ))
        self._labels.append(LabelRec("net", net, x, y,
                                     box=_text_box(x, y, net, "left")))

    def port(self, name: str, x: int, y: int, io: PortIOType = PortIOType.BIDIRECTIONAL,
             style: PortStyle = PortStyle.LEFT_RIGHT, width_mils: int = 700,
             side: str = "auto") -> None:
        """Off-sheet signal port — the Altium analogue of hier_label/global_label.

        (x,y) is the CONNECTION point (where the wire terminates). altium_monkey
        always draws the port body extending +x from its anchor, so `side`
        controls where the body sits relative to the wire:
          side="right"  body extends RIGHT from (x,y) — use when the wire
                        arrives from the LEFT (port on the right margin).
          side="left"   body sits in the LEFT margin, ending its right edge at
                        (x,y) — use when the wire arrives from the RIGHT (port
                        on the left margin). Anchored at (x-width) so the body
                        never gets impaled by the incoming wire.
          side="auto"   (default) inspect the wire(s) already drawn to this
                        connection point and put the body on the side AWAY from
                        the net, so the wire never crosses the body. This is why
                        callers draw the wire BEFORE the port.
        The connectivity record (LabelRec) stays at (x,y) either way, so the
        validator binds the wire endpoint regardless of which side the body is
        drawn on."""
        x, y = self._t(x, y)
        if side == "auto":
            side = self._infer_port_side(x, y)
        anchor_x = x - width_mils if side == "left" else x
        self.doc.add_object(make_sch_port(
            location_mils=SchPointMils.from_mils(anchor_x, y), name=name,
            width_mils=width_mils, height_mils=100, io_type=io, style=style,
            font=FONT_DEFAULT, border_color=_BLACK,
            fill_color=ColorValue.from_hex("#D9EAD3"), text_color=_BLACK,
            alignment=SchHorizontalAlign.CENTER,
            border_width=LineWidth.SMALL, auto_size=False, show_net_name=True,
        ))
        body = (anchor_x, y - 50, anchor_x + width_mils, y + 50)
        self._labels.append(LabelRec("port", name, x, y, box=body))

    def _infer_port_side(self, x: int, y: int, tol: float = 1.0) -> str:
        """Pick the body side ('left'/'right') that keeps the connecting net off
        the port body. Looks at horizontal wires already drawn through this
        connection point: if more wire material lies to the RIGHT of x, the body
        belongs on the LEFT, and vice-versa. Vertical-only / no wire -> 'right'.
        Coords are EMITTED (page) mils, matching self._wires."""
        right = left = 0.0
        for (a, b) in self._wires:
            if abs(a[1] - y) < tol and abs(b[1] - y) < tol:        # horizontal at y
                lo, hi = min(a[0], b[0]), max(a[0], b[0])
                if lo - tol <= x <= hi + tol:
                    right += max(0.0, hi - x)
                    left += max(0.0, x - lo)
        if right > left + tol:
            return "left"
        return "right"

    def _vwire_through(self, x: int, y: int, tol: float = 1.0) -> bool:
        """True if a vertical wire at column x passes THROUGH row y (material both
        above and below) — i.e. a glyph at (x,y) would straddle that net."""
        up = down = False
        for (a, b) in self._wires:
            if abs(a[0] - x) < tol and abs(b[0] - x) < tol:
                lo, hi = min(a[1], b[1]), max(a[1], b[1])
                if lo - tol <= y <= hi + tol:
                    up |= hi > y + tol
                    down |= lo < y - tol
        return up and down

    def _power_stub(self, x: int, y: int, length: int = 200, tol: float = 1.0) -> int:
        """Generation rule helper: if the net runs vertically THROUGH (x,y),
        return a signed horizontal offset to a clear column so the power glyph
        can sit beside the net and terminate a short stub instead of straddling.
        A candidate column is clear only if (a) no vertical wire passes through it
        at row y (else the glyph would just straddle THAT net) and (b) the stub
        path along row y is free of an existing horizontal wire. Returns 0 when
        the point already terminates the net or no clear column is found. Coords
        are EMITTED (page) mils, matching self._wires."""
        if not self._vwire_through(x, y, tol):
            return 0

        def stub_path_clear(nx: int) -> bool:
            x0, x1 = min(x, nx), max(x, nx)
            for (a, b) in self._wires:
                if abs(a[1] - y) < tol and abs(b[1] - y) < tol:    # horizontal at row y
                    lo, hi = min(a[0], b[0]), max(a[0], b[0])
                    if lo < x1 - tol and hi > x0 + tol:
                        return False
            return True

        for dx in (length, -length, 2 * length, -2 * length, 3 * length, -3 * length):
            if not self._vwire_through(x + dx, y, tol) and stub_path_clear(x + dx):
                return dx
        return 0

    def power_at(self, rail: str, x: int, y: int,
                 orientation: TextOrientation | None = None,
                 stub: int = 0) -> tuple[int, int]:
        """Place a power port for `rail` at (x,y). Returns the NET pin coord (==(x,y)).

        Orientation follows schematic convention so the glyph reads right in
        Altium: GROUND-family ports point DOWN (270°, bar hangs below the wire)
        and supply rails point UP (90°, arrow rises above the wire). Pass an
        explicit `orientation` to override.

        Generation rule (no-straddle): a power glyph must sit OFF TO THE SIDE of
        the net and terminate it, never straddle a net that runs through it. Pass
        a signed `stub` (mils) to branch a short horizontal stub and place the
        glyph at its end; the electrical net point stays (x,y) so connectivity is
        unaffected. Callers usually leave this 0 — straddles are auto-corrected
        post-build by `auto_fix_power()` (which can see the FULL wire set, unlike
        this call). Caught by layout_lint.power_straddles_net."""
        is_gnd = "GND" in rail.upper()
        if orientation is None:
            orientation = (TextOrientation.DEGREES_270 if is_gnd
                           else TextOrientation.DEGREES_90)
        if stub:
            self.wire(x, y, x + stub, y)        # stub ties the glyph to the net
            x, y = x + stub, y                  # glyph sits at the stub end
        sx, sy = self._t(x, y)
        obj = make_sch_power_port(
            location_mils=SchPointMils.from_mils(sx, sy), text=rail,
            style=power_style_for(rail), font=FONT_DEFAULT, color=_PWR_RED,
            orientation=orientation, show_net_name=not is_gnd,
        )
        self.doc.add_object(obj)
        # Power text renders alongside the glyph. GND (down) hangs its bar below
        # with no net name; rails (up) show the rail name above. Box the name's
        # extent above/below the hot-spot so the linter sees collisions.
        ori = int(getattr(orientation, "value", orientation))
        pbox = self._power_box(sx, sy, rail, is_gnd)
        self._labels.append(LabelRec("power", rail, sx, sy,
                                     orientation=ori, box=pbox, obj=obj))
        return (x, y)

    @staticmethod
    def _power_box(sx: int, sy: int, rail: str, is_gnd: bool) -> tuple:
        if is_gnd:
            return (sx - 110, sy - 190, sx + 110, sy)        # glyph bar below
        return _text_box(sx, sy + 140, rail, "center")       # rail name above

    def auto_fix_power(self, length: int = 200) -> list[tuple[str, int]]:
        """Auto-correct power/rail glyphs that STRADDLE a net (the net runs
        vertically through the connection point) by branching a short horizontal
        stub to a clear side and relocating the glyph to the stub end, so it
        sits beside the net and terminates the stub. Runs post-build (full wire
        set known), mirroring auto_fix_text. The electrical net point is
        untouched (the stub re-ties the glyph), so connectivity is unchanged.
        Returns (rail, dx) for each relocation. See layout_lint.power_straddles_net."""
        changes: list[tuple[str, int]] = []
        for lb in [l for l in self._labels if l.kind == "power" and l.obj is not None]:
            dx = self._power_stub(lb.x, lb.y, length)
            if not dx:
                continue
            nx = lb.x + dx
            self.doc.add_object(make_sch_wire(
                points_mils=[SchPointMils.from_mils(lb.x, lb.y),
                             SchPointMils.from_mils(nx, lb.y)],
                color=_NET_BLUE, line_width=LineWidth.SMALL))
            self._wires.append(((lb.x, lb.y), (nx, lb.y)))
            # power-port location is a CoordPoint (not SchPointMils) — rebuild it
            # via the same type so to_geometry's .x/.y stay valid.
            lb.obj.location = lb.obj.location.from_mils(nx, lb.y)
            lb.box = self._power_box(nx, lb.y, lb.name, "GND" in lb.name.upper())
            lb.x = nx
            changes.append((lb.name, dx))
        return changes

    def no_connect(self, x: int, y: int) -> None:
        x, y = self._t(x, y)
        self.doc.add_object(make_sch_no_erc(location_mils=SchPointMils.from_mils(x, y)))
        self._no_connects.append((x, y))

    def text(self, body: str, x: int, y: int) -> None:
        x, y = self._t(x, y)
        obj = make_sch_text_string(
            location_mils=SchPointMils.from_mils(x, y), text=body,
            font=FONT_NOTE, color=_BLACK,
        )
        self.doc.add_object(obj)
        # Recorded (kind "text") so centering accounts for note extents and the
        # linter can flag a note overlapping other items / running off the page.
        # The obj handle lets auto_fix_text nudge the note clear of collisions.
        self._labels.append(LabelRec("text", body, x, y,
                                     box=_text_box(x, y, body, "left"), obj=obj))

    def auto_fix_text(self, max_steps: int = 40, step: int = 100) -> list[tuple[str, int]]:
        """Auto-correct cosmetic note overlaps: nudge each drawn ``text`` note
        vertically until its box clears every other label, value-comment, and
        component body. ONLY notes move — they carry no connectivity — so ports,
        power symbols, net labels and component bodies stay as fixed anchors and
        the netlist is untouched. Structural lint issues (shorts, wires through
        bodies, off-grid) are NOT auto-fixed here; they remain surfaced by the
        linter because resolving them means re-routing. Returns the list of
        ``(note_text, dy)`` nudges applied (empty when nothing overlapped)."""
        def _ov(a, b):
            return bool(a and b) and not (
                a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])

        def _body_boxes():
            out = []
            for p in self._placed.values():
                if p.is_power or not p.pins:
                    continue
                xs = [c[0] for c in p.pins.values()]
                ys = [c[1] for c in p.pins.values()]
                out.append((min(xs) - 100, min(ys) - 100,
                            max(xs) + 100, max(ys) + 100))
            return out

        bodies = _body_boxes()
        changes: list[tuple[str, int]] = []
        for note in [l for l in self._labels
                     if l.kind == "text" and l.obj is not None and l.box]:
            obstacles = [l.box for l in self._labels if l is not note and l.box]
            obstacles += [p.comment_box for p in self._placed.values() if p.comment_box]
            obstacles += bodies
            if not any(_ov(note.box, b) for b in obstacles):
                continue
            bx0, by0, bx1, by1 = note.box
            placed = None
            for d in range(step, step * max_steps + 1, step):
                for dy in (-d, d):           # prefer nudging DOWN first
                    cand = (bx0, by0 + dy, bx1, by1 + dy)
                    if not any(_ov(cand, b) for b in obstacles):
                        placed = (dy, cand)
                        break
                if placed:
                    break
            if placed:
                dy, cand = placed
                note.y += dy
                note.box = cand
                note.obj.location = SchPointMils.from_mils(note.x, note.y)
                changes.append((note.name, dy))
        return changes

    # --- placement --------------------------------------------------------
    def place(self, lib_path: Path, symbol: str, ref: str, value: str,
              x: int, y: int, orientation: int = 0, unit: int = 1
              ) -> dict[str, tuple[int, int]]:
        """Place a SchLib symbol (part `unit` for multi-unit), record it, and
        return {designator: (x,y)} for that unit's pins IN LOGICAL coords (the
        page offset is removed on the way out so builders can keep chaining pin
        coords into wires without double-applying the centering shift)."""
        px0, py0 = self._t(x, y)
        comp = self.doc.add_component_from_library(
            library_path=lib_path, symbol_name=symbol, designator=ref,
            x=px0, y=py0, orientation=orientation, part_id=unit,
        )
        pins = pin_world_coords(comp)                  # emitted (page) coords
        # Show the value as the component Comment (the Altium-native value
        # field, like KiCad's Value), placed clear of the body just above the
        # top pin so it doesn't collide. Library metadata parameters (Footprint/
        # Datasheet/MPN/...) stay hidden — only designator + comment are drawn.
        top = max((py for (_px, py) in pins.values()), default=py0)
        cy = top + 150
        try:
            comp.set_comment(value, x=0, y=(top - py0) + 150, visible=True)
            comp.set_comment_style(font_name="Arial", font_size=10)
        except Exception:
            pass
        # Comment renders centered at (px0, top+150); box it for overlap checks.
        cbox = _text_box(px0, cy, value, "center") if value else None
        self._placed[(ref, unit)] = PlacedPart(ref, symbol, value, px0, py0, pins,
                                               unit=unit, comment_box=cbox)
        return {d: (cx - self._ox, cy - self._oy) for d, (cx, cy) in pins.items()}

    def place_from_netlist(self, lib_path: Path, libid_to_symbol: dict[str, str],
                           netlist, refdes: str, x: int, y: int,
                           orientation: int = 0, unit: int = 1
                           ) -> dict[str, tuple[int, int]]:
        """Place a part whose symbol/value come from the YAML netlist, mapping
        its KiCad lib_id to an authored SchLib symbol name. For multi-unit parts
        call once per declared unit. Mirrors gen.shared.place_from_netlist."""
        p = netlist.parts[refdes]
        symbol = libid_to_symbol.get(p.lib_id)
        if symbol is None:
            raise ValueError(f"no SchLib symbol mapped for lib_id {p.lib_id!r} (refdes {refdes})")
        if unit not in p.units:
            raise ValueError(f"{refdes} unit {unit} not in declared units {p.units}")
        return self.place(lib_path, symbol, p.refdes, p.value, x, y, orientation, unit=unit)

    def pins_of(self, ref: str, unit: int = 1) -> dict[str, tuple[int, int]]:
        """{designator: (x,y)} in LOGICAL coords for an already-placed part —
        the same space place() returns, so builders can re-fetch an earlier
        part's pins and feed them into wire()/place() without double-applying
        the centering offset (self._placed stores PAGE coords for the linter)."""
        p = self._placed[(ref, unit)].pins
        return {d: (x - self._ox, y - self._oy) for d, (x, y) in p.items()}

    # --- cluster helper (ports gen.shared.gnd_bus) ------------------------
    def gnd_bus(self, pins: list[tuple[int, int]], rail_x: int,
                gnd_extra: int = 200) -> tuple[int, int]:
        """Bus a column of pins to a vertical GND rail ending in ONE GND port.

        Altium Y grows UP, so the GND symbol sits BELOW the lowest pin
        (smallest y). Interior taps get junctions (cosmetic) and, more to the
        point, are T-intersections the validator + Altium treat as connected.
        """
        if not pins:
            raise ValueError("gnd_bus: pins list is empty")
        sp = sorted(pins, key=lambda p: p[1])     # ascending y
        bot_y, top_y = sp[0][1], sp[-1][1]
        for (px, py) in sp:
            self.wire(px, py, rail_x, py)
        if len(sp) >= 2:
            self.wire(rail_x, top_y, rail_x, bot_y)
        for (_, py) in sp[1:-1]:
            self.junction(rail_x, py)
        gnd_y = bot_y - gnd_extra
        self.wire(rail_x, bot_y, rail_x, gnd_y)
        self.power_at("GND", rail_x, gnd_y)
        return (rail_x, gnd_y)

    # --- hierarchical sheet symbol (root sheet) ---------------------------
    def sheet_symbol(self, child_name: str, title: str, x: int, y: int,
                     w: int, h: int,
                     entries: list[tuple[str, str, str, int]]) -> None:
        """Embed a child sheet as a hierarchical sheet symbol at (x,y) size wxh.

        entries: list of (name, io, side, distance_from_top_mil) where io is
        'input'|'output'|'bidirectional' (child's perspective) and side is
        'left'|'right'. The Altium analogue of gen.shared.sheet_block.
        """
        x, y = self._t(x, y)
        sym = make_sch_sheet_symbol(
            bounds_mils=SchRectMils.from_corners_mils(x, y, x + w, y + h),
            border_width=LineWidth.MEDIUM, border_color=_BLACK,
            fill_color=ColorValue.from_hex("#F0E6C8"), fill_background=True,
            symbol_type=SchSheetSymbolType.NORMAL, design_item_id=child_name)
        io_map = {"input": SchSheetEntryIOType.INPUT,
                  "output": SchSheetEntryIOType.OUTPUT,
                  "bidirectional": SchSheetEntryIOType.BIDIRECTIONAL}
        side_map = {"left": SheetEntrySide.LEFT, "right": SheetEntrySide.RIGHT}
        for (name, io, side, dist) in entries:
            sym.add_entry(make_sch_sheet_entry(
                name=name, side=side_map[side],
                io_type=io_map.get(io, SchSheetEntryIOType.UNSPECIFIED),
                distance_from_top_mils=dist))
        sym.set_sheet_name(make_sch_sheet_name(
            text=title, location_mils=SchPointMils.from_mils(x, y + h + 60),
            font=FONT_DEFAULT, color=_BLACK))
        sym.set_file_name(make_sch_file_name(
            text=f"{child_name}.SchDoc",
            location_mils=SchPointMils.from_mils(x, y - 160),
            font=FONT_NOTE, color=_BLACK))
        self.doc.add_object(sym)

    # A-series landscape usable sizes in mil (preferred order, smallest first).
    _PAPER_MIL = {"A4": (11690, 8270), "A3": (16535, 11690),
                  "A2": (23390, 16535), "A1": (33110, 23390), "A0": (46810, 33110)}

    def content_bbox(self) -> tuple[int, int, int, int]:
        """(min_x, min_y, max_x, max_y) over all placed pins, wires, labels."""
        xs, ys = [], []
        for p in self._placed.values():
            for (px, py) in p.pins.values():
                xs.append(px); ys.append(py)
        for (a, b) in self._wires:
            xs += [a[0], b[0]]; ys += [a[1], b[1]]
        for lb in self._labels:
            xs.append(lb.x); ys.append(lb.y)
        if not xs:
            return (0, 0, 0, 0)
        return (min(xs), min(ys), max(xs), max(ys))

    def _fit_paper(self, margin: int = 600) -> str:
        """Pick the preferred paper if the content fits, else the smallest
        standard size that does. Guarantees the layout fits the sheet cleanly."""
        _minx, _miny, maxx, maxy = self.content_bbox()
        need_w, need_h = maxx + margin, maxy + margin
        order = ["A4", "A3", "A2", "A1", "A0"]
        start = order.index(self.paper) if self.paper in order else 0
        for name in order[start:]:
            w, h = self._PAPER_MIL[name]
            if need_w <= w and need_h <= h:
                return name
        return "A0"

    def _apply_paper(self) -> None:
        """Set the document sheet template. Prefers `self.paper` (default A4);
        auto-upgrades to the smallest A-series size that contains the layout so
        nothing overflows the frame. Altium's default is style 5 (A, too small)."""
        chosen = self._fit_paper()
        try:
            self.doc.sheet.sheet_style = int(getattr(SheetStyle, chosen))
            self.doc.sheet.use_custom_sheet = False
        except Exception:
            pass
        self._chosen_paper = chosen

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_paper()
        self.doc.save(path)
        return path

    def render_svg(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_paper()
        path.write_text(self.doc.to_svg(), encoding="utf-8")
        return path
