"""Phase 1: parse design_requirements.md into a structured dict.

The requirements doc is hand-written markdown — we parse it into a
predictable shape so deterministic rules and the LLM reviewer both
consume the same canonical structure.

We DON'T try to fully parse free-form prose. Instead we:
  1. Pick out structured sections by H2/H3 heading.
  2. Extract every (key, value) pair from markdown tables.
  3. Extract bullet lists from named sections (e.g. "Parts to implement").
  4. Return the raw markdown for each part-block as `raw_text` so the
     LLM reviewer can still read prose for context — but rules can key
     off the structured fields.

Output schema (RequirementsIndex):
  application: str                  — H2 "Application" body
  specs: dict[str, str]             — parsed "Specs" bullets, key=label
  parts: dict[refdes_or_label, PartRequirement]
      - bobcat (DUT) + every named block in "Parts to implement"
  fmc_power: list[(pin, net, use)]  — power & management pin table
  fmc_control: list[(pin, net, use)] — control / sideband pin table
  fmc_la_pairs: list[(label, row, p_pin, n_pin)] — LA-pair table
  topology: str                     — H2 "Topology / block diagram" prose
  notes: list[str]                  — "Notes / open questions" bullets
  assembly_notes: list[str]         — "Assembly / provisioning notes" bullets
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIREMENTS_PATH = (
    Path(__file__).resolve().parent.parent / "design_requirements.md"
)


@dataclass
class PartRequirement:
    name: str                  # e.g. "TPS7A8401A", "Bobcat", "Bias circuit"
    raw_text: str = ""         # full bullet body, prose preserved
    required_passives: list[str] = field(default_factory=list)
    required_nets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RequirementsIndex:
    application: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    parts: dict[str, PartRequirement] = field(default_factory=dict)
    fmc_power: list[tuple[str, str, str]] = field(default_factory=list)
    fmc_control: list[tuple[str, str, str]] = field(default_factory=list)
    fmc_la_pairs: list[tuple[str, str, int, int]] = field(default_factory=list)
    topology: str = ""
    notes: list[str] = field(default_factory=list)
    assembly_notes: list[str] = field(default_factory=list)
    raw_markdown: str = ""

    def part(self, name: str) -> PartRequirement | None:
        """Lookup by partial name match (case-insensitive)."""
        n = name.lower()
        for k, v in self.parts.items():
            if n in k.lower() or n in v.name.lower():
                return v
        return None


# ---------------------------------------------------------------------------
# Section splitter
# ---------------------------------------------------------------------------

_H2 = re.compile(r"^## (.+)$", re.MULTILINE)


def _split_h2(md: str) -> dict[str, str]:
    """Return {section_title: body} for every H2."""
    out: dict[str, str] = {}
    matches = list(_H2.finditer(md))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        out[title] = md[start:end].strip()
    return out


# ---------------------------------------------------------------------------
# Specs block — bullet "**Label:** body" → {label: body}
# ---------------------------------------------------------------------------

_SPEC_BULLET = re.compile(r"^- \*\*([^:]+):\*\*\s*(.+)$", re.MULTILINE)


def _parse_specs(body: str) -> dict[str, str]:
    return {m.group(1).strip(): m.group(2).strip()
            for m in _SPEC_BULLET.finditer(body)}


# ---------------------------------------------------------------------------
# Parts list — each top-level bullet is one part block.
# Sub-bullets / multi-line text indented under a "  -" are part of the block.
# ---------------------------------------------------------------------------

# Top-level bullet: "- **Name** — body…"  (em-dash variants tolerated)
_PART_HEAD = re.compile(
    r"^- \*\*([^*]+)\*\*\s*[—\-–]?\s*(.*)$", re.MULTILINE
)


def _parse_parts(body: str) -> dict[str, PartRequirement]:
    """Split the 'Parts to implement' section into one PartRequirement per
    top-level bullet, preserving sub-bullet prose as `raw_text`."""
    parts: dict[str, PartRequirement] = {}
    lines = body.splitlines()
    cur: PartRequirement | None = None
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur, cur_lines
        if cur is None:
            return
        cur.raw_text = "\n".join(cur_lines).strip()
        # Extract simple passive value mentions ("10kΩ pull-down", "0.1µF",
        # "1µF", "0Ω") for the deterministic-rules layer to grep against.
        for pat in (r"\d+\s*k?Ω", r"\d+\.?\d*\s*[µu]F", r"\d+\s*kΩ", r"\b0Ω\b"):
            cur.required_passives.extend(
                re.findall(pat, cur.raw_text)
            )
        parts[cur.name] = cur
        cur = None
        cur_lines = []

    for line in lines:
        m = _PART_HEAD.match(line)
        # Top-level bullet (column 0, starts with "- **"). Sub-bullets are
        # indented and start with "  -", so they won't match.
        if m and not line.startswith("  "):
            flush()
            name = m.group(1).strip()
            cur = PartRequirement(name=name)
            cur_lines = [m.group(2).strip()] if m.group(2).strip() else []
        elif cur is not None:
            cur_lines.append(line)
    flush()
    return parts


# ---------------------------------------------------------------------------
# Markdown table parser — extract rows from FMC pin tables.
# ---------------------------------------------------------------------------

def _parse_md_tables(body: str) -> list[list[list[str]]]:
    """Return every markdown table in `body` as a list-of-rows-of-cells.
    Each table includes header row first. Cells are stripped strings."""
    tables: list[list[list[str]]] = []
    cur: list[list[str]] = []
    in_table = False
    for line in body.splitlines():
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # Skip the divider row (---/:---).
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                in_table = True
                continue
            cur.append(cells)
        else:
            if cur:
                tables.append(cur)
                cur = []
            in_table = False
    if cur:
        tables.append(cur)
    return tables


# ---------------------------------------------------------------------------
# FMC tables — pick out power, control, LA-pair tables by header signature.
# ---------------------------------------------------------------------------

def _parse_fmc_power(tables: list[list[list[str]]]) -> list[tuple[str, str, str]]:
    """Find the first table whose header is (Pin(s), Net, Use…)."""
    for t in tables:
        if not t:
            continue
        hdr = [c.lower() for c in t[0]]
        if "pin(s)" in hdr[0] and "net" in hdr[1]:
            return [(r[0], r[1], r[2]) for r in t[1:] if len(r) >= 3]
    return []


def _parse_fmc_control(tables: list[list[list[str]]]) -> list[tuple[str, str, str]]:
    """Find the table whose header is (Pin, Net, Use)."""
    for t in tables:
        if not t:
            continue
        hdr = [c.lower() for c in t[0]]
        if hdr[0] == "pin" and hdr[1] == "net":
            return [(r[0], r[1], r[2]) for r in t[1:] if len(r) >= 3]
    return []


_LA_PAIR_RE = re.compile(
    r"([CDGH])(\d+)/[CDGH]?(\d+)\s+(LA\d+(?:_CC)?)", re.IGNORECASE,
)


def _parse_fmc_la_pairs(body: str) -> list[tuple[str, str, int, int]]:
    """Extract every 'C8/C9 LA01_CC'-style triple from the LA-bank prose."""
    out: list[tuple[str, str, int, int]] = []
    for row, p, n, label in _LA_PAIR_RE.findall(body):
        try:
            out.append((label.upper(), row.upper(), int(p), int(n)))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Bullets — generic flat list extractor.
# ---------------------------------------------------------------------------

_BULLET = re.compile(r"^- (.+)$", re.MULTILINE)


def _parse_bullets(body: str) -> list[str]:
    """All top-level (column-0) bullets in `body`."""
    return [m.group(1).strip()
            for m in _BULLET.finditer(body)
            if not body[max(0, m.start() - 2):m.start()].endswith("  ")]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load(path: Path = REQUIREMENTS_PATH) -> RequirementsIndex:
    md = path.read_text()
    idx = RequirementsIndex(raw_markdown=md)
    sections = _split_h2(md)

    idx.application = sections.get("Application", "")
    idx.specs = _parse_specs(sections.get("Specs", ""))
    idx.parts = _parse_parts(sections.get("Parts to implement", ""))

    # FMC tables live inside one umbrella section.
    fmc_section = sections.get(
        "FMC LPC pinout (VITA 57.1, Genesys 2 host side)", ""
    )
    tables = _parse_md_tables(fmc_section)
    idx.fmc_power = _parse_fmc_power(tables)
    idx.fmc_control = _parse_fmc_control(tables)
    idx.fmc_la_pairs = _parse_fmc_la_pairs(fmc_section)

    idx.topology = sections.get("Topology / block diagram", "")
    idx.notes = _parse_bullets(sections.get("Notes / open questions", ""))
    idx.assembly_notes = _parse_bullets(
        sections.get("Assembly / provisioning notes", "")
    )
    return idx
