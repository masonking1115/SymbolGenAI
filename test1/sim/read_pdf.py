#!/usr/bin/env python3
"""Render datasheet PDF pages to PNGs so the sim agents can READ diagrams.

The headless `claude -p` Read tool needs poppler (`pdftoppm`) to rasterize a PDF
page into an image, and poppler is NOT installed here — so an agent told to
"read the datasheet PDF" can get the TEXT (via pdftotext) but not the PINOUT,
block diagrams, or graphs, which is where a lot of the electrical spec lives
(pin tables, the EC-table layout, characteristic curves).

This CLI uses PyMuPDF (`fitz`, already in the venv) to render pages to PNG. The
agent runs it, then Reads the printed PNG paths as images — giving it the
diagrams. It also dumps the text layer so the agent gets both in one shot.

Usage (agent cwd is test1/):
    python sim/read_pdf.py "Parts Library/OPA2388/opa2388.pdf"            # all pages (capped)
    python sim/read_pdf.py "<pdf>" --pages 1-8                            # a page range
    python sim/read_pdf.py "<pdf>" --pages 4,7 --zoom 3 --text            # specific pages + text

Prints, for each rendered page, an absolute PNG path the agent should Read.
PNGs land in a temp dir (system temp) so they don't clutter the repo.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# Datasheet text carries non-ASCII (θ, µ, ±, Ω, …); force UTF-8 stdout so
# printing the text layer never dies on a cp1252 console (Windows default).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


def _parse_pages(spec: str, total: int) -> list[int]:
    """'1-8' or '4,7' or '3' → 0-based page indices (clamped to the doc)."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    # dedupe, 1-based → 0-based, clamp
    seen = []
    for p in out:
        i = p - 1
        if 0 <= i < total and i not in seen:
            seen.append(i)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description="Render datasheet PDF pages to PNGs for the agent to Read.")
    ap.add_argument("pdf", help="path to the datasheet PDF (relative to test1/ or absolute)")
    ap.add_argument("--pages", default=None, help="e.g. '1-8' or '4,7' (default: first 4)")
    ap.add_argument("--zoom", type=float, default=2.2, help="render scale (higher = sharper text/diagrams)")
    ap.add_argument("--text", action="store_true", help="also print the extracted text layer")
    ap.add_argument("--text-only", dest="text_only", action="store_true",
                    help="print ONLY the text layer, render no images (fast; the preferred first pass)")
    ap.add_argument("--max", type=int, default=4, help="cap pages rendered when --pages omitted")
    args = ap.parse_args()
    # Reading many high-res PNGs as vision input is heavy — keep page count small.
    PAGE_HARD_CAP = 12

    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("ERROR: PyMuPDF (fitz) not available in this interpreter. Run with the "
              "venv python that has it.", file=sys.stderr)
        return 2

    pdf_path = Path(args.pdf)
    if not pdf_path.is_absolute():
        # resolve relative to test1/ (this file's parent.parent)
        pdf_path = Path(__file__).resolve().parents[1] / args.pdf
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    doc = fitz.open(pdf_path)
    total = doc.page_count
    pages = _parse_pages(args.pages, total) if args.pages else list(range(min(args.max, total)))
    capped = False
    if len(pages) > PAGE_HARD_CAP:
        pages = pages[:PAGE_HARD_CAP]
        capped = True

    # --text-only: print text, render NOTHING (fast path, no vision cost).
    if args.text_only:
        print(f"PDF: {pdf_path.name}  ({total} pages; text of {len(pages)} pages)")
        for i in pages:
            txt = doc[i].get_text().strip()
            print(f"\n===== PAGE {i + 1} =====\n{txt if txt else '(no extractable text — render this page as an image)'}")
        return 0

    out_dir = Path(tempfile.mkdtemp(prefix="dsheet_"))
    stem = pdf_path.stem.replace(" ", "_")
    mat = fitz.Matrix(args.zoom, args.zoom)

    print(f"PDF: {pdf_path.name}  ({total} pages; rendering {len(pages)} at {args.zoom}x)")
    if capped:
        print(f"(capped to {PAGE_HARD_CAP} pages — re-run with a tighter --pages range for others)")
    print("Read these PNGs as images to see pinouts / diagrams / tables:")
    for i in pages:
        png = out_dir / f"{stem}_p{i + 1:02d}.png"
        doc[i].get_pixmap(matrix=mat).save(str(png))
        print(f"  {png}")

    if args.text:
        print("\n--- TEXT LAYER (per page) ---")
        for i in pages:
            txt = doc[i].get_text().strip()
            if txt:
                print(f"\n===== PAGE {i + 1} =====\n{txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
