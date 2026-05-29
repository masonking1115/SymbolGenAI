"""ngspice subprocess wrapper.

Takes a SPICE deck as text, runs `ngspice -b` in a temp dir, captures
stdout/stderr and any `wrdata` CSV traces, and returns a parsed Result
object the agent can consume.

We use the CLI rather than PySpice because:
  - PySpice has been semi-orphaned and adds an install hurdle.
  - The deck is just text, which is easy for an LLM to read/write/critique.
  - ngspice's `wrdata` command produces plain ASCII columns — trivial to
    parse with numpy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


# Resolve the ngspice binary. Prefer PATH; allow an explicit override via the
# NGSPICE env var (set it on machines where ngspice isn't on PATH). The previous
# hardcoded "/opt/homebrew/bin/ngspice" fallback was a Mac/dev-era assumption and
# is gone — this project runs on Windows now. If ngspice can't be found, run_deck
# returns a clear "ngspice not found" result instead of raising a raw OSError.
NGSPICE = os.environ.get("NGSPICE") or shutil.which("ngspice")


@dataclass
class Trace:
    name: str
    columns: list[str]
    data: np.ndarray  # shape (N, len(columns))

    def col(self, name: str) -> np.ndarray:
        return self.data[:, self.columns.index(name)]


@dataclass
class SimResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    deck: str
    traces: dict[str, Trace] = field(default_factory=dict)
    op_point: dict[str, float] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "returncode": self.returncode,
            "op_point": self.op_point,
            "traces": {
                name: {
                    "columns": t.columns,
                    "samples": int(t.data.shape[0]),
                    "t_start": float(t.data[0, 0]) if t.data.size else None,
                    "t_end": float(t.data[-1, 0]) if t.data.size else None,
                }
                for name, t in self.traces.items()
            },
        }


def _parse_op_point(stdout: str) -> dict[str, float]:
    """Extract `.print op` style lines.

    ngspice's batch op-point output looks like:
        v(+3v3)             =  3.300000e+00
        v(+vddio)           =  1.800000e+00
    We greedily pull anything matching `name = number`.
    """
    out: dict[str, float] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        left, _, right = line.partition("=")
        name = left.strip().lower()
        if not name or " " in name:
            continue
        try:
            out[name] = float(right.strip().split()[0])
        except (ValueError, IndexError):
            continue
    return out


def _read_wrdata(path: Path, columns: list[str]) -> Trace:
    """ngspice wrdata writes whitespace-separated columns.

    With N vectors, layout is: t v1 t v2 t v3 ... (time repeated per vector).
    We pull the first time column and every non-time column.
    """
    raw = np.loadtxt(path)
    if raw.ndim == 1:
        raw = raw.reshape(1, -1)
    if raw.size == 0:
        return Trace(path.stem, ["time"] + columns, raw)
    # Time is column 0, then for each vector the data is at odd indices,
    # with time repeated at even indices. Collapse to [time, v1, v2, ...].
    t = raw[:, 0:1]
    vals = raw[:, 1::2]  # skip repeated time columns
    data = np.hstack([t, vals])
    return Trace(path.stem, ["time"] + columns, data)


def run_deck(deck: str, *, trace_specs: dict[str, list[str]] | None = None,
             workdir: Path | None = None) -> SimResult:
    """Run a SPICE deck via `ngspice -b`.

    deck:         the full deck text (including .control / .end sections).
    trace_specs:  optional mapping of {output_filename_stem: [vector_name, ...]}
                  matching `wrdata <stem>.dat <vectors>` commands in the deck.
                  We read each .dat file after the run and attach to result.
    """
    if not NGSPICE:
        # ngspice isn't installed / not on PATH. Surface a clear, structured
        # result rather than a raw FileNotFoundError so the service layer can
        # report "simulator unavailable" cleanly. Install ngspice and put it on
        # PATH (or set the NGSPICE env var to its full path) to run sims.
        return SimResult(
            ok=False, returncode=-1, stdout="", deck=deck,
            stderr="ngspice not found: install it and add to PATH, or set the "
                   "NGSPICE environment variable to the ngspice executable.",
        )

    cleanup = False
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="sim_"))
        cleanup = True
    workdir.mkdir(parents=True, exist_ok=True)

    deck_path = workdir / "deck.cir"
    # Explicit UTF-8: deck text can contain non-ASCII (e.g. "→" in a block
    # description copied into a header comment). Windows' default cp1252 would
    # raise UnicodeEncodeError on write. ngspice ignores comment bytes, so UTF-8
    # is safe for the engine.
    deck_path.write_text(deck, encoding="utf-8")

    proc = subprocess.run(
        [NGSPICE, "-b", "-o", str(workdir / "log.txt"), str(deck_path)],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=60,
    )

    stdout = proc.stdout
    if (workdir / "log.txt").exists():
        stdout = (workdir / "log.txt").read_text(encoding="utf-8", errors="replace") + "\n" + stdout

    traces: dict[str, Trace] = {}
    if trace_specs:
        for stem, cols in trace_specs.items():
            p = workdir / f"{stem}.dat"
            if p.exists():
                try:
                    traces[stem] = _read_wrdata(p, cols)
                except Exception as exc:
                    # Keep the failure visible but don't abort the whole run.
                    traces[stem] = Trace(stem, ["time"] + cols,
                                         np.zeros((0, 1 + len(cols))))
                    stdout += f"\n[runner] failed to parse {p}: {exc}\n"

    result = SimResult(
        ok=proc.returncode == 0 and "error" not in stdout.lower()[:5000],
        returncode=proc.returncode,
        stdout=stdout,
        stderr=proc.stderr,
        deck=deck,
        traces=traces,
        op_point=_parse_op_point(stdout),
    )

    if cleanup and result.ok:
        # Keep on failure for debugging; clean on success.
        shutil.rmtree(workdir, ignore_errors=True)

    return result
