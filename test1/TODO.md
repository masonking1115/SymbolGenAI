# TODO

Deferred work items (not blocking; pick up when convenient).

## Commit + push once TODO is current (2026-05-31) — DONE

- [x] **Bring TODO up to date, then commit + push.** Done — commit 6e2fb2b pushed
      58146c8..6e2fb2b on cosmetic-lint-rules. (gui/state excluded — runtime only.)

## Bobcat power-glyph placement refactor + persist Generator console (2026-05-31) — DONE

- [x] **Place the 3 bobcat power glyphs correctly in build_bobcat.py so
      auto_fix_power has nothing to correct** (kills the repeated `~ off-set power`
      console lines, which were idempotent cosmetic relocations re-applied on every
      rebuild — not real per-run edits). The two `+VDDD` glyphs (pins 12, 20) were
      straddling their vertical pin→cap wire → placed on opposite side stubs
      (`power_at(..., stub=∓200)`) so they terminate a branch beside the net. The
      pin-13 `+VDDIO` glyph capped a from-above vertical drop (up-arrow pointing
      into its net → wrong-side) → moved to a horizontal stub (`stub=-400`).
      Verified: both auto-fixers now return [], bobcat 0/0/0, FAILURES: none,
      connectivity unchanged (nets re-tied via the stub), 4/4 satisfiability tests.
- [x] **Retain the most recent/active Generator console across tab switch + refresh.**
      Console `lines` + `runState` were component state (Generator unmounts on tab
      switch → lost; refresh → lost). Now persisted to localStorage
      (`test1.gen.console`, bounded 2000-line tail) and rehydrated on mount. A
      persisted "running" rehydrates as idle (the SSE can't resume after remount;
      no phantom spinner — mirrors the sim-tab rule). A new run still clears + re-saves.

## Sim tab: whole header toggles the block dropdown, not just the arrow (2026-05-31) — DONE

- [x] **Clicking anywhere on the Simulation row drives the block dropdown.** DONE —
      Sidebar.tsx: the main Simulation button now navigates+opens when arriving from
      another tab, and TOGGLES open/closed when already on the sim tab. The ▸ caret
      stays as an explicit affordance (its own toggle, stopPropagation).

## Add the schematic-gen diff option to the Generator page (2026-05-31) — DONE

- [x] **Bring the Design Review tab's schematic diff to the Generator page.** DONE.
      Before/after = state snapshotted at the START of a Generate (apply+build) vs
      the rebuilt result (user's choice). Backend: factored the loop's snapshot into
      `closed_loop.snapshot_render_and_netlist(snap_id)`; the apply-and-generate
      endpoint snapshots at entry under a fresh `gen-<hex>` id (before apply edits /
      build rewrites renders — safe because _start_run schedules the build as a task
      that hasn't run yet) and returns `diff_id` in all 3 paths; reuses
      `compute_loop_diff` + the png_snapshot route (now allows the hyphenated gen id);
      prunes to the newest 5 gen snapshots. Frontend: Generator passes `diff_id` up
      via `onGenDiff` on build complete; App fetches `api.loopDiff(diff_id)`, reuses
      DiffPanes in the right pane (parallel genDiff* state mirroring the Review diff),
      auto-shows only on real changes (genHasRealDiff), with a Schematic|Diff toggle
      bar (+ change count, "no schematic changes this run", dismiss). Verified: diff
      detects C40 0.1uF→0.22uF end-to-end; 0 on no-change; diff route live.

## Remove "slide deck" references from the GUI (2026-05-31) — DONE

- [x] **Don't call out slide decks specifically in the GUI.** DONE — generalized all
      user-facing wording to "design document": Reference-links header ("· from the
      design documentation"), the per-link badge "slide N" → "p.N", and the
      design_requirements.md text ("Bobcat PPT" → "Bobcat design document", which is
      viewable in the GUI editor). Also tidied the related backend/api comments +
      renamed `_BOBCAT_PPT_CANDIDATES` → `_BOBCAT_DOC_CANDIDATES`. Left "SPICE deck"
      (unrelated — the ngspice circuit deck) and the .pptx upload-format list (a
      generic accepted format, not a reference to the Bobcat source).

## File timestamps in Design Resources (2026-05-31) — DONE

- [x] **Show one timestamp per file (upload OR last-edit, whichever is newer); not
      URLs.** DONE — used file `st_mtime` (single field, covers both upload and
      edit). Added `mtime` to the datasheets + requirement-docs listings (BOM had it,
      skills had `updated`). Frontend `fmtTime()` (relative for recent, short date
      when old) renders it in each file row across all 4 sub-tabs (datasheets, req
      docs, BOM, skills). Reference links show NO timestamp (not files).

## Verify Bobcat PPT → design_requirements.md is complete + add its URLs (2026-05-31) — DONE

Source = `[External] Bobcat Board Design.pdf` (the "Bobcat PPT", a slide deck exported
to PDF; also at `Parts Library/Bobcat/`). Target = `test1/design_requirements.md`.

- [x] **Double-check Bobcat PPT → design_requirements.md.** DONE — read all 13 pages
      (text + rendered images). The .md was already thorough (more detailed than the
      PPT — adds the FMC pinout table, resolved bias decision, provisioning notes).
      Genuine gaps found + FILLED: (a) Ironwood CG25-QFN-2003 socket (was absent),
      (b) a "Mechanical / PCB / fab requirements" section from slide 12 (mounting
      holes, 69mm FMC width, 50Ω SMA traces, silkscreen, 4–6 layers ≥1.6mm) — tagged
      PCB-layout scope / not implemented by the schematic generator, (c) a bias
      preferred-vs-backup traceability note (PPT preferred an I²C current DAC; we
      implement the PMOS backup). NON-issue avoided: PPT text "GPIO0-3 to 14 100 mil
      header" is "1×4" with the ×4 mangled — the .md's "1×4 header" is correct
      (confirmed from the page-4 image).
- [x] **Add the Bobcat PPT URLs to the Design Requirements sub-tab.** DONE as a
      separate UI links list (user's choice): `GET /api/requirements/links` extracts
      the 5 URLs LIVE from the PDF's link annotations (stays in sync) + labels them
      (_LINK_LABELS); RequirementsPanel renders a "Reference links" section
      (clickable, with slide number). Degrades to empty (no 500) if the PDF/fitz is
      absent. Links: Genesys-2, VITA57 FMC pinout, TPS7A84A datasheet, Ironwood
      socket drawing, unconv.ai.

## Agent Models UI polish + audit which agents really have skills (2026-05-31) — IN PROGRESS

- [x] **Fix the Agent Models row UI.** DONE — root cause was the "· default"/
      "· latest" suffix inside the option labels (a native <select> shows the
      selected option's full text when closed, so it clipped). Now: option labels
      are the bare value (off/low/medium/high; the bare model id), and default/
      custom/latest show as small tags beside each select. Fixed-width reset slot so
      rows align, tighter gaps.
- [ ] **Audit skills vs agents — "are these all the skills the agents use?"**
      No: there is exactly ONE skill file (.claude/skills/sim-datasheet-extraction.md),
      attached to sim_setup + sim_interpret. Every other agent's methodology is baked
      into inline prompt blocks (_APPLY_INSTRUCTIONS, _LINT_FIX_INSTRUCTIONS, the long
      sim_generate/sim_update/symbol_gen/rule_gen prompt bodies), NOT expressed as
      skills. Decide + do: which of those embedded how-tos should become real skill
      files (e.g. altium-builder-idioms / anti-short for apply+lint_fix+topology;
      spice-deck-authoring for sim_generate+sim_update; symbol-authoring for
      symbol_gen; rule-authoring for rule_gen). Either author them as skills + attach
      (and then the prompt can reference instead of duplicate — see the "shown not
      injected" note in [[agent-effort-and-skills]]), or make the UI clearly say
      "agents also use built-in methodology not shown here" so the dropdown isn't
      mistaken for the complete picture.

## Agent effort/thinking + attached skills in Design Resources; show skills in Skills tab (2026-05-31) — DONE

- [x] **Per-agent effort / thinking option in Design Resources → Agent Models.**
      DONE: added an effort scale (off=0 / low=2000 / medium=4000 / high=12000)
      mapping to MAX_THINKING_TOKENS. Per-kind override persisted in
      `gui/state/agent_effort.json` (mirrors agent_models.json); `effort_for` /
      `thinking_for` / `set_agent_effort` in agent.py; `agent_model_config()` now
      carries effort + effort_default + effort_overridden + the effort_levels
      catalog; `POST /api/sim/agent-effort` setter. Threaded `thinking_tokens=
      thinking_for(kind)` into all 11 `_spawn_claude` sites. lint_fix's default is
      "off" (its hard-won anti-spiral setting), now user-adjustable. UI: an effort
      <select> beside the model picker per agent row.
- [x] **Show skill files attached to each agent (dropdown) in Agent Models.** DONE
      via skill frontmatter `agents: [sim_setup, ...]`. Backend: app.py skills
      listing exposes `agents`; agent.py `attached_skills(kind)` surfaced in
      `agent_model_config()` per agent. UI: a per-row "N skills ▸" disclosure
      showing each attached skill's title + description (read-only — managed in the
      Skills tab). NOTE: skills are shown but NOT auto-appended to prompts — the sim
      agents already inline the same datasheet methodology, so appending would
      duplicate. The seam (`agent._attached_skills_prompt`) is left for later if a
      skill becomes the single source. Attached sim-datasheet-extraction to
      sim_setup + sim_interpret.

- [x] **Show current skills in the Skills tab.** DONE — root cause: SKILLS_DIR
      pointed at `test1/resources/skills/` (never existed) while the real skill
      lives at `test1/.claude/skills/`. Repointed SKILLS_DIR to `.claude/skills`
      (the canonical Claude-Code dir the agents share). Also: `_skill_title` now
      reads frontmatter `name` (was showing the slug), and the listing surfaces the
      `description`. Save/open/delete all use SKILLS_DIR so they stay consistent.

## Per-block sim staleness vs the current schematic + a Refresh (2026-05-31) — DONE

- [x] **Show a sim block as out-of-date only when ITS OWN inputs changed.** When a
      new schematic is uploaded/generated, a sim block is stale only if something
      *inside that block* changed — its sheet's netlist (the parts/values/nets the
      deck reads via design_extract), or the deck builder / catalog entry. A block
      whose inputs are untouched must NOT show stale, even if other sheets changed.
      Per-block granularity, not a global "everything changed" flag.
    - There's already a per-block **SPICE-model** freshness signal:
      `deck_provenance.deck_status(block)` → none/unknown/fresh/**stale**, surfaced
      as `block.model_status` and shown by `ModelLifecycle` ("SPICE model may be out
      of date → Update to match schematic"). Reuse/extend this rather than inventing
      a parallel mechanism. Check what `deck_status` hashes — it must key off the
      block's own sheet inputs (netlist/<sheet>.yaml + the deck file), so unrelated
      sheet edits don't flip it.
    - Also factor in the **cached scenario / sim results**: a run shown on the card
      (chart/verdict, persisted in localStorage + the backend sim_config cache) is
      stale if the block's inputs changed since that run. Mark the displayed result
      "out of date — re-run" distinctly from the model being stale.
- [x] **A Refresh that updates the sims + SPICE models to the current schematic.**
      DONE per user direction: Refresh = DETECT (tab-level banner "N blocks out of
      date — Refresh" re-fetches the catalog so staleness re-evaluates; per-block
      "out of date" chip + lifecycle banner). UPDATE is per-block: the existing
      "Update to match schematic" button now also clears the block's cached scenario
      + datasheet params (POST /api/sim/update-model), so it re-syncs sim + params +
      SPICE model together. Auto re-fetch wired: App.tsx re-fetches /api/sim/blocks
      when `bust` changes (build/generate/loop), so badges update without a reload.
    - Backend: `deck_provenance.block_staleness(block)` → {stale, model_status,
      run_stale, changed, reason}, keyed off the block's OWN sheet fingerprint(s)
      (content-hash) + `simconfig.is_fresh` for the cached-run staleness. Surfaced as
      `block.staleness` in service.list_blocks.
    - VERIFIED end-to-end: stamped two blocks, edited only power.yaml → ldo_rail
      flipped stale (changed=[power]), vddio_pdn (bobcat.yaml) stayed fresh; restored
      cleanly. An unchanged-sheet block never flips.

## Build status must be consistent + live across all tabs (2026-05-31) — DONE

- [x] **Every tab's build/lint status must agree and be up to date.** Root cause:
      the two tabs measure DIFFERENT things — Review reads `api.findings()` (rule/
      semantic eval), Generator reads `api.lint()` (geometric layout lint) — and
      Review only re-fetched on mount, so it went STALE after a generate elsewhere.
      Fixed BOTH: (1) Review now takes `refreshSignal={bust}` and re-fetches findings
      whenever artifacts change (build/generate/loop), so it can't go stale relative
      to the build — same invalidation signal the Generator already uses. (2) Made
      the two status surfaces source-explicit so they're not read as one disagreeing
      number: status bar now shows `review: …` vs `lint: …`, and the Review badge is
      "Review findings: all clear/needs review" (tooltip: separate from layout-lint).

## Configurable loop count — regeneration + design review (2026-05-31) — DONE

- [x] **User chooses how many fix rounds the regeneration loop runs.** New shared
      `RoundsPicker` (1–10, default **3 (recommended)**) sits next to the Fix-errors
      ticks on the Schematic Generator, shown only when a loop mode is on. Threaded:
      Generator.tsx → `api.applyAndGenerate(loopReview, fixWarnings, maxRounds)` →
      `ApplyAndGenOpts.max_rounds` → `_clamp_rounds()` → the chain's
      `while ... rnd < max_rounds`. Server clamps to [1, LOOP_MAX_ROUNDS_CEILING=10];
      None → LOOP_MAX_ROUNDS=3. Verified: 7→7, 99→10, 0→1.
- [x] **Same for the design review (closed loop).** Same `RoundsPicker` next to the
      "Design review" button. Threaded: Review.tsx → `api.loopStart(maxRounds)` →
      `/api/loop/start` (LoopStartBody.max_rounds) → `start_loop(max_rounds)` →
      `Loop.max_rounds` (clamped via `closed_loop.clamp_rounds`, default
      MAX_ROUNDS_DEFAULT=3, ceiling MAX_ROUNDS=10) → the round loop + lint_fix
      dispatch use `L.max_rounds`. Verified clamp_rounds: None→3, 0→1, 50→10.

## Linter — two new placement/routing rules (2026-05-31) — DONE

- [x] **`passive_on_corner` (WARNING).** A passive (R/C/L) pin must not land on a
      wire CORNER — the net entering on one axis and turning 90° exactly at the
      component terminal (the C22/R20-style "passive hung off the corner of a net"
      defect). Detected geometrically in `altium/layout_lint.py`: a 2-pin passive
      pin where the only wires terminating are exactly one H + one V stub (a clean
      L-bend). Skips junction taps (≥3 segments), straight pass-throughs/single
      stubs, and DNP passives → no false positives. Fires on the real design:
      **R20 pin 1** (net comes in horizontally, turns down at the terminal).
- [x] **`power_borders_component` (WARNING).** A GND or power-rail glyph must not
      sit flush against a component body (the R30–R33 ladder / +3V3-over-R61
      crops). Measures the glyph's electrical body (`body_box`) vs each part's true
      drawn body (`graphic_box`); flags a hard overlap or a sub-100-mil near-touch.
      Exempts the part whose own pin the glyph terminates (normal decap/rail tap),
      so only a glyph crowding a *different* part is caught. Fires on the real
      design: **GND at (8300,10500) 90 mil from U20**.
- Both are WARNING-level (advisory, never fail the build) and registered in
  `RULES` + `ALL_CHECKS` so the GUI checklist, PDF export, and the review/apply
  agent all see them. Full build still `FAILURES: none`; the 5 other sheets stay
  clean (no false positives). Not auto-fixed — moving a wire bend or a power glyph
  can create a short, so (like cramped_spacing/decap_grouping) they're surfaced
  for the builder/agent to address, not nudged mechanically.

## Test plans — answer (2026-05-31)

- There is **no separate formal "test plan" document** and no `test plan` /
  `testplan` references anywhere in the repo. The closest artifact is
  **`test1/SYSTEM_TESTS.md`** — a living end-to-end capability-test catalog (one
  entry so far: **T1**, the incorrect-part → autonomous-remediation flow, loop
  `a66156e2`, PASS). Each entry is a reproducible scenario against the live stack
  with Scenario / Setup / Expected flow / Result (+ loop id) / Wiring. The intent
  is to add a T# per new capability. If a heavier/structured test plan is wanted
  (per-requirement coverage matrix, regression suite, CI hooks), that's net-new.

## Library part detail: embed the datasheet (2026-05-31) — TODO

- [ ] **Show the datasheet PDF in the Library part-detail view**, filling the
      empty space below the Symbol (and/or Properties). It should be scrollable
      and zoomable — embed the PDF inline (the datasheet is already served at
      `api.datasheetUrl(mpn)`), e.g. an `<iframe>`/`<embed>` with the browser's
      native scroll+zoom, or a pan/zoom canvas if we want custom controls. This
      is the Library tab's PartDetail (tabs/Library.tsx), not Design Resources.
      Only show it when `properties.Datasheet` exists; otherwise leave the space.

## Multi-agent console (2026-05-30) — DONE

- [x] **Visually see + click through every spawned agent and what each is doing.**
      DONE — added an "Agents" view to WorkflowConsole (third toggle beside Steps/
      Raw). `flattenAgents(rounds)` rolls up EVERY action with an agent_run_id across
      ALL rounds (newest first, de-duped), each row showing kind + round tag + status
      badge (running spinner / ok / fail / cancelled) and click-to-expand its full
      reasoning via LiveConsole (backend replays the buffered stream for any id, so
      finished agents from earlier rounds repopulate). Covers apply / symbol_gen /
      lint_fix / sim / missing_part / topology_adapt — every sub-agent that carries a
      run id (the eval phase spawns none, noted in the empty state). WorkflowSection
      passes `rounds={summary.rounds}`. (Per-round Steps view + Round-history rows
      kept as-is.)

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

- [x] **Symbol-gen console survives part switching.** DONE (verified 2026-05-31,
      already implemented). Library.tsx keeps per-MPN gen state (`gen: Record<mpn,
      GenEntry>`), holds live subscriptions keyed by run_id (`subs` ref), and
      re-attaches to an in-progress run on return to a part (the backend replays the
      full stream). The displayed console reads from `gen[sel]`, stable across switches.
- [x] **Make all console displays white.** DONE (verified 2026-05-31 — no dark
      console surfaces remain). The dark `bg-[#0F1115]` was already replaced; an
      exhaustive sweep found every console/log/stream display on a white/light bg
      (LiveConsole, WorkflowConsole, Console, Library symbol-gen, sim model-agent
      log all `bg-white`/light). Only action BUTTONS stay dark (intentional).
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

## Review — sim in the loop (DONE — validated 2026-05-31)

- [x] **Simulation is in the review evaluation, agent-judged.** VALIDATED end-to-end:
      the `sim_review` rule kind (11 rules in rules.yaml) runs the real block via
      `sim_service.run_block_sim` (deriving the scenario via the sim-setup path when
      stale), then a `claude -p` judge returns PASS/FAIL vs the criterion; cached per
      (block,sim_type) so siblings reuse one ngspice run; gated behind `semantic=True`
      (the fast lint path stays instant); fail-safe (infra failure → PASS, no false
      finding). The TODO's "two defects" were already fixed before this pass: block
      names are all REAL (opa_bias/ldo_rail/vddio_pdn/vddd_pdn/vdda1_pdn/vdda2_pdn),
      and `closed_loop` calls `run_all(None, None, True, …)` with `eval_sim_review`
      doing the run + reshape into {(block,sim_type): result}.
    - **BUG FOUND + FIXED during validation:** the judge returned a *reproducible
      false FAIL* on BLK_BIAS_FS_CEILING (669 µA ≥ 640 µA is PASS) — would have made
      the loop churn "fixing" an in-spec circuit. Root causes: (1) units mismatch —
      criterion in µA, analysis value in amps (0.000669), judge fumbled the convert;
      (2) the judge emits a wrong JSON object then self-corrects with a second, but
      `_parse_verdict` took the FIRST. Fixes in rule_eval.py: `_humanize_units()`
      annotates _A/_V/_s/_Hz/_ohm/_dB metrics with engineering-unit readings; the
      judge prompt forces an explicit `comparison` field the verdict must follow;
      `_parse_verdict` now takes the LAST verdict object + a consistency guard
      (verdict follows "satisfied/not satisfied"). Semantic rules (no comparison
      field) unaffected — verified.
    - **Verified:** false-FAIL rule now 5/5 PASS; all 11 sim_review rules run ngspice
      with correct units-clean verdicts + 0 false findings; 21/21 review tests pass;
      full `run_all(semantic=True)` yields only the pre-existing R40/R41 INFO.

- [x] **Lingering ldo_rail / transient_powerup changelog item** — MOOT: the changelog
      is empty; nothing lingering (resolved earlier).

- [x] **Clear the simulation cache when starting a design review** — DONE (already
      implemented): `closed_loop._clear_sim_cache_for_review()` runs before the
      initial eval, so sim_review rules run from scratch.

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
- ~~OPEN: R40/R41 value vs 5.11k MPN~~ RESOLVED (2026-05-31). There was NO part
  swap left to do — the netlist already has R40/R41 = value 3.65k + lib_id
  TNPW06033K65BEEA + footprint, and the 3.65k symbol exists in Parts Library. The
  "mismatch" was a STALE, project-specific RULE PROMPT: CHK_VALUE_MATCHES_MPN's
  prompt literally said "R40/R41 ... may still reference the 5.11k MPN ... a real
  mismatch to flag", so the judge kept emitting a false-positive INFO. Fixed by
  GENERALIZING the CHK_* checklist prompts for reuse on future projects.

## Generalize CHK_* rule prompts for reuse on later projects (2026-05-31) — DONE

- [x] **The general-checklist (CHK_*) rule prompts must not hardcode project
      specifics** (refdes, MPNs, specific nets/sheets) — they're meant to apply to
      ANY design. Rewrote all 8 CHK_* prompts/fix_hints to state the general
      principle: CHK_VALUE_MATCHES_MPN (dropped the stale R40/R41 + 5.11k-MPN lead);
      CHK_POWER_NOT_SHORTED_GND (rail list → "any supply-rail net"); CHK_CLOCK_PINS_
      CLOCK_NETS (CLK_OUT0–3 → generic clock-naming convention; also dropped its
      `sheet: connectors` scope); CHK_PARTS_HAVE_MPN (J50–J56 → "connectors/headers/
      mechanical"); CHK_SIGNAL_NET_MIN_TWO_PINS (SAMPLE_OUT example → generic series-
      R example). The design-specific BLK_*/SEM_*/ROUTE_* rules are INTENTIONALLY
      Bobcat-scoped (generated per-project from design_requirements.md) — left as-is.
      NOTE: rule `source:` quotes stay project-specific (they're real per-project
      citations, regenerated each project; only the reusable PROMPT logic was
      generalized). Verified: 115 rules validate; CHK_VALUE_MATCHES_MPN now PASSes
      3/3 (false positive gone); the other generalized CHK rules still PASS on the
      real design; 21/21 review tests pass.

## Strengthen CHK_VALUE_MATCHES_MPN with a deterministic MPN-value decoder (2026-05-31) — DONE

- [x] **The value↔MPN judge couldn't decode opaque manufacturer value codes**
      (Murata `104`=0.1µF, Vishay `3K65`=3.65k) so it PASSED a deliberately wrong
      part (an E2E loop test: R40 labeled 5.11k behind a `3K65` MPN slipped through).
      Two root causes: (1) the judge had no way to read the codes from memory; (2)
      CHK_VALUE_MATCHES_MPN has an EMPTY applies_to, so it got the "no specific
      subject" fallback and saw NO part list at all. Fix (same philosophy as the
      sim-units fix — compute in Python, judge a clean comparison): new module
      `test1/review/mpn_value.py` decodes R/C MPNs (RKM `3K65`→3650, EIA-4 `1002`→10k
      with a package-size strip to kill the `0402`/`1002` collision, Murata 3-digit
      pF codes anchored between voltage+tolerance letters); `rule_eval.py`'s
      `_netlist_context_for` appends a "DECODED PART VALUE vs MPN" MATCH/MISMATCH
      block, scoped to every R/C part board-wide for the empty-applies_to rule.
      Conservative: undecodable MPN → no line (judge unaided, defaults PASS) — never
      a wrong decoded value. Verified: decoder 26/26 on the real BOM; isolated judge
      FAILs the R40 mismatch + PASSes the clean design (no false positive across ~85
      R/C parts); LIVE loop end-to-end (Test 3): R40 mismatch → 3 findings (the
      strengthened CHK static check + 2 bias sim rules) → 1 apply round → all_clear;
      30/30 review tests pass. Also added `test1/review/e2e_monitor.py` — a reusable
      harness that triggers POST /api/loop/start and renders the SSE stream live.
