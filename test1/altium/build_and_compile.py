"""Generate-button orchestrator: build the project, then (on a clean build) run a
real-Altium compile + cross-reference as a built-in final step.

This is what POST /api/run/generate invokes on the Altium backend, so "Generate"
is one click = build + Altium compile, with no separate button or checkbox. The
Altium compile is the slow/hang-prone part, so it runs ONCE here AFTER the build
(never inside the review auto-fix loop) and is guarded by altium_compile's own
kill-watchdog. A build failure skips the compile (nothing valid to compile).

    python -m test1.altium.build_and_compile
"""
from __future__ import annotations

import sys


def main() -> int:
    from . import build_project
    print("=" * 60)
    print("GENERATE — building the Altium project")
    print("=" * 60)
    try:
        rc = build_project.main()
    except SystemExit as e:
        rc = int(e.code or 0)
    if rc != 0:
        print("\nBuild failed — skipping Altium compile (nothing valid to compile).")
        return rc

    print("\n" + "=" * 60)
    print("GENERATE — verifying with a real-Altium compile (built-in)")
    print("=" * 60)
    # Subprocess (not in-process): altium_compile reads sys.argv for the project
    # path; a clean subprocess avoids any argv bleed-through and isolates the
    # slow/X2-driving step. Advisory — a flaky/absent Altium never fails generate.
    import subprocess
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    try:
        subprocess.run(
            [sys.executable, "-m", "test1.altium.verify.altium_compile_check"],
            cwd=str(repo_root), check=False)
    except Exception as e:            # noqa: BLE001
        print(f"Altium compile step did not complete: {type(e).__name__}: {e}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
