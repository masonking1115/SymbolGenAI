"""Assemble the whole design into an Altium project (.PrjPcb).

Builds + validates all 6 child sheets, builds the root sheet, then writes a
test1.PrjPcb referencing the root + children so the design opens as one project
in Altium and cross-sheet nets resolve. This is the top-level entry point for
the Altium backend (the analogue of running gen_schematic.py for KiCad).
"""

from __future__ import annotations

import json
import re
import time
import traceback

from altium_monkey.altium_prjpcb import AltiumPrjPcb

from ..gen.validator import validate as _revalidate_post_autofix
from .build_all import BUILDERS
from .build_symbols import get_library
from .config import OUT_DIR, RENDER_DIR
from .layout_lint import counts as lint_counts
from .layout_lint import lint, lint_library, lint_netlist_semantics
from .shared import build_centered

PROJECT = "test1"


def _schdoc_unique_id(schdoc) -> str | None:
    """The SchDoc's own FileHeader UniqueID, so the .PrjPcb references it by its
    real identity (not a freshly-invented one). Read straight from the file bytes;
    the FileHeader UniqueID is the first such token."""
    try:
        m = re.search(rb"\|UniqueID=([A-Za-z0-9]+)", schdoc.read_bytes())
        return m.group(1).decode() if m else None
    except OSError:
        return None


def _component_pin_counts(doc) -> list[int]:
    """Pins per component in a parsed AltiumSchDoc (component children that are
    pins). A component with 0 pins is a 'ghost' — the signature of a serialization
    desync (a malformed record upstream drops the child pins of the components
    written after it)."""
    counts = []
    for comp in doc.components:
        kids = getattr(comp, "children", None) or []
        counts.append(sum(1 for k in kids if type(k).__name__ == "AltiumSchPin"))
    return counts


def verify_saved_sheet(sheet, path) -> list[str]:
    """Build-time FAIL-SAFE: re-read the just-saved .SchDoc and assert it
    serialized soundly for Altium. Catches the whole class of save-time corruption
    that is INVISIBLE in memory and only surfaces as an Altium connectivity-compile
    hang on project open (root cause history: auto_fix_text wrote a note location
    as a raw SchPointMils, desyncing serialization so two components were written
    pinless — Altium then infinite-loops compiling nets to a pinless component).

    Two checks:
      (1) no component serialized as a ghost (0 pins) — the direct hang trigger;
      (2) reloaded component count + total pin count match the in-memory sheet —
          catches any record drop, not just pins-on-a-component.

    Returns a list of error strings (empty = OK). Caller fails the build on any.
    """
    from altium_monkey.altium_schdoc import AltiumSchDoc

    errs: list[str] = []
    try:
        reloaded = AltiumSchDoc(path)
    except Exception as e:  # noqa: BLE001
        return [f"save-integrity: re-reading {path.name} failed: {type(e).__name__}: {e}"]

    reloaded_pins = _component_pin_counts(reloaded)
    ghosts = sum(1 for n in reloaded_pins if n == 0)
    if ghosts:
        errs.append(
            f"save-integrity: {ghosts} pinless 'ghost' component(s) in saved "
            f"{path.name} — serialization desync (would hang Altium on open). "
            f"Likely a record written with a wrong-typed field (e.g. .location as "
            f"SchPointMils instead of .to_coord_point()); check the most recent "
            f"doc-mutating pass (auto_fix_*).")

    # Cross-check counts against the in-memory sheet (what we intended to write).
    try:
        mem_comps = len(list(sheet.doc.components))
        mem_pins = sum(_component_pin_counts(sheet.doc))
        re_comps = len(reloaded_pins)
        re_pins = sum(reloaded_pins)
        if re_comps != mem_comps:
            errs.append(f"save-integrity: {path.name} component count {re_comps} "
                        f"!= in-memory {mem_comps} (records dropped on save).")
        if re_pins != mem_pins:
            errs.append(f"save-integrity: {path.name} total pin count {re_pins} "
                        f"!= in-memory {mem_pins} (pin records dropped on save).")
    except Exception as e:  # noqa: BLE001
        errs.append(f"save-integrity: count cross-check on {path.name} errored: "
                    f"{type(e).__name__}: {e}")
    return errs


# Centering now lives in shared.build_centered so EVERY build path (this driver
# AND every standalone build_<sheet> main()) centers identically — one source of
# truth. _build_centered kept as a thin alias for any external callers.
_build_centered = build_centered


def _source_hash() -> str:
    """A short content hash of the design SOURCE (netlist YAML + altium builders).
    Stamped into lint.json so a consumer (the GUI, the loop) can tell whether the
    report reflects the CURRENT sources or is stale (sources edited since the
    build). Single source of truth for "is this build up to date" (A4)."""
    import hashlib
    from .config import OUT_DIR as _OUT
    proj = _OUT.parent.parent              # test1/
    h = hashlib.sha256()
    files = []
    for d in (proj / "netlist", proj / "altium"):
        if d.exists():
            for pat in ("*.yaml", "*.yml", "build_*.py"):
                files.extend(sorted(d.glob(pat)))
    for p in sorted(files):
        try:
            h.update(p.name.encode())
            h.update(p.read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:16]


def _write_lint_json(status: str, counts: dict, report: list) -> None:
    """The ONE place lint.json is written — stamps it with build time + a source
    hash so every reader (GUI tabs, the loop's gate) shares one authoritative
    record of the current build's status (A4)."""
    (OUT_DIR / "lint.json").write_text(json.dumps({
        "generated_at": time.time(),
        "source_hash": _source_hash(),
        "status": status,
        "counts": counts,
        "issues": report,
    }, indent=2))


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
    # A component the design references but has no committed .SchLib (a "new
    # component not in the library") used to crash build_library() with an opaque
    # FileNotFoundError mid-build. Instead, surface it as a clean, actionable
    # library ERROR listing the MPNs that need a symbol (authored via
    # author_symbol / installed from Ultra Librarian, or sourced by the review's
    # missing-part flow) — and fail the build gracefully.
    from .build_symbols import missing_symbols
    missing = missing_symbols()
    if missing:
        msg = ("component(s) referenced by the design have no symbol in the "
               "library — author/install them (test1.altium.author_symbol or an "
               "Ultra Librarian .SchLib), or let the review's missing-part flow "
               "source them: " + ", ".join(missing))
        report.append({"sheet": "library", "severity": "ERROR",
                       "rule": "missing_symbol", "message": msg,
                       "refs": list(missing)})
        print(f"symbol library: MISSING {len(missing)} symbol(s): {', '.join(missing)}")
        # Persist the report (same shape as the normal exit path) so the GUI lint
        # panel + the closed loop see the missing-symbol ERROR, then fail cleanly.
        _write_lint_json("fail", {"ERROR": 1, "WARNING": 0, "INFO": 0}, report)
        print("\nFAILURES: missing symbols — see report")
        return 1
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
            sheet_path = OUT_DIR / f"{name}.SchDoc"
            s.save(sheet_path)
            # FAIL-SAFE: re-read the saved file and verify it serialized soundly
            # for Altium (no pinless 'ghost' components; counts match in-memory).
            # A serialization desync here is INVISIBLE in memory and otherwise only
            # surfaces as an Altium connectivity-compile hang on project open.
            integrity_errs = verify_saved_sheet(s, sheet_path)
            if integrity_errs:
                fails += 1
                for msg in integrity_errs:
                    print(f"{name:12} {'-':6} {'-':14} SAVE-INTEGRITY FAIL: {msg}")
                    report.append({"sheet": name, "severity": "ERROR",
                                   "rule": "save_integrity", "message": msg, "refs": []})
            s.render_svg(RENDER_DIR / f"{name}.svg")
            docs.append(f"{name}.SchDoc")
            issues = lint(s)
            # Advisory semantic intent checks over the netlist (WARNING/INFO only;
            # never ERROR → never fails the build). Surfaces decoupling/DNP-path
            # gaps the connectivity+layout gates can't see.
            try:
                issues = issues + lint_netlist_semantics(nl)
            except Exception as _sem_e:
                print(f"             ~ (semantic checks skipped: {_sem_e})")
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

    # FLAT (non-hierarchical) project: the 6 child sheets are siblings and
    # cross-sheet signals connect by matching PORT name (the design already wires
    # every inter-sheet net as same-named ports on two/three sheets). There is
    # intentionally NO root sheet. Net scope is pinned to Flat (ports global) so
    # Altium does not fall back to "Automatic", which would pick Hierarchical and
    # require sheet symbols/entries. (build_root.py is retained but no longer
    # built.) NOTE: the Altium project-open hang we chased was NOT actually the
    # hierarchy — root cause was a serialization bug (see the save_integrity gate
    # above + verify/altium_open_check.py); flat is kept because the design is
    # genuinely flat-by-port and it's the simpler/correct model.
    prj = AltiumPrjPcb.create_minimal(PROJECT)
    prj.config.set("Design", "NetIdentifierScope", "Flat")
    for d in docs:
        prj.add_document(d, unique_id=_schdoc_unique_id(OUT_DIR / d))
    prj_path = OUT_DIR / f"{PROJECT}.PrjPcb"
    prj.save(prj_path)

    # Persist the structured lint report so the GUI checklist reflects THIS
    # build (survives a backend restart; includes INFO, which the console table
    # only counts). Read by GET /api/lint.
    sev = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for r in report:
        sev[r["severity"]] = sev.get(r["severity"], 0) + 1
    _write_lint_json("fail" if fails else "pass", sev, report)

    print("-" * 36)
    print(f"wrote {prj_path.name} (flat) referencing {len(docs)} child sheets")
    print("FAILURES: " + (str(fails) if fails else "none"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
