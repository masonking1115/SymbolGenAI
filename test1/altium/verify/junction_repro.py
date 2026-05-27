"""Minimal junction repro — diagnose the Tier-1 junction 0-vs-1 discrepancy.

Builds a SchDoc with TWO junction scenarios so the Altium oracle result tells
us *why* Altium's junction count differs from altium_monkey's:

  Scenario A (4-way cross): two wires fully cross; junction at the centre.
      Altium requires an EXPLICIT junction here to connect the four arms.
  Scenario B (T-intersection): a wire ends on the midpoint of another;
      junction at the tee. Altium normally AUTO-creates this junction.

altium_monkey will report 2 junctions either way. What Altium reports tells us:
  - Altium 2  -> altium_monkey's junctions serialize faithfully; the smoke-test
                 0 was something else (e.g. coordinate/off-grid).
  - Altium 1  -> Altium keeps the 4-way, drops the auto-able T == auto-junction
                 semantics, NOT a serialization bug. (Expected.)
  - Altium 0  -> Altium ignores altium_monkey junction records == real fidelity
                 gap to file upstream.

Run:
    python -m test1.altium.verify.junction_repro          # build + print counts
    python -m test1.altium.verify.run_altium_verify <path> # then oracle it
"""

from __future__ import annotations

from altium_monkey import AltiumSchDoc, ColorValue, LineWidth, SchPointMils, make_sch_junction, make_sch_wire

from ..config import OUT_DIR

_BLUE = ColorValue.from_hex("#000080")


# NOTE: a `fixed_junction` that set Color/IndexInSheet/cleared UniqueID to
# mirror a real Altium junction record was tried and REJECTED. Findings
# (see FINDINGS.md):
#   - bare make_sch_junction(): altium_monkey reads it back, but real Altium
#     DROPS it on load -- even a 4-way crossing (which Altium never
#     auto-creates). So Altium rejects altium_monkey's junction record.
#   - adding Color (to match real Altium's record) makes altium_monkey unable
#     to read its OWN output, and real Altium still drops it.
# => altium_monkey cannot currently emit an Altium-retained junction. This is
#    an upstream write bug. The migration does NOT depend on junction objects:
#    connectivity rides on T-intersections (Altium auto-junctions) + pins; we
#    forbid 4-way crossings in layout. Junctions stay in our validator graph
#    only. This repro is the minimal upstream bug report.


def _wire(doc, x1, y1, x2, y2):
    doc.add_object(make_sch_wire(
        points_mils=[SchPointMils.from_mils(x1, y1), SchPointMils.from_mils(x2, y2)],
        color=_BLUE, line_width=LineWidth.SMALL))


def build() -> str:
    doc = AltiumSchDoc()

    # Scenario A — 4-way cross at (2000, 4000).
    _wire(doc, 1600, 4000, 2400, 4000)   # horizontal through centre
    _wire(doc, 2000, 3600, 2000, 4400)   # vertical through centre
    doc.add_object(make_sch_junction(location_mils=SchPointMils.from_mils(2000, 4000)))

    # Scenario B — T-intersection at (3000, 4000): vertical wire ends on the
    # midpoint of a horizontal wire.
    _wire(doc, 2600, 4000, 3400, 4000)   # horizontal
    _wire(doc, 3000, 4000, 3000, 4400)   # vertical ending ON the horizontal
    doc.add_object(make_sch_junction(location_mils=SchPointMils.from_mils(3000, 4000)))

    out = OUT_DIR / "junction_repro.SchDoc"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)

    re = AltiumSchDoc(out)
    print(f"Wrote {out}")
    print(f"altium_monkey reads back: wires={len(re.wires)} junctions={len(re.junctions)}")
    return str(out)


if __name__ == "__main__":
    build()
