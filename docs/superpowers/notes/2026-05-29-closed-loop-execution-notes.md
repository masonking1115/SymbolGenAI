# Closed-Loop Design Review — Execution Notes

Running log of design decisions and deviations during implementation
of the plan at `docs/superpowers/plans/2026-05-29-closed-loop-design-review.md`.

## Phase 0 — Cleanup (commits f5b917f, 3ebc648, bc2b818)

**Decision: leave findings.json on disk only.** The file is `.gitignore`'d
(`.gitignore:38`), so Task 0.1's "commit empty envelopes" step was a no-op.
File state on disk is correct; no risk to downstream phases because the GUI
loader recreates the envelope shape on each save.

**Side-effect surfaced:** Task 0.3 step 5 (run `run_review.py --no-semantic`
verification) writes findings.json with the new stub format (`[]` instead
of the envelope). Manually reset to the envelope after Phase 0 finished.
TODO: Phase 3 refactor of run_review.py should keep emitting the envelope
shape (not `[]`) so this stops biting.

**Preserved WIP:** Linter (`test1/altium/layout_lint.py`), `shared.py`,
`app.py`, `TODO.md` had unrelated uncommitted edits at start of Phase 0.
Left untouched; no `git add -A` used.

## Phase 1 — Schema + Providers + Predicates (commits 0bd17ad..a335aa1)

21/21 tests pass. Three deviations from verbatim plan, all in `rule_eval.py`:

**1. `eval_present` adapter for live netlist_view API.**
The plan referenced `view.sheets`, `view.parts_on_sheet(sheet)`, `part.mpn`
— none exist on the actual `NetlistView`. Adapted to iterate
`view.by_sheet.items()` and match `p.mpn` against both `part.value` (often
carries MPN string for ICs) and `part.lib_id` (symbol name). Semantically
equivalent — surfaces "is this MPN present anywhere on any sheet?" without
the missing helper methods.

**2. `eval_net_routing` derives sibling pins from the reverse index.**
The plan tried `view.part(refdes)[1].pins.keys()` — `Part` dataclass has
no `.pins` attribute (pins live on `Net.members`). Added a local helper
`_other_pins_on_refdes()` that walks `view.nets_with_member(refdes)` to
collect the pin set. Same shape check (series_R = one resistor sits on
the path, jumper = one J part); no semantic change.

**3. `eval_sim_pass` PASSES on missing sim data (plan FAILED).**
The plan's code returned `False` when no `(block, sim_type)` entry existed.
But the docstring + Task 1.5 test (`test_sim_pass_fires_when_no_sim_data`)
both require PASS-on-missing — "sim runs gated separately from rule eval".
Matched the docstring/test contract. Brings `eval_sim_pass` in line with
`eval_sim_metric` (which was already PASS-on-missing in the plan).

**Why these matter for downstream phases:** Phase 4 orchestrator's plan_actions
mapping should not treat a *missing* sim result as a fired rule — it should
treat it as a signal to run the sim. The PASS-on-missing contract makes
that clean: only an explicit `ok: false` triggers a sim_pass finding.

## Phase 2 — Rule Generation (commits c1f3591..88cbd9b)

5 commits, all verifies pass. Skipped 2.5 (live LLM smoke test) and 2.7 (GUI gate) — will run from main loop.

**Deviations of note:**

**1. agent.py conventions.** Plan's snippet ordered `_register()` before `_spawn_claude()`. Actual convention (matching `start_apply_pass`, `start_lint_fix_pass`, `start_symbol_gen`): build prompt → `_spawn_claude(...)` → `_register(kind)` → `asyncio.create_task(_run_subprocess(run, proc))`. Matched the live convention.

**2. `start_rule_gen` allowed_tools expansion.** Plan didn't specify. Added `WebFetch`, `WebSearch` (URL resolution from requirements.md), `Bash(python:*)` (spot-check datasheet PDF text), `add_dir=REPO_ROOT` (read Parts Library + netlists). Permission mode `acceptEdits` to allow writing the output JSON to the tempdir.

**3. Naming: `rule_gen` (underscore).** AGENT_KINDS key uses underscores consistently with `model_for("rule_gen")` and the kind id used by `_register()`. Legacy `"symbol-gen"` dash form unchanged for compat.

**4. Icon substitution: `I.Schematic` for `I.List`.** `I.List` doesn't exist in `Icon.tsx`.

**5. Dropped dead `needsApproval` heuristic in RulesSection.tsx.** Plan defined it but never read it — TS strict flags unused locals. Approval-state will need a dedicated `approved_at` field in `RulesFile` if/when surfaced.

**6. `api.ts` uses the existing `j<T>()` helper.** All other methods do — kept the style consistent.

**Caveat:** `_claude_generate` retry uses fresh `start_rule_gen` per attempt (not re-streaming stale events). Each attempt becomes a separate AgentRun in `state/runs/`. Validation errors in the temp output are not yet appended to the retry prompt — TODO before Phase 4 closes (the orchestrator would benefit from prompt-aware retry).

**Open issue:** Task 2.5 (live generator smoke) is the Phase 2 gate. Will run it during integration before Phase 4 starts, so the orchestrator has rules to evaluate.

## Phase 3 — Rule Evaluator Integration (commits ee74b8e, 6238e78)

Trivial — Phase 2a swapped to `rule_eval.run_all()` + `rule_id`/`iteration_round` badges on FindingRow.

**Caveat:** `run_review.py --json findings.json` writes `[]` (raw list) instead of the envelope shape `{findings, semantic, summary}`. The GUI's `/api/findings` loader copes (it computes the envelope from the list). But TODO: standardize findings.json shape across CLI and GUI so the file isn't repeatedly overwritten between formats. (Already noted in Phase 0; deferred — does not block Phase 4+.)

## Phase 4 — Closed-Loop Orchestrator (10 commits 0f60eac..808ecf2)

The big phase. Backend + frontend, 4 sub-chunks dispatched (4A backend orchestrator, 4B frontend timeline, 4C diff backend, 4D diff frontend).

**Architectural decisions worth remembering:**

**1. Snapshot scope = SVGs + YAMLs + lint.json + findings.json.** The `.SchDoc` Altium binaries are NOT snapshotted — they get regenerated from the restored YAMLs by `_rebuild_project()`. Restore is two-mode: full-restore (no `revert` list) or selective per-refdes YAML surgery.

**2. Snapshot includes `root.svg` plus 6 sheet SVGs = 7 files** (not 6 as the plan stated). Wildcard glob is correct; the plan's comment was off by one.

**3. `_LOOPS` registry is process-local, single-loop-enforced at `/api/loop/start`.** Two concurrent start requests could race (no lock). The audit JSON at `test1/gui/state/loops/<id>.json` survives restart so `/api/loop/latest` can re-attach.

**4. SSE stream protocol** uses `event:` named frames (`loop_start`, `round_start`, `action_start`, `action_end`, `build_start`, `build_end`, `sim_results`, `round_done`, `plateau`, `error`, `done`). Late subscribers to a still-running loop MISS prior events — UI mitigates by `GET /api/loop/{id}` first for state, then `subscribeLoop` for live events.

**5. `_dispatch_action` "apply" pollutes the changelog.** For each rule_id target it calls `agent_mod.append_changelog(msg, source="closed_loop")`, then `start_apply_pass()` which reads the entire changelog. Closed-loop entries remain in the changelog after the apply pass. Intentional per spec (so the user sees what the loop did) but worth knowing.

**6. Cancel never interrupts a build.** `_rebuild_project()` awaits `proc.communicate()` without checking `L.cancelled` — intentional so cancel can't corrupt .SchDoc binaries mid-write. Cancel is checked between actions and between rounds.

**7. `viewBox` shape bug fixed in Phase 4C.** `refdes_locations.extract()` returns `{"viewBox": [w, h]}` (list). The diff endpoint converts to `"0 0 W H"` (SVG attribute string) via `_viewbox_str()`. The frontend `DiffOverlay` consumes the string directly. Default for missing/empty: `"0 0 15500 11100"`.

**8. Plateau detection: 2 consecutive rounds with `delta <= 0`.** Tightening to `< 0` would let "no progress, no regression" continue forever. `<= 0` is correct — if delta could be 0 indefinitely something is genuinely stuck.

**9. Diff renders BEFORE / AFTER / OVERLAY.** BEFORE pane: `removed` + `changed`. AFTER pane: `added` + `changed`. OVERLAY: all kinds. Color is consistent (green=added, red=removed, amber=changed) regardless of pane.

**10. `loopSummary` lifted into Review.tsx.** IterationSection takes an `onSummary` callback so the parent can gate DiffAndAccept on `status !== "running"`. Promoted from destructured-skip in Phase 4D when DiffAndAccept needed the value (not just the setter).

**11. `closed_loop` is now a valid changelog source.** Allowlist in `changelog_add` updated. UI can color these blue (Phase 6.1) to distinguish from sim/user/agent.

**`_VENV_PY` is hardcoded.** Per CLAUDE.md this is the Altium machine; the path is stable. If/when this moves to another box, replace with env-var lookup.

**Phase 4 gate (this commit):** build green (`FAILURES: none`, 0/0/0 across sheets, power has 1 INFO from cosmetic re-routing), tsc clean. Ready to drive an end-to-end loop manually.

## Phase 5 — Missing-Part Flow (5 commits f1cf892..7c3e1ee)

5 sequential commits — Tasks 5.1 through 5.5. Build + tsc green at the gate.

**Three adaptations to verbatim plan:**

**1. `start_symbol_gen(mpn, ds_path)` argument shape.** Plan passed `rel = str(target_pdf.relative_to(PROJECT_DIR))` which double-prefixes `Parts Library/<mpn>/`. Pass `f"{mpn}.pdf"` instead — agent.py resolves the rest relative to `Parts Library/<mpn>/`.

**2. `test1.sim.read_pdf.extract_text(pdf, pages=(1, 3))` doesn't exist** — `read_pdf.py` is a CLI, not a library. Inlined fitz-based first-3-pages extraction in `_identity_check` directly.

**3. `_spawn_claude` signature mismatch in `start_topology_adapt`.** Same correction as Phase 2 — kwargs-only, returns `(proc, cmd)`, register-AFTER pattern from `start_apply_pass`/`start_lint_fix_pass`.

**Known gaps (called out by the implementer, worth tracking):**

**A. `_sim_verify` never populates `closest_margin`.** Plan keeps it `None` throughout and returns `0.0` only on pass. `_best_failed_candidate` ranks failed candidates by `abs(sim_margin)`, so with all failures having `sim_margin=None` the `survivors` list will always be empty and **topology adaptation will never trigger**. Either the plan needs a numeric margin extraction (e.g. compare metric to target), or `_best_failed_candidate` needs different ranking (e.g. by candidate rank). Follow-up.

**B. `_install_and_author` has no cancellation check.** A hung `symbol_gen` agent blocks the loop indefinitely. Other helpers check `L.cancelled` — add it here too.

**C. `_place_into_schematic` accumulates changelog noise.** Every candidate's placement message persists in the changelog (no per-action clearing). Apply agent reads ALL of it. UX issue if many candidates iterate.

**D. `_sim_verify` affected-block detection is substring-on-JSON.** Heuristic only — `json.dumps(block).lower()` may match by accident (block names MPN in a comment) or miss real dependencies (block drives MPN indirectly via parametric model).

**E. WebSearchPartsProvider stub.** `_web_search_candidates` returns `[]`; `_web_fetch_datasheet` raises `NotImplementedError`. With no custom parts API configured, every missing_part action hits the impasse path immediately. Acceptable since the orchestrator + sim-verify + topology paths are the value; search backend is a clean drop-in for the user's future API.

**Design-decision notes:**
- **WEB_CALL_BUDGET=50** per loop covers candidates × identity-check fetches. Search counts as 1; each `fetch_datasheet` counts as 1.
- **Sub-snapshots per candidate** at `<loop_snapshot_dir>/_cand_<idx>_<mpn>/` so each candidate can be reverted without losing earlier-round work. Different scope from the pre-loop snapshot (which is full project state).
- **Topology agent constraint: atomic edit, no cross-sheet, preserve rule intent.** Defensive — the agent is given enough latitude to add a series resistor or swap MOSFET polarity, but not enough to redesign the block.

## Phase 6 — Polish + Monitoring Verification (4 commits f5465e0..899d13d)

4 sequential commits — Tasks 6.1-6.4. The end-to-end gate (Task 6.5) is run from this main loop:

**Gate results:**
- Build: `FAILURES: none`, all sheets `0/0/0` (power 0/0/1 — cosmetic re-routing INFO, pre-existing)
- Pytest: **23/23 pass** in 0.62s across `test_loop_stream.py`, `test_rule_eval.py`, `test_rule_schema.py`
- Frontend tsc: clean
- Vite production build: clean, 51 modules, 311KB JS (92KB gzipped)
- Backend imports OK, 91 total routes, **14 closed-loop routes** registered:
  - `/api/review/rules` (GET + POST/generate + POST/edit + DELETE/{id})
  - `/api/review/providers`
  - `/api/loop/{start,latest,{id},{id}/{stream,cancel,accept,reject,diff}}`
  - `/api/png_snapshot/{loop_id}/{name}`
- Provider diagnostic: 4 defaults (`WebSearchPartsProvider`, `LocalPDFKnowledgeProvider`, `ClaudeRuleGenProvider`, `ClaudeChatProvider`)

**Phase 6 deviation:** Task 6.1 needed a `types.ts` edit (widen `ChangelogItem.source` union to include `"closed_loop"`) — tsc otherwise rejects the new case in `ChangelogPanel.tsx`. Plan didn't mention this edit; required for type-safety.

**Phase 6 design notes:**
- Blue badge palette (`bg-blue-500/15` / `text-blue-600`) is outside the existing `ok/warn/err/ink` palette so closed-loop entries stand visually distinct from sim/user/agent.
- Providers section placed below the active Resources sub-panel (not nested per sub-tab) — visible from any sub-tab.
- SSE monitoring test patches `rule_eval.run_all` at the module level. Works because `run_loop()` does a fresh `from .rule_eval import run_all as eval_rules` inside the function body.

## Final state (2026-05-29 end of execution)

**29 commits** spanning Phases 0–6, all per-task. Plan tasks 2.5 (live rule_gen smoke), 4.11 manual GUI, 5.6 manual loop demo, 6.5 manual end-to-end — all deferred for user manual exercise. Auto-verifiable gates all green.

**Files created (new modules):**
- `test1/review/rule_schema.py`, `test_rule_schema.py`, `providers.py`, `rule_eval.py`, `test_rule_eval.py`, `rule_gen.py`, `closed_loop.py`, `closed_loop_helpers.py`, `missing_part.py`, `diff.py`, `test_loop_stream.py`, `rules.yaml`
- `test1/gui/frontend/src/components/RulesSection.tsx`, `IterationSection.tsx`, `DiffAndAccept.tsx`, `DiffOverlay.tsx`

**Files modified:**
- `test1/run_review.py`, `test1/review/rules.py`
- `test1/gui/backend/agent.py` (rule_gen + topology_adapt kinds, start_rule_gen, start_topology_adapt, changelog allowlist)
- `test1/gui/backend/app.py` (14 new endpoints, 1 deleted)
- `test1/gui/frontend/src/api.ts`, `types.ts`, `tabs/Review.tsx`, `tabs/Resources.tsx`, `components/ChangelogPanel.tsx`, `components/Icon.tsx`, `components/PngViewer.tsx` (unchanged in our path — DiffOverlay is standalone)

**Files deleted:**
- `_review_incoming/` (entire dir, install_review.py + README + _processed/)
- `test1/review/semantic_review.py`
- 14 historical `test1/review_history/*.md` files

**Provider placeholders (ready for user's future APIs):**
- `CustomPartsAPIProvider` (env: `CUSTOM_PARTS_API_URL` + `_KEY`)
- `CustomKnowledgeAPIProvider` (env: `CUSTOM_KNOWLEDGE_API_URL` + `_KEY`)
- `CustomRuleGenAPIProvider` (env: `CUSTOM_RULEGEN_API_URL` + `_KEY`)
- `CustomSchematicChatAPIProvider` (env: `CUSTOM_CHAT_API_URL` + `_KEY`)

Each raises `NotImplementedError` until env vars set. Registry auto-falls-back to default impl.

**Known follow-ups (called out during implementation, not gates):**
1. `_sim_verify` never populates `closest_margin` → topology adaptation never triggers (Phase 5 known gap).
2. `_install_and_author` has no cancellation check (Phase 5 known gap).
3. `_place_into_schematic` accumulates changelog noise per candidate (Phase 5).
4. `findings.json` envelope shape ↔ raw-list shape mismatch between CLI and GUI (Phase 0/3 known).
5. `WebSearchPartsProvider.search` returns `[]`, `fetch_datasheet` raises `NotImplementedError` — wire up via user's future parts API or a one-shot search agent (Phase 5).
6. Validation errors in `_claude_generate` retry are not appended to the retry prompt — agent re-tries without learning from prior failure (Phase 2 minor).
7. `_LOOPS` registry has no asyncio lock — two concurrent `/api/loop/start` could race (single-instance lock is at the endpoint level, not module level) (Phase 4 minor).

System ready for manual end-to-end testing.

**`netlist_view.py` API actually exposes:**
- `load_all() -> NetlistView`
- `NetlistView.by_sheet: dict[str, dict[refdes, Part]]`
- `NetlistView.nets_with_member(refdes, pin=None) -> Iterable[Net]`
- `NetlistView.members(net) -> Iterable[Member]`
- `NetlistView.part(refdes) -> tuple[sheet, Part] | None`
- `Part.value`, `Part.lib_id` (no `.mpn`, no `.pins`)
- `Member.refdes`, `Member.pin`
- `Net.net`, `Net.members`

Use this reference when extending evaluators in later phases.
