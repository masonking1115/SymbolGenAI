"""Decode the electrical value encoded in a resistor/capacitor manufacturer
part number (MPN) — the deterministic half of CHK_VALUE_MATCHES_MPN.

WHY THIS EXISTS
---------------
The value↔MPN check is a semantic (claude -p) rule: the judge is shown each
part's displayed value + lib_id/MPN and asked whether they agree. But many MPNs
encode their value in an *opaque manufacturer code* the judge can't reliably
decode from memory — e.g. a Murata `GRM155R71C104KA88D` is 0.1 µF (the `104` =
10×10⁴ pF), and a Vishay `TNPW06033K65BEEA` is 3.65 kΩ (the `3K65`). An E2E
review test showed the judge passing a deliberately mismatched part (R40 labeled
5.11k behind a `3K65` MPN) because it couldn't read the code. So we decode the
MPN's value HERE, deterministically, and hand the judge a pre-computed
comparison ("displayed 5.11k vs MPN-implied 3.65k — MISMATCH"). Same philosophy
as the sim-review units fix: do the exact arithmetic in Python, let the model
judge a clean comparison instead of guessing.

CONSERVATIVE BY DESIGN: every decoder returns None when it isn't confident.
A None means "can't tell from the MPN" — the judge then falls back to its own
reasoning and (per the rule) defaults to PASS. We never emit a *wrong* decoded
value, because a confident-but-wrong number would manufacture a false finding.

Covers the encodings actually present in this project's BOM (verified against
the netlist) plus the common general forms, so it carries to later projects:
  Resistors:  RKM code (`3K65`, `4R7`, `1M0`), EIA-4-digit (`1002`=10k,
              `0000`=0Ω), EIA-3-digit (`222`=2.2k).
  Capacitors: EIA-3-digit pF code embedded in the MPN (`104`=100nF=0.1µF,
              `226`=22µF), located via the Murata/standard voltage-letter anchor.
"""
from __future__ import annotations

import re

from test1.sim.design_extract import UnparseableValue, parse_value

__all__ = [
    "decode_resistor_mpn",
    "decode_capacitor_mpn",
    "decode_mpn",
    "values_match",
    "describe",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_lib_prefix(mpn: str) -> str:
    """Drop a leading library namespace like 'Lib:' so we decode the bare MPN."""
    s = (mpn or "").strip()
    if ":" in s:
        s = s.split(":", 1)[1]
    return s.strip()


def _eia_digits_to_value(code: str) -> float | None:
    """Decode an EIA significant-figures + multiplier code to a base value.

    3-digit `NNX`  -> NN × 10^X   (e.g. '222' -> 22×10²  = 2200)
    4-digit `NNNX` -> NNN × 10^X  (e.g. '1002' -> 100×10² = 10000, '0000' -> 0)
    Returns None for anything that isn't all-digits of length 3 or 4.
    """
    if not code.isdigit() or len(code) not in (3, 4):
        return None
    sig = int(code[:-1])
    mult = int(code[-1])
    return sig * (10.0 ** mult)


# ---------------------------------------------------------------------------
# Resistors
# ---------------------------------------------------------------------------

# RKM / IEC 60062 code: an R/K/M (and the rarer G) acts as BOTH a decimal point
# AND the magnitude. '3K65'=3.65e3, '4R7'=4.7, '1M0'=1.0e6, 'R47'=0.47. We bound
# the significant digits to <=3 either side so the package token glued in front
# ('0603' in 'TNPW06033K65BEEA') can't be swept into the value — see the package
# strip below, which also removes that ambiguity at the source.
_RKM_RE = re.compile(r"(\d{1,3})([RKMG])(\d{1,3})")
_RKM_MULT = {"R": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}
# A bare EIA 4-digit run not adjacent to other digits (e.g. the '1002' in
# 'CR0402-FX-1002GLF'). 4 digits is the standard chip-R marking; we only read it
# AFTER stripping the package size, which is also a 4-digit run.
_EIA4_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
# Imperial chip package codes (also 4 digits) — these are SIZES, never values, so
# we excise them before decoding to kill the '0402' vs '1002' collision. A code
# may carry the size more than once; remove every occurrence.
_PACKAGE_SIZES = ("01005", "0201", "0402", "0603", "0805",
                  "1206", "1210", "1812", "2010", "2512")


def _strip_package_token(s: str) -> str:
    """Remove imperial package-size tokens (0402/0603/...) from an MPN so they
    can't be mis-read as a value code. Order matters: strip the 5-digit 01005
    before the 4-digit sizes. Each is removed only when not embedded in a longer
    digit run on BOTH sides (so we don't chew a real value's digits)."""
    out = s
    for sz in _PACKAGE_SIZES:
        # Replace a size token that is bounded by a non-digit / string edge on at
        # least one side (the package code is a discrete field). Use a function
        # so we can require a boundary before the token (after it, the value-code
        # digits legitimately follow, e.g. '06033K65').
        out = re.sub(rf"(?<!\d){sz}", "", out)
    return out


def decode_resistor_mpn(mpn: str) -> float | None:
    """Best-effort resistance (ohms) encoded in a resistor MPN, or None.

    Strategy: strip the package-size token first (it collides with both code
    forms), then, most-specific first:
      1. RKM code   ('3K65' -> 3650, '4R7' -> 4.7) — explicit, unambiguous.
      2. EIA 4-digit ('1002' -> 10000, '0000' -> 0) — standard chip-R marking.
    We deliberately do NOT try a bare 3-digit code for resistors: even after the
    package strip it is the least reliable form and rarely used on modern MPNs.
    """
    raw = _strip_lib_prefix(mpn).upper()
    if not raw:
        return None
    s = _strip_package_token(raw)

    # 1) RKM code. Take the first plausible match.
    for m in _RKM_RE.finditer(s):
        whole, letter, frac = m.group(1), m.group(2), m.group(3)
        mult = _RKM_MULT[letter]
        # '3K65' -> 3.65 * 1e3 ; 'R47' -> 0.47 ; '1M0' -> 1.0 * 1e6.
        whole_v = float(whole) if whole else 0.0
        frac_v = float(f"0.{frac}") if frac else 0.0
        val = (whole_v + frac_v) * mult
        # Sanity: chip resistors span ~0.001 Ω .. 100 MΩ. Reject absurd decodes
        # (a spurious letter match) so we stay conservative.
        if 1e-3 <= val <= 1e8:
            return val

    # 2) EIA 4-digit code (incl. 0000 = 0 Ω) — package already removed.
    for m in _EIA4_RE.finditer(s):
        val = _eia_digits_to_value(m.group(1))
        if val is None:
            continue
        if val == 0.0:
            return 0.0
        if 1e-2 <= val <= 1e8:
            return val
    return None


# ---------------------------------------------------------------------------
# Capacitors
# ---------------------------------------------------------------------------

# Murata GRM / standard ceramic MPN: ...<dielectric><VOLT_LETTER><3-digit pF
# code><TOL_LETTER>... e.g. GRM155R71 C 104 K A88D. The cap code is the 3 digits
# immediately following the single voltage-code letter (and usually followed by a
# tolerance letter J/K/M). Anchoring on "<letter><3 digits><letter>" is what
# disambiguates the real cap code from the size token ('155') and the dielectric
# code ('R71').
_CAP_ANCHORED_RE = re.compile(r"[A-Z](\d{3})[A-Z]")
# RKM code in pF/uF/nF context appears on some MPNs/markings too ('p47'=0.47pF is
# rare; we only honor uF/nF/pF-suffixed RKM like '1U0', 'N10', 'P22').
_CAP_RKM_RE = re.compile(r"(?<![A-Z0-9])(\d*)([UNP])(\d{1,3})(?![0-9])")
_CAP_RKM_MULT = {"U": 1e-6, "N": 1e-9, "P": 1e-12}


def decode_capacitor_mpn(mpn: str) -> float | None:
    """Best-effort capacitance (farads) encoded in a capacitor MPN, or None.

    Primary: the EIA 3-digit pF code anchored between a voltage letter and a
    tolerance letter (`...C104K...` -> 100 nF). Fallback: an RKM uF/nF/pF code.
    Returns None if no confident decode (the judge then reasons unaided).
    """
    s = _strip_lib_prefix(mpn).upper()
    if not s:
        return None

    # Primary: anchored 3-digit pF code. There can be more than one "<L>3dig<L>"
    # window; the cap code is the one yielding a sane capacitance (1 pF .. 1 F).
    # Collect candidates and prefer the one nearest the part's TOLERANCE letter
    # (J/K/M) — that is by construction the real cap-code position.
    best: tuple[int, float] | None = None  # (preference, value)
    for m in _CAP_ANCHORED_RE.finditer(s):
        code = m.group(1)
        pf = _eia_digits_to_value(code)
        if pf is None:
            continue
        farads = pf * 1e-12
        if not (1e-12 <= farads <= 1.0):
            continue
        # Preference: the trailing anchor letter being a known tolerance code is
        # the strongest signal it's the cap value (e.g. the 'K' in '104K').
        trailing = s[m.end() - 1]
        pref = 2 if trailing in ("J", "K", "M") else 1
        if best is None or pref > best[0]:
            best = (pref, farads)
    if best is not None:
        return best[1]

    # Fallback: RKM uF/nF/pF code ('1U0' -> 1e-6).
    for m in _CAP_RKM_RE.finditer(s):
        whole, letter, frac = m.group(1), m.group(2), m.group(3)
        whole_v = float(whole) if whole else 0.0
        frac_v = float(f"0.{frac}") if frac else 0.0
        val = (whole_v + frac_v) * _CAP_RKM_MULT[letter]
        if 1e-15 <= val <= 1.0:
            return val
    return None


# ---------------------------------------------------------------------------
# Unified entry points
# ---------------------------------------------------------------------------

def decode_mpn(refdes: str, mpn: str) -> float | None:
    """Decode the MPN's value, dispatching on the refdes prefix (R*/C*). Returns
    a base-SI value (ohms or farads) or None if not a passive / not decodable."""
    if not refdes:
        return None
    head = refdes[0].upper()
    if head == "R":
        return decode_resistor_mpn(mpn)
    if head == "C":
        return decode_capacitor_mpn(mpn)
    return None


def _relative_match(a: float, b: float, *, tol: float = 0.02) -> bool:
    """True if a and b agree within `tol` (default 2%) — generous enough to
    absorb E-series rounding (3.65k vs 3650) but tight enough to flag a real
    swap (0.1µF vs 1µF, 3.65k vs 5.11k)."""
    if a == 0.0 or b == 0.0:
        return a == b
    return abs(a - b) / max(abs(a), abs(b)) <= tol


def values_match(displayed: str, refdes: str, mpn: str) -> bool | None:
    """Compare a part's DISPLAYED value string against its MPN-decoded value.

    Returns:
      True  — both parse and agree (within tolerance),
      False — both parse and DISAGREE (a real value↔MPN mismatch),
      None  — can't decide (value unparseable, MPN not decodable, or not a passive).
    None is the safe answer: the caller must not raise a finding on None.
    """
    mpn_val = decode_mpn(refdes, mpn)
    if mpn_val is None:
        return None
    try:
        disp_val = parse_value(displayed)
    except UnparseableValue:
        return None
    return _relative_match(disp_val, mpn_val)


def _human(refdes: str, val: float) -> str:
    """Render a base-SI value back to an EE string for the prompt."""
    head = (refdes[:1] or "").upper()
    if head == "C":
        for suf, scale in (("F", 1.0), ("mF", 1e-3), ("uF", 1e-6),
                           ("nF", 1e-9), ("pF", 1e-12)):
            if val >= scale:
                n = val / scale
                return f"{n:g}{suf}"
        return f"{val:g}F"
    # resistor / generic
    if val == 0.0:
        return "0"
    for suf, scale in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0)):
        if val >= scale:
            n = val / scale
            return f"{n:g}{suf}"
    return f"{val:g}"


def describe(refdes: str, displayed: str, mpn: str) -> str | None:
    """A one-line decoded comparison for the semantic prompt, or None if the MPN
    can't be decoded. E.g.:
      'R40: displayed 5.11k vs MPN-implied 3.65k (TNPW06033K65BEEA) -> MISMATCH'
    """
    mpn_val = decode_mpn(refdes, mpn)
    if mpn_val is None:
        return None
    bare = _strip_lib_prefix(mpn)
    implied = _human(refdes, mpn_val)
    verdict = values_match(displayed, refdes, mpn)
    if verdict is None:
        # MPN decoded but displayed value unparseable — still surface the implied
        # value so the judge can compare against the raw displayed string.
        return (f"{refdes}: displayed {displayed!r} vs MPN-implied {implied} "
                f"({bare}) -> displayed value not machine-parseable, compare manually")
    tag = "MATCH" if verdict else "MISMATCH"
    return (f"{refdes}: displayed {displayed} vs MPN-implied {implied} "
            f"({bare}) -> {tag}")
