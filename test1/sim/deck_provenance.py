"""Deck provenance + staleness — does a block's SPICE model match the schematic?

The sim decks are behavioral models authored against a specific netlist sheet
(`netlist/<sheet>.yaml`). When the schematic changes — a part added/removed, a
value or net edited — the deck and its catalog entry can silently fall out of
sync with the as-built design. This module makes that detectable so the GUI can
offer to UPDATE the model agentically (and to GENERATE one where none exists).

Two questions, two answers:
  - has_model(block)   — is there a deck builder at all? (service.has_deck_builder)
                         No  → the GUI offers "Generate SPICE model".
  - deck_status(block) — for a block that HAS a model: does it still match the
                         schematic? We snapshot a fingerprint of the block's
                         netlist sheet(s) when the model is generated/updated;
                         if the live fingerprint differs, the model is STALE and
                         the GUI offers "Update to match schematic".

Fingerprint = a content hash of the block's netlist sheet file(s) — the same
files design_extract reads. It deliberately covers the WHOLE sheet (not just the
block's nets): a behavioral deck's correctness can depend on parts/nets the
catalog author judged in-scope, and a coarse "the sheet changed" signal is the
honest, low-false-negative trigger for a re-check. The agent decides what (if
anything) actually needs updating; this just flags "worth re-checking".

The snapshot is written by the generate/update agents (via stamp()) after they
finish, and read here. No snapshot yet (a hand-authored deck that predates this)
→ status "unknown" (not "stale"): we don't nag about decks we never stamped, but
the GUI can still offer an explicit update.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # test1/
NETLIST_DIR = ROOT / "netlist"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
PROV_FILE = CACHE_DIR / "deck_provenance.json"


def _sheets_for(block: dict) -> list[str]:
    """The netlist sheet stems a block depends on. Usually one (`sheet:`), but a
    composed/integration block can name several as "(power + bias + bobcat)"."""
    raw = (block.get("sheet") or "").strip()
    if not raw:
        return []
    if raw.endswith(".yaml"):
        return [raw[:-5]]
    # a composed pseudo-sheet like "(power + bias + bobcat)"
    import re
    stems = re.findall(r"[A-Za-z0-9_]+", raw)
    return [s for s in stems if (NETLIST_DIR / f"{s}.yaml").exists()]


def fingerprint(block: dict) -> str | None:
    """Content hash of the block's netlist sheet file(s). None if the block has
    no resolvable sheet on disk (nothing to compare against)."""
    stems = _sheets_for(block)
    h = hashlib.sha256()
    found = False
    for stem in sorted(stems):
        p = NETLIST_DIR / f"{stem}.yaml"
        if p.exists():
            h.update(stem.encode("utf-8"))
            h.update(p.read_bytes())
            found = True
    return h.hexdigest() if found else None


def _load() -> dict:
    try:
        return json.loads(PROV_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def stamp(block: dict) -> str | None:
    """Record the current netlist fingerprint for a block — called by the
    generate/update agents (via the CLI below) once the model matches the
    schematic. Returns the stamped fingerprint (or None if no sheet)."""
    fp = fingerprint(block)
    if fp is None:
        return None
    data = _load()
    data[block.get("id")] = {"fingerprint": fp, "sheets": _sheets_for(block)}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PROV_FILE.write_text(json.dumps(data, indent=2))
    return fp


def stamped_fingerprint(block_id: str) -> str | None:
    return (_load().get(block_id) or {}).get("fingerprint")


def deck_status(block: dict, *, has_model: bool) -> str:
    """A block's model status for the GUI:
        "none"     — no deck builder; offer Generate.
        "unknown"  — has a deck but never stamped (hand-authored / pre-dates
                     provenance); we can't prove fresh-or-stale. Offer update,
                     don't nag.
        "fresh"    — stamped fingerprint == live netlist fingerprint.
        "stale"    — stamped fingerprint differs → schematic changed; offer Update.
    """
    if not has_model:
        return "none"
    stamped = stamped_fingerprint(block.get("id"))
    if not stamped:
        return "unknown"
    live = fingerprint(block)
    if live is None:
        return "unknown"
    return "fresh" if live == stamped else "stale"


# CLI — the generate/update agents call this (via bash) once their model matches
# the schematic, to record the current netlist fingerprint as the baseline:
#     python sim/deck_provenance.py --stamp <block_id>
if __name__ == "__main__":      # pragma: no cover
    import argparse
    import sys

    HERE = Path(__file__).resolve()
    REPO = HERE.parents[2]
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from test1.sim import catalog          # noqa: E402

    ap = argparse.ArgumentParser(description="Deck provenance: stamp/check a block's netlist fingerprint.")
    ap.add_argument("--stamp", metavar="BLOCK_ID", help="record the current netlist fingerprint for BLOCK_ID")
    ap.add_argument("--status", metavar="BLOCK_ID", help="print the deck status for BLOCK_ID")
    args = ap.parse_args()

    if args.stamp:
        blk = catalog.get_block(args.stamp)
        fp = stamp(blk)
        print(json.dumps({"block": args.stamp, "stamped": fp}))
    elif args.status:
        blk = catalog.get_block(args.status)
        from test1.sim import service
        st = deck_status(blk, has_model=service.has_deck_builder(args.status))
        print(json.dumps({"block": args.status, "status": st}))
    else:
        ap.print_help()
