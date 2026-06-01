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
PARAM_FILE = CACHE_DIR / "datasheet_params.json"

ROOT = Path(__file__).resolve().parents[1]          # test1/
NETLIST_DIR = ROOT / "netlist"
REQUIREMENTS = ROOT / "design_requirements.md"
PARTS_DIR = ROOT / "Parts Library"


def load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
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


def _clarification_blocks(entry: dict) -> bool:
    """True iff this part's clarification should force setup to re-run.

    A `needs_clarification` note blocks freshness — EXCEPT when it has been
    acknowledged (`clarification_acknowledged: true`). Acknowledgement means the
    open question has been reviewed and the cached value accepted as a documented
    assumption — typically because the answer is NOT obtainable from any available
    source (e.g. the Bobcat deck states no per-rail load current, so the LDO/load-
    switch params keep their estimate-based note rather than a cited number).
    Without this escape hatch an unresolvable clarification loops forever: the
    block is never fresh → setup re-runs every time → the agent sees params are
    already present and writes nothing → the flag never clears. The note itself is
    PRESERVED (the assumption stays visible); only its freshness-gating drops."""
    if not entry.get("needs_clarification"):
        return False
    return not entry.get("clarification_acknowledged")


def _cached_param_mpns() -> set[str]:
    """MPNs present in the device-param cache whose clarification (if any) does
    not block — i.e. either no open clarification, or an acknowledged one.

    Setup OWNS datasheet → param extraction (the interpret pass no longer reads
    datasheets), so a block isn't fully set up until every one of its parts has
    params here. Mirror agent.dscache_cached_mpns without importing the GUI."""
    try:
        data = json.loads(PARAM_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    return {
        m for m, e in data.items()
        if isinstance(e, dict) and not _clarification_blocks(e)
    }


def _params_complete(block: dict) -> bool:
    """True iff every part this block uses that ACTUALLY feeds an ngspice model
    param has device params cached. A block lists datasheets for all its parts,
    but only some (the ones with a param_map mapper) inject datasheet numbers
    into the deck — the rest are behavioral stubs or netlist-valued (caps, the
    DUT load). Requiring those unmapped parts would make e.g. the PDN blocks
    (zero mapped parts) never fresh. A missing MAPPED part, though, means the
    sim silently falls back to model defaults, so setup must run."""
    from . import param_map  # peer sim module; avoids a GUI import here

    mapped = set(param_map._MAP)
    needed = {
        d.get("mpn") for d in (block.get("datasheets") or [])
        if d.get("mpn") in mapped
    }
    return needed.issubset(_cached_param_mpns())


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
    """A block is fresh (setup can be skipped) iff:
      - its scenario exists in the cache AND no input (requirements / netlist
        sheet / datasheet) is newer than the scenario cache file, AND
      - every part it uses already has device params cached.
    The second clause is what makes setup the sole owner of param extraction:
    if a part (e.g. a newly added op-amp) has no cached params, setup runs and
    fills it rather than letting the sim fall back to model defaults."""
    bid = block.get("id")
    if not bid or bid not in load():
        return False
    if not CONFIG_FILE.exists():
        return False
    if not _params_complete(block):
        return False
    cfg_mtime = CONFIG_FILE.stat().st_mtime
    newest_input = max((p.stat().st_mtime for p in _input_paths(block)), default=0.0)
    return cfg_mtime >= newest_input


# ---- cache clearing (per block) --------------------------------------------
# Backs the GUI "reset/clear cache" button. Scoped to one block so clearing one
# sim doesn't blow away every block's hard-won datasheet extraction.

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 + ensure_ascii=False: the setup agent writes Unicode into the cache
    # (µ, ±, ≈, smart quotes from datasheet prose). Pin the encoding so the file
    # round-trips and the readers above (which now also read UTF-8) never hit the
    # Windows-default cp1252 codec, which can't decode those bytes.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_scenario(block_id: str) -> bool:
    """Drop a block's operating-point scenario from sim_config.json. Next Run
    re-derives it (setup agent). Returns True if an entry was removed."""
    data = load()
    if block_id not in data:
        return False
    del data[block_id]
    _write_json(CONFIG_FILE, data)
    return True


def clear_params(mpns: list[str]) -> list[str]:
    """Drop the given MPNs from datasheet_params.json (a block's device parts).
    Next Run re-extracts them from the datasheets (setup agent). Returns the
    MPNs actually removed."""
    try:
        data = json.loads(PARAM_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError, UnicodeDecodeError):
        return []
    removed = [m for m in mpns if m in data]
    for m in removed:
        del data[m]
    if removed:
        _write_json(PARAM_FILE, data)
    return removed


def clear_iter_counters(block_id: str) -> int:
    """Delete the per-(block,sim_type) re-sim counter files (.iter_<block>_*).
    Returns the count removed."""
    n = 0
    for p in CACHE_DIR.glob(f".iter_{block_id}_*.json"):
        try:
            p.unlink(); n += 1
        except OSError:
            pass
    return n
