# TODO

Deferred work items (not blocking; pick up when convenient).

## Multi-agent console (2026-05-30) — TODO

- [ ] **Visually see + click through every spawned agent and what each is doing.**
      The closed loop spawns multiple sub-agents (apply, symbol_gen, lint_fix, sim,
      missing_part, topology_adapt) — the user wants a console that lists ALL of
      them (running + finished) and lets you click each to see its live "doing +
      thinking" stream. WorkflowConsole already does a split per-agent view for the
      loop's current round; extend it to (a) show agents across ALL rounds / the
      whole loop, (b) include the eval + sim sub-runs, (c) a clear running/done
      badge per agent, (d) click-to-expand each agent's full reasoning (reuse
      LiveConsole + the /api/agent/{id}/stream replay). Tie into the per-round
      actions[].agent_run_id already on the loop audit.

## System capability test catalog (2026-05-30) — DONE (seeded; grow over time)

- [x] **Created the living capability-test catalog at `test1/SYSTEM_TESTS.md`.**
      Seeded with **T1 — Incorrect part: value↔MPN mismatch → autonomous symbol
      generation + remediation** (loop `a66156e2`, PASS): the loop detected
      `CHK_VALUE_MATCHES_MPN`, cloned the 3.65k symbol from its 5.11k sibling via
      `author_symbol --clone-from`, repointed R40/R41 lib_id+footprint, rebuilt
      0/0/0, and reached `all_clear`. Add a new T# entry per new capability;
      follow the T1 template (Scenario/Setup/Expected flow/Result/Wiring/Caveats).

## Datasheets → part link / generate (2026-05-30) — DONE

- [x] **Each datasheet group links to its part (or offers to generate one).** DONE:
      `DatasheetsPanel` now joins datasheet MPNs to the library list (`has_symbol`).
      Per group header: symbol exists → "view part" link (jumps to Library + auto-
      selects via App `goToPart`/`pendingPart` → `Library initialPart`); no symbol →
      ❗ caution + "Generate symbol"; generating → ⏳ "generating symbol…"; success →
      flips to the link (library re-read); fail → ⚠️ + Retry. Generation runs INLINE
      (symbolGen + subscribeAgent in the panel; full console stays in Library). New
      `PartLinkOrGenerate` component. NOTE: inline generate hits the same venv-python
      approval prompt as the Library/sim runs — the allowlist fix below unblocks it.

## Console UX (2026-05-30) — IN PROGRESS

- [ ] **Symbol-gen console survives part switching.** In the Library tab, kicking
      off "Generate symbol" shows the live subagent console; switching to another
      part and back makes the console vanish and only restart when the run
      finishes. Root cause: `genLog`/`genState` are reset by the `useEffect([sel])`
      and the live subscription is parent-local with no re-attach. Fix: track
      per-part run state (run_id keyed by MPN), don't clear a running part's log on
      switch, and re-attach to the in-progress run on return.
- [ ] **Make all console displays white** to match the other sections (the
      symbol-gen subagent console is currently dark `bg-[#0F1115]`). Apply a light
      background uniformly to every console/live-stream view (Library symbol-gen,
      Workflow console steps/raw, any LiveConsole/agent-stream panels).
- [x] **Zoom + pan the symbol in the parts viewer.** DONE: `SymbolViewer` now
      reuses the shared pan/zoom `Canvas` + `ImgLayer` from PngViewer (the same
      one the schematic viewer uses) — wheel-zoom toward cursor, drag to pan,
      double-click/fit, +/-/1:1 overlay, %-readout. `key={mpn:unit}` resets the
      view fit-to-frame on unit/part switch. No new dependency (reused existing
      component); no import cycle; bundle size unchanged.
- [ ] **Inspect the TNPW06035K11BEEA symbol-gen run output.** User pasted a trace
      showing the subagent ended `✓ subagent ok` but the `author_symbol` venv-Python
      invocation kept hitting per-call approval prompts (not allowlisted) — same
      class of blocker found in the sim-setup run (datasheet read_pdf). The symbol
      DID get authored (files present, glyph valid), but the agent had to fight the
      allowlist. Root fix: add `Bash(*altium_spike/.venv/Scripts/python.exe*)` (and/or
      `Bash(*python* -m test1.altium.author_symbol*)`) to settings.local.json so
      symbol-gen + sim agents run the venv Python without prompts. Verify the run
      log for any silent fallback/skip.

## UI cleanup + Resources uploads (2026-05-30) — DONE

- [x] **Clean up the Schematic Generator + Design Resources tabs UI.** Framing
      pass (per user: "that's enough"): extracted a shared `PageHeader` component
      (eyebrow + title) now used by Review, Generator, and Resources; gave Design
      Resources a proper page header + aligned padding (px-6 py-5, max-w-900) so
      it frames like the Review tab. (Deeper per-panel token polish deferred.)
- [x] **Design Requirements accepts common file types.** Backend whitelist +
      frontend `accept` now allow pdf, md, docx/doc, pptx/ppt, xlsx/xls, csv,
      txt, rtf, odt; note updated. Verified .csv → 200.
- [x] **Added a "BOM" sub-tab next to Datasheets.** New `BomPanel` + backend
      GET/POST `/api/resources/bom` + file-serve (accepts .xlsx/.xls/.csv, stored
      in `resources/bom/`); seeded the existing `test1_bom.xlsx` into it. Verified:
      BOM listed, .csv accepted, .pdf rejected (400).

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

### Iteration / Findings legibility (2026-05-30) — DONE

- [x] **Describe the meaning of each pipeline step.** The loop's step strip
      (round N/10: Plan · Apply · Sim · Missing · Lint fix · Build · Re-eval) is
      not self-explanatory — "Missing" especially is opaque. Add a short
      plain-English description per step (tooltip on hover and/or a one-line
      caption) so a non-author understands what each stage does:
        - Plan — decide which findings to act on this round
        - Apply — edit the builders to implement the chosen fixes
        - Sim — run ngspice on affected blocks to check the change physically
        - Missing — source/author a part that the design references but lacks
        - Lint fix — auto-correct cosmetic linter nits (overlaps, stub sides)
        - Build — regenerate the Altium schematic from the edited builders
        - Re-eval — re-run the rules to see if findings cleared
- [x] **Findings dropdown → structured summary.** The Findings view should be a
      structured report, not a flat list: group by family/block, summarize
      counts (pass/fail/severity) in a table, and add small graphs where genuinely
      useful (e.g. severity breakdown, findings-over-rounds). Tables/graphs only
      where they aid comprehension — don't decorate.
      DONE: new FindingsSummary.tsx at the top of the Findings section — a
      collapsible "Summary" with a CSS severity bar graph + a breakdown table
      grouped by family (general checks / components / blocks→per-block) ×
      ERROR/WARNING/INFO. Joins finding.rule_id → rules(family,block); unknown
      rule_ids fall into an "other / linter" bucket so nothing is dropped.
      (Findings-over-rounds deferred — lives in the Iteration round history.)

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

## Rule-set audit (2026-05-30) — DONE
- Verified all rules representative vs requirements + Bobcat PPT + datasheets.
- GAP CLOSED: added 10 ROUTE_* rules (SAMPLE_OUTV/0-7 + MISO -> FMC via series 0Ω);
  these signals had pull-up/down rules but nothing asserting they reach the FMC.
- DUP DROPPED: SEM_SHARED_LDO_INTENT (BLK_LDO_SHARED_RAIL_INTENT covers it).
- CHECKLIST APPLIED (user's general checklist): added 8 CHK_* semantic rules for
  the items NOT already covered — MPN-present, passives-have-value, signal>=2-pins,
  no-multi-driver, power-not-shorted-GND, value-matches-MPN, cap-derating, clock-net
  naming. Skipped items already covered by existing rules / the layout linter
  (shorted-components, decoupling, IC pwr/gnd, I2C pull-ups/names, open-drain pull-up,
  designator/pin uniqueness, pin-names-match-datasheet, diff-pair _P/_N + polarity).
- 115 rules total (general 80, components 9, blocks 26). All validate; ROUTE_ rules
  pass on the as-built design; PDF export + UI serve them.
- OPEN (flagged by CHK_VALUE_MATCHES_MPN): R40/R41 value=3.65k but lib_id still the
  5.11k MPN (TNPW06035K11BEEA) — needs a real 3.65k 0.1% part selected.
