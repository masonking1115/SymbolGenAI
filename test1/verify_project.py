#!/usr/bin/env python3
"""
Connectivity + duplicate-refdes verifier for the test1 KiCad project.

KiCad's built-in `sch erc` is unavailable on this dev build, so we parse
the .kicad_sch files directly and check:

  1. Duplicate refdes anywhere in the project (KiCad's refdes namespace
     is global across all sheets). Power symbols (#PWR*) are exempt.

  2. Hierarchical-label connectivity: every (sheet (pin "NAME" <dir>))
     on the root must have a matching (hierarchical_label "NAME" (shape <dir>))
     on the child sheet, AND vice versa. Direction is normalized to handle
     parent (input/output) → child (input/output) parity.

  3. Orphan hierarchical labels: a child sheet declaring a hier_label that
     doesn't exist as a pin on the parent's sheet block.

Exit code: 0 if clean, 1 if any issue is reported.
"""

from __future__ import annotations
import re
import sys
from collections import defaultdict
from pathlib import Path

KICAD_DIR = Path(__file__).resolve().parent / "kicad"


def read(p: Path) -> str:
    return p.read_text()


# --- refdes scan ---

REFDES_PROP = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')
SYMBOL_BLOCK = re.compile(r'\(symbol\s+\(lib_id\b')


def collect_refdes_per_sheet(sch_text: str) -> list[str]:
    """Return list of refdes from every symbol-instance block in the sheet.
    A symbol instance is identified by `(symbol (lib_id "...")` (lib_symbols
    body symbols match `(symbol "..." ...)` instead, so they're excluded)."""
    out = []
    for m in SYMBOL_BLOCK.finditer(sch_text):
        # Look ahead a few hundred chars for the Reference property
        snippet = sch_text[m.start(): m.start() + 600]
        rm = REFDES_PROP.search(snippet)
        if rm:
            out.append(rm.group(1))
    return out


# --- hierarchical-label scan ---

# Match (sheet ...) blocks on the root and extract their pin declarations
SHEET_OPEN = re.compile(r'\(sheet\b')
SHEET_PIN = re.compile(
    r'\(pin\s+"([^"]+)"\s+(input|output|bidirectional|tri_state|passive)\b'
)
SHEETFILE = re.compile(r'\(property\s+"Sheetfile"\s+"([^"]+)"')

# Match (hierarchical_label "NAME" (shape <dir>) ...) on a child sheet
HIER_LABEL = re.compile(
    r'\(hierarchical_label\s+"([^"]+)"\s+\(shape\s+(\w+)\)'
)


def _find_match(text: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def collect_sheet_blocks(root_text: str) -> list[tuple[str, dict[str, str]]]:
    """Return [(sheetfile, {pin_name: direction}), ...] for each child sheet."""
    out = []
    for m in SHEET_OPEN.finditer(root_text):
        end = _find_match(root_text, m.start())
        block = root_text[m.start(): end + 1]
        fm = SHEETFILE.search(block)
        if not fm:
            continue
        pins = {pm.group(1): pm.group(2) for pm in SHEET_PIN.finditer(block)}
        out.append((fm.group(1), pins))
    return out


def collect_hier_labels(child_text: str) -> dict[str, list[str]]:
    """{label_name: [shape, ...]} — list because the same name may appear twice."""
    result: dict[str, list[str]] = defaultdict(list)
    for m in HIER_LABEL.finditer(child_text):
        result[m.group(1)].append(m.group(2))
    return result


# --- direction compatibility ---

def directions_compat(parent_dir: str, child_dirs: list[str]) -> bool:
    """A parent's sheet-pin direction must match exactly one of the child's
    hier-label shapes for the same net name."""
    return parent_dir in child_dirs


# --- main ---

def main() -> int:
    if not KICAD_DIR.exists():
        print(f"ERROR: {KICAD_DIR} not found", file=sys.stderr)
        return 1

    root_path = KICAD_DIR / "test1.kicad_sch"
    if not root_path.exists():
        print(f"ERROR: {root_path} not found", file=sys.stderr)
        return 1

    issues = 0

    # === 1. Duplicate refdes (project-wide) ===
    print("=" * 60)
    print("1. Duplicate refdes check (project-wide)")
    print("=" * 60)
    refdes_locations: dict[str, list[str]] = defaultdict(list)
    sheets = sorted(KICAD_DIR.glob("*.kicad_sch"))
    for sch in sheets:
        for r in collect_refdes_per_sheet(read(sch)):
            if r.startswith("#PWR"):
                continue  # power-symbol refs are auto-generated per-instance
            refdes_locations[r].append(sch.name)

    dups = {r: locs for r, locs in refdes_locations.items() if len(locs) > 1}
    if dups:
        for r, locs in sorted(dups.items()):
            same_sheet = len(set(locs)) == 1
            print(f"  DUP {r}: {len(locs)} occurrences in {sorted(set(locs))}"
                  f"{'  (multi-unit OK)' if same_sheet else '  *** ERROR'}")
            # Multi-unit instances of the same chip share refdes by design
            # (one (symbol ...) per unit). Flag as error only if they appear
            # on *different* sheets.
            if not same_sheet:
                issues += 1
    else:
        print(f"  OK — {len(refdes_locations)} unique refdes, no duplicates")

    # === 2. Parent ↔ child hierarchical pin matching ===
    print()
    print("=" * 60)
    print("2. Hierarchical pin / label name + direction match")
    print("=" * 60)
    root_text = read(root_path)
    sheet_blocks = collect_sheet_blocks(root_text)

    for sheetfile, parent_pins in sheet_blocks:
        child_path = KICAD_DIR / sheetfile
        if not child_path.exists():
            print(f"  MISSING child {sheetfile}")
            issues += 1
            continue
        child_text = read(child_path)
        child_labels = collect_hier_labels(child_text)

        # Parent declares pin → child must have matching hier_label
        for pin_name, pin_dir in parent_pins.items():
            if pin_name not in child_labels:
                print(f"  {sheetfile}: parent declares pin '{pin_name}' ({pin_dir}), "
                      f"child has no hierarchical_label of that name")
                issues += 1
            elif not directions_compat(pin_dir, child_labels[pin_name]):
                print(f"  {sheetfile}: '{pin_name}' direction mismatch — "
                      f"parent={pin_dir}, child={child_labels[pin_name]}")
                issues += 1

        # Child declares hier_label → parent should declare matching pin
        for label_name in child_labels:
            if label_name not in parent_pins:
                # global_label-style nets (power, common buses across sheets)
                # are allowed to exist on children without parent pins —
                # they're auto-tied. Power-rail names like +VDDD live as
                # power symbols, not hier labels, so a real hier_label
                # without a parent pin IS suspect.
                print(f"  {sheetfile}: child has hierarchical_label "
                      f"'{label_name}' but parent has no matching pin "
                      f"(orphan label)")
                issues += 1

    if issues == 0:
        print("  OK — all parent pins and child hier_labels match")

    # === 3. Summary ===
    print()
    print("=" * 60)
    print(f"Summary: {issues} issue(s)")
    print("=" * 60)
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
