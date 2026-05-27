"""Assemble the whole design into an Altium project (.PrjPcb).

Builds + validates all 6 child sheets, builds the root sheet, then writes a
test1.PrjPcb referencing the root + children so the design opens as one project
in Altium and cross-sheet nets resolve. This is the top-level entry point for
the Altium backend (the analogue of running gen_schematic.py for KiCad).
"""

from __future__ import annotations

from altium_monkey.altium_prjpcb import AltiumPrjPcb

from .build_all import BUILDERS
from .build_root import build_root
from .build_symbols import get_library
from .config import OUT_DIR, RENDER_DIR
from .layout_lint import counts as lint_counts
from .layout_lint import lint, lint_library
from .shared import set_build_offset

PROJECT = "test1"

_LOW_MARGIN = 300    # keep content >= this from the left/bottom edge
_HIGH_MARGIN = 600   # ... and >= this from the right/top edge (matches _fit_paper)


def _axis_shift(lo: float, hi: float, page: int) -> int:
    """Grid-snapped shift that centers [lo,hi] in [0,page], clamped so the span
    stays within [_LOW_MARGIN, page-_HIGH_MARGIN] (never overflow / upgrade)."""
    target = (page - (hi - lo)) / 2 - lo            # shift that centers
    d = max(_LOW_MARGIN - lo, min((page - _HIGH_MARGIN) - hi, target))
    return int(round(d / 100) * 100)


def _build_centered(fn):
    """Build a sheet, then re-build it shifted so its content is centered on the
    chosen page (connectivity is offset-invariant, so this is layout-only)."""
    set_build_offset(0, 0)
    s, nl = fn()
    paper = getattr(s, "_chosen_paper", None) or s._fit_paper()
    W, H = s._PAPER_MIL.get(paper, (0, 0))
    minx, miny, maxx, maxy = s.content_bbox()
    if not W or maxx <= minx:
        return s, nl
    dx, dy = _axis_shift(minx, maxx, W), _axis_shift(miny, maxy, H)
    if dx == 0 and dy == 0:
        return s, nl
    set_build_offset(dx, dy)
    try:
        s, nl = fn()
    finally:
        set_build_offset(0, 0)
    return s, nl


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Symbol-library quality gate (pin-name fit, etc.) before placing.
    lib_path, _ = get_library()
    lib_issues = lint_library(lib_path)
    if lib_issues:
        print("symbol library:")
        for i in lib_issues:
            print(f"  {i}")
    else:
        print("symbol library: clean")

    print(f"{'sheet':12} {'paper':6} {'lint (E/W/I)':14} status")
    print("-" * 44)
    fails = 0
    docs: list[str] = []

    # Child sheets: builder validates connectivity; layout linter checks
    # quality (overlaps, shorts, off-grid, containment). ERROR fails the build.
    for name, fn in BUILDERS.items():
        try:
            s, _nl = _build_centered(fn)
            # Auto-correct cosmetic note overlaps before linting/saving (notes
            # carry no connectivity, so this never changes the netlist).
            autofixes = s.auto_fix_text()
            s.save(OUT_DIR / f"{name}.SchDoc")
            s.render_svg(RENDER_DIR / f"{name}.svg")
            docs.append(f"{name}.SchDoc")
            issues = lint(s)
            c = lint_counts(issues)
            lint_str = f"{c['ERROR']}/{c['WARNING']}/{c['INFO']}"
            status = "OK" if c["ERROR"] == 0 else "LINT ERROR"
            if c["ERROR"]:
                fails += 1
            print(f"{name:12} {getattr(s, '_chosen_paper', '?'):6} {lint_str:14} {status}")
            # Show what the auto-fixer corrected this run.
            for note, dy in autofixes:
                short = note if len(note) <= 40 else note[:37] + "..."
                print(f"             ~ auto-fixed note {short!r} (moved {dy:+d} mil)")
            # Surface ERROR/WARNING detail so every generation shows what to fix.
            order = {"ERROR": 0, "WARNING": 1}
            for i in sorted((x for x in issues if x.severity in order),
                            key=lambda x: order[x.severity]):
                print(f"             - {i}")
        except Exception as e:
            fails += 1
            print(f"{name:12} {'-':6} {'-':14} FAIL: {type(e).__name__}: {e}")

    # Root sheet (hierarchy only — no netlist to validate).
    root = build_root()
    root.save(OUT_DIR / "root.SchDoc")
    root.render_svg(RENDER_DIR / "root.svg")
    print(f"{'root':12} {getattr(root, '_chosen_paper', '?'):6} OK")

    # Project file: root first, then children.
    prj = AltiumPrjPcb.create_minimal(PROJECT)
    prj.add_document("root.SchDoc")
    for d in docs:
        prj.add_document(d)
    prj_path = OUT_DIR / f"{PROJECT}.PrjPcb"
    prj.save(prj_path)

    print("-" * 36)
    print(f"wrote {prj_path.name} referencing root + {len(docs)} child sheets")
    print("FAILURES: " + (str(fails) if fails else "none"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
