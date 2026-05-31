# Future Test Cases — HW-SW Co-Designer Validation Harness

**Status:** specification (drafted 2026-05-31). These are planned planted-error
scenarios for end-to-end validation of the schematic build, linter, validator,
semantic evaluator, simulation, and closed-loop review pipeline. None are wired
into an automated runner yet — each test case is a self-contained recipe that
can be applied to a clean checkout, exercised, and graded by hand or by a
future runner that consumes these files.

**Scope:** every file in this folder describes ERRORS to be planted (not fixes
to be applied). The harness applies one plant, runs the pipeline, asserts
detection (and optionally fix), then reverts. Plants are independent — never
combine two unless explicitly noted in the test case.

---

## Why this folder exists

The pipeline today is built and shipping; validation is mostly hand-authored.
A formal test harness raises confidence that:

- the **layout linter** catches geometric/cosmetic regressions before fab,
- the **strict validator** catches net-membership drift between YAML and the
  placed SchDoc,
- the **semantic rule evaluator** catches design-intent drift,
- the **simulation runs** catch component-value drift (e.g. R_sense → bias FS),
- the **closed-loop review** converges to a minimal correct fix without churn,
- the **agents** (planner, applier, simulator, lint-fixer, semantic re-eval)
  don't regress on prompt edits or model swaps.

Each test case lives at exactly one of these layers, so a failure points
directly at the responsible code path.

---

## File map

| File | Category | Approx. count |
|---|---|---|
| `01_component_values.md`        | Wrong R/C/L values planted into netlist YAMLs.                    | 12 |
| `02_simulation_validation.md`   | Plants that should only be caught by ngspice block sims.          | 12 |
| `03_linter_coverage.md`         | One test per `_check_*` rule in `layout_lint.py`.                 | 31 |
| `04_symbol_library.md`          | Pin name/number/electrical-type/footprint drift in `parts.SchLib`.| 12 |
| `05_topology_and_polarity.md`   | Swapped pins, wrong rail, wrong polarity, missing components.     | 15 |
| `06_cross_sheet_naming.md`      | Global/hier label typos, mis-routed FMC LA pins.                  | 10 |
| `07_bom_consistency.md`         | BOM xlsx ↔ netlist ↔ symbol library reconciliation.               | 8  |
| `08_provisioning_failsafe.md`   | POR / fail-safe / sequencing behaviors.                           | 10 |

Total: ~110 test cases. Many overlap intentionally (a single plant exercising
both linter and validator is fine — both should fire).

---

## Test case format

Every entry follows the same shape so a runner can parse it:

```
### <ID> — <Title>

**Description.** One paragraph: what's wrong and why it matters.

**Plant.**
- File: `<path>`
- Region: `<line range / yaml key / symbol name>`
- Before: <literal>
- After:  <literal>

**Detect.**
- Tool: <build | validator | linter | semantic | sim | bom_check>
- Rule/ID: <e.g. SERIESR_VDDA1 | _check_label_overlap | BLK_BIAS_FS_CEILING>
- Severity: <ERROR | WARNING | INFO>
- Expected message snippet: `"<substring>"`

**Fix.** What the closed-loop review should converge on — exact diff or net
behavior. Used to grade Plan/Apply outputs.

**Pass criteria.** Bullet list of boolean assertions a runner can grade.

**Anti-test (optional).** Adjacent scenarios that LOOK similar but should NOT
trigger this rule. Used for false-positive pressure.

**Notes (optional).** Citations to datasheets / design docs / memory entries.
```

---

## Severity rubric

| Severity | Meaning |
|---|---|
| ERROR    | Schematic is wrong on the board; must block fab. The closed-loop MUST fix or escalate. |
| WARNING  | Strong suspicion; usually fixed but may be a valid exception (e.g. DNP override). |
| INFO     | Cosmetic / informational. Closed-loop MAY ignore. |

Severity is set per-test in the **Detect** block. A single plant may produce
findings at multiple severities from different tools — record them all.

---

## Tool taxonomy

Each test cites which tool(s) should detect it. The full set:

| Tool | Command | Source |
|---|---|---|
| **build**       | `python -m test1.altium.build_project`                  | `test1/altium/build_*.py`                           |
| **validator**   | invoked from `build`                                    | `test1/altium/verify/`                              |
| **linter**      | invoked from `build`                                    | `test1/altium/layout_lint.py` (31 `_check_*` rules) |
| **semantic**    | invoked from `run_review`                               | `test1/review/rule_eval.py` + `rules.yaml`          |
| **sim**         | `python -m test1.sim.run_sim --block <id>`              | `test1/sim/decks/*.py` + `blocks.yaml`              |
| **bom_check**   | planned; not yet implemented                            | `test1_bom.xlsx` ↔ `netlist/*.yaml`                 |
| **closed-loop** | `python -m test1.run_review`                            | `test1/review/closed_loop.py`                       |
| **agent**       | Plan/Apply phases inside closed-loop                    | agent prompts under `test1/review/providers.py`     |

---

## Harness operating procedure

For each test case:

1. Ensure the working tree is clean (`git status` reports no diffs in `test1/`).
2. Apply exactly ONE plant (manual edit or recipe in the test case).
3. Run `python -m test1.altium.build_project`. Capture stdout + `lint.json`.
4. Run `python -m test1.run_review`. Capture review log + `findings.json` +
   any proposed `fix_queue.json`.
5. For sim-tagged tests, also run
   `python -m test1.sim.run_sim --block <id>` and capture the deck output.
6. Grade against the test case's **Detect** and **Pass criteria** blocks.
7. Revert the plant (`git checkout -- <files>`) before the next test.

A future runner should script steps 1–7 over every test ID in this folder, but
the harness must be revert-clean between tests — no two plants ever live in the
checkout simultaneously.

---

## Independence

Each test is independent. If a test depends on another (e.g. "PF-02 needs
PF-03 reverted first"), it must say so in **Notes**. Otherwise the runner
treats them as fully orthogonal.

When in doubt, prefer splitting a multi-fault scenario into multiple tests
over chaining plants.

---

## Out of scope

- PCB layout (Altium PCB-side rules — separate harness needed).
- Manufacturing DFM/DFA.
- Carrier-side (Genesys 2) firmware behavior.
- Anything outside `test1/`.

The harness validates the **schematic + sim + review** stack only.

---

## Conventions

- "Refdes" = reference designator (e.g. R40, C20, U10).
- "Net" = named net in YAML (e.g. `+3V3`, `BIAS0`, `LDO_SET_50mV`).
- "Block" = sim block in `blocks.yaml` (e.g. `opa_bias`, `ldo_rail`).
- "Sheet" = one of `bobcat | power | bias | eeprom | fmc | connectors`.
- "Setpoint name" = the per-bit label on TPS7A8401A ANY-OUT pins (currently
  mislabeled — see XS-01 / 06_cross_sheet_naming.md).
- "Schematic netlist" = the YAML files in `test1/netlist/`. These are the
  declarative source of truth; the SchDoc binaries are derived.

---

## Authoring new test cases

When adding a test:

1. Pick the category file (or add a new one if it's a genuinely new family).
2. Reserve the next sequential ID. Don't renumber existing IDs.
3. Fill all five mandatory blocks (Plant / Detect / Fix / Pass criteria; +
   optional Anti-test / Notes).
4. If the test depends on a tool that doesn't exist yet (e.g. `bom_check`),
   mark it with `**Status: tool not implemented**` so the runner can skip
   gracefully.
5. Prefer a single-file plant. Multi-file plants are harder to revert and
   harder to attribute when something fires.
6. Add the entry to that file's index at the top.

A test case should be small enough to reason about in 30 seconds. If it's
longer, it's probably two tests.
