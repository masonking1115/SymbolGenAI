# TODO

Deferred work items (not blocking; pick up when convenient).

## Review — sim in the loop (IN PROGRESS 2026-05-30)

- [ ] **Include simulation in the review evaluation, driven by an agent.** The
      review's sim_pass/sim_metric rules currently pass-by-absence (no sim data →
      return True). Wire the sim subsystem into the closed loop so an agent reads
      the requirements, dynamically derives the test parameters (sim_setup writes
      sim_config), runs the sim (run_block_sim), iterates (iterate_sim, cap 3),
      and reports a verdict — and feed those results into run_all(sim_results=...)
      so the rules evaluate for real. TWO defects found:
        1. Phantom block names — rules reference bias0/bias1/ldo_out/loadsw which
           DON'T exist; real blocks are opa_bias, ldo_rail, vddio_pdn/vddd_pdn/
           vdda1_pdn/vdda2_pdn. Must remap the sim rules to real (block, sim_type).
        2. closed_loop runs the sim but calls run_all with sim_results=None on
           re-eval, and doesn't reshape results into {(block,sim_type): result}.

- [ ] **Review why a changelog item is still attached to ldo_rail /
      transient_powerup.** It should have been consumed/cleared by now — figure
      out why it's lingering (not drained after apply? re-added each run? stale
      sim suggestion?) and clear the root cause.

- [ ] **Clear the simulation cache when starting a design review**, so sim_review
      rules run from scratch (no stale scenario/result reused). Wire a cache clear
      into the loop start (and/or run_review) before the sim_review evaluation.

## UI / GUI

- [ ] **Surface the changelog directly in the Schematic Generator tab**, under the
      Regenerate button (and above the Linter checklist). The user should be able to
      ADD to and VIEW the changelog from the Generator tab itself — not only from the
      Agent rail. Reuse the existing add/view/delete/clear logic from
      `AgentRail.tsx` → `ChangelogPanel` (extract it into a shared component so both
      places stay in sync). The Agent rail (AI chat) must stay UNCHANGED and identical
      across all tabs — chat is the only thing that lives there now.

- [ ] **Collapse the changelog into a dropdown when it has more than 3 bullets**,
      like the Linter checklist (show a count + expand/collapse). Under 3 stays
      expanded inline. Applies to the shared ChangelogPanel.

## Simulation → changelog flow

- [ ] **Reflect sim suggestions in the UI the moment they're added to the changelog,
      and mark them PENDING until applied.** In the Simulation window, when a suggested
      change is added to the changelog (the "Add to changelog" action on an interpret
      SUGGESTION), the suggestion's row should immediately update to a "added / pending"
      state (not stay as a fresh, un-actioned suggestion). The corresponding changelog
      item stays flagged **pending** until the apply pass actually implements it (then
      it clears / shows applied). I.e. give sim-originated changelog items a lifecycle:
      suggested → pending (in changelog) → applied. Ties into the existing
      source="sim" + sim_block/sim_type tagging and the decisions.json
      (APPLIED/STOPPED/CLARIFY) outcome record so "applied" can be detected reliably.

## Closed-loop design review — done

- [x] **Widen semantic-evaluator context (2026-05-30).** Each semantic rule's
      prompt now includes the FULL membership of every net its subject touches
      (with each member's value), so a pull-up/down wired through a series
      resistor on the same node is visible. Fixes false positives where the
      evaluator only saw the subject's own pins. Verified: the LDO PG node now
      shows R12 (10k→+3V3) and the rule passes.
- [x] **Fixed the 2 false-positive semantic rules (2026-05-30).**
      `SEM_MCP4728_VREF_EXTERNAL` disabled (the MCP4728 has no VREF pin — it's an
      EEPROM config bit selecting VDD, not schematic-checkable).
      `SEM_LDO_PG_OPEN_DRAIN` prompt sharpened to accept a pull-up via a series
      resistor (now PASSes against the real design).
- [x] **Per-agent reasoning dropdown (2026-05-30).** Each spawned agent in the
      Iteration view (loop sub-runs) is now its own collapsible row; expanding it
      shows that agent's live "doing + thinking" stream (tool calls, assistant
      lines, thinking: lines) via LiveConsole — auto-opens while running. Backend
      `stream_run` now replays the full `stream_log` (and falls back to the
      persisted `state/runs/<id>.log` if the run isn't in memory, e.g. after a
      restart), so reasoning is visible live AND after the fact.

- [x] **Wire semantic-rule evaluation (2026-05-30).** The 8 SemanticRules were
      previously deferred no-ops, so the loop had nothing to iterate on and
      reported "all_clear" instantly. `rule_eval.run_all(semantic=True)` now
      evaluates each via a read-only `claude -p` verdict (rule prompt + cited
      source quotes + the applies_to sheet's parts → strict PASS/FAIL JSON →
      Finding). Fail-safe (timeout/parse error → no finding). Threaded into
      `closed_loop` via `asyncio.to_thread`. Structural fast path unchanged
      (semantic defaults off). Verified end-to-end: 6 PASS / 2 real FAIL
      (U40 VREF, U10 PG open-drain stub).
- [x] **Clean-loop UX (2026-05-30).** A loop that starts with 0 findings now
      says "Already clean — passes every review rule" instead of "resolved in 0
      rounds", and `startLoop` fetches the summary directly so an instant
      completion always shows a result (no dependence on SSE timing).

## Closed-loop design review — deferred follow-ups (2026-05-29)

These were attached to the closed-loop spec but are tracked here. Items #2 and #3
are already covered by the main spec (Diff & Accept section); #1 is a verification
step that lives in the implementation plan, not a separate feature.

- [ ] **Verify the iteration-view monitoring catches the generation after it
      starts.** The closed-loop SSE (`/api/loop/{id}/stream`) and the existing
      per-AgentRun streams must not drop the start of a generation/apply sub-run
      (the documented race in `subscribeAgent` is settled-on-CLOSED + watchdog; the
      replay-then-attach pattern in `_stream_subprocess` should cover late
      subscribers, but verify end-to-end with a real loop run that the first event
      reaches the timeline before the first round completes).
- [ ] **Side-by-side schematic diff toggle next to the schematic.** Covered by the
      Diff & Accept section of the closed-loop spec — pre-loop SVG snapshot
      (`out/render_snapshots/<loop_id>/`) vs current `out/render/*.svg`, reusing
      the existing `RegionOverlay` mask pattern with `kind: added|removed|changed`
      boxes. Sheet tabs apply to both panes; toggle to single-pane overlay for
      narrow screens.
- [ ] **Accept-all / Reject-all / Selective revert after the loop completes.**
      Covered by the Diff & Accept section — buttons live next to the diff view,
      "Reject" restores the snapshot, "Accept" leaves `out/` as-is and clears the
      snapshot dir.
