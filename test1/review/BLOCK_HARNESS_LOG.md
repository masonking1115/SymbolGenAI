# Block-rule harness — build & test process log

Standing request (2026-05-30): *"along this process, monitor any tests and log
the process as to look for bugs in the workflow."* This file logs each build/test
step, what passed/failed, and any workflow bug found, so the harness work itself
is auditable.

## Goal
A dedicated `block` rule family + a stress-test harness that validates each
functional block's **boundaries** against requirements, datasheets, and EE first
principles. Headline bias concerns (user-selected):
  #1 op-amp headroom / full-scale current ceiling (OPA2388 single-supply can't
     drive the PMOS gate below GND → loop saturates below the 646 µA ideal).
  #4 sense-R tolerance + Vos/INL accuracy budget vs the ~1 µA-step / FS spec.
Blocks: bias + LDO at minimum, plus load switch + PDN at my discretion.

## Process log

### Step 0 — survey (done)
- rule_eval splits fast (structural) vs slow (semantic + sim_review); slow gated
  behind `semantic=True`, run concurrently. `block` family will piggyback on the
  existing `sim_review` (real ngspice + judge) and `semantic` (datasheet reasoning)
  evaluation modes — both already route to the `apply` bucket in closed_loop
  plan_actions, so **no orchestrator change needed**.
- blocks.yaml already encodes each block's boundary params + `pass:` criteria —
  the ground truth the block rules cite.
- design_extract gives netlist-true component values (sense_resistance(), etc.).
- opa_bias deck already has dc_sweep (reports i_max_regulated_A — the #1 ceiling)
  and dc_compliance (0.5 V headroom). The block rules will *judge those outputs
  against the spec*, which the generic sim_pass did not (pass-by-absence bug).

### Step 1 — schema + harness + rules authored (done)
- `rule_schema.Family` += `"block"`.
- `block_harness.py` — loads block-family rules, runs each through the SAME
  `rule_eval.run_all` path (one rule at a time for per-rule timing, shared sim
  cache), logs start/finish/verdict, renders a per-block stress report, exit 1
  on any fired ERROR rule. CLI: `--block`, `--no-sim`, `--json`.
- `gen_block_rules.py` — code-built, schema-validated, idempotent merge of 10
  block rules into rules.yaml (replaces BLK_* on re-run, preserves the rest).

10 block rules (96 total now):
  BLK_BIAS_FS_CEILING       (sim_review dc_sweep)      #1 headline — FS ceiling vs 640µA
  BLK_BIAS_COMPLIANCE_0V5   (sim_review dc_compliance) 320µA @ 0.5V, drain headroom
  BLK_BIAS_ACCURACY_BUDGET  (semantic)                 #4 headline — 0.1%R + Vos + INL
  BLK_BIAS_LOOP_STABILITY   (sim_review ac_stability)  peaking ≤3dB
  BLK_BIAS_POR_FAILSAFE     (sim_review por)  ERROR     ≤1µA at POR
  BLK_LDO_SETPOINT_COVERAGE (sim_review setpoint_coverage)
  BLK_LDO_DROPOUT_MARGIN    (semantic INFO)
  BLK_LDO_LINE_REG          (sim_review line_regulation)
  BLK_LOADSW_DEFAULT_OFF    (semantic)  ERROR
  BLK_PDN_VDDIO_DROOP       (sim_review transient_load_step)

### BUGS / friction found so far (workflow-bug hunt)
1. **gen_block_rules `_sim()` missing `net=` kwarg** — `BLK_PDN_VDDIO_DROOP`
   passed `net="+VDDIO"`; `_sim` only had `refdes`. TypeError at build time.
   FIXED (added `net` param, threaded into AppliesTo). [generator bug, not pipeline]
2. **No venv at the memory-recorded path** (`altium_spike/.venv`) on this run —
   fell back to system Python 3.12 (pydantic 2.12.5, yaml, numpy all present).
   Not a code bug; noting in case the GUI backend launch script hardcodes the
   venv python. → TODO: verify backend launch still resolves an interpreter.
3. **Must run from `SymbolGenAI/` (the package root), not repo root** — `test1`
   is the top package. `cd` persistence in the Bash tool bit me once. Not a bug.

### Verified clean (no bug)
- `_clear_sim_cache_for_review` (closed_loop) already guards
  `isinstance(StructuralRule) and kind=='sim_review'` → auto-picks up the new
  block sim_review blocks (opa_bias/ldo_rail/vddio_pdn) for fresh re-sim, and
  skips semantic rules without KeyError. Block rules are first-class here.
- `plan_actions` routes all 10 block findings → one `apply` action (semantic +
  sim_review both bucket to apply). No crash on the new family.
- All 96 rules still validate against the schema after the merge.

### Step 2 — harness run, bias block (DONE — concern #1 CONFIRMED)
`python -m test1.review.block_harness --block opa_bias` → 4 rules, 33.8s:

  ✗ BLK_BIAS_FS_CEILING (11.0s) — **FIRED, the headline #1 result**
      "i_max_regulated_A is 484.3 µA, which falls short of the required 640 µA
       spec maximum — the loop saturates and cannot deliver the top of the range."
  ✓ BLK_BIAS_COMPLIANCE_0V5 (9.7s)
  ✓ BLK_BIAS_LOOP_STABILITY (4.8s)
  ✓ BLK_BIAS_POR_FAILSAFE (8.1s)

**This is the whole point of the block family.** Direct sim of opa_bias/dc_sweep
reports `overall=OK` (linearity error 0.013% WITHIN the regulated range) AND
`full_scale_A=645.8µA` but `i_max_regulated_A=484.3µA`. The deck's OK flag scores
only accuracy inside the regulated band — it does NOT flag that the OPA2388
single-supply output headroom caps the loop at ~484 µA, i.e. the block cannot
reach the top ~24% of its specified 0–640 µA range. The old `sim_pass` rule
passed by absence. `BLK_BIAS_FS_CEILING` judges `i_max_regulated_A` vs the 640 µA
spec and fires — exactly user bias concern #1, validated by physics + the sim.

### BUG #4 (workflow) — harness `--json` crashed: parent dir missing
`review/state/` didn't exist → `Path.write_text` FileNotFoundError at the very
end (the full run + report had already completed; only the optional JSON dump
failed). Caught precisely by the "monitor tests / log for bugs" directive.
FIXED: `args.json.parent.mkdir(parents=True, exist_ok=True)` before write.
Severity: low (cosmetic, post-run), but it would have bitten the GUI/CI path
that passes `--json` into a fresh state dir.

### Step 3 — full 10-rule suite (DONE — 10 rules, 137.0s, 1 fired, 0 ERROR)
`python -m test1.review.block_harness` (all blocks):

  bias       1/1 ok   BLK_BIAS_ACCURACY_BUDGET ✓ (66.2s — #4, agent did the full
                      tolerance stack-up; PASS = budget closes over usable range)
  ldo_rail   2/2 ok   BLK_LDO_SETPOINT_COVERAGE ✓, BLK_LDO_LINE_REG ✓
  opa_bias   3/4      BLK_BIAS_FS_CEILING ✗ (#1, 484µA<640µA), others ✓
  power      2/2 ok   BLK_LDO_DROPOUT_MARGIN ✓, BLK_LOADSW_DEFAULT_OFF ✓
  vddio_pdn  1/1 ok   BLK_PDN_VDDIO_DROOP ✓

Net: the suite is sensitive (catches the real FS-ceiling shortfall) AND specific
(the 9 boundaries that genuinely hold all pass — including the ERROR-severity
safety rules POR-failsafe + load-switch-default-off, so exit code is 0). The
#4 accuracy rule taking 66s (vs ~6s for the others) confirms the agent actually
computed the stack-up rather than fail-safe-passing on a timeout.

### LIMITATION (documented, not fixed — honors "don't fundamentally change the linter")
`rule_eval.run_all` returns a Finding (with `observed`) only on FAIL; on PASS it
returns nothing. So the harness shows the observation for FIRED rules but
`observed` is EMPTY for PASS rules — we see WHY something failed, not the computed
numbers behind a pass (e.g. the accuracy rule's per-term error %). Surfacing PASS
reasoning means changing the shared evaluator's return contract; left as-is and
flagged for a future opt-in (harness-only verbose judge that returns observed on
pass too).

### Workflow-bug hunt — FINAL tally
  #1 generator `_sim()` missing `net=` kwarg — FIXED.
  #2 no venv at memory-recorded path — env note (system py 3.12 works), not a bug.
  #3 must run from SymbolGenAI/ package root — usage note.
  #4 harness `--json` parent dir missing — FIXED (mkdir parents).
  #5 shell `> state/...log` redirect into a MISSING dir reported "completed exit 0"
     but the harness NEVER RAN (the redirect failed before exec, so the whole
     `python -m ...; echo` chain was skipped). A FALSE-SUCCESS trap — a green exit
     code hiding a no-op run. Caught by reading the actual log (empty) rather than
     trusting the exit status. Mitigation: create state/ up front; in CI, assert
     the log is non-empty. Most insidious of the five.
  Limitation (above): PASS observations not surfaced — documented.

### Outcome
Block family + harness are live: schema, 10 rules, harness, run_review count, and
closed-loop routing all verified. User bias concerns validated — #1 (FS ceiling)
FIRES with the real 484µA number; #4 (accuracy budget) is computed and closes.
ngspice + judge agents run clean end-to-end in ~2.3 min for the 10 rules.



---

## Topology trade study (640µA assumed real) — test1/sim/topology_study.py

Throwaway experiment (NOT wired into review). Reuses production models
(models.opa_models) + the real ngspice runner. Acceptance: FS≥640µA reg,
nominal 320µA±1% with BIAS0 held at 0.5V, PMOS drain ≥0.5V.

### ROOT-CAUSE CORRECTION (a real workflow lesson)
My first paper analysis blamed the op-amp single-supply OUTPUT SWING. The sim
disproved it: sweeping the op-amp V- from 0 → -2.0V moved the ceiling only
491→547µA and then SATURATED — a negative rail does NOT fix it. Dumping node
voltages at the ceiling showed why: at high current VSENSE collapses to ~0.5V
because 640µA × 5.11k = 3.27V is dropped across R_sense, consuming the entire
3.3V supply and leaving ~0V for the PMOS V_SD + the 0.5V DUT compliance.

**True binding constraint = the VOLTAGE BUDGET, not op-amp swing:**
    3.3V = I_FS·R_sense + V_SD(pmos) + V_DS(isolator) + V_compliance(0.5V)
At 640µA with 5.11k, I·R alone = 3.27V → infeasible. The limit is DOWNSTREAM of
the gate, so Option A (negative rail) can't help. Lowering R_sense IS the physics
fix because it shrinks the I·R term. This is why the earlier "lower R" result
worked on the ceiling — for the right reason, which I had mis-attributed.

### Measured verdicts (fine 0.01V sweep grid)
  topology                         FS_ideal  i_max_reg  ≥640?  i@nom   nom_err  drain   verdict
  baseline single-supply 5.11k       646u     491µA      no    320.9µ   0.29%   0.50V   fail
  Option A neg-rail (-1.0V) 5.11k    646u     547µA      no    320.9µ   0.29%   0.50V   fail  ← rail doesn't help
  R-fix 3.65k single-supply          904u     684µA     YES    320.5µ   0.17%   0.50V   PASS
  R-fix 3.32k single-supply          994u     751µA     YES    319.3µ   0.23%   0.50V   PASS
  Option B mirror 3.65k              904u     448µA      no    327.1µ   2.20%   0.50V   fail  ← mirror lossy+offset

### Conclusions
- **No new topology is needed to hit 640µA — it's a component-value (R_sense)
  fix.** R_sense ≈ 3.32k–3.65k 0.1% reaches the regulated ceiling >640µA AND
  re-centers nominal 320µA within 0.2% AND holds 0.5V drain. (3.65k leaves more
  high-side headroom; 3.32k more ceiling margin.)
- Option A (negative op-amp rail) is the WRONG fix — added cost, doesn't move the
  binding constraint. Ruled out by sim.
- Option B (low-side sense + PMOS mirror) removes the op-amp swing concern but the
  behavioral mirror already shows matching loss (448µA ceiling, 2.2% nominal err)
  before any real device mismatch is added — more parts, worse accuracy. Ruled out.
- CAVEAT: the earlier --block harness run at 3.24k FAILED nominal (315.7µA) — that
  was the PRODUCTION deck's coarse 0.033V sweep grid landing off the 320µA point,
  NOT a physics fail. The fine grid here lands 319-320µA. → if a value-change is
  adopted, also confirm against the production dc_compliance grid (or refine it).
- Absolute current numbers are behavioral-model-grade (PMZ1200/2N7002 are level-1
  KP-tuned for loop dynamics, not saturation precision). The RELATIVE ranking and
  the voltage-budget root cause are robust; a real-silicon sign-off wants vendor
  SPICE models for the pass FET + isolator.

### Recommendation to user
Keep the topology. Change R40/R41 5.11k → ~3.32k–3.65k 0.1% (one-line netlist
edit, flows through design_extract automatically). Then either tighten the
production dc_compliance sweep step or accept the grid note above. Negative-rail
and current-mirror topologies are measurably worse — ruled out by sim, not opinion.

---

## Applied R40/R41 5.11k → 3.65k 0.1% + refined dc_compliance grid (option (a))

### Production harness, opa_bias, R=3.65k
  step 1 (coarse 0.033V grid, as-built deck):
    FS_CEILING ✓ 669µA (clears 640!)   COMPLIANCE ✗ 316.44µA / 1.114%   STABILITY ✓   POR ✓
    → the 1.11% nominal FAIL was a SWEEP-GRID artifact (predicted by the trade
      study: 0.033V step lands the nominal sample up to ±16mV ≈ 5µA off 320µA).
  GRID FIX (opa_bias.py compliance mode): dc VDAC step 0.033 → 0.01 V.
    Pure measurement-resolution change (more sweep points); no behavior/criteria
    change. analyze_compliance picks the nominal point by nearest-V_DAC, so the
    finer grid samples 320µA accurately. (dc_sweep mode left at 0.033 — it scores
    a ceiling, not a point, so it's grid-insensitive.)
  step 2 (refined 0.01V grid, cache cleared):
    i_at_nominal = 320.54µA, nominal_err 0.17%, drain 0.50V, overall OK.
  FULL agent-judged harness @ 3.65k: 4/4 rules PASS, 0 fired, 32.3s.
    ✓ FS_CEILING  ✓ COMPLIANCE_0V5  ✓ LOOP_STABILITY  ✓ POR_FAILSAFE(ERROR-gate)

### WORKFLOW BUG #6 (real, fixed) — coarse compliance sweep grid false-fails nominal
The production dc_compliance deck swept V_DAC at 0.033V. Because the nominal-point
check is a nearest-sample pick, any R_sense whose 320µA V_DAC falls between grid
points reads several µA off and trips the 1% rule — a measurement artifact, not a
design fault. It was masked at 5.11k (320µA happened to land near a grid point)
and only surfaced when R changed. FIXED by refining to 0.01V. This is the most
useful bug the whole exercise found: a latent false-fail that would mis-judge ANY
future R/topology change. (Caught exactly per the "monitor tests / log bugs" ask.)

### State of the tree right now
- test1/netlist/bias.yaml: R40/R41 = 3.65k 0.1% (APPLIED — pending user keep/revert)
- test1/sim/decks/opa_bias.py: compliance sweep 0.033 → 0.01V (KEEP regardless —
  it's a correctness fix independent of the R value)
- /tmp/bias.yaml.bak holds the 5.11k snapshot for clean revert if requested.

---

## Schematic note added + RENDER/LINT VERIFIED (env resolved)

- altium_monkey lives in the spike venv at:
  C:\Users\mking\Downloads\altium_spike\.venv\Lib\site-packages\altium_monkey
  (venv is in Downloads\altium_spike, NOT inside SymbolGenAI — corrects the
  earlier "no venv found" note; memory altium-environment-setup should point here).
  Build/lint interpreter: ...\altium_spike\.venv\Scripts\python.exe
- Added sense-R design-decision note (build_bias.py): two lines at x=9000,
  y=6950/7100, next to the R40/R41 column:
    "R40/R41 = 3.65k 0.1%: sets 0-640uA FS."
    "(5.11k capped FS at ~484uA - V budget)"
- bias.yaml R40 note updated + R41 note added to match the sheet.
- `python -m test1.altium.build_bias` → "validated OK | wrote bias.SchDoc + bias.svg".
- `python -m test1.altium.layout_lint` → **[bias] layout-lint: clean** (note does
  not overlap symbol/label/edge). The 6 WARNINGs are all pre-existing bobcat
  +VDDD/+VDDIO power-stub items, untouched by this work.
- OPEN: R40/R41 lib_id still = Lib:TNPW06035K11BEEA (the 5.11k MPN) — value/notes
  say 3.65k but the BOM part is stale. Needs a real 3.65k 0.1% MPN + UL symbol.
