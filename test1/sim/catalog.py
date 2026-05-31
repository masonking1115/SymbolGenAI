"""Loader for the curated block catalog (blocks.yaml).

This is the single source of truth the deck builders, the (future) backend
endpoint, and the frontend tab all read from. It resolves a block's
boundary assignments for a given sim type by merging the block's base
boundaries with that sim type's `boundary_overrides`.

Keeping the merge here (rather than in each deck builder) is what makes
blocks.yaml an actual driver instead of parallel documentation.
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
from pathlib import Path

import yaml

CATALOG_PATH = Path(__file__).resolve().parent / "blocks.yaml"

# ---- Ephemeral run-time parameter overrides --------------------------------
# A manual "tune before running" layer the GUI can set per-run. It is held in a
# ContextVar (NOT written to blocks.yaml) so it lives ONLY for the duration of
# the run() call that sets it, is isolated per request/thread, and vanishes
# entirely on a backend restart — i.e. these edits are never persisted. Shape:
#   { net_name: { param_key: value, ... }, ... }
# Highest-priority layer in resolve_boundaries (wins over the catalog base and
# the per-sim-type boundary_overrides).
_RUN_OVERRIDES: contextvars.ContextVar[dict[str, dict]] = contextvars.ContextVar(
    "sim_run_overrides", default={}
)


@contextlib.contextmanager
def run_overrides(overrides: dict[str, dict] | None):
    """Apply ephemeral boundary-param overrides for the duration of the block.

    Use around a single run_block_sim() call so resolve_boundaries() (called by
    the deck builders) picks them up. Nothing is written to disk; the override
    is reset when the block exits, so it can't leak into a later request.
    """
    token = _RUN_OVERRIDES.set(overrides or {})
    try:
        yield
    finally:
        _RUN_OVERRIDES.reset(token)


def load_catalog() -> list[dict]:
    data = yaml.safe_load(CATALOG_PATH.read_text())
    return data.get("blocks", [])


def get_block(block_id: str) -> dict:
    for b in load_catalog():
        if b.get("id") == block_id:
            return b
    raise KeyError(f"no block {block_id!r} in {CATALOG_PATH.name}")


def sim_types(block_id: str) -> list[str]:
    return [s["type"] for s in get_block(block_id).get("sim_types", [])]


def _sim_entry(block: dict, sim_type: str) -> dict:
    for s in block.get("sim_types", []):
        if s["type"] == sim_type:
            return s
    raise KeyError(
        f"block {block.get('id')!r} has no sim type {sim_type!r}; "
        f"has {[s['type'] for s in block.get('sim_types', [])]}"
    )


def _coerce(v):
    """Coerce numeric-looking strings to float.

    YAML 1.1 only resolves a scalar to float if the mantissa has a decimal
    point, so `100e-6` parses as the string "100e-6". Rather than make every
    catalog author remember to write `100.0e-6`, normalize here: anything
    float() accepts becomes a float; everything else (node names like "V3V3")
    is left untouched.
    """
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return v
    return v


def resolve_boundaries(block_id: str, sim_type: str) -> dict[str, dict]:
    """Return {net_name: {stub, params}} with per-sim-type overrides merged in.

    Base params come from block['boundaries'][net]['params']; the sim type's
    boundary_overrides[net] dict is shallow-merged on top, and finally any
    ephemeral run-time overrides (run_overrides(), the GUI's "tune before run")
    are merged last so they win over both. The stub *shape* is fixed by the base
    entry and never overridden.
    """
    block = get_block(block_id)
    base = copy.deepcopy(block.get("boundaries", {}))
    overrides = _sim_entry(block, sim_type).get("boundary_overrides", {}) or {}
    run_ov = _RUN_OVERRIDES.get() or {}

    resolved: dict[str, dict] = {}
    for net, spec in base.items():
        params = dict(spec.get("params", {}))
        params.update(overrides.get(net, {}))
        params.update(run_ov.get(net, {}))          # ephemeral, highest priority
        params = {k: _coerce(v) for k, v in params.items()}
        resolved[net] = {"stub": spec["stub"], "params": params}
    return resolved


def pass_criterion(block_id: str, sim_type: str) -> str | None:
    return _sim_entry(get_block(block_id), sim_type).get("pass")
