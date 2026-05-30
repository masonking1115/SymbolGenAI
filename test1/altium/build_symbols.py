"""Aggregate the design's symbol library + verify it covers every netlist.

Symbols are now committed as native per-MPN Altium libraries
(`Parts Library/<MPN>/<MPN>.SchLib`, authored by author_symbol / migrate_
symbols). This module merges the ones the design uses into a single
`out/lib/parts.SchLib` (plus stock R/C passives) and returns the
lib_id -> symbol-name map the sheet builders place from. No KiCad in the path.
"""

from __future__ import annotations

from pathlib import Path

from altium_monkey import AltiumSchLib

from functools import lru_cache

from ..gen.netlist import load_netlist, parse_member
from .config import LIB_DIR
from .symbols import _add_passive
from .symlib import read_pins, schlib_path, symbol_name

SHEETS = ["fmc", "power", "bobcat", "eeprom", "bias", "connectors"]


@lru_cache(maxsize=None)
def _netlist(sheet: str):
    """Load each sheet's netlist AT MOST ONCE per process. libid_map() and
    verify_coverage() both walk every sheet; without this they each re-parsed
    all six YAMLs (and build_library/main called both)."""
    return load_netlist(sheet)


def symbol_name_for(lib_id: str) -> str:
    """SchLib symbol name to PLACE for a KiCad lib_id.

    Stock passives are authored as `R`/`C`. For `Lib:<MPN>` parts we resolve the
    symbol's ACTUAL name inside `<MPN>/<MPN>.SchLib` rather than assuming it is
    `<MPN>`: vendor/Ultra-Librarian libraries often name the symbol after the
    full orderable part (e.g. `Lib:OPA2388` -> `OPA2388IDGKR`). Falls back to the
    MPN when the file is absent (caught later as a missing-symbol error).
    """
    if lib_id == "Device:R":
        return "R"
    if lib_id == "Device:C":
        return "C"
    if lib_id.startswith("Lib:"):
        mpn = lib_id.split(":", 1)[1]
        return symbol_name(mpn) or mpn
    raise ValueError(f"unmapped lib_id {lib_id!r}")


def libid_map() -> dict[str, str]:
    """lib_id -> symbol name across all sheets (pure, no file write)."""
    out: dict[str, str] = {}
    for sh in SHEETS:
        for p in _netlist(sh).parts.values():
            out[p.lib_id] = symbol_name_for(p.lib_id)
    return out


def missing_symbols() -> list[str]:
    """MPNs the design references that have NO committed per-MPN .SchLib yet —
    i.e. components that need a symbol authored/installed before the design can
    build. Pure query (no raise, no write); the review pipeline + GUI call this
    to detect the 'new component not in the library' case and route it to the
    missing-part flow, instead of letting build_library() crash mid-build."""
    out: list[str] = []
    for libid in sorted(libid_map()):
        if not libid.startswith("Lib:"):
            continue
        mpn = libid.split(":", 1)[1]
        if not schlib_path(mpn).exists():
            out.append(mpn)
    return out


def _author_passives(out_path: Path, names: set[str]) -> Path | None:
    """Author a small SchLib with the stock R/C passives the design uses."""
    wanted = [n for n in ("R", "C") if n in names]
    if not wanted:
        return None
    lib = AltiumSchLib()
    for n in wanted:
        _add_passive(lib, n, n)
    lib.save(out_path)
    return out_path


def build_library(out_path: Path | None = None, force: bool = False
                  ) -> tuple[Path, dict[str, str]]:
    """Merge every per-MPN .SchLib the design uses (+ stock R/C) into
    parts.SchLib. Skips the merge if the file exists and force is False, so
    concurrent sheet builders (separate processes) never race on the write."""
    out_path = out_path or (LIB_DIR / "parts.SchLib")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lmap = libid_map()

    # Gather the per-MPN source libraries this design uses.
    src_mpns: list[str] = []
    missing: list[str] = []
    for libid in sorted(lmap):
        if not libid.startswith("Lib:"):
            continue
        mpn = libid.split(":", 1)[1]
        sp = schlib_path(mpn)
        if not sp.exists():
            missing.append(mpn)
        else:
            src_mpns.append(mpn)
    if missing:
        raise FileNotFoundError(
            "missing per-MPN .SchLib for: " + ", ".join(missing)
            + " — author them via test1.altium.author_symbol, or install an"
            + " Ultra Librarian .SchLib into Parts Library/<MPN>/")
    src_paths = [schlib_path(m) for m in src_mpns]

    # Reuse the merged library only when it is up to date: it must exist and be
    # newer than every source .SchLib. This way swapping in a new symbol (e.g.
    # an Ultra-Librarian import) is picked up on the next build without needing
    # force=True, while concurrent sheet builders still avoid redundant merges.
    if out_path.exists() and not force:
        merged_mtime = out_path.stat().st_mtime
        if all(p.stat().st_mtime <= merged_mtime for p in src_paths):
            return out_path, lmap

    inputs: list[Path] = []
    passives = _author_passives(LIB_DIR / "_passives.SchLib", set(lmap.values()))
    if passives:
        inputs.append(passives)
    inputs.extend(src_paths)

    AltiumSchLib.merge(inputs, out_path, handle_conflicts="error", verbose=False)
    return out_path, lmap


_CACHE: tuple[Path, dict[str, str]] | None = None


def get_library() -> tuple[Path, dict[str, str]]:
    """Build (once per process) and return (parts.SchLib path, lib_id->symbol)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = build_library()
    return _CACHE


def verify_coverage() -> int:
    """Check every netlist part maps to a symbol and every net-member pin
    exists on that part (in the right unit). Returns failure count."""
    fails = 0
    _, lmap = build_library()
    for sh in SHEETS:
        nl = _netlist(sh)
        for ref, part in nl.parts.items():
            if part.lib_id not in lmap:
                print(f"  [FAIL] {sh}: {ref} lib_id {part.lib_id!r} unmapped"); fails += 1
        for net in nl.nets.values():
            for m in net.members:
                refdes, unit, pin = parse_member(m)
                part = nl.parts.get(refdes)
                if part is None:
                    continue  # member may reference a part on another sheet
                if not part.lib_id.startswith("Lib:"):
                    continue  # stock R/C: 2-pin passives, pins 1/2 by construction
                pins = read_pins(part.lib_id.split(":", 1)[1])
                if pin not in pins:
                    print(f"  [FAIL] {sh}: {m} -> pin {pin!r} not in {part.lib_id}"); fails += 1
    return fails


def main() -> int:
    out, lmap = build_library(force=True)
    print(f"Wrote {out} with {len(lmap)} symbols:")
    for libid, name in sorted(lmap.items()):
        if libid.startswith("Lib:"):
            pins = read_pins(libid.split(":", 1)[1])
            units = sorted({u for *_, u in pins.values()})
            u = f", {len(units)} units" if len(units) > 1 else ""
            print(f"  {libid:28} -> {name:18} ({len(pins)} pins{u})")
        else:
            print(f"  {libid:28} -> {name:18} (stock passive)")
    print("\nCoverage check:")
    fails = verify_coverage()
    print("  all parts + net-member pins covered" if fails == 0 else f"  {fails} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
