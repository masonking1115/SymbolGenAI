"""Datasheet-parameter cache.

The sim_interpret agent reads each block's datasheet PDFs once, extracts the
key parameters, and writes them here. Deck builders read `model_params` to
parameterize the ngspice models with real device numbers; the agent reads
`spec` when interpreting results against the datasheet. Cached per MPN so the
PDFs are only re-read when missing or when the agent flags a clarification.

Entry shape (written by the agent):
  {
    "<MPN>": {
      "model_params": { "DROPOUT": 0.18, "LINE_REG": 5e-4, ... },  # -> ngspice
      "spec":         { "accuracy_pct": 0.75, "noise_uVrms": 4.4, ... },
      "source": "tps7a84a.pdf",
      "extracted_at": "2026-05-26T...",
      "needs_clarification": null   # or a question string
    }
  }
"""

from __future__ import annotations

import json
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_FILE = CACHE_DIR / "datasheet_params.json"


def load() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def entry(mpn: str) -> dict:
    return load().get(mpn, {})


def model_params(mpn: str) -> dict:
    """ngspice model overrides for this part (empty if not yet extracted)."""
    return entry(mpn).get("model_params", {}) or {}


def is_cached(mpn: str) -> bool:
    e = entry(mpn)
    return bool(e) and not e.get("needs_clarification")


def needs_clarification() -> dict[str, str]:
    """{mpn: question} for any cached entry the agent flagged as ambiguous."""
    return {m: e["needs_clarification"] for m, e in load().items()
            if e.get("needs_clarification")}
