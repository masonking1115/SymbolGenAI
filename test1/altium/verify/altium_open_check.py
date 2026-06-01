"""Automated 'does Altium open this project without the connectivity-compile
hang' checker. No manual clicking, no DelphiScript-side watchdog (the hang is IN
the compile, so the watchdog must live OUTSIDE Altium).

Per project:
  1. launch X2.EXE opening the .PrjPcb directly (the open triggers Altium's
     connectivity compile),
  2. from Python, poll X2's CPU. The compile spins one core at ~100%. If CPU
     drops to idle (<IDLE_PCT) and STAYS there -> the project compiled/opened
     cleanly. If CPU is still pegged at HANG_AFTER_S -> it's hung.
  3. kill X2 and report CLEAN / HANG / NO_PROC, then move to the next project.

CPU is the verdict because it is the one signal we have proven reliable here
(pegged+flat-memory = infinite compile; drop-to-idle = done).

Usage:
    python -m test1.altium.verify.altium_open_check <proj1.PrjPcb> [proj2 ...]
    python -m test1.altium.verify.altium_open_check --incr      # sweep out/incr/step*.PrjPcb in order
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "test1" / "altium" / "out"

# Tunables
WARMUP_S = 30        # ignore the first N s (app+project load always busy)
WINDOW_S = 120       # max time to wait for a verdict after warmup
SAMPLE_S = 4
IDLE_PCT = 15        # core% below this = idle
IDLE_HITS = 3        # consecutive idle samples => CLEAN
HANG_PCT = 70        # core% above this sustained => still compiling


def find_x2() -> Path | None:
    base = Path(r"C:\Program Files\Altium")
    return next(iter(sorted(base.glob("AD*/X2.EXE"), reverse=True)), None) if base.exists() else None


def _kill_all_x2() -> None:
    import psutil  # type: ignore
    for p in psutil.process_iter(["name"]):
        try:
            n = (p.info["name"] or "").lower()
            if n in ("x2.exe", "cefsharp.browsersubprocess.exe"):
                p.kill()
        except Exception:
            pass


def _x2_procs():
    import psutil  # type: ignore
    out = []
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == "x2.exe":
                out.append(p)
        except Exception:
            pass
    return out


def check_one(x2: Path, prj: Path) -> str:
    import psutil  # type: ignore
    _kill_all_x2()
    time.sleep(2)
    # Launch X2 opening the project directly.
    subprocess.Popen([str(x2), str(prj)])
    # find the X2 process
    proc = None
    for _ in range(20):
        ps = _x2_procs()
        if ps:
            proc = ps[0]
            break
        time.sleep(1)
    if proc is None:
        return "NO_PROC"

    t0 = time.time()
    # warmup
    time.sleep(WARMUP_S)
    idle_run = 0
    last = None
    while time.time() - t0 < WARMUP_S + WINDOW_S:
        try:
            pct = proc.cpu_percent(interval=SAMPLE_S)  # % of ONE core (psutil)
        except psutil.NoSuchProcess:
            return "EXITED"
        el = int(time.time() - t0)
        if pct != last:
            print(f"      [{el}s] cpu={pct:.0f}%")
            last = pct
        if pct < IDLE_PCT:
            idle_run += 1
            if idle_run >= IDLE_HITS:
                return "CLEAN"
        else:
            idle_run = 0
    # window expired still busy
    return "HANG"


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__); return 2
    # Stop at the first HANG only in --incr mode (cumulative sweep). For an
    # explicit project list, test ALL of them (we want the full CLEAN/HANG map).
    stop_on_hang = (args == ["--incr"])
    if args == ["--incr"]:
        projs = sorted((OUT / "incr").glob("step*.PrjPcb"),
                       key=lambda p: int(p.stem.split("_")[0][4:]))
    else:
        projs = [Path(a) for a in args]

    x2 = find_x2()
    if x2 is None:
        print("FAIL: X2.EXE not found"); return 2
    try:
        import psutil  # noqa: F401
    except ImportError:
        print("FAIL: psutil not installed in the venv (pip install psutil)"); return 2

    print(f"Altium: {x2}\nChecking {len(projs)} project(s). "
          f"warmup={WARMUP_S}s window={WINDOW_S}s\n")
    results = []
    for prj in projs:
        if not prj.exists():
            print(f"  {prj.name:24} MISSING"); results.append((prj.name, "MISSING")); continue
        print(f"  {prj.name} ...")
        verdict = check_one(x2, prj)
        print(f"  {prj.name:24} -> {verdict}\n")
        results.append((prj.name, verdict))
        if verdict == "HANG" and stop_on_hang:
            print(f"  >>> first HANG at {prj.name} <<<")
            break
    _kill_all_x2()

    print("\n=== summary ===")
    for name, v in results:
        print(f"  {name:24} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
