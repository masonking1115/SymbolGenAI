# System capability tests

A living catalog of end-to-end tests that demonstrate what this system can do.
Each entry is a real, reproducible scenario run against the live stack (FastAPI
backend on :8765 + the closed-loop review + Altium build + ngspice sim). Add a
new entry every time we teach the system a new capability; update an entry's
**Last verified** line when it's re-run.

How to read an entry: **Scenario** is what we're proving; **Setup** is the
starting state; **Expected flow** is the steps the system should take on its own;
**Result** is what actually happened on the last run (with the loop id so it's
auditable); **Wiring** points at the code that makes it work.

---

## T1 — Incorrect part: value↔MPN mismatch → autonomous symbol generation + remediation

**Capability:** The closed-loop review can detect that a component's schematic
value no longer matches its assigned manufacturer part (MPN), determine the
correct part, notice that the correct part has a datasheet but **no symbol yet**,
**generate the symbol**, repoint the component, rebuild, re-simulate, and re-run
the rules until the design passes — with the cleared finding shown in the final
review. No human edits to the design.

**Scenario (concrete):** R40/R41 (the bias-current sense resistors) carry
`value: 3.65k 0.1%` but still point at `lib_id: Lib:TNPW06035K11BEEA` — a **5.11k**
MPN. (3.65k is the correct value: 5.11k caps the regulated full-scale at ~484 µA,
below the 640 µA floor.) The correct 3.65k part, `TNPW06033K65BEEA`, has a
datasheet installed in `Parts Library/TNPW06033K65BEEA/` but no `.SchLib`.

**Setup:**
- `netlist/bias.yaml`: R40/R41 `lib_id: Lib:TNPW06035K11BEEA`, `value: 3.65k 0.1%`,
  `footprint: Resistor_SMD:R_0402_1005Metric` (note: also a latent 0402-vs-0603
  package mismatch — the MPN is 0603).
- `Parts Library/TNPW06033K65BEEA/` contains only `tnpw_e3.pdf` (datasheet, no
  `.SchLib`, no pinspec).
- Backend running on the venv Python (the one with `altium_monkey`).

**Expected flow (what the loop should do on its own):**
1. Eval flags `CHK_VALUE_MATCHES_MPN` (R40/R41 value 3.65k vs 5.11k MPN lib_id).
2. Apply pass recognizes the correct part is the 3.65k `TNPW06033K65BEEA`, sees
   its datasheet is present but the `.SchLib` is missing.
3. Because it's a **value swap of an existing part** (same 0603 thin-film
   resistor as the 5.11k sibling), it **clones** the sibling's symbol — geometry
   identical — via `python -m altium.author_symbol "<new>" --clone-from "<sibling>"`.
4. Repoints R40/R41 `lib_id` **and** `footprint` together (also fixing the
   0402→0603 mismatch).
5. Rebuild → `bias 0/0/0`.
6. Re-eval: `CHK_VALUE_MATCHES_MPN` clears.
7. (Sim gate: `opa_bias/dc_sweep` runs and passes with the 3.65k value.)
8. Final review shows the finding resolved → loop reaches `all_clear`.

**Result — PASS (last verified 2026-05-30, loop `a66156e2`):**
- Round 1: apply agent ran
  `python -m altium.author_symbol "TNPW06033K65BEEA" --clone-from "TNPW06035K11BEEA"`
  → "Symbol cloned (2 pins, geometry-identical)", repointed R40/R41 lib_id +
  footprint. Build `ok`. **`CHK_VALUE_MATCHES_MPN` cleared.**
- Round 2: cleared `BLK_BIAS_FS_CEILING` (the bias full-scale semantic rule).
  Build `ok`.
- **Loop status: `all_clear`.** Symbol internal name correct
  (`get_symbol_names → ['TNPW06033K65BEEA']`); `bias` builds 0/0/0;
  `opa_bias/dc_sweep` sim runs OK with 3.65k.

**Wiring (what makes this work):**
- `gui/backend/agent.py` `_APPLY_INSTRUCTIONS` — the "VALUE↔MPN RECONCILIATION"
  block, CASE 1 (value swap → `--clone-from`) vs CASE 2 (new part → pin-spec).
  Uses a plain `python` (the backend prepends its venv to the agent's PATH, so
  bare `python` resolves to the `altium_monkey`-having interpreter and matches
  the `Bash(python:*)` allow-list).
- `altium/author_symbol.py` `build_from_clone()` + `--clone-from` CLI — copies a
  sibling `.SchLib` byte-for-byte and renames the symbol identity in BOTH the
  ASCII records (LibRef/DesignItemId/Text) and the UTF-16LE OLE storage-directory
  name (what `get_symbol_names` reads). Refuses unequal-length MPNs (OLE
  directory offsets are length-sensitive). This guarantees the new symbol's pin
  geometry is identical to the sibling's, so the sheet builder's hardcoded pin
  routing stays valid.
- `review/closed_loop.py` `_dispatch_action` (apply branch) — pushes a
  finding-detailed changelog item (title + subject + observed + fix_hint) so the
  apply agent gets full context, not a bare "address rule X".

**Why it was hard / what we learned (regression guards):**
- **Symbol geometry must match the builder.** A symbol re-authored from a
  pin-spec lands pins on a clean 200-mil grid; the original was hand-tuned
  (pins at `Y±10`, not `±300`). `build_bias.py` routes R40/R41 at the *original*
  coordinates, so a regenerated symbol **shorts/splits nets** (`internal_PMOS0_
  source_feedback` split across components; SHORT at the gate net). Fixed by
  cloning instead of regenerating. (First run `f0dbfbb2` failed exactly this way.)
- **Bare `python`, not an absolute path.** The backend puts its venv first on the
  agent's PATH on purpose. An absolute/quoted interpreter path hits the
  permission gate and makes the agent thrash (and fall back to a raw `cp`, which
  leaves the wrong internal symbol name). Run `f8e23f1e` passed functionally but
  via `cp`; the bare-`python` fix made run `a66156e2` use `--clone-from` properly.
- **Backend must run on the venv Python** (`altium_monkey` isn't in system
  Python), else `author_symbol` fails for everyone.

**Known caveats observed (not blockers for this test):**
- `BLK_BIAS_FS_CEILING` is a semantic/margin rule that **flaps** (669 µA vs the
  640 µA floor is borderline; the LLM judge flips run-to-run). It passed on one
  eval, fired on another. Tracked separately (determinism / hysteresis).
- The loop's `sim_results` array wasn't populated during these runs even though
  the sim gate is wired; the design was sim-validated out-of-band
  (`opa_bias/dc_sweep` → ok). Tracked separately (sim-in-loop wiring).

---

<!-- Add new capability tests below, following the T1 template. -->
