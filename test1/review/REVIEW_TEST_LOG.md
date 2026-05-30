# Design-Review feature test log

## TL;DR — executive summary

Exercised every design-review feature (rules view, PDF, providers, findings +
structured summary, per-finding apply/dismiss, the full real closed loop, diff,
accept/reject/clear, roll-forward guard) against the live backend, with deliberate
failure injection. **One feature was completely broken; I fixed it. Two correctness
issues in the loop need attention. Several stale/dead pieces found. The safety
machinery (roll-forward guard, teardown, locks, fail-safes) all passed.**

**Fixed during testing (1):**
- **Per-finding Apply was 100% broken (HTTP 500 on every click).** `apply_finding`
  subscripted a `JSONResponse`. Fixed via `_findings_payload()` helper. Now
  200/400/404 correct. All 23 review unit tests still pass. (B2a)

**Needs your attention — correctness (❌):**
- **B3c/B3d — the loop can't tell a real fix from a documented punt.** On the one
  real finding (`CHK_VALUE_MATCHES_MPN`, the R40/R41 value↔MPN mismatch), the apply
  agent reasoned well — it documented the issue + correct fix in `design_intent.md`
  and *declined* to auto-edit (the fix needs a build-verified `.SchLib`). But the
  loop scored that apply `ok`, the finding never cleared, and it only "resolved"
  via nondeterministic re-eval. → Add a post-apply source-diff; if the subject is
  unchanged, mark `no-op/needs-human`, not `ok`.
- **B3d — finding flapping.** A semantic rule AND a sim_review rule returned
  different verdicts across rounds on an *unchanged* design → unreliable
  convergence. → Pin semantic determinism (temp 0 / cache by design-hash); make
  sim_review assert on a margin, not a knife-edge.
- **C6 — one invalid rule bricks the whole Rules UI + all reviews (HTTP 500).**
  `load_rules()` validates strictly with no isolation; the endpoint has no
  try/except. Since you can now hand-add/edit rules, a single bad `family`/`severity`
  blanks everything. → Catch → 422 with offending rule id, or skip-and-collect.

**Stale / dead (🗑️):**
- **A1 — the loop's "Lint fix" stage is dead code** — `plan_actions` never emits a
  `lint_fix` action (the dispatch handler is unreachable). The strip shows a stage
  that can never run. → wire it, or drop it.
- **A5 — rule-gen client is fully dead** — `api.ts` `generateRules`/`subscribeRuleGen`
  + types have zero callers after Regenerate was removed; backend `/generate*` (4
  routes) + `rule_gen.py` (525 lines) orphaned from the GUI. → delete the dead FE
  exports; decide whether to keep `/generate*` for CLI.

**Improve (⚠️):** B1b PDF separator mojibake · B2b Apply dead for rule-eval findings
(no `id`/`actions`) · B3f cancel latency ~54s (only checks between phases) · B3e
`findings_cleared` mis-reported in the round wire-format · A6/B3 SSE has no replay
buffer (late subscribers miss early eval events) · B1a `by_family` reports a stale
`simulation:0` key · A3 duplicate `_rebuild_project` + dup `_read_lint_failures`.

**Passed clean (✅):** rules list/PDF/providers · structured summary grouping
(families→blocks→other, conservation holds) · fix-queue dismiss · diff is
content-aware (no phantom boxes from rebuild noise) · **roll-forward guard catches a
revert-into-broken-build and rolls forward** (C1, the headline safety test) ·
clean-reject teardown · `/clear` · accept (tar+remove) · concurrent-loop 409 ·
malformed-findings fail-safe · SSE-to-done single frame · sim-cache-clear targets the
right blocks · 23/23 review unit tests.

**Restore:** design rebuilt clean (`FAILURES: none`), all injections reverted
(rules.yaml/bias.yaml/findings.json/fix_queue at baseline md5), test-loop snapshots
cleaned, `tsc` EXIT 0, backend healthy. Working tree net change = intended FE +
the app.py apply-fix + design_intent.md (agent's doc edit, flagged) + this log.

---

**Date:** 2026-05-30
**Scope:** Comprehensively exercise every design-review feature **except** add/subtract
rules (per request). Real closed loop end-to-end (full agents, real edits, real
rebuilds), with deliberate **failure injection**. Auto-restore after each mutation.
Runs are driven against the live backend (:8765) so they appear in the user's GUI
(:5173).

**Safety net:**
- git HEAD baseline `b1deb2a` (working tree clean except FE-only UI changes).
- Physical backup of mutable state at `/tmp/review_test_backup` (findings.json,
  semantic_findings.json, fix_queue.json, netlist/bias.yaml, gui/state/loops/,
  out/render_snapshots/).
- Baseline checksums recorded (bias.SchDoc / bias.yaml / rules.yaml).
- Restore: `git checkout -- test1/altium/out test1/netlist test1/review/rules.yaml`
  + copy back the physical backup for ignored state.

**Legend:** ✅ works · ⚠️ works-but-improve · ❌ broken/not-as-intended · 🗑️ stale/unused

---

## Part A — Static survey + code-review findings (before live runs)

The review surface (endpoints the GUI uses):

| Area | Endpoints |
|---|---|
| Rules (view) | `GET /api/review/rules`, `/rules/pdf`, `/api/review/providers` |
| Findings | `GET /api/findings`, `POST /api/findings/{id}/apply`, `DELETE /api/fix-queue/{id}` |
| Loop lifecycle | `POST /api/loop/start`, `GET /loop/latest`, `/loop/{id}`, `/loop/{id}/stream` (SSE), `POST /cancel` `/accept` `/reject` `/clear`, `GET /diff`, `GET /png_snapshot/{id}/{name}` |
| Rule-gen (RETIRED in UI) | `POST /rules/generate`, `/generate/latest`, `/generate/{job}`, `/generate/{job}/stream` |

### Code-review findings (to verify/така act on during live runs)

- **❌ A1 — `plan_actions` never emits a `lint_fix` action (CONFIRMED).**
  `lint_fix_targets` is declared at `closed_loop.py:372` and **never referenced
  again** (no append, not in the assembled `out`). The dispatch handler for
  `kind=="lint_fix"` exists (line 465) but is **unreachable** — the planner can't
  produce that action. Consequence: the "Lint fix" pipeline step can only ever
  render `skipped`; cosmetic lint ERRORs surfaced by a rebuild are never
  auto-fixed inside the loop. Mitigation in place: the build runs `auto_fix_*` so
  cosmetic nits get corrected at build time — so this is a dead code path rather
  than a functional gap, but the strip advertises a stage that never runs.
  Recommend: either wire lint ERRORs from the rebuild into a lint_fix action, or
  drop the dead step + handler.
- **⚠️ A2 — apply pass acts on the WHOLE changelog, not just this loop's targets.**
  `_dispatch_action` (apply branch) appends synthetic `closed_loop` changelog
  items for the targeted rule IDs, then calls `start_apply_pass()` which reads the
  *entire* changelog. If unrelated user/sim changelog items are present, the apply
  agent may act on them too. _Verify live: confirm the apply prompt scope._
- **⚠️ A3 — duplicate `_rebuild_project`.** Two functions same name, different
  signatures: `closed_loop.py:533` → `(status, lint_summary)`; `app.py:2617` →
  `(ok, log_tail)`. Not a bug (separate modules) but a maintenance trap.
- **⚠️ A4 — `emit()` silently drops on `QueueFull`** (`closed_loop.py:427`); SSE
  queue is `maxsize=1000` (`app.py:2575`). A very chatty round + slow client could
  drop events. _Verify live: event count vs received._
- **🗑️ A5 — rule-gen client is fully dead (CONFIRMED).** `api.ts` still defines
  `generateRules`, `ruleGenJob`, `ruleGenLatest`, `subscribeRuleGen` + the
  `RuleGenEvent`/`RuleGenSummary` types, but grep finds **zero** `.tsx` callers
  (the Regenerate button + pipeline viewer were removed last turn). Backend
  `/api/review/rules/generate*` (4 routes) + the rule-gen job machinery are
  correspondingly orphaned from the GUI. Recommend: delete the dead `api.ts`
  exports + types; decide whether to keep `/generate*` for CLI use or remove.
- **note A6 — `loop_stream` keeps no replay buffer.** A subscriber that attaches
  mid-round only sees events from attach time; if already done, gets a single
  `done` frame. Frontend compensates by polling `loopGet`. OK by design; note it.

---

## Part B — Live test runs

### B1 — Rules viewing (read-only) ✅

- **`GET /api/review/rules`** ✅ — 115 rules. families reconcile (80 schematic / 9
  design / 26 block); 88 structural / 27 semantic; 61 ERROR / 38 WARN / 16 INFO.
  8 block groups (opa_bias 7, ldo_rail 8, loadsw 3, vddio/vddd/vdda1/vdda2 pdn,
  eeprom 2). **11 sim_review rules** carry the "simulated" tag. `stale_sources: []`,
  no disabled rules. by_origin 114 generated + 1 user (`PULLDOWN_MOSI` — a real,
  long-standing rule that's hand-authored; NOT leftover test residue — the temp
  add/delete rule from the prior session is confirmed gone).
- **⚠️ B1a — `by_family` still reports a `"simulation": 0` key** (the retired
  family). Harmless (0 rules) but stale; the recount has no such key. Minor.
- **`GET /api/review/rules/pdf`** ✅ — valid `%PDF-1.4`, 10 pages, 30.6K chars.
  Title-Case section headers `General Checks (80)` / `Components` / `Blocks` →
  per-block; header line "115 active of 115 rules · generated … · exported …";
  rules listed with severity; block names + sim "simulated" marker present.
- **⚠️ B1b — PDF separator mojibake.** The PDF header renders
  `test1 � Design Review Rules` and `115 rules � generated …` — a separator char
  (· middot / em-dash) isn't encoding in the chosen reportlab font (Helvetica
  can't render it, or it's passed as a raw non-latin-1 byte). Cosmetic but visible.
  Fix: use an ASCII separator (`-` / `|`) in the PDF, or register a Unicode font.
- **`GET /api/review/providers`** ✅ — returns
  `{parts: WebSearchPartsProvider, knowledge: LocalPDFKnowledgeProvider,
  rulegen: ClaudeRuleGenProvider, chat: ClaudeChatProvider}`. (rulegen provider
  still wired even though the UI no longer triggers rule-gen — see A5.)

### B2 — Findings (summary + apply + dismiss)

**Setup:** structural-only `run_review.py` → **0 findings** (design is currently
clean on all 88 structural + 26 block-boundary rules; 27 semantic skipped). To
exercise the Findings UI I **injected** (INJECT #1) a rich findings.json: 6
findings (ERR 3 / WARN 2 / INFO 1) spanning all families + 2 blocks + 1 unknown
rule_id, each with valid hex `id` + fix/alt/verify `actions`. (Visible in the
user's GUI Findings panel during the test.)

- **❌→✅ B2a — per-finding Apply was 100% broken (HTTP 500); FIXED.** Root cause:
  `apply_finding` (app.py ~2122) called the `findings()` *route function* and then
  subscripted the result — but `findings()` returns a `JSONResponse`, which is not
  subscriptable → `TypeError` → unhandled → **HTTP 500 on every Apply click**. This
  is a regression from when `/api/findings` was wrapped in `JSONResponse` to add a
  `Cache-Control: no-store` header without updating the internal caller.
  **Fix:** extracted `_findings_payload() -> dict`; the route wraps it in
  JSONResponse, `apply_finding` calls the dict helper directly. (The other internal
  caller, `_refresh` at line 344, was already correct — it `json.loads(resp.body)`.)
  Verified after backend restart: apply→**200** (queue shows `queued:1`),
  out-of-range idx→**400** (was 500), nonexistent id→**404** (was 500), bad-format
  id→**400**, re-apply idempotent (queue stays 1). _The user could not apply ANY
  review finding before this fix._
- **⚠️ B2b — Apply only works for findings that carry `id` + `actions`.** Those come
  only from the **Voltai-PDF parser** path (`install_review.py`). `render.write_json`
  (used by run_review.py AND implicitly the closed-loop's finding shape) writes
  `rule_id` but **no `id` and no `actions`** — so rule-eval / loop findings are
  **not apply-able** via this endpoint (the cross-check 404s them). This is arguably
  by-design (the loop applies its own findings via the apply agent), but a user
  staring at rule-eval findings in the panel has a dead Apply control for them.
  Recommend: hide/disable Apply for findings without `actions`, or synthesize a
  generic action.
- **✅ B2c — structured Summary grouping** verified end-to-end against the live
  injected data via the real `/api/findings` + `/api/review/rules`: general checks
  2 ERR · components 1 WARN · blocks {opa_bias 1 ERR, ldo_rail 1 INFO} · other/linter
  1 WARN (the unknown rule_id correctly bucketed — nothing dropped). Conservation
  holds (Σ families == grand total). Severity bar + table render this.
- **✅ B2d — fix-queue dismiss** (`DELETE /api/fix-queue/{id}`): removes entry
  (`removed:1`), idempotent (`removed:0` repeat), validates id (400 on bad format).

**Infra note:** backend on :8765 was running as `python app.py` (system Python,
**no --reload**) → had to **restart** to load the apply fix. Also cleaned a stray
2nd `app.py` (venv python, pid 8624, bound to nothing). Relaunched once on the
canonical venv python; healthy in 1s; injected findings survived (on disk).

### B3 — Full REAL closed loop (loop `74df8e1d`, visible in GUI)

Started via `POST /api/loop/start` after resetting findings.json to []. **Forward
path fully exercised and correct:**
- **Initial eval** ran all 115 rules (88 structural instant + 27 semantic via
  `claude -p`, interleaved off-thread). SSE streamed `eval_progress` per rule with
  pass/fail + evaluation type — exactly what the GUI loop console shows. ✅
- **Result: exactly 1 finding** — `CHK_VALUE_MATCHES_MPN` (semantic FAIL). The
  evaluator **correctly caught the known real issue**: R40/R41 value=3.65k but
  lib_id still the 5.11k MPN (TNPW06035K11BEEA). Strong signal the semantic
  evaluator works on a genuine discrepancy (not a toy). ✅
- **Plan → dispatch:** `loop_start(1)` → `round_start(1)` → `action_start` with
  `kind=apply, targets=[CHK_VALUE_MATCHES_MPN]` → real apply agent
  `c850b3dfdcea` spawned (5 `claude` procs). ✅
- **Snapshot at start:** `out/render_snapshots/74df8e1d/` with render/, netlist/,
  lint.json, findings_initial.json (`[]`). ✅
- **`GET /diff`** (mid-run, no edits yet): all 6 sheets +0/-0/~0, each with
  `viewBox` + `snapViewBox` present. **`GET /png_snapshot/{id}/bias`** → 200 (69KB);
  bad sheet → 404. ✅
- **✅ A6 confirmed live:** SSE has **no replay buffer** — my stream attached a beat
  after start and captured only 38/115 eval_progress events (missed the early
  structural ones). Frontend compensates by polling `loopGet` (summary `initial:1`
  was always correct). Working-as-designed, but a late-attaching client's console
  shows a partial eval. Consider a small ring-buffer replay on attach.
- **⚠️ B3a — apply agent is VERY slow for MPN reconciliation.** The single
  `CHK_VALUE_MATCHES_MPN` apply ran 8+ min without completing (likely web-searching
  for a real 3.65k 0.1% MPN + authoring a symbol). No progress visibility on the
  *substep* (web search vs edit vs build) from the loop summary — the action just
  says "running". The per-agent reasoning stream (GUI dropdown) is the only window
  in. Consider surfacing a coarse substep label. _Decision: cancelled to proceed
  with diff/accept/reject + injection tests on a faster controlled finding (B4)._
- **⚠️ B3b — `/api/run/{agent_id}` returns empty shape for loop sub-agents**
  (`status:None, log:[]`). The loop's sub-agent runs aren't exposed via the
  top-level `/api/run/{id}` the way I queried; the GUI uses a different
  (stream_run) path. Not a bug, but the run-status endpoint is misleading for
  sub-agent ids.

**The loop ran to round 2 then I cancelled it. Critical findings:**
- **❌ B3c — apply reported `ok` but the finding it targeted was NOT fixed (and the
  loop can't tell).** The `CHK_VALUE_MATCHES_MPN` apply ran ~9.4 min → status `ok`.
  `bias.yaml` (where R40/R41 live) is **byte-identical to baseline**; no netlist/
  builder change. **BUT** the agent DID make one persistent edit: it appended a
  thorough, accurate explanation to **`test1/design_intent.md`** — documenting why
  R40/R41 are 3.65k (FS-ceiling), the exact MPN mismatch, the correct fix (repoint
  lib_id to a 3.65k TNPW0603 part e.g. TNPW06033K65BEEA + author a matching
  `.SchLib`), and explicitly: *"This requires a build to verify — it was left for a
  human / build-capable pass, not auto-applied."* So this is **good agent
  judgment** (document + decline a fix it can't safely complete), NOT a do-nothing.
  The real defect is in the **loop's accounting**: it treats "agent exited 0 +
  wrote a note" as a successful apply (`ok`), but the finding stays failed → the
  loop has no "acknowledged / not-fixable-here" state and can't distinguish a real
  fix from a documented punt. Recommend: after an apply action, **diff the design
  source**; if the targeted finding's subject is unchanged, mark the action
  `no-op`/`needs-human` (not `ok`) and stop counting it as progress. (This is the
  root of B3d's apparent flapping: the loop never truly resolved the finding.)
  **NOTE for the user:** the design_intent.md edit is correct & useful — I left it
  in the working tree rather than reverting a good improvement; review + keep/drop.
- **❌ B3d — finding flapping (semantic + sim_review nondeterminism).** Round 1:
  start {CHK_VALUE_MATCHES_MPN}; after apply+rebuild re-eval = {CHK_VALUE_MATCHES_MPN,
  **BLK_BIAS_FS_CEILING**} (a sim_review rule newly fired with NO source change).
  Round 2: re-eval → **0** findings (both gone, again with no source change). So
  both a semantic rule (CHK_VALUE) and a sim_review rule (BLK_BIAS_FS_CEILING)
  returned **different verdicts across rounds on an unchanged design** — LLM
  nondeterminism + sim variability. This makes loop convergence unreliable and can
  manufacture/clear findings spuriously. Recommend: pin semantic eval determinism
  (temp 0 / cache per (rule, design-hash)); for sim_review, ensure the sim is
  deterministic or assert on a stable margin, not a knife-edge.
- **❌ B3e — `findings_cleared` mis-reported.** Round 2 settled at `2 -> 0,
  build: ok` (finalized) but `findings_cleared: []` and `findings_new: []`. With
  before=2/after=0 it should list the 2 cleared rule_ids. The delta math
  (`old_ids - new_ids`, closed_loop.py ~630) is right in principle, but the
  serialized round showed empty — likely `L.findings_current` was already mutated,
  or the round serialized between `findings_after` (line 629) and `findings_cleared`
  (line 634). Either way the Round wire-format can show inconsistent
  before/after/cleared. _Confirmed at terminal state, not just mid-flight._
- **⚠️ B3f — cancel latency ~54s.** `POST /cancel` returned `{ok:true}` immediately
  but status stayed `running` for ~54s — `L.cancelled` is only checked between
  rounds/actions (closed_loop.py 593/605), not inside the long re-eval
  `to_thread` (line 626) or a running apply. A user hitting Cancel during eval/apply
  waits out that whole phase. Recommend: pass a cancel check into the eval worker
  (abort between rules) and document the "cancels at the next safe point" behaviour.

### B4 — Diff & Accept / reject / roll-forward / teardown (loop `74df8e1d`)

- **✅ Diff is content-aware.** Despite out/*.svg differing by rebuild noise, `/diff`
  reported **+0/-0/~0** on all 6 sheets (real component positions unchanged). Shape
  correct: `viewBox, snapViewBox, added, removed, changed, count`. So the diff won't
  show phantom boxes from a no-op rebuild. ✅
- **✅ Reject + roll-forward guard.** `POST /reject {}` → `ok:true,
  rolled_forward:false` (clean revert, no worsening → no roll-forward), rebuild
  after revert `FAILURES: none` (0/0 all sheets). The **worse-state branch** (where
  it should roll forward) is exercised separately under injection (C-series).
- **✅ Teardown after clean reject.** Snapshot dir removed; closed_loop changelog
  items cleared (0). This is the prior-session "can't clear changelog/cache" fix
  working. (Note: changelog already had 0 closed_loop items pre-reject — the
  synthetic apply-dispatch items didn't linger.)
- **✅ png_snapshot** 200/404 (tested in B3).

### C — Failure injection (each auto-restored)

- **✅ C1 — roll-forward guard, WORSE-STATE branch (the critical safety test).**
  Started a fresh loop (snapshot of the good design), cancelled it (post-loop ==
  good), then **corrupted the snapshot's bias.yaml** (the revert target). `POST
  /reject` → reverted to the corrupt snapshot → rebuild **failed** → guard detected
  worse → **rolled forward** to the good post-loop state → rebuilt clean
  (`FAILURES: none`). Response `ok:false, rolled_forward:true, reason:"Revert
  produced a worse state (rebuild failed); rolled forward…"`. Verified live design
  is the GOOD baseline (bias.yaml md5 matches, not the corrupt marker); snapshot
  KEPT (correct — roll-forward preserves it for retry). **This is the headline
  safety mechanism and it passed.**
- **✅ C2 — malformed findings.json** → `/api/findings` fail-safes to empty (HTTP
  200, 0 findings) via the JSONDecodeError guard. No 500.
- **✅ C3 — concurrent loop start** → second `POST /loop/start` returns **409**
  `{"detail":"loop … already running"}`. Single-loop lock works.
- **✅ C4 — SSE attach to a done/cancelled loop** → single `done` frame with correct
  status, then closes (no hang for late subscribers).
- **✅ C5 — /api/loop/{id}/clear** (manual clear) → `snapshot_removed:true`,
  changelog drained, `/diff`→empty, **live design untouched** (bias.yaml baseline).
  The prior-session "clear cache / delete these" control works.
- **⚠️ C5b — `/diff` for a NONEXISTENT loop returns 200 `{sheets:{}}`** (vs 404 for
  `/loop/{id}` and `/png_snapshot`). `compute_loop_diff` returns `{}` when the
  snapshot dir is absent. Benign (frontend shows "no diff") but inconsistent.
- **❌ C6 — one invalid rule takes down the ENTIRE Rules UI + all reviews.** Two
  variants, both → **HTTP 500**:
  - C6a: a *syntactically* broken rules.yaml (bad indentation) → `yaml.ParserError`.
  - C6b: *well-formed YAML* but schema-invalid rule (`family: banana`, empty
    `source`) → Pydantic `ValidationError`.
  `load_rules()` validates strictly with **no error isolation**, and
  `/api/review/rules` has **no try/except**, so a single bad rule returns an opaque
  500 and **blanks the whole Rules panel + blocks every review** (load_rules is
  shared by eval too). Since the user can now **hand-add/edit rules**, a typo in a
  `family`/`severity` value bricks the review subsystem. Recommend: catch the
  validation/parse error in the endpoint → 422 with the offending rule id + reason;
  or skip-and-collect invalid rules into a "rejected rules" list surfaced in the UI
  (like `stale_sources`). Verified rules.yaml fully restored after each (md5
  `afe2317…`, 115 rules).

### Injections NOT run (and why)
- **agent-cancel-mid-apply**: partially covered — I cancelled loop `74df8e1d` during
  re-eval (B3f: ~54s latency). A cancel *during the apply agent's edit* would test
  `cancel_run` killing the subprocess; deferred to avoid another 9-min agent run.
- **double-revert / reject-twice**: the roll-forward guard (C1) is the generalized
  protection; an explicit second reject on a torn-down loop would 404 (snapshot
  gone) — low value.
