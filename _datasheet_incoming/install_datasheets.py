"""Allocate datasheet PDFs to their Parts Library/<MPN>/ folders.

Drop PDFs into `_datasheet_incoming/` with the MPN anywhere in the filename
(case-insensitive, hyphens optional) and run this. Each file is matched against
the existing Parts Library/<MPN>/ directory names — unambiguous matches are
MOVED into that part's folder. Ambiguous (multiple MPNs in the name) and
unmatched files stay put and are reported so you can rename them.

The build path does NOT read these PDFs — they are convenience documentation
next to each symbol/footprint for whoever opens the part later. Existing PDFs
in the destination folder are kept; the incoming file is renamed
`<original>__N.pdf` (N=2,3,...) if its target name already exists.

Run:  python install_datasheets.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE.parent / "test1" / "Parts Library"

# Extra filename patterns that should also match an MPN. Distributors regularly
# strip the trailing termination letter (Murata), use a document number
# (Microchip), or name by family (TI/Vishay). Each entry maps MPN -> list of
# additional substrings (case/punctuation insensitive). The directory name
# itself is always tried first, so you don't need to re-list it.
ALIASES: dict[str, list[str]] = {
    # Murata GRM series — Murata's PDFs drop the trailing K/L/D termination
    # code, naming by base + "-01" suffix.
    "GRM155R70J105KA12D": ["GRM155R70J105KA12"],
    "GRM155R71C104KA88D": ["GRM155R71C104KA88"],
    "GRM155R71H103KA88D": ["GRM155R71H103KA88"],
    "GRM21BR61A226ME44L": ["GRM21BR61A226ME44"],
    "GRM21BR71A106KA73L": ["GRM21BR71A106KA73"],
    # Microchip — datasheets are named by doc number, not MPN.
    "24AA08-I-SN":        ["20001710", "DS20001710"],   # 24AA08 EEPROM doc
    "MCP4728":            ["22187"],                    # MCP4728 DAC doc
    # TI — family-level datasheet covers the specific variant.
    "TPS7A8401A":         ["tps7a84"],                  # TPS7A84A family doc
    "TPS22916CNYFPR":     ["tps22916"],                 # base part name
    # Vishay CRCW — one datasheet for the whole CRCW series; "e3" is the
    # lead-finish designator commonly appended in distributor filenames.
    "CRCW04020000Z0ED":   ["dcrcw", "crcw_e3"],
    # Bourns CR0402 — family datasheet covers every value.
    "CR0402-FX-1001GLF":  ["CR0402-FX"],
    "CR0402-FX-1002GLF":  ["CR0402-FX"],
    "CR0402-FX-2201GLF":  ["CR0402-FX"],
    # Vishay TNPW — thin-film family doc.
    "TNPW06035K11BEEA":   ["tnpw_e3", "tnpw0603"],
    # Keystone — catalog-page filenames (K75p62 = catalog 75, page 62 = 5011).
    "Keystone-5011":      ["K75p62", "5011"],
    # Samtec TSW — series datasheet.
    "TSW-102-05-G-S":     ["tsw_series", "tsw-1xx"],
    "TSW-104-05-G-S":     ["tsw_series", "tsw-1xx"],
    # ON / Nexperia / Diodes — small-signal MOSFET datasheets by part name.
    "2N7002":             ["nds7002", "2n7002"],
    "PMZ1200UPEYL":       ["pmz1200upe"],
}


def _norm(s: str) -> str:
    """Lowercase, strip non-alphanumeric — so 'CR0402-FX-1001GLF', 'cr0402 fx
    1001glf', and 'cr0402fx1001glf' all match."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match(filename: str, mpns: list[str]) -> list[str]:
    """Return the MPNs whose normalized form (or any alias) appears in the
    normalized filename. If multiple match, prefer the most-specific (longest
    matched substring) so a generic family alias loses to an exact MPN."""
    nf = _norm(filename)
    # For each MPN, the longest substring length that fired on this filename.
    scores: dict[str, int] = {}
    for m in mpns:
        candidates = [m] + ALIASES.get(m, [])
        best = max((len(_norm(c)) for c in candidates if _norm(c) in nf),
                   default=0)
        if best:
            scores[m] = best
    if not scores:
        return []
    top = max(scores.values())
    return [m for m, s in scores.items() if s == top]


def _unique_dest(folder: Path, name: str) -> Path:
    """Return folder/name, suffixing __2/__3/... if the name already exists."""
    dest = folder / name
    if not dest.exists():
        return dest
    stem, suf = dest.stem, dest.suffix
    for i in range(2, 100):
        cand = folder / f"{stem}__{i}{suf}"
        if not cand.exists():
            return cand
    raise SystemExit(f"too many collisions for {name}")


def main() -> int:
    if not PARTS.is_dir():
        print(f"  ! Parts Library not found at {PARTS}", file=sys.stderr)
        return 2
    mpns = sorted(p.name for p in PARTS.iterdir() if p.is_dir())
    pdfs = sorted(p for p in HERE.iterdir()
                  if p.is_file() and p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"no PDFs in {HERE} (drop datasheets here and rerun)")
        return 0

    placed: list[tuple[str, str]] = []
    ambiguous: list[tuple[str, list[str]]] = []
    unmatched: list[str] = []

    for pdf in pdfs:
        hits = _match(pdf.name, mpns)
        if len(hits) == 1:
            dest = _unique_dest(PARTS / hits[0], pdf.name)
            shutil.move(str(pdf), str(dest))
            placed.append((pdf.name, str(dest.relative_to(PARTS.parent.parent))))
        elif len(hits) > 1:
            ambiguous.append((pdf.name, hits))
        else:
            unmatched.append(pdf.name)

    print(f"=== {len(placed)} placed, "
          f"{len(ambiguous)} ambiguous, {len(unmatched)} unmatched ===\n")
    for fn, where in placed:
        print(f"  [moved] {fn}")
        print(f"          -> {where}")
    for fn, hits in ambiguous:
        print(f"  [skip:ambiguous] {fn}  (matches: {', '.join(hits)})")
    for fn in unmatched:
        print(f"  [skip:unmatched] {fn}")
    if ambiguous or unmatched:
        print(f"\nRename ambiguous/unmatched files to include exactly one MPN "
              f"from Parts Library/ and rerun. MPNs available:")
        for m in mpns:
            print(f"  {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
