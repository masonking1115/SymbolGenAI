# Tier 1 Altium-oracle verification — findings

Automated verification of altium_monkey output against **real Altium Designer
AD26** (`X2.EXE`), driven unattended by `run_altium_verify.py` (generates a
DelphiScript + `.PrjScr`, launches Altium, enumerates objects via Altium's own
SCH API, diffs against altium_monkey's counts).

## Headline

The KiCad→Altium backend is sound. Real Altium opens altium_monkey's
`.SchDoc` **uncorrupted** and agrees on every object type **except junctions**:

| Object | Altium | altium_monkey |
|---|---|---|
| components | 2 | 2 ✓ |
| wires | 5 | 5 ✓ |
| ports | 1 | 1 ✓ |
| power_ports | 2 | 2 ✓ |
| net_labels | 1 | 1 ✓ |
| no_erc | 1 | 1 ✓ |
| **junctions** | **0** | 1 ✗ |

## Junction bug (isolated, reproducible)

Minimal repro: `junction_repro.py` builds a 4-way crossing + a T-intersection,
each with an explicit junction (`out/junction_repro.SchDoc`).

| Junction form | altium_monkey readback | real Altium |
|---|---|---|
| bare `make_sch_junction()` | 2 | **0** (dropped) |
| with `Color` set (to mirror a real Altium junction record) | **0** (can't read its own) | **0** (dropped) |

- Real Altium drops the junction **even at the 4-way crossing**, which Altium
  *never* auto-creates — so this is not auto-junction semantics, it's rejection
  of altium_monkey's RECORD=29 junction.
- A real Altium-authored junction record (from the example corpus,
  `bunny_brain_D.SchDoc`) is `{RECORD:29, IndexInSheet:-1, OwnerPartId:-1,
  Location.X, Location.Y, Color:128}`. altium_monkey's bare junction omits
  `Color`; adding it breaks altium_monkey's own reader.
- `IndexInSheet` is assigned on `save` (not actually missing); `UniqueID`
  presence/absence is harmless to readback.

**Conclusion:** altium_monkey cannot currently emit a junction that real Altium
retains. Upstream write bug — file with this repro.

## Why the migration is not blocked

`AltiumSchDoc.to_netlist()` on the smoke schematic shows correct connectivity
**without** junction objects:

```
[00001] +3V3   C1.1, U1.1 (VIN)     <- merged through the T-intersection
[00002] GND    C1.2
[00003] VOUT   U1.8
```

Real Altium **auto-junctions T-intersections** electrically. So:

- **Design rule for the backend:** emit no junction object dependence; never
  route a 4-way crossing (split into offset T's). The KiCad `gnd_bus` /
  `decoupling_cluster` helpers already tap as T-intersections.
- Junctions are retained only in our internal validator connectivity graph.
- `AltiumSheet.junction()` still adds the (Altium-ignored) record so the
  altium_monkey SVG shows the dot; it is cosmetic, not electrical.

## Open follow-ups

1. File the junction write bug upstream (repro: `out/junction_repro.SchDoc`).
2. Tier 2+ (optional): confirm Altium's *compiled* netlist (not just
   altium_monkey's `to_netlist`) connects a T-intersection — needs wrapping the
   sheet in a `.PrjPcb` and running Altium's netlister from the verify script.
