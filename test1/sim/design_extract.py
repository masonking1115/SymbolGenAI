"""Single source of as-built design values for the sim decks.

The simulation decks are behavioral SPICE models, but their *component values*
(decoupling caps, the bias sense resistor, jumpers) must come from the ACTUAL
built design — `netlist/<sheet>.yaml`, the declarative connectivity + value
source of truth that `altium/build_<sheet>.py` consumes — so a design change
flows straight into the sim with no hand-editing of `blocks.yaml`.

This module is the one place that reads the netlist for the sim layer. It wraps
the typed loader `gen.netlist.load_netlist` (which validates schema, handles
multi-unit pins via `parse_member`, and exposes `Part.value`/`Part.dnp`,
`Net.members`) and adds the EE-specific helpers the decks need: an EE-value
parser, cap-on-net collection, and resistor lookups. Previously each deck
hand-rolled its own `_parse_value`/`_caps_with_net` against raw `yaml.safe_load`;
those copies had drifted (different unit suffixes, one couldn't parse a
tolerance like "5.11k 0.1%"). Centralizing here kills that drift.

No caching: `load_netlist` is a cheap YAML parse and the decks build per request,
so a netlist edit is always reflected on the next sim. (The *scenario* cache —
operating points — lives in simconfig and is freshness-gated separately; as-built
extraction is intentionally NOT cached so it can never go stale.)
"""

from __future__ import annotations

import re

from ..gen.netlist import Netlist, load_netlist, parse_member

# EE magnitude suffixes. "meg" is the SPICE/EE mega (1e6); a bare "m" is milli.
_SI = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
       "k": 1e3, "meg": 1e6, "g": 1e9}

# Trailing tolerance token to strip before parsing a value, e.g. the " 0.1%" in
# "5.11k 0.1%" or the " 1%" in "10k 1%". Every resistor value in the netlist
# carries one; caps happen not to, which is why the old parser survived on caps.
_TOLERANCE_TAIL = re.compile(r"\s*[\d.]+\s*%\s*$")
_VALUE_RE = re.compile(r"^([\d.]+)\s*([a-zA-Z]*)$")


class UnparseableValue(ValueError):
    """Raised when an EE value string can't be parsed (callers decide whether to
    fall back loudly or skip)."""


def parse_value(s: str | None) -> float:
    """Parse an EE-style value to base SI units.

    Handles magnitude suffixes ('10uF'->1e-5, '5.11k'->5110, '10meg'->1e7), a
    bare number ('0.038'->0.038), unit letters (F/H/ohm/Ω), AND a trailing
    tolerance token ('5.11k 0.1%'->5110). Raises UnparseableValue on anything
    that isn't a number (e.g. a part name like '2N7002').
    """
    if s is None:
        raise UnparseableValue("value is None")
    s = str(s).strip()
    # Drop a trailing tolerance like "0.1%" / "1 %" first (resistors carry it).
    s = _TOLERANCE_TAIL.sub("", s).strip()
    # Drop unit letters (F/H/ohm/Ω) from the end; keep magnitude suffixes.
    s = s.rstrip("FfHhΩΩohmsOHMS").strip()
    if not s:
        raise UnparseableValue("empty after stripping units/tolerance")
    m = _VALUE_RE.match(s)
    if not m:
        try:
            return float(s)
        except ValueError as e:
            raise UnparseableValue(f"cannot parse value {s!r}") from e
    num, suffix = m.group(1), m.group(2).lower()
    try:
        base = float(num)
    except ValueError as e:
        raise UnparseableValue(f"cannot parse number in {s!r}") from e
    if not suffix:
        return base
    if suffix == "meg":
        return base * 1e6
    return base * _SI.get(suffix[0], 1.0)


def _net(nl: Netlist, net: str):
    return nl.nets.get(net)


def net_members(sheet: str, net: str) -> set[str]:
    """{'REFDES.PIN', ...} declared on `net` in `sheet`.yaml (empty if absent)."""
    n = _net(load_netlist(sheet), net)
    return set(n.members) if n else set()


def _pin_refdes(member: str) -> tuple[str, str]:
    """('R40','2') from a member token, tolerating multi-unit ':uN'."""
    refdes, _unit, pin = parse_member(member)
    return refdes, pin


def caps_on_net(sheet: str, net: str) -> list[tuple[str, float]]:
    """[(refdes, C_farads)] for capacitors whose pin .1 sits on `net`.

    Pin .1 is the rail/signal side by the project's passive convention. A cap
    whose value can't be parsed is skipped (it simply isn't added to the deck) —
    acceptable for decoupling since a stray unparseable cap is rare and the
    netlist values are clean; the loud path is reserved for resistors below."""
    nl = load_netlist(sheet)
    n = _net(nl, net)
    if not n:
        return []
    on_net = {_pin_refdes(m) for m in n.members}
    out: list[tuple[str, float]] = []
    for ref, part in nl.parts.items():
        if not ref.startswith("C"):
            continue
        if (ref, "1") not in on_net:
            continue
        try:
            out.append((ref, parse_value(part.value)))
        except UnparseableValue:
            continue
    return out


def part_value(sheet: str, refdes: str) -> float | None:
    """Parsed value of one part, or None if absent/unparseable."""
    part = load_netlist(sheet).parts.get(refdes)
    if part is None:
        return None
    try:
        return parse_value(part.value)
    except UnparseableValue:
        return None


def resistor_value(sheet: str, refdes: str, *, fallback: float,
                   honor_dnp: bool = False) -> float:
    """Resistance of `refdes` from the netlist, falling back LOUDLY (the caller's
    `fallback`) when the part is missing, unparseable, or — when honor_dnp — not
    populated. Resistors drive analysis math (e.g. the bias ideal-current
    formula), so a silent wrong value would poison verdicts; we always return a
    usable number and never silently drop."""
    nl = load_netlist(sheet)
    part = nl.parts.get(refdes)
    if part is None:
        return fallback
    if honor_dnp and part.dnp:
        return fallback
    try:
        return parse_value(part.value)
    except UnparseableValue:
        return fallback


def resistor_bridging(sheet: str, net_a: str, net_b: str) -> tuple[str, float] | None:
    """(refdes, ohms) for the first 2-pin R with one pin on net_a and the other
    on net_b, or None. Used to find e.g. the sense resistor between +3V3 and the
    feedback node without hardcoding its refdes."""
    nl = load_netlist(sheet)
    na, nb = _net(nl, net_a), _net(nl, net_b)
    if not na or not nb:
        return None
    refs_a = {_pin_refdes(m)[0] for m in na.members}
    refs_b = {_pin_refdes(m)[0] for m in nb.members}
    for ref in sorted(refs_a & refs_b):
        if not ref.startswith("R"):
            continue
        try:
            return ref, parse_value(nl.parts[ref].value)
        except (UnparseableValue, KeyError):
            continue
    return None


# Bias channel → sense-resistor refdes (from bias.yaml). Channel 0 = R40, ch1 = R41.
_SENSE_R = {0: "R40", 1: "R41"}
SENSE_R_FALLBACK = 5110.0   # 5.11k 0.1% — the as-designed value, if extraction fails.


def sense_resistance(channel: int = 0) -> float:
    """The opa_bias channel sense-R value (ohms) read from bias.yaml, e.g. R40's
    '5.11k 0.1%' → 5110.0. Falls back to SENSE_R_FALLBACK if absent/unparseable
    so the deck always builds."""
    ref = _SENSE_R.get(channel, "R40")
    return resistor_value("bias", ref, fallback=SENSE_R_FALLBACK)
