"""Small helpers extracted from closed_loop.py for unit-testability."""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "altium" / "out"


def _read_lint_failures() -> dict:
    """Read out/lint.json and bucket by sheet."""
    p = OUT_DIR / "lint.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    by_sheet: dict[str, list[dict]] = {}
    for item in data:
        sheet = item.get("sheet", "?")
        by_sheet.setdefault(sheet, []).append(item)
    return by_sheet
