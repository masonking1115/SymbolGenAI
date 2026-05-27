"""Dev-only: rasterize a built sheet SVG to PNG (SVG->reportlab PDF->fitz PNG)
so the agent can view layouts (cairo is unavailable on this box). Not part of
the build. Usage: python -m test1.altium._render <sheet> [x0 y0 x1 y1] [zoom]
fractions are 0..1 of the page; omit for the full sheet."""
from __future__ import annotations
import sys
from pathlib import Path
import fitz
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg
from .config import RENDER_DIR


def render(sheet: str, frac=None, zoom=3.0) -> Path:
    svg = RENDER_DIR / f"{sheet}.svg"
    pdf = svg.with_suffix(".pdf")
    renderPDF.drawToFile(svg2rlg(str(svg)), str(pdf))
    doc = fitz.open(str(pdf))
    pg = doc[0]
    r = pg.rect
    clip = None
    if frac:
        x0, y0, x1, y1 = frac
        clip = fitz.Rect(r.width * x0, r.height * y0, r.width * x1, r.height * y1)
    pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    out = RENDER_DIR / f"_view_{sheet}.png"
    pix.save(str(out))
    doc.close()
    pdf.unlink(missing_ok=True)
    print(out)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    sheet = a[0]
    frac = tuple(float(v) for v in a[1:5]) if len(a) >= 5 else None
    zoom = float(a[5]) if len(a) >= 6 else (5.0 if frac else 2.0)
    render(sheet, frac, zoom)
