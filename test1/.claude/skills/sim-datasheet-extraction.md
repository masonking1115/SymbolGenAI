---
name: sim-datasheet-extraction
description: How to extract device parameters from a datasheet PDF for a SPICE simulation and how to choose the operating-point scenario, for the test1 simulation pipeline. Covers rendering PDF pages to read pinouts/EC-tables/curves, the descriptive param-key convention that sim/param_map.py consumes, worst-case value selection, and grounding the operating point in the requirements + as-built netlist. Use during a sim setup/interpret pass when reading a part's datasheet to parameterize or judge a behavioral SPICE model.
---

# Extracting datasheet params for a SPICE sim

This is the methodology the **sim setup** pass uses to turn a datasheet into the
device parameters a behavioral ngspice model needs, and to pick the operating
point. (The **interpret** pass uses the same PDF-reading technique to cite the
numbers it judges against.)

## Reading the PDF (the Read tool can't rasterize these)

The headless Read tool has no poppler, so it cannot open a `.pdf` as an image —
pinouts, the electrical-characteristics (EC) table layout, and characteristic
curves won't come through. Render the pages first, then Read the PNGs:

```
<python> sim/read_pdf.py "Parts Library/<MPN>/<file>.pdf" --pages 4-9 --text
```

(run via bash; `<python>` is the interpreter the prompt names). It prints one PNG
path per page — **Read those as images** — and also dumps the text layer. The
numbers that matter almost always live in the **EC table** and the **graphs**,
which are images; the text layer alone usually misses conditions and curve
values. Target the EC + pinout pages (commonly pages 4–9).

## Which numbers to extract

Only parts with a `sim/param_map.py` mapper feed the model — extract those. For
each, pull the values that drive the behavior being simulated, and prefer the
**worst case** where it matters:

- **Op-amp** (e.g. OPA2388): `VOS` max (not typ), `GBW`, `AOL` min (worst-case
  gain), CMRR/PSRR if relevant.
- **LDO** (e.g. TPS7A8401A): dropout max at the actual load + BIAS condition,
  line/load regulation, output accuracy, noise.
- **Load switch / MOSFET**: `RON` max at the actual VIN and hot temperature,
  turn-on time `tON`.

Read the **test conditions** off the EC table — a number is meaningless without
its VIN/temp/load condition. When a value that matters is ambiguous, record a
`needs_clarification` question rather than guessing.

## Param-key convention (what the cache expects)

Cache entries are keyed by MPN with `model_params` and `spec` sub-dicts. Use
**descriptive keys that name the value, its condition, and its UNIT** — a
deterministic code mapper (`sim/param_map.py`) converts these to the ngspice
model inputs, so accuracy + clear units matter more than matching a fixed name:

```
"DROPOUT_mV_max_VIN1V1_BIAS_3A", "RON_mOhm_max_VIN1V8_85C",
"tON_us_typ_VIN1V8", "VOS_uV_max_25C", "GBW_MHz", "AOL_dB_min"
```

Always READ the cache file first, MERGE (never drop already-cached parts), then
write it back. Set `source`, `extracted_at`, `needs_clarification`.

## Choosing the operating point (scenario)

The scenario must be GROUNDED in the requirements + the as-built netlist, never
an arbitrary default:

- Read `design_requirements.md` and the block's `netlist/<sheet>.yaml` to learn
  what the block actually drives, at what voltages/currents.
- e.g. if the LDO feeds the Bobcat core rails at 0.6–1.0 V, the operating points
  are `[0.6, 1.0]` (worst-case at both ends), not 1.8 V.
- Pick a single representative `primary_*` setpoint for the default Run.
- Record `load_note`, `rationale`, and `sources` (the files you used).

## Boundary

Behavioral component VALUES that are in the netlist (decoupling caps, the bias
sense resistor) are NOT extracted from datasheets — they flow from
`netlist/<sheet>.yaml` via `sim/design_extract.py`. Datasheets supply the DEVICE
MODEL params (the part's intrinsic behavior); the netlist supplies the values.
