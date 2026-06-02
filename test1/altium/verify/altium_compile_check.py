"""Opt-in Altium compile cross-check (the GUI 'compile in Altium' action).

Runs, in sequence, against the current out/test1.PrjPcb:
  1) altium_compile  -- headless real-Altium project compile (DM_Compile) ->
     violation COUNT (writes out/verify/compile_result.txt). Slow (~30-90s) and
     drives X2.EXE; this is why it is OPT-IN and never auto-runs in the loop.
  2) compile_crossref -- cross-reference Altium's exported Messages
     (out/MessageListReport.html, if present) against our out/lint.json, mapping
     Altium error CLASSES to our lint rules and flagging any unmapped class as a
     candidate new rule.

Streamed to the GUI via the same subprocess/SSE plumbing as generate/review.
The compile count is authoritative-but-coarse; the per-class cross-reference needs
a Messages export (Altium's IViolation text isn't reachable headlessly), so step 2
reports "no export found" gracefully if MessageListReport.html is stale/absent and
tells the user how to refresh it.

    python -m test1.altium.verify.altium_compile_check
"""
from __future__ import annotations

import sys

from . import altium_compile, compile_crossref


def main() -> int:
    print("=" * 60)
    print("STEP 1/2 — headless Altium project compile (violation count)")
    print("=" * 60)
    try:
        rc1 = altium_compile.main()
    except SystemExit as e:        # the module calls sys.exit
        rc1 = int(e.code or 0)
    except Exception as e:         # noqa: BLE001
        print(f"compile step errored: {type(e).__name__}: {e}")
        rc1 = 1

    print()
    print("=" * 60)
    print("STEP 2/2 — cross-reference Altium messages vs our lint")
    print("=" * 60)
    try:
        rc2 = compile_crossref.main()
    except SystemExit as e:
        rc2 = int(e.code or 0)
    except Exception as e:         # noqa: BLE001
        print(f"cross-reference step errored: {type(e).__name__}: {e}")
        rc2 = 1
    if rc2 == 2:
        # crossref returns 2 when no Messages export is present — not a hard fail.
        print("\n(Cross-reference skipped: no fresh Messages export. The compile "
              "count above is still valid. To enable per-class cross-reference, in "
              "Altium: right-click the Messages panel after Validate > Export to "
              "out/MessageListReport.html, then re-run.)")
        rc2 = 0

    # Overall: the compile step's success is what gates this action.
    return rc1


if __name__ == "__main__":
    sys.exit(main())
