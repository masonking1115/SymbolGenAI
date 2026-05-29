"""Assemble the whole design into an Altium project (.PrjPcb).

Builds + validates all 6 child sheets, builds the root sheet, then writes a
test1.PrjPcb referencing the root + children so the design opens as one project
in Altium and cross-sheet nets resolve. This is the top-level entry point for
the Altium backend (the analogue of running gen_schematic.py for KiCad).
"""

from __future__ import annotations

import json
import time
import traceback

from altium_monkey.altium_prjpcb import AltiumPrjPcb

from ..gen.validator import validate as _revalidate_post_autofix
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
    # Every lint issue from THIS build, attributed to its sheet, so the GUI can
    # render a checklist that reflects the most recent build (see _write_report).
    report: list[dict] = []

    def _record(sheet: str, issues) -> None:
        for i in issues:
            report.append({"sheet": sheet, "severity": i.severity,
                           "rule": i.rule, "message": i.message,
                           "refs": list(i.refs)})

    # Symbol-library quality gate (pin-name fit, etc.) before placing.
    lib_path, _ = get_library()
    lib_issues = lint_library(lib_path)
    _record("library", lib_issues)
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
            s, nl = _build_centered(fn)
            # Auto-correct cosmetic note overlaps before linting/saving (notes
            # carry no connectivity, so this never changes the netlist).
            autofixes = s.auto_fix_text()
            # auto_fix_power emits new wires (relocation stubs) AFTER the
            # in-builder validator has already run. Those stubs can create
            # T-shorts that violate connectivity (a stub endpoint landing on
            # an unrelated wire's interior auto-junctions in Altium). Re-run
            # the connectivity validator against the post-autofix wire set to
            # catch this — the U41.OUTB/+3V3 short Voltai flagged on
            # 2026-05-28 was missed in the original build precisely because
            # validation ran too early.
            powerfixes = s.auto_fix_power()
            # Then correct any rail/GND glyph sitting on the WRONG side of its
            # stub (net on its pointing side) — relocates it to a clear stub that
            # points off the net. Also emits stubs, so fold into the revalidation.
            powerfixes += s.auto_fix_power_stub_side()
            if powerfixes:
                _revalidate_post_autofix(s, nl)
            s.save(OUT_DIR / f"{name}.SchDoc")
            s.render_svg(RENDER_DIR / f"{name}.svg")
            docs.append(f"{name}.SchDoc")
            issues = lint(s)
            _record(name, issues)
            c = lint_counts(issues)
            lint_str = f"{c['ERROR']}/{c['WARNING']}/{c['INFO']}"
            status = "OK" if c["ERROR"] == 0 else "LINT ERROR"
            if c["ERROR"]:
                fails += 1
            print(f"{name:12} {getattr(s, '_chosen_paper', '?'):6} {lint_str:14} {status}")
            # Show what the auto-fixers corrected this run.
            for note, dy in autofixes:
                short = note if len(note) <= 40 else note[:37] + "..."
                # Encode safely for Windows console (cp1252)
                short = short.encode('cp1252', errors='replace').decode('cp1252')
                print(f"             ~ auto-fixed note {short!r} (moved {dy:+d} mil)")
            for rail, dx in powerfixes:
                print(f"             ~ off-set power {rail!r} beside the net (moved {dx:+d} mil)")
            # Surface ERROR/WARNING detail so every generation shows what to fix.
            order = {"ERROR": 0, "WARNING": 1}
            for i in sorted((x for x in issues if x.severity in order),
                            key=lambda x: order[x.severity]):
                print(f"             - {i}")
        except Exception as e:
            fails += 1
            traceback.print_exc()
            report.append({"sheet": name, "severity": "ERROR",
                           "rule": "build_failed", "message": f"{type(e).__name__}: {e}",
                           "refs": []})
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

    # Persist the structured lint report so the GUI checklist reflects THIS
    # build (survives a backend restart; includes INFO, which the console table
    # only counts). Read by GET /api/lint.
    sev = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for r in report:
        sev[r["severity"]] = sev.get(r["severity"], 0) + 1
    (OUT_DIR / "lint.json").write_text(json.dumps({
        "generated_at": time.time(),
        "status": "fail" if fails else "pass",
        "counts": sev,
        "issues": report,
    }, indent=2))

    print("-" * 36)
    print(f"wrote {prj_path.name} referencing root + {len(docs)} child sheets")
    print("FAILURES: " + (str(fails) if fails else "none"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
