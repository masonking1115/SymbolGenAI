"""Sim-scenario cache + freshness.

The flow is context-first: the agent reads datasheets + design_requirements.md
+ the current design (netlist/*.yaml), determines the parameters to apply, and
ONLY THEN runs the sim. This module holds the *scenario* half of that decision
— the operating point(s) and load the sim should use — keyed by block. (Device
model params live in dscache.) The deck builders read it so the sim runs at the
real operating point, e.g. the LDO at the Bobcat 0.6-1.0V rails rather than an
arbitrary default.

Cache-gating: a block's scenario is re-derived by the agent only when it's
missing or STALE — i.e. when a datasheet, the requirements, or the block's
netlist sheet has changed since the scenario was written. Otherwise the sim
runs immediately on the cached scenario.

Entry shape (written by the sim_setup agent):
  {
    "ldo_rail": {
      "operating_points_V": [0.6, 1.0],   # Bobcat core rails (VDDD/VDDA)
      "primary_vout_set_V": 1.0,           # default single-point setpoint
      "load_note": "VDDIO from VADJ 1.2-3.3V via switch; worst case at 1.2V",
      "rationale": "...",
      "sources": ["design_requirements.md", "tps7a84a.pdf", "power.yaml"],
      "needs_clarification": null
    }
  }
"""

from __future__ import annotations

import json
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / "cache"
CONFIG_FILE = CACHE_DIR / "sim_config.json"

ROOT = Path(__file__).resolve().parents[1]          # test1/
NETLIST_DIR = ROOT / "netlist"
REQUIREMENTS = ROOT / "design_requirements.md"
PARTS_DIR = ROOT / "Parts Library"


def load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def entry(block_id: str) -> dict:
    return load().get(block_id, {})


def primary_vout(block_id: str, default: float = 1.8) -> float:
    e = entry(block_id)
    v = e.get("primary_vout_set_V")
    return float(v) if isinstance(v, (int, float)) else default


def operating_points(block_id: str, default: list[float] | None = None) -> list[float]:
    e = entry(block_id)
    pts = e.get("operating_points_V")
    return [float(x) for x in pts] if isinstance(pts, list) and pts else (default or [])


def _input_paths(block: dict) -> list[Path]:
    """Files whose change should invalidate the cached scenario: the
    requirements, the block's netlist sheet, and the block's datasheets."""
    paths = [REQUIREMENTS]
    sheet = (block.get("sheet") or "").strip()
    if sheet.endswith(".yaml"):
        paths.append(NETLIST_DIR / sheet)
    for d in block.get("datasheets", []) or []:
        paths.append(PARTS_DIR / d.get("mpn", "") / d.get("file", ""))
    return [p for p in paths if p.exists()]


def is_fresh(block: dict) -> bool:
    """A block's scenario is fresh iff it exists in the cache AND no input
    (requirements / netlist sheet / datasheet) is newer than the cache file."""
    bid = block.get("id")
    if not bid or bid not in load():
        return False
    if not CONFIG_FILE.exists():
        return False
    cfg_mtime = CONFIG_FILE.stat().st_mtime
    newest_input = max((p.stat().st_mtime for p in _input_paths(block)), default=0.0)
    return cfg_mtime >= newest_input
