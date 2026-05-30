"""Per-sheet refdes-level netlist diff for the closed-loop Diff & Accept view.

Compares snapshot netlists vs current netlists, returns {added, removed, changed}
per sheet with refdes anchor positions (for the SVG overlay highlights)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Make sure `test1.altium.refdes_locations` resolves when diff.py is imported by
# anything other than the running backend (e.g. ad-hoc smoke tests with the
# venv's bare interpreter). The backend already sets sys.path up; this is a
# belt-and-braces guard for direct imports.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from .closed_loop import OUT_DIR, NETLIST_DIR, SNAPSHOT_ROOT  # noqa: E402


# Sensible default viewBox if a sheet hasn't been rendered yet (matches the
# Altium drawable-frame width/height in mils used elsewhere).
_DEFAULT_VIEWBOX = "0 0 15500 11100"


@dataclass
class SheetDiff:
    viewBox: str           # SVG viewBox, e.g. "0 0 15500 11100"
    added:   dict[str, dict]   # refdes -> {x, y, kind: "added"}
    removed: dict[str, dict]
    changed: dict[str, dict]   # refdes -> {x, y, kind: "changed", from_value, to_value}


def _load_netlist(path: Path) -> dict:
    if not path.exists():
        return {"parts": {}, "nets": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _refdes_anchors(svg_path: Path) -> dict:
    """Use the existing test1/altium/refdes_locations.extract to get
    {"viewBox": [w, h], "refdes": {refdes: {x, y}}} from a rendered SVG.

    Returns the raw extractor shape (viewBox as a [w, h] list); callers are
    responsible for converting to the SVG-attribute string form."""
    from test1.altium import refdes_locations
    try:
        return refdes_locations.extract(svg_path)
    except Exception:
        return {"viewBox": [0.0, 0.0], "refdes": {}}


def _viewbox_str(anchors: dict) -> str:
    """Convert the extractor's {"viewBox": [w, h]} shape into an SVG attribute
    string "0 0 W H". Falls back to a sane default for missing/empty viewBoxes
    so the frontend overlay always has a valid coordinate system."""
    vb = anchors.get("viewBox") or [0, 0]
    try:
        w = int(float(vb[0]))
        h = int(float(vb[1]))
    except (TypeError, ValueError, IndexError):
        w = h = 0
    if w <= 0 or h <= 0:
        return _DEFAULT_VIEWBOX
    return f"0 0 {w} {h}"


def compute_loop_diff(loop_id: str) -> dict[str, dict]:
    """Returns {sheet_stem: {viewBox, added, removed, changed, count}} per sheet."""
    snapshot_dir = SNAPSHOT_ROOT / loop_id
    if not snapshot_dir.exists():
        return {}

    out: dict[str, dict] = {}
    snap_netlist_dir = snapshot_dir / "netlist"
    cur_render_dir = OUT_DIR / "render"

    if not snap_netlist_dir.exists():
        return {}

    for snap_yaml in snap_netlist_dir.glob("*.yaml"):
        sheet = snap_yaml.stem
        cur_yaml = NETLIST_DIR / f"{sheet}.yaml"

        snap_nl = _load_netlist(snap_yaml)
        cur_nl = _load_netlist(cur_yaml)
        snap_parts = snap_nl.get("parts", {}) or {}
        cur_parts = cur_nl.get("parts", {}) or {}

        added: dict[str, dict] = {}
        removed: dict[str, dict] = {}
        changed: dict[str, dict] = {}

        # Refdes-level adds/removes
        for rd in cur_parts.keys() - snap_parts.keys():
            added[rd] = {"kind": "added"}
        for rd in snap_parts.keys() - cur_parts.keys():
            removed[rd] = {"kind": "removed"}
        # Value changes on the same refdes
        for rd in cur_parts.keys() & snap_parts.keys():
            cur_v = (cur_parts[rd] or {}).get("value", "")
            snap_v = (snap_parts[rd] or {}).get("value", "")
            if cur_v != snap_v:
                changed[rd] = {
                    "kind": "changed",
                    "from_value": snap_v,
                    "to_value": cur_v,
                }

        # Get anchor positions from the rendered SVGs (current + snapshot).
        cur_svg = cur_render_dir / f"{sheet}.svg"
        snap_svg = snapshot_dir / "render" / f"{sheet}.svg"
        cur_anchors = _refdes_anchors(cur_svg) if cur_svg.exists() else {"viewBox": [0.0, 0.0], "refdes": {}}
        snap_anchors = _refdes_anchors(snap_svg) if snap_svg.exists() else {"viewBox": [0.0, 0.0], "refdes": {}}

        cur_refdes = cur_anchors.get("refdes") or {}
        snap_refdes = snap_anchors.get("refdes") or {}

        # Annotate ADDED with current positions (they exist only in current).
        for rd, body in added.items():
            anchor = cur_refdes.get(rd, {})
            body.update(x=anchor.get("x", 0), y=anchor.get("y", 0))

        # Annotate REMOVED with snapshot positions (they exist only in snapshot).
        for rd, body in removed.items():
            anchor = snap_refdes.get(rd, {})
            body.update(x=anchor.get("x", 0), y=anchor.get("y", 0))

        # Annotate CHANGED with BOTH anchors: the part exists in both renders and
        # may sit at different coordinates if the layout moved between snapshot and
        # now. x/y = CURRENT position (the AFTER pane, drawn on the current image);
        # from_x/from_y = SNAPSHOT position (the BEFORE pane, drawn on the snapshot
        # image). Using current coords on the snapshot image is what mis-placed the
        # BEFORE (red) box; each pane must use the anchor that matches ITS image.
        for rd, body in changed.items():
            cur_a = cur_refdes.get(rd, {})
            snap_a = snap_refdes.get(rd, {})
            body.update(
                x=cur_a.get("x", 0), y=cur_a.get("y", 0),
                from_x=snap_a.get("x", cur_a.get("x", 0)),
                from_y=snap_a.get("y", cur_a.get("y", 0)),
            )

        # ---- Is this diff meaningfully RENDERABLE as a visual box overlay? ----
        # A surgical change (a few parts moved/added) renders fine. But a
        # substantial change — a re-layout, or many adds/removes — makes the
        # box-overlay misleading (boxes everywhere, or anchors that don't map
        # between the two renders). In that case we DON'T force a visual diff;
        # we flag it so the UI shows "change too substantial to show visually,
        # see the value table / rebuilt schematic" instead of a noisy overlay.
        n_changed = len(added) + len(removed) + len(changed)
        n_parts = max(len(cur_parts), len(snap_parts), 1)
        # Changed parts missing an anchor in either render can't be boxed.
        unanchored = sum(
            1 for rd in changed
            if rd not in cur_refdes or rd not in snap_refdes
        ) + sum(1 for rd in added if rd not in cur_refdes) \
          + sum(1 for rd in removed if rd not in snap_refdes)
        # viewBox shift: a big change in drawable size ⇒ re-layout ⇒ coords don't map.
        def _vb_area(a: dict) -> float:
            vb = a.get("viewBox") or [0, 0]
            try:
                return float(vb[0]) * float(vb[1])
            except (TypeError, ValueError, IndexError):
                return 0.0
        cur_area, snap_area = _vb_area(cur_anchors), _vb_area(snap_anchors)
        vb_ratio = (max(cur_area, snap_area) / min(cur_area, snap_area)
                    if min(cur_area, snap_area) > 0 else 1.0)

        renderable = True
        reason = ""
        if n_changed == 0:
            renderable = True  # nothing to draw, but that's fine (no overlay needed)
        elif n_changed > 0.5 * n_parts and n_changed >= 6:
            renderable = False
            reason = (f"{n_changed} of {n_parts} parts changed — too substantial "
                      f"to show as a visual diff; see the value table / rebuilt schematic.")
        elif unanchored >= 3 and unanchored >= 0.5 * n_changed:
            renderable = False
            reason = (f"{unanchored} changed parts can't be located in both renders "
                      f"(symbols moved/renamed) — visual diff would be misleading.")
        elif vb_ratio >= 1.4:
            renderable = False
            reason = ("sheet was re-laid-out (drawing area changed substantially) — "
                      "box positions don't map between versions; compare the schematics directly.")

        out[sheet] = {
            "viewBox": _viewbox_str(cur_anchors),
            "snapViewBox": _viewbox_str(snap_anchors),
            "added": added,
            "removed": removed,
            "changed": changed,
            "count": n_changed,
            "renderable": renderable,
            "unrenderable_reason": reason,
        }
    return out
