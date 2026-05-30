# Closed-Loop Design Review — Design

**Date:** 2026-05-29
**Status:** Approved spec, awaiting implementation plan
**Project:** test1 (Bobcat carrier board) under `SymbolGenAI/`

---

## 1. Goal & framing

Turn the test1 GUI's one-shot Design Review tab into a **closed-loop schematic
design assistant**: rules generated from project docs, an autonomous iteration
loop (sim · schematic gen · review checkoff), missing-part discovery, plateau
detection, with the human checkpoint at the end via a side-by-side schematic
diff and accept/reject.

The system must keep a human in the loop *at checkpoints* (rule approval,
plateau notification, end-of-loop diff acceptance) but iterate **autonomously
inside a loop** — no per-fix approval gate.

### Sub-features (in dependency order)

| # | Name | Depends on |
|---|---|---|
| A | Cleanup of outdated review state | — |
| B | Rule generation from docs | A |
| C | Closed-loop orchestrator | B |
| D | Missing-part flow | B, C |
| E | Plateau detection (folded into C) | C |

---

## 2. Architecture overview

```
docs ────────────────────────────────────────────┐
  design_requirements.md                          │ rule generator
  Parts Library/<MPN>/<MPN>.pdf  (×16)            │ (rulegen_provider)
  [External] Bobcat Board Design.pdf              │   reads docs + URLs
  embedded URLs (e.g. fmchub VITA 57.1)           │     → emits candidate
  netlist/<sheet>.yaml                            │       rules.yaml
                                                  ▼
                                         test1/review/rules.yaml
                                         (polymorphic Rule schema:
                                          family ∈ {schematic, sim, design}
                                          evaluation ∈ {structural, semantic}
                                          origin ∈ {generated, user, imported})
                                                  │
                                user inspects/    │ user edits/disables
                                approves on first │ rules survive regen
                                run + on staleness│
                                                  ▼
              ┌────────────────────┐
              │ GUI · Review tab   │
              │  • Rules           │
              │  • Iteration       │
              │  • Diff & Accept   │
              └──────────┬─────────┘
                         │ POST /api/loop/start
                         ▼
       ┌─────────────────────────────────────────┐
       │ Closed-Loop Orchestrator (Python)        │
       │   for round in 1..MAX_ROUNDS:            │
       │     1. evaluate rules → findings         │
       │     2. dispatch sub-AgentRuns:           │
       │          apply / lint_fix / symbol_gen   │
       │          missing-part flow / sim_*       │
       │     3. rebuild (build_project)           │
       │     4. re-evaluate                       │
       │     5. compute Δ; check plateau          │
       │   end · snapshot → all_clear/plateau    │
       │                                          │
       │ Emits SSE on /api/loop/{id}/stream:      │
       │   round_start / agent_run / build /      │
       │   round_done / plateau / done            │
       └─────────────────────────────────────────┘
                         │
                         ▼
            out/render_snapshots/<loop_id>/      ← pre-loop snapshot
                                                  for Diff & Accept
```

### Layering

| Layer | Module | Responsibility |
|---|---|---|
| Rule generation | `test1/review/rule_gen.py` (new) | Builds doc bundle, dispatches `rulegen_provider().generate(...)` → candidate `rules.yaml`. Merge with user-origin rules. |
| Rule schema | `test1/review/rule_schema.py` (new) | Pydantic discriminated-union models (`Rule` with `evaluation` discriminator); load/save `rules.yaml`. |
| Rule evaluator | `test1/review/rule_eval.py` (new) | Dispatch table for structural predicates; semantic rules invoked via `knowledge_provider()` + claude-p. Emits `Finding`s (existing dataclass extended). |
| Orchestrator | `test1/review/closed_loop.py` (new) + endpoints in `app.py` | Owns the loop, plateau detection, snapshotting, fan-out to existing `start_*` agent runs. |
| Missing-part flow | `test1/review/missing_part.py` (new) | `parts_provider().search(...)` → datasheet → `symbol_gen` → place → sim-verify → topology-adapt fallback. |
| Provider layer | `test1/review/providers.py` (new) | Four provider interfaces (parts, knowledge, rulegen, schematic-chat) with today-impls + placeholder classes for user's future APIs. |
| Diff computation | `test1/review/diff.py` (new) | Reads pre/post `netlist/*.yaml` + `refdes_locations.extract` per sheet → per-sheet `{added, removed, changed}` overlay boxes. |
| Backend endpoints | `test1/gui/backend/app.py` | New `/api/review/rules*`, `/api/loop/*`, `/api/diff/*` endpoints. Retire `/api/review/upload`. |
| UI | `test1/gui/frontend/src/tabs/Review.tsx` + new components | Reorganize into Rules / Iteration / Diff & Accept sections. Extend `PngViewer` for side-by-side. |

### Compatibility

- The existing `Finding` dataclass + `findings.json` envelope are *extended*
  (new optional fields), not replaced.
- The existing per-row Apply fix-queue flow stays available for ad-hoc fixes
  outside a loop; loop is fully autonomous.
- Hardcoded `BOBCAT_PULLS`/`IC_POWER_GROUPS`/`OPEN_DRAIN_OUTPUTS`/`I2C_BUSES`
  literals in `review/rules.py` are deleted (per cleanup A).
- The existing linter (`test1/altium/layout_lint.py`) is **not** modified
  (standing rule).

---

## 3. Rule schema + storage

### Pydantic models (`test1/review/rule_schema.py`)

```python
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field

Severity = Literal["ERROR", "WARNING", "INFO"]
Family   = Literal["schematic", "simulation", "design"]
Origin   = Literal["generated", "user", "imported"]

class SourceCitation(BaseModel):
    doc:   str           # path or URL
    loc:   str           # "line 15" | "page 4" | "§7.3.4" | "#anchor"
    quote: str = ""      # short verbatim excerpt, ≤200 chars

class AppliesTo(BaseModel):
    refdes:    str | None  = None
    pins:      list[str] = []
    net:       str | None  = None
    rail:      str | None  = None
    sheet:     str | None  = None
    sim_block: str | None  = None
    sim_type:  str | None  = None
    mpn:       str | None  = None
    role_spec: dict      = {}     # parametric constraints for missing-by-spec

class RuleBase(BaseModel):
    id:        str                   # SCREAMING_SNAKE, stable
    family:    Family
    severity:  Severity
    title:     str
    applies_to: AppliesTo
    source:    list[SourceCitation] = Field(min_length=1)
    fix_hint:  str = ""
    enabled:   bool = True
    origin:    Origin = "generated"

class StructuralRule(RuleBase):
    evaluation: Literal["structural"] = "structural"
    predicate:  "Predicate"
    prompt:     None = None

class SemanticRule(RuleBase):
    evaluation: Literal["semantic"] = "semantic"
    predicate:  None = None
    prompt:     str

Rule = Annotated[
    Union[StructuralRule, SemanticRule],
    Field(discriminator="evaluation"),
]
```

### Predicate library

Closed list — generator may only emit these `kind`s. New predicates added via
PR (keeps evaluation deterministic + auditable).

| `kind` | Args | Fires when |
|---|---|---|
| `decoupling_count` | `refdes, pins[], min, value_match?` | Fewer than `min` caps share a net with `refdes.<pin>` |
| `pullup_pulldown` | `net, rail, value_match, kind: "up"\|"down"` | No matching resistor connects `net` to `rail` (or GND) |
| `no_connect` | `refdes, pin` | Datasheet-NC pin is wired |
| `net_routing` | `from, to, via: series_R\|jumper\|direct` | Topology between two pins doesn't match |
| `connector_pin` | `refdes, pin, net` | Connector pin not wired to expected net |
| `power_rail_membership` | `refdes, pin, rail` | Power pin not on expected rail |
| `value_in_range` | `refdes, min?, max?, value_regex?` | Part value outside spec window |
| `present` | `mpn` OR `role_spec` | Required part / role isn't represented |
| `sim_pass` | `sim_block, sim_type` | Named sim doesn't verdict OK |
| `sim_metric` | `sim_block, sim_type, metric, op, value` | Specific analyzer metric out of bounds |

### Storage location & merge policy

- Single file at `test1/review/rules.yaml` (committed to git).
- Top-level `version` field for future migration.
- `sources_seen: [{path, mtime}]` records every doc the generator read —
  drives the **staleness banner** when any current source mtime is newer than
  the recorded value.
- Merge on regenerate:
  - `origin: user` rules kept verbatim.
  - `origin: generated` from prior file: kept only if a new candidate `id`
    doesn't collide.
  - `id` collision between `user` and new `generated`: keep user, write
    `_rule_conflicts.json` for the GUI to surface.
- `enabled: false` is the soft-delete path; evaluator skips disabled rules;
  GUI shows them collapsed.

### Generation flow (`rule_gen.py`)

When `/api/review/rules/generate` fires (lazy on first Run Review, or explicit
"Regenerate"):

1. Build doc bundle from `design_requirements.md`, every `Parts Library/<MPN>/
   <MPN>.pdf`, `[External] Bobcat Board Design.pdf`, every URL embedded in
   `design_requirements.md` (fetched via `WebFetch`, cached to
   `test1/review/.url_cache/<sha256>.txt`), every `netlist/<sheet>.yaml`.
2. Dispatch `rulegen_provider().generate(doc_bundle, predicate_spec,
   existing_user_rules)`. Default impl: `ClaudeRuleGenProvider` (new
   `rule_gen` `AGENT_KIND`, default model `claude-opus-4-8`).
3. Validate output via `Rule.model_validate_json`; retry up to 2× on
   validation error with the error fed back as feedback.
4. Source-citation verification: every rule's `source[*].quote` must be a
   substring of the cited doc (verifier reads the doc and checks). Rules with
   unverifiable quotes are dropped from the candidate set with a warning.
5. Merge with existing user-origin rules; write `rules.yaml`; emit
   `sources_seen`.
6. Endpoint returns the new rule count + per-family breakdown.

---

## 4. Orchestrator

### Endpoint family

```
POST /api/loop/start                → { loop_id }
GET  /api/loop/{id}                 → { state }
GET  /api/loop/{id}/stream          → SSE event stream
POST /api/loop/{id}/cancel          → { ok: true }
POST /api/loop/{id}/accept          → { ok: true }
POST /api/loop/{id}/reject          → { ok: true, revert?: [refdes, ...] }
GET  /api/loop/{id}/diff            → per-sheet diff payload
GET  /api/loop/latest               → most recent loop_id (for reload)
```

State lives in-memory in `_LOOPS: dict[str, Loop]` plus an on-disk audit at
`test1/gui/state/loops/<loop_id>.json` (survives backend restart so Diff &
Accept stays available for the most recent loop).

### Loop dataclass

```python
@dataclass
class Loop:
    loop_id: str
    started_at: float
    status: str  # "running" | "all_clear" | "plateau" | "max_rounds"
                 #   | "cancelled" | "error"
    round: int = 0
    rounds: list[Round] = field(default_factory=list)
    findings_initial: list[Finding] = field(default_factory=list)
    findings_current: list[Finding] = field(default_factory=list)
    snapshot_dir: Path | None = None
    sub_runs: list[str] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    cancelled: bool = False
    last_delta: int | None = None
    plateau_streak: int = 0
    finished_at: float | None = None

@dataclass
class Round:
    n: int
    started_at: float
    finished_at: float | None
    findings_before: int
    findings_after:  int
    findings_cleared: list[str]
    findings_new:     list[str]
    actions: list[Action]
    build_status: str = ""
    lint_summary: dict | None = None
    sim_results: list[dict] = field(default_factory=list)

@dataclass
class Action:
    kind: str        # "apply" | "lint_fix" | "symbol_gen" | "missing_part" | "sim"
    agent_run_id: str | None
    targets: list[str]
    status: str
    summary: str
```

### Inner loop (`closed_loop.py`)

```
async def run_loop(loop_id):
    L = _LOOPS[loop_id]
    L.snapshot_dir = OUT_DIR / "render_snapshots" / loop_id
    snapshot_pre_loop()           # copy out/render/*.svg + netlist/*.yaml
                                  #   + out/lint.json + review/findings.json
    L.findings_initial = evaluate_rules()
    L.findings_current = L.findings_initial[:]
    emit("loop_start", findings=len(L.findings_initial))

    for r in 1..MAX_ROUNDS:            # MAX_ROUNDS = 10
        if L.cancelled: break
        if not L.findings_current: break   # all-clear

        R = Round(n=r, findings_before=len(L.findings_current), ...)
        L.round = r; L.rounds.append(R)
        emit("round_start", round=r, findings=R.findings_before)

        for action in plan_actions(L.findings_current):
            if L.cancelled: break
            A = Action(kind=action.kind, targets=action.targets, ...)
            R.actions.append(A)
            emit("action_start", round=r, action=A)
            A.agent_run_id = await dispatch(action)   # reuses start_* fns
            emit("action_end", round=r, action=A)

        if not L.cancelled:
            emit("build_start", round=r)
            R.build_status, R.lint_summary = await rebuild_project()
            emit("build_end", round=r, status=R.build_status,
                              lint=R.lint_summary)

            if needs_resim(R):
                R.sim_results = await run_affected_sims(R)
                emit("sim_results", round=r, results=R.sim_results)

        R.finished_at = now()
        new_findings = evaluate_rules()
        R.findings_after = len(new_findings)
        cleared, added = diff_finding_sets(L.findings_current, new_findings)
        R.findings_cleared, R.findings_new = cleared, added
        delta = len(cleared) - len(added)
        L.findings_current = new_findings
        L.last_delta = delta
        L.plateau_streak = (L.plateau_streak + 1) if delta <= 0 else 0
        emit("round_done", round=r, delta=delta, cleared=cleared,
                            new=added, remaining=R.findings_after)

        if L.plateau_streak >= 2:
            L.status = "plateau"; break

    if not L.cancelled and L.status == "running":
        L.status = "all_clear" if not L.findings_current else "max_rounds"
    if L.cancelled:
        L.status = "cancelled"
    L.finished_at = now()
    persist_loop_audit(L)
    if L.status == "plateau":
        post_plateau_changelog(L)   # source="closed_loop"
    emit("done", status=L.status, rounds=len(L.rounds),
                  remaining=len(L.findings_current))
```

### `plan_actions(findings)` mapping

| Finding source | Action `kind` |
|---|---|
| `predicate.kind ∈ {decoupling_count, pullup_pulldown, no_connect}` | `apply` (trivial bucket; multiple grouped per call) |
| `predicate.kind == present (role_spec or unknown mpn)` | `missing_part` |
| `predicate.kind == present (known mpn, just not placed)` | `apply` |
| `predicate.kind ∈ {net_routing, connector_pin, power_rail_membership, value_in_range}` | `apply` |
| `predicate.kind ∈ {sim_pass, sim_metric}` | `sim` (failure routes a follow-up `apply` next round with root cause) |
| `evaluation == semantic` | `apply` (with rule's `prompt` + verdict text in agent prompt) |
| Build-failure or ERROR-lint finding | `lint_fix` |

Within one round, actions dispatch **sequentially**. Parallel fan-out is a
non-goal.

### Halt conditions

- **All-clear**: every rule passes, lint `0/0/0`, all affected sims OK.
- **Plateau**: `Δ = cleared - new ≤ 0` for 2 consecutive rounds.
- **Max rounds**: 10 (safety cap).
- **User cancel**: cancel button → `L.cancelled = True`; checked between
  actions and between rounds (never mid-build, which could corrupt `.SchDoc`s).
- **Error**: unhandled exception → `status: error`, snapshot stays for
  forensic.

### Event stream

```
event: loop_start    data: {"findings": 23}
event: round_start   data: {"round": 1, "findings": 23}
event: action_start  data: {"round": 1, "kind": "apply",
                            "agent_run_id": "abc123", "targets": [...]}
event: action_end    data: {"round": 1, "kind": "apply", "status": "ok",
                            "summary": "applied 5 of 7 trivial fixes"}
event: build_end     data: {"round": 1, "status": "ok",
                            "lint": {"E":0,"W":0,"I":2}}
event: sim_results   data: {"round": 1, "results": [...]}
event: round_done    data: {"round": 1, "delta": 5, "cleared": [...],
                            "new": [], "remaining": 18}
event: plateau       data: {"streak": 2, "remaining": 12,
                            "by_severity": {"E":2,"W":7,"I":3}}
event: done          data: {"status": "all_clear", "rounds": 4,
                            "remaining": 0}
```

Frontend subscribes via `subscribeLoop(loop_id, onEvent, onDone)` — a new
helper in `api.ts` mirroring `subscribeAgent`. The live console embedded in
the Iteration view subscribes to the *active* `agent_run_id` for each
`action_start`, unsubscribing on `action_end`.

### Snapshot mechanics

Before round 1, copy to `out/render_snapshots/<loop_id>/`:
- every `out/render/*.svg` → `<loop_id>/render/`
- every `netlist/*.yaml` → `<loop_id>/netlist/`
- `out/lint.json` → `<loop_id>/lint.json`
- `review/findings.json` → `<loop_id>/findings_initial.json`

**Accept**: tar + remove the snapshot dir; keep `out/` and YAMLs as-is.
**Reject**: restore from snapshot; rebuild once to refresh `out/render/`.
**Selective revert**: per-refdes/per-change YAML-level surgical revert; not
full file restore.

---

## 5. Missing-part flow (`missing_part.py`)

Triggered by the orchestrator when a finding's rule has `predicate.kind ==
"present"`. Two sub-cases:

- **by-MPN** — `applies_to.mpn` set but `Parts Library/<mpn>/` missing.
- **by-spec** — `applies_to.role_spec` describes a role + parametric
  constraints; no library entry matches.

### Strenuous selection process

```
1. SEARCH
   provider = parts_provider()
   candidates = provider.search(query, role_spec)
   (Default WebSearchPartsProvider builds the query and calls WebSearch +
    WebFetch; future CustomPartsAPIProvider hits the user's API.)

2. RANK + DEEP-READ TOP 5 CANDIDATES
   For each: WebFetch distributor page + datasheet URL; extract via
   knowledge_provider().query(mpn=cand.mpn, question="parametric specs,
   typical-application circuit, pinout, abs-max ratings, lifecycle
   status") — when the future knowledge API is wired, this is fast.
   Reject candidates with: identity-check fail, NRND/obsolete, missing
   hard role_spec constraint, wrong package.
   Rank survivors by:
     + cross-distributor confirmation
     + soft-constraint match (precision class, automotive grade,
       package pref, manufacturer reputation)
     + abs-max margin
     + (future) BOM cost

3. ITERATE THROUGH SURVIVORS — EACH FULL EVALUATION
   For each candidate in ranked order, until one PASSES or list exhausts:
     a. Install datasheet (move from _datasheet_incoming/ via
        install_datasheets.py), run symbol_gen agent → .SchLib.
     b. Place via apply agent — values seeded from datasheet typical-
        application + role_spec midpoints + sheet-local precision hints.
     c. Build_project + lint must pass (≤1 lint_fix sub-round on fail).
     d. SIM VERIFICATION — affected-block gate:
        "affected" = every blocks.yaml entry whose deck builder or
        refdes_map references the new refdes/MPN. For each affected
        (block, sim_type) that's "implemented":
          run; on FAIL enter VALUE-TWEAK SUBLOOP (≤3 inner rounds,
          sim_interpret suggests adjustments).
        Blocks the part doesn't touch are skipped.
     e. All sims OK → candidate ACCEPTED.
        Any sim still failing → candidate FAILED; revert; next candidate.
   Each candidate's outcome (passed / failed-why) recorded in audit.

4. NO CANDIDATE PASSED  →  TOPOLOGY-ADAPTATION FALLBACK
   Pick the best-margin failed candidate. Dispatch a `topology_adapt`
   apply-agent call (new AGENT_KIND, default opus) with:
     - the failed candidate's MPN + datasheet excerpts (via knowledge
       provider)
     - the verdict text + "stuck because" reason from sim_interpret
     - the relevant sheet's build_<sheet>.py + netlist YAML
     - the rule that triggered the missing-part action
     - instruction: "propose a LOCAL topology change that lets THIS
       candidate satisfy the rule. Examples allowed: series resistor,
       buffer, level shift, swap PMOS↔NMOS with rail inversion, gate
       resistor + clamp. Do NOT cross sheet boundaries or alter parent
       rule's stated intent."
   Up to 2 topology adaptations per missing-part action; each goes
   through the full apply → build → lint → sim gate.

5. IMPASSE  →  surface to user
   When no candidate AND no topology adaptation works:
     - Action recorded as `fail` with full audit
     - Iteration timeline shows red card with details: every candidate
       considered + sim margins + rejection reason, every topology
       attempt + why it failed
     - "Manual override" button → opens Library tab with the
       role_spec / search query pre-filled
     - Counts as `-Δ` round for plateau tracking (2 in a row halts loop)
```

### Where new artifacts land

| Artifact | Path | Lifecycle |
|---|---|---|
| Search query + top candidates JSON | `test1/review/.web_cache/<sha256>.json` | 7-day cache |
| Datasheet PDF (raw download) | `_datasheet_incoming/<MPN>.pdf` | Moved by `install_datasheets.py` |
| Datasheet PDF (installed) | `Parts Library/<MPN>/<MPN>.pdf` | Permanent |
| Symbol library | `Parts Library/<MPN>/<MPN>.SchLib` | Permanent |
| JSON pin-spec (audit) | `Parts Library/<MPN>/<MPN>.pinspec.json` | Permanent |
| Loop audit | `test1/gui/state/loops/<loop_id>.json` → `rounds[i].actions[j]` | Per loop |

---

## 6. Provider layer (`test1/review/providers.py`)

One module, four interfaces. Each has a today-impl (default) and a placeholder
for the user's future APIs.

### Interfaces

```python
class PartsProvider(ABC):
    @abstractmethod
    def search(self, query: str, role_spec: dict | None) -> list[Candidate]: ...
    @abstractmethod
    def fetch_datasheet(self, candidate: Candidate) -> Path: ...

class KnowledgeProvider(ABC):
    """Queryable datasheet knowledge store."""
    @abstractmethod
    def query(self, mpn: str | None, question: str,
              max_excerpts: int = 5) -> list[Excerpt]: ...
    @abstractmethod
    def list_indexed(self) -> list[str]: ...

class RuleGenProvider(ABC):
    """LLM that emits rules.yaml from a doc bundle."""
    @abstractmethod
    async def generate(self, doc_bundle: DocBundle,
                       predicate_spec: PredicateSpec,
                       existing_user_rules: list[Rule]) -> list[Rule]: ...

class SchematicChatProvider(ABC):
    """AgentRail chat backend — whole-schematic, multi-session."""
    @abstractmethod
    async def chat_turn(self, session_id: str, user_msg: str,
                        context: SchematicContext) -> ChatRun: ...
```

### Default + placeholder impls

| Slot | Default (today) | Placeholder (future) |
|---|---|---|
| Parts | `WebSearchPartsProvider` — `WebSearch` + distributor sites + identity check | `CustomPartsAPIProvider` — env `CUSTOM_PARTS_API_URL` / `_KEY`; POST `{query, role_spec}` |
| Knowledge | `LocalPDFKnowledgeProvider` — reads PDFs on demand via `sim/read_pdf.py` (fitz); keyword scoring | `CustomKnowledgeAPIProvider` — env `CUSTOM_KNOWLEDGE_API_URL` / `_KEY`; POST `{mpn, question, max_excerpts}` |
| RuleGen | `ClaudeRuleGenProvider` — dispatches `rule_gen` `AGENT_KIND` via `claude -p` with the doc bundle | `CustomRuleGenAPIProvider` — env `CUSTOM_RULEGEN_API_URL` / `_KEY`; POST docs + spec |
| SchemaChat | `ClaudeChatProvider` — existing `start_chat_turn` → `chat` `AGENT_KIND` | `CustomSchematicChatAPIProvider` — env `CUSTOM_CHAT_API_URL` / `_KEY` |

All placeholder classes raise `NotImplementedError` until their env vars are
set; the registry function returns the default impl when not configured.

### Registry

```python
def parts_provider()      -> PartsProvider:        ...
def knowledge_provider()  -> KnowledgeProvider:    ...
def rulegen_provider()    -> RuleGenProvider:      ...
def chat_provider()       -> SchematicChatProvider: ...
```

Phase 6 of rollout adds a small "Providers configured" diagnostic in the GUI
(Resources tab) showing each slot's current backend.

---

## 7. UI layout (Review tab remodel)

### Sections inside the tab

```
┌─ Phase 3 · Design Review ────────────────────────────────────────────┐
│   E·W·I·System stat strip       (existing)                            │
│   [ ▶ Run review ]   [ ⟳ Refresh ]                                    │
│   ▸ Rules · 47 active · 0 disabled · approved                         │
│   ▸ Iteration · idle / running round R of 10                          │
│   ▸ Diff & Accept · loop e7a3c (rendered only after a completed loop) │
│   ▸ Findings · 12 open / 5 dismissed   (existing list, extended)      │
│   ▸ error_log.md                       (existing)                     │
└───────────────────────────────────────────────────────────────────────┘
```

All section headers collapse independently. Default-expanded on load:
Rules (if needs approval) → Iteration (if running) → Diff & Accept (if loop
completed) → Findings.

### A. Rules section — three states

- **A.1 First run, no rules**: candidate rule list grouped by family with
  per-rule enable checkbox, severity tag, source citation, fix hint, and a
  collapsible details body. `Approve all & Run loop` button writes the rule
  set with `origin: user` on anything edited, then `POST /api/loop/start`.
- **A.2 Steady state**: collapsed list with family chips and counts;
  `Add rule`, `Regenerate`, `Export YAML` buttons.
- **A.3 Staleness banner**: when `sources_seen` mtimes are older than
  on-disk sources, shows the changed file list with `Regenerate rules`
  and `Run with current rules anyway` buttons.

### B. Iteration section

Renders only while a loop is live or just finished. Card-per-round timeline
showing each action with status, delta, build status, and sim summary. Live
console embedded subscribing to the active sub-agent's stream. Cancel button
checks the flag between actions and rounds (never mid-build).

**B.2 Plateau halt** — inline banner: "Loop halted at round R. Plateau —
N findings unresolved. Reasons surfaced below." Plus a `source="closed_loop"`
line into `ChangelogPanel`.
**B.3 All clear** — green success header with "Open Diff & Accept".

### C. Diff & Accept

- Mode toggle: **Side-by-side** (default) or **Overlay** (single pane with
  Before / After / Diff toggle).
- Sheet tabs with change badges (count + dominant change kind color).
- Two `PngViewer` Canvas instances with synced `{zoom, tx, ty}`.
- Highlights via extended `RegionOverlay`: `boxes: {x, y, kind:
  "added"|"removed"|"changed"}[]`; colors green / red / amber.
- Change list below: refdes-level rows; click → scroll/zoom both panes.
- **Accept** / **Reject (revert)** / **Selective revert** buttons hit
  `/api/loop/{id}/accept|reject`.

### Cross-cutting UI changes

- E/W/I top strip reflects `findings_current` while a loop is running, falls
  back to `review/findings.json` when idle.
- `FindingRow` gains a "round N" badge linking back to that round's card.
- PDF dropzone deleted (`Review.tsx:206–241` + supporting state/refs/api).
- `ChangelogPanel` gets a new `sourceTone` for `closed_loop` (calm blue) and
  backend `changelog_add` adds `"closed_loop"` to its source allowlist.
- Per-row Apply buttons in the existing Findings list are **disabled while a
  loop is `running`** — the loop owns the design during that window. They
  re-enable on loop completion / cancel.

---

## 8. Cleanup · Migration · Rollout · Testing

### Cleanup (Phase 0)

| Item | Action |
|---|---|
| Purge stale findings + delete the processed PDF | Empty `findings.json`, delete `semantic_findings.json` + `fix_queue.json`, delete `_review_incoming/_processed/report_U41_—_2026-05-28.pdf` |
| Retire hardcoded rule tables | Delete `BOBCAT_PULLS`/`IC_POWER_GROUPS`/`OPEN_DRAIN_OUTPUTS`/`I2C_BUSES`/`PARTS_INDEX_HINTS` + their `check_*` functions; `RULES = []`. Retire `semantic_review.py` |
| Retire Voltai-PDF upload flow | Delete `_review_incoming/` (folder + `install_review.py` + `_processed/`), delete `/api/review/upload` endpoint + `ReviewUploadBody`, delete `api.uploadReview` + TS type, delete dropzone JSX + state |
| Wipe `review_history/` | Delete the 14 dated `.md` files inside; keep the directory |

### Migration (schema-level)

- `Finding` dataclass gains `iteration_round: int \| None`,
  `resolved_by_run_id: str \| None`, `loop_id: str \| None` — all optional;
  existing serialized findings still load.
- `findings.json` envelope gains optional `loop_id, round` top-level keys when
  written by the loop.
- `FixQueueEntry` unchanged.
- `rules.py` `RULES` becomes `[]` (file kept for `Finding` import compat).
- `AGENT_KINDS` gains `rule_gen` (default `claude-opus-4-8`) and
  `topology_adapt` (default `claude-opus-4-8`).
- `_LOOPS` registry added parallel to `_RUNS`.

### Rollout phases (each ends with `build_project` green + `tsc -b` clean)

| Phase | Scope | Gate |
|---|---|---|
| **0** | Cleanup (all four items) | Build green; backend boots; Review tab loads with empty findings + no dropzone |
| **1** | `rule_schema.py` + `rule_eval.py` skeleton with predicate dispatch table; `providers.py` with all 4 interfaces + default + placeholder impls; empty `rules.yaml` | `pytest` for predicate dispatch passes; provider registry returns defaults; placeholder classes raise `NotImplementedError` |
| **2** | `rule_gen.py` + `rule_gen` `AGENT_KIND` + `/api/review/rules/generate` endpoint + Section A UI (approval gate, staleness banner) | First generation pass produces ≥30 valid rules with verified source citations; A.1 mockup renders |
| **3** | `rule_eval.py` full evaluator + `run_review.py` refactor to evaluate `rules.yaml`; findings.json reflects rule evaluations with `rule_id` | Clicking Run Review (one-shot mode) evaluates all rules; findings appear in existing list with new `rule_id` badges |
| **4** | `closed_loop.py` + `_LOOPS` + `/api/loop/*` endpoints + Section B (Iteration view) + Section C (basic Diff & Accept, no missing-part flow yet) + snapshot mechanics | A loop runs over test1 with the generated rules; reaches all-clear or plateau; Diff & Accept side-by-side works; Accept/Reject round-trip |
| **5** | `missing_part.py` + `topology_adapt` `AGENT_KIND` + topology-adaptation subloop + parts/knowledge provider integration | Inject a missing-part rule; loop downloads datasheet, generates symbol, places, sim-verifies, reaches all-clear OR clean impasse with full audit |
| **6** | Polish: ChangelogPanel `closed_loop` source color; Iteration view live-console polish; sheet-tab change badges; TODO #1 monitoring verification test; "Providers configured" diagnostic in Resources tab | All standing-memory tests pass; build green; end-to-end loop smoke test |

### Testing

| Layer | Type | Verifies |
|---|---|---|
| Predicate dispatch | unit | each `predicate.kind` against fixture netlist |
| Rule schema | unit | `Rule.model_validate` accepts sample yaml, rejects malformed |
| Generator merge | unit | user-origin survives regenerate; collision → conflict file; staleness banner trips on mtime |
| Orchestrator round loop | integration | given fixture findings + stub `start_*`, loop terminates at all-clear / plateau / max_rounds correctly |
| Plateau detection | unit | `Δ ≤ 0` × 2 → plateau; positive Δ resets streak |
| Snapshot round-trip | integration | snapshot before round 1; Reject restores byte-for-byte; rebuild green |
| Diff endpoint | integration | snapshot + current → `{added, removed, changed}` matches hand-authored expected |
| SSE event stream | integration | events arrive in expected order/shape; late subscriber sees replay then `done` (TODO #1 verification) |
| Missing-part flow | smoke (manual) | end-to-end on synthetic missing-MPN rule; audit log non-empty + final part installed OR clean impasse |
| UI components | manual + light Playwright (optional) | approval gate fires; iteration streams; diff toggles; Accept/Reject hits correct endpoints |

### Non-goals

- No parallel fan-out inside a round. Sequential within, parallel across
  rounds isn't a thing.
- No edits to the linter (`test1/altium/layout_lint.py`).
- No changes to Generator / Library / Resources / Simulation tabs or
  AgentRail chat UX (only `ChangelogPanel` gets a new source color).
- No new build pipeline; orchestrator drives existing `build_project` +
  `start_*` agents.
- Real Altium fidelity oracle stays a manual check, not coupled to the loop.

### Risks + mitigations

| Risk | Mitigation |
|---|---|
| Rule generator hallucinates citations | Pre-write verifier rejects rules whose `quote` substring isn't in cited doc |
| Loop corrupts design unilaterally | Snapshot + Reject; loop never bypasses `build_project` gates |
| Missing-part flow downloads wrong PDF | Identity check (step 3 of Section 5): MPN literal in first 3 pages, manufacturer line on cover |
| SSE stream drops mid-loop | Reuses `subscribeAgent`'s settled-on-CLOSED + 240s watchdog (`[[sim-run-resilience-and-telemetry]]`); TODO #1 verification test enforces it |
| Web search budget runaway | Per-loop hard cap: total `WebSearch + WebFetch` calls ≤ 50 |
| Loop concurrency | Backend rejects `POST /api/loop/start` while another loop is `running` |
| Future custom API has different output shape | Validation at the boundary (`Rule.model_validate_json`) regardless of source |
| Custom chat provider breaks AgentRail | `SchematicChatProvider.chat_turn` signature pins the session contract; registry rejects + falls back if violated |
| Knowledge provider returns excerpts without `loc` | Excerpt contract enforces it; provider rejects + falls back to LocalPDF on violation |

---

## 9. Configuration surface (for future API wire-up)

```
# .claude/settings.local.json or environment
CUSTOM_PARTS_API_URL      / CUSTOM_PARTS_API_KEY
CUSTOM_KNOWLEDGE_API_URL  / CUSTOM_KNOWLEDGE_API_KEY
CUSTOM_RULEGEN_API_URL    / CUSTOM_RULEGEN_API_KEY
CUSTOM_CHAT_API_URL       / CUSTOM_CHAT_API_KEY
```

`providers.py` reads at startup; absent → default impl. The "Providers
configured" diagnostic in the Resources tab shows current bindings.

---

## 10. Deferred follow-ups (already in `test1/TODO.md`)

- Verify the iteration-view monitoring catches the generation start (covered
  by Phase 6's TODO #1 verification test).
- Side-by-side schematic diff toggle (covered by Section 7.C).
- Accept-all / Reject-all / Selective revert (covered by Section 7.C).

---

## Open questions deferred to implementation

- Concurrency model when two browser tabs subscribe to the same loop stream
  (probably fine — fan-out is per-`subscriber` queue) — verify in Phase 4.
- Loop audit cleanup policy: how many historical loop audits to retain on
  disk (proposal: keep last 20, tar older into `state/loops/_archive.tar`).
- Orchestrator model: `claude-opus-4-8` for the planning step, or use Sonnet
  for cost? Defer to user during Phase 4 implementation.
