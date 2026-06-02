"""Small helpers extracted from closed_loop.py for unit-testability."""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "altium" / "out"


def _read_lint_failures() -> dict:
    """Read out/lint.json into the shape agent._build_fix_prompt expects.

    lint.json is a DICT: {generated_at, source_hash, status, counts, issues:[...]}
    where each issue is {severity, rule, sheet, message}. _build_fix_prompt reads
    `issues`/`counts`/`status` (and optional `exit`/`tail`), so we pass that dict
    straight through. (Previously this iterated lint.json as if it were a LIST and
    bucketed by sheet into {sheet: [...]}, which both crashed on the dict AND
    produced a shape with no `issues` key — so the lint_fix prompt saw zero
    structured issues. Returning the dict as-is fixes the handoff.)"""
    p = OUT_DIR / "lint.json"
    if not p.exists():
        return {"issues": [], "counts": {}, "status": "unknown"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"issues": [], "counts": {}, "status": "unreadable"}
    # Defensive: if some older writer left a list, normalize to the dict shape.
    if isinstance(data, list):
        return {"issues": data, "counts": {}, "status": "list-form"}
    data.setdefault("issues", [])
    return data
