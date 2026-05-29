"""Extract component designator → pixel location from a rendered sheet SVG.

The GUI's "show what's being simulated" feature highlights the simulated block's
parts on the real Altium sheet. The rendered SVG (altium/out/render/<sheet>.svg)
draws each component's designator as a <text> element at its placed coordinate,
and the SVG viewBox maps 1:1 to what the browser displays — so a refdes → (x,y)
map plus the viewBox is enough to overlay highlight boxes.

This parses the designator text elements (e.g. "R40", "U41", "C40"). It is a
read-only, best-effort helper: designators it can't find are simply absent from
the result (the caller highlights what it can).
"""

from __future__ import annotations

import re
from pathlib import Path

# A designator label: 1-3 leading letters + digits (R40, U41, C40, Q42, LC24…).
_REFDES = re.compile(r"^[A-Za-z]{1,3}\d+$")
# <text x=".." y=".." ...>CONTENT</text>  — content may sit on the next line
# because the renderer emits xml:space="preserve".
_TEXT = re.compile(r'<text\s+x="([\d.]+)"\s+y="([\d.]+)"[^>]*>\s*([^<]*)</text>', re.S)
_VIEWBOX = re.compile(r'viewBox="0 0 ([\d.]+) ([\d.]+)"')


def extract(svg_path: Path) -> dict:
    """Return {"viewBox": [w, h], "refdes": {REF: {"x": float, "y": float}}}.

    Empty result (viewBox [0,0], no refdes) if the file is missing/unreadable."""
    try:
        svg = svg_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"viewBox": [0.0, 0.0], "refdes": {}}

    vb = _VIEWBOX.search(svg)
    view = [float(vb.group(1)), float(vb.group(2))] if vb else [0.0, 0.0]

    refdes: dict[str, dict] = {}
    for x, y, content in _TEXT.findall(svg):
        text = content.strip()
        if not _REFDES.match(text):
            continue
        # Keep the first occurrence (designators appear once; MPN labels that
        # happen to look like a refdes are rare and harmless).
        refdes.setdefault(text, {"x": float(x), "y": float(y)})
    return {"viewBox": view, "refdes": refdes}
