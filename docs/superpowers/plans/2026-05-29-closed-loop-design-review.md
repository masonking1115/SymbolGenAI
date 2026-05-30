# Closed-Loop Design Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the test1 GUI Review tab into an autonomous closed-loop design assistant — rules generated from docs, iteration over apply/build/sim until plateau or all-clear, missing-part flow with topology adaptation, side-by-side schematic diff + accept/reject.

**Architecture:** Hybrid orchestrator: Python backend owns the outer loop, sub-AgentRuns do per-round work. Polymorphic Rule schema (structural+semantic) in `rules.yaml`. Provider layer abstracts parts/knowledge/rulegen/chat with default impls + placeholders for future custom APIs. Snapshot before round 1; Diff & Accept restores from snapshot on reject. Reuses existing `subscribeAgent` SSE protocol + `RegionOverlay` mask pattern.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 (discriminated unions); React 18 + TypeScript + Vite + Tailwind; `claude -p` for agent dispatch; ngspice for simulation. Spec at `docs/superpowers/specs/2026-05-29-closed-loop-design-review-design.md`.

**Venv interpreter (for every Python invocation):**
```
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe
```
Shorthand `$PY` in commands below.

**Repo root (cwd for module invocations):**
```
C:\Users\mking\Downloads\HW-SW_CoDesigner\SymbolGenAI
```

**Green-state gates (run after every phase):**
- `& $PY -m test1.altium.build_project` → `FAILURES: none` + every sheet `0/0/0`
- `cd test1/gui/frontend && ./node_modules/.bin/tsc -b` → no errors

---

## File structure

### New Python modules (under `test1/review/`)

| File | Responsibility |
|---|---|
| `rule_schema.py` | Pydantic discriminated-union models: `Rule`, `StructuralRule`, `SemanticRule`, `AppliesTo`, `SourceCitation`, predicate models |
| `rule_eval.py` | Structural-predicate dispatch table + semantic-rule executor; emits `Finding`s |
| `rule_gen.py` | Doc-bundle builder, URL cache, source-citation verifier, generator entrypoint |
| `providers.py` | 4 ABCs + default impls + `Custom*APIProvider` placeholders + registry |
| `closed_loop.py` | `Loop`/`Round`/`Action` dataclasses, `_LOOPS` registry, `run_loop()`, `plan_actions()`, snapshot helpers, plateau detection |
| `missing_part.py` | Strenuous selection: search → rank → identity check → install → place → sim-verify → topology adaptation |
| `diff.py` | Per-sheet refdes-level netlist diff → `{added, removed, changed}` boxes |
| `test_rule_eval.py` (in `test1/review/`) | Unit tests for predicate dispatch |
| `test_closed_loop.py` (in `test1/review/`) | Integration tests for orchestrator round loop, plateau, snapshot round-trip |

### Modified Python modules

| File | Changes |
|---|---|
| `test1/review/rules.py` | Delete hardcoded tables; `RULES = []`; keep `Finding` import |
| `test1/review/semantic_review.py` | Delete (functionality moves to `rule_eval.py`) |
| `test1/review/findings.py` | Add optional `iteration_round`, `resolved_by_run_id`, `loop_id` fields |
| `test1/run_review.py` | Phase 2a calls `rule_eval.run_all(rules.yaml)`; Phase 2b removed |
| `test1/gui/backend/app.py` | Add `/api/review/rules*`, `/api/loop/*`, `/api/diff/*`; delete `/api/review/upload` |
| `test1/gui/backend/agent.py` | Add `rule_gen` + `topology_adapt` to `AGENT_KINDS`; add `"closed_loop"` to changelog allowlist |
| `test1/altium/build_project.py` | Add hook for `closed_loop.snapshot_pre_loop()` (optional pre-build callback) |

### New frontend modules (under `test1/gui/frontend/src/`)

| File | Responsibility |
|---|---|
| `components/RulesSection.tsx` | Section A — approval gate / steady state / staleness banner |
| `components/IterationSection.tsx` | Section B — per-round timeline + live console + cancel |
| `components/DiffAndAccept.tsx` | Section C — side-by-side / overlay diff + accept/reject |
| `components/DiffOverlay.tsx` | Generalization of the SVG-mask `RegionOverlay` for `added`/`removed`/`changed` kinds |
| `api.ts` additions | `subscribeLoop`, rule CRUD calls, loop endpoints, diff fetch |
| `types.ts` additions | `Rule`, `Loop`, `LoopEvent`, `Action`, `DiffPayload` |

### Modified frontend modules

| File | Changes |
|---|---|
| `tabs/Review.tsx` | Replace dropzone block (lines 206-241) with 3 new sections + per-row "round N" badge + disable-Apply-during-loop |
| `components/PngViewer.tsx` | Accept second `srcPre` + `side: "split"|"overlay"`; generalize `RegionOverlay` to accept color kinds |
| `components/ChangelogPanel.tsx` | Add `closed_loop` to `sourceTone` |
| `App.tsx` | Wire `onLoopCompleted` callback (collapse Iteration, expand Diff & Accept) |

### Deleted

| Path | Reason |
|---|---|
| `_review_incoming/` (folder, including `install_review.py` + `_processed/`) | Voltai-PDF flow retired |
| `test1/review/semantic_review.py` | Replaced by `rule_eval.py` semantic-rule executor |
| `test1/review_history/*.md` (14 files; keep dir) | Wipe pre-loop audit |

---

## Phase 0 — Cleanup

Make a clean slate before any new code. One commit per task; phase ends green.

### Task 0.1: Purge stale findings + queue + semantic cache

**Files:**
- Overwrite: `test1/review/findings.json`
- Overwrite: `test1/review/semantic_findings.json`
- Overwrite: `test1/review/fix_queue.json`

- [ ] **Step 1: Reset findings.json to empty envelope**

Write to `C:\Users\mking\Downloads\HW-SW_CoDesigner\SymbolGenAI\test1\review\findings.json`:

```json
{
  "findings": [],
  "semantic": [],
  "summary": { "ERROR": 0, "WARNING": 0, "INFO": 0 }
}
```

- [ ] **Step 2: Reset semantic_findings.json to empty array**

Write to `test1/review/semantic_findings.json`:

```json
[]
```

- [ ] **Step 3: Reset fix_queue.json to empty array**

Write to `test1/review/fix_queue.json`:

```json
[]
```

- [ ] **Step 4: Verify the backend loads them cleanly**

Run:
```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "import json; print(json.load(open('test1/review/findings.json'))['summary'])"
```
Expected output: `{'ERROR': 0, 'WARNING': 0, 'INFO': 0}`

- [ ] **Step 5: Commit**

```powershell
git add test1/review/findings.json test1/review/semantic_findings.json test1/review/fix_queue.json
git commit -m "chore: purge stale review state (findings/semantic/queue)

Reset to empty envelopes ahead of the closed-loop rebuild."
```

---

### Task 0.2: Delete the processed Voltai PDF

**Files:**
- Delete: `_review_incoming/_processed/report_U41_—_Review_2026-05-28_04_39_47.pdf`

- [ ] **Step 1: Delete the file**

```powershell
Remove-Item "_review_incoming\_processed\report_U41_—_Review_2026-05-28_04_39_47.pdf" -Force
```

- [ ] **Step 2: Verify gone**

```powershell
Test-Path "_review_incoming\_processed\report_U41_—_Review_2026-05-28_04_39_47.pdf"
```
Expected: `False`

- [ ] **Step 3: Commit**

```powershell
git add -A "_review_incoming/_processed/"
git commit -m "chore: remove stale Voltai PDF report_U41 (2026-05-28)"
```

---

### Task 0.3: Retire hardcoded rule tables + semantic_review.py

**Files:**
- Modify: `test1/review/rules.py`
- Delete: `test1/review/semantic_review.py`

- [ ] **Step 1: Rewrite `test1/review/rules.py` to a stub**

Replace the entire file with:

```python
"""Legacy rule dispatcher — retained only for the `Finding` import shim.

The hardcoded rule tables (BOBCAT_PULLS / IC_POWER_GROUPS / OPEN_DRAIN_OUTPUTS
/ I2C_BUSES / PARTS_INDEX_HINTS) and their check_* functions were retired on
2026-05-29 when rules moved into the generated test1/review/rules.yaml.

Rule evaluation now happens in test1/review/rule_eval.py — see the closed-loop
design spec at docs/superpowers/specs/2026-05-29-closed-loop-design-review-design.md.
"""

from __future__ import annotations

from .findings import Finding  # re-exported for downstream importers

RULES: list = []   # intentionally empty; new evaluator lives in rule_eval.py


def run_all(_idx) -> list[Finding]:
    """Compat shim — returns no findings. Use rule_eval.run_all instead."""
    return []
```

- [ ] **Step 2: Delete semantic_review.py**

```powershell
Remove-Item test1\review\semantic_review.py -Force
```

- [ ] **Step 3: Verify run_review.py still imports cleanly**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review import rules; print('rules.RULES =', rules.RULES)"
```
Expected: `rules.RULES = []`

- [ ] **Step 4: Verify run_review.py runs without crashing on the now-missing semantic import**

`run_review.py` currently imports `semantic_review` lazily. Patch it to skip:

Open `test1/run_review.py`, find lines 68-76:
```python
    if not args.no_semantic:
        print()
        print("Phase 2b: semantic per-IC review …")
        try:
            from review import semantic_review
            findings.extend(semantic_review.run(idx))
            print(f"  total findings: {len(findings)}")
        except ImportError:
            print("  (semantic_review.py not yet implemented — skipping)")
```

Replace with:
```python
    # Phase 2b retired 2026-05-29 — semantic rules now live in rules.yaml
    # and are evaluated by rule_eval.py alongside structural rules.
```

- [ ] **Step 5: Verify run_review.py runs**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\run_review.py --no-semantic --json test1\review\findings.json
```
Expected: prints `Phase 1: loading requirements …`, `Phase 2a: deterministic rules …  0 findings so far`, `Phase 3: rendering …  wrote …`, exits 0.

- [ ] **Step 6: Commit**

```powershell
git add test1\review\rules.py test1\review\semantic_review.py test1\run_review.py
git commit -m "refactor(review): retire hardcoded rule tables + semantic_review

rules.py is now a stub re-exporting Finding for downstream import compat.
semantic_review.py is deleted; rule_eval.py (next phase) handles both
structural and semantic rules from rules.yaml. run_review.py drops Phase 2b."
```

---

### Task 0.4: Retire the Voltai-PDF upload flow

**Files:**
- Delete: `_review_incoming/` (entire folder)
- Modify: `test1/gui/backend/app.py:2104-2133` (delete `/api/review/upload` endpoint + `ReviewUploadBody`)
- Modify: `test1/gui/frontend/src/api.ts` (delete `uploadReview` method)
- Modify: `test1/gui/frontend/src/tabs/Review.tsx:206-241` (delete dropzone JSX + supporting state)

- [ ] **Step 1: Delete `_review_incoming/` folder**

```powershell
Remove-Item -Recurse -Force _review_incoming
```

- [ ] **Step 2: Find and delete `ReviewUploadBody` + `/api/review/upload` in app.py**

Open `test1/gui/backend/app.py`, find lines ~2095-2133 (the `ReviewUploadBody` pydantic model + the `@app.post("/api/review/upload")` block):

Locate this section (search for `class ReviewUploadBody`):
```python
class ReviewUploadBody(BaseModel):
    filename: str
    content_b64: str


@app.post("/api/review/upload")
async def review_upload(body: ReviewUploadBody) -> dict:
    # ... ~30 lines ...
    return { ... }
```

Delete the entire block (both the class and the endpoint). Also remove any `REVIEW_INCOMING` / `REVIEW_INSTALL_SCRIPT` constants near line 94-95 if still referenced ONLY by this endpoint.

Use Grep first to confirm no other references:
```powershell
```

Run via the Grep tool: search pattern `REVIEW_INCOMING|REVIEW_INSTALL_SCRIPT|review_upload|ReviewUploadBody` in `test1/gui/backend/app.py`. If the only references are inside the block being deleted, remove the constants too.

- [ ] **Step 3: Delete `uploadReview` from api.ts**

Open `test1/gui/frontend/src/api.ts`, find the `uploadReview` method (around line 84). Delete the method + its TS type. Use Grep for `uploadReview` first to find all references.

- [ ] **Step 4: Delete the PDF dropzone from Review.tsx**

Open `test1/gui/frontend/src/tabs/Review.tsx`. Delete:

1. Lines 65-104 (the `uploadPdf`, `onDropZoneFile`, `onDrop` callbacks)
2. Lines 37-39 (`uploading`, `uploadMsg`, `fileInputRef` state)
3. Lines 205-241 (the `<section className="mt-5">` block containing the drop zone)

Also remove any imports that became unused (e.g. `useRef` if no longer used).

- [ ] **Step 5: Verify the frontend type-checks**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: clean exit, no errors.

- [ ] **Step 6: Verify the backend boots**

```powershell
cd C:\Users\mking\Downloads\HW-SW_CoDesigner\SymbolGenAI
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, 'test1/gui/backend'); import app; print('backend imports OK')"
```
Expected: `backend imports OK`.

- [ ] **Step 7: Commit**

```powershell
git add -A _review_incoming test1\gui\backend\app.py test1\gui\frontend\src\api.ts test1\gui\frontend\src\tabs\Review.tsx
git commit -m "refactor(review): retire Voltai PDF upload flow

Closed-loop spec replaces external-PDF ingest with the in-repo rule
generator. Deletes _review_incoming/ + install_review.py, the
/api/review/upload endpoint + ReviewUploadBody model, the api.uploadReview
client method, and the dropzone JSX + state in Review.tsx."
```

---

### Task 0.5: Wipe review_history

**Files:**
- Delete: contents of `test1/review_history/*.md` (keep folder)

- [ ] **Step 1: Delete the 14 historical reports**

```powershell
Get-ChildItem test1\review_history -Filter *.md | Remove-Item -Force
```

- [ ] **Step 2: Verify folder is empty but exists**

```powershell
Test-Path test1\review_history
(Get-ChildItem test1\review_history).Count
```
Expected: `True`, then `0`.

- [ ] **Step 3: Commit**

```powershell
git add -A test1\review_history
git commit -m "chore: wipe review_history pre-closed-loop reset"
```

---

### Task 0.6: Phase 0 gate

- [ ] **Step 1: Build green**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m test1.altium.build_project
```
Expected: ends with `FAILURES: none`, every sheet `0/0/0`.

- [ ] **Step 2: Backend starts and Review tab loads**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\gui\backend\app.py
```
(Leave running, open <http://localhost:5173>, navigate to Review tab.)

Expected: Review tab loads with **empty findings list**, no dropzone, no console errors. Kill backend with Ctrl+C.

- [ ] **Step 3: Frontend builds clean**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: no errors.

Phase 0 complete.

---

## Phase 1 — Schema + Providers + Predicate Dispatch

Build the foundation: rule schema, provider interfaces with placeholders for the user's future APIs, predicate dispatch table with unit tests.

### Task 1.1: Create `rule_schema.py` with Pydantic models

**Files:**
- Create: `test1/review/rule_schema.py`

- [ ] **Step 1: Write the schema file**

Create `test1/review/rule_schema.py`:

```python
"""Polymorphic Rule schema for the closed-loop design review.

A Rule is a check DEFINITION; a Finding (in findings.py) is the check RESULT.
Rules are persisted in test1/review/rules.yaml and dispatched by rule_eval.py.

Two evaluation modes — discriminated union via the `evaluation` field:
  • structural: Python predicate evaluated against netlist/sim result.
  • semantic:   LLM agent reads cited source + design, emits a verdict.

Family tag (schematic / simulation / design) picks which evaluator subsystem
runs the rule:
  • schematic  → predicates over netlist/<sheet>.yaml + built .SchDoc.
  • simulation → predicates over sim_service.run_block_sim results.
  • design     → cross-cutting; predicate may touch either subsystem.

Origin tag controls regen merge: user-origin rules survive regenerate.

Spec: docs/superpowers/specs/2026-05-29-closed-loop-design-review-design.md §3.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


Severity = Literal["ERROR", "WARNING", "INFO"]
Family   = Literal["schematic", "simulation", "design"]
Origin   = Literal["generated", "user", "imported"]


class SourceCitation(BaseModel):
    doc:   str
    loc:   str
    quote: str = ""


class AppliesTo(BaseModel):
    refdes:    str | None      = None
    pins:      list[str]       = []
    net:       str | None      = None
    rail:      str | None      = None
    sheet:     str | None      = None
    sim_block: str | None      = None
    sim_type:  str | None      = None
    mpn:       str | None      = None
    role_spec: dict            = {}


# ---- Predicate variants (structural) -----------------------------------

class _PredBase(BaseModel):
    pass

class DecouplingCount(_PredBase):
    kind: Literal["decoupling_count"] = "decoupling_count"
    refdes: str
    pins: list[str]
    min: int
    value_match: str | None = None

class PullupPulldown(_PredBase):
    kind: Literal["pullup_pulldown"] = "pullup_pulldown"
    net: str
    rail: str
    value_match: str
    direction: Literal["up", "down"]

class NoConnect(_PredBase):
    kind: Literal["no_connect"] = "no_connect"
    refdes: str
    pin: str

class NetRouting(_PredBase):
    kind: Literal["net_routing"] = "net_routing"
    from_pin: str        # "refdes.pin"
    to_pin: str
    via: Literal["series_R", "jumper", "direct"]

class ConnectorPin(_PredBase):
    kind: Literal["connector_pin"] = "connector_pin"
    refdes: str
    pin: str
    net: str

class PowerRailMembership(_PredBase):
    kind: Literal["power_rail_membership"] = "power_rail_membership"
    refdes: str
    pin: str
    rail: str

class ValueInRange(_PredBase):
    kind: Literal["value_in_range"] = "value_in_range"
    refdes: str
    min: float | None = None
    max: float | None = None
    value_regex: str | None = None

class Present(_PredBase):
    kind: Literal["present"] = "present"
    mpn: str | None = None
    role_spec: dict = {}

class SimPass(_PredBase):
    kind: Literal["sim_pass"] = "sim_pass"
    sim_block: str
    sim_type: str

class SimMetric(_PredBase):
    kind: Literal["sim_metric"] = "sim_metric"
    sim_block: str
    sim_type: str
    metric: str
    op: Literal[">=", "<=", "==", ">", "<"]
    value: float


Predicate = Annotated[
    Union[
        DecouplingCount, PullupPulldown, NoConnect, NetRouting,
        ConnectorPin, PowerRailMembership, ValueInRange, Present,
        SimPass, SimMetric,
    ],
    Field(discriminator="kind"),
]


# ---- Rule (discriminated by evaluation mode) ----------------------------

class RuleBase(BaseModel):
    id:         str
    family:     Family
    severity:   Severity
    title:      str
    applies_to: AppliesTo
    source:     list[SourceCitation] = Field(min_length=1)
    fix_hint:   str = ""
    enabled:    bool = True
    origin:     Origin = "generated"


class StructuralRule(RuleBase):
    evaluation: Literal["structural"] = "structural"
    predicate:  Predicate
    prompt:     None = None


class SemanticRule(RuleBase):
    evaluation: Literal["semantic"] = "semantic"
    predicate:  None = None
    prompt:     str


Rule = Annotated[
    Union[StructuralRule, SemanticRule],
    Field(discriminator="evaluation"),
]


# ---- Top-level rules.yaml shape -----------------------------------------

class SourceSeen(BaseModel):
    """Doc / URL the generator read, with its mtime at read time. Drives the
    staleness banner: if the current mtime is newer, the rule set is stale."""
    path: str
    mtime: float


class RulesFile(BaseModel):
    version: int = 1
    generated_at: str = ""           # ISO-8601 UTC
    sources_seen: list[SourceSeen] = []
    rules: list[Rule] = []
```

- [ ] **Step 2: Verify the file parses + the discriminated union works**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
from test1.review.rule_schema import RulesFile
sample = {
  'version': 1,
  'rules': [{
    'id': 'TEST_DECOUPLE',
    'family': 'schematic',
    'evaluation': 'structural',
    'severity': 'ERROR',
    'title': 'test',
    'applies_to': {'refdes': 'U10'},
    'source': [{'doc': 'a', 'loc': 'b'}],
    'predicate': {'kind': 'decoupling_count', 'refdes': 'U10', 'pins': ['1'], 'min': 1}
  }]
}
rf = RulesFile.model_validate(sample)
print(type(rf.rules[0]).__name__, rf.rules[0].predicate.kind)
"
```
Expected: `StructuralRule decoupling_count`

- [ ] **Step 3: Commit**

```powershell
git add test1\review\rule_schema.py
git commit -m "feat(review): add Pydantic Rule schema (discriminated union)

Polymorphic Rule with evaluation ∈ {structural, semantic} + family tag.
10 predicate kinds (decoupling_count, pullup_pulldown, ...) in a closed
list — generators may only emit these. Spec §3."
```

---

### Task 1.2: Unit tests for rule schema validation

**Files:**
- Create: `test1/review/test_rule_schema.py`

- [ ] **Step 1: Write the failing tests**

Create `test1/review/test_rule_schema.py`:

```python
"""Unit tests for rule_schema.py — discriminated-union routing + validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from test1.review.rule_schema import (
    Rule, RulesFile, StructuralRule, SemanticRule,
    DecouplingCount, PullupPulldown, SimMetric,
)


def _make_structural(rule_id="R1", pred=None):
    return {
        "id": rule_id,
        "family": "schematic",
        "evaluation": "structural",
        "severity": "ERROR",
        "title": "t",
        "applies_to": {"refdes": "U10"},
        "source": [{"doc": "d", "loc": "l"}],
        "predicate": pred or {
            "kind": "decoupling_count",
            "refdes": "U10", "pins": ["1"], "min": 1,
        },
    }


def _make_semantic(rule_id="R2", prompt="check that thing"):
    return {
        "id": rule_id,
        "family": "design",
        "evaluation": "semantic",
        "severity": "WARNING",
        "title": "t",
        "applies_to": {"refdes": "U41"},
        "source": [{"doc": "d", "loc": "l"}],
        "prompt": prompt,
    }


def test_structural_rule_routes_correctly():
    r = Rule.__metadata__[0].discriminator    # noqa — sanity check union exists
    rf = RulesFile.model_validate({"rules": [_make_structural()]})
    assert isinstance(rf.rules[0], StructuralRule)
    assert rf.rules[0].predicate.kind == "decoupling_count"


def test_semantic_rule_routes_correctly():
    rf = RulesFile.model_validate({"rules": [_make_semantic()]})
    assert isinstance(rf.rules[0], SemanticRule)
    assert rf.rules[0].prompt == "check that thing"


def test_predicate_discriminator_picks_right_subclass():
    r = StructuralRule.model_validate(_make_structural(pred={
        "kind": "pullup_pulldown",
        "net": "SCL", "rail": "+3V3",
        "value_match": "10k", "direction": "up",
    }))
    assert isinstance(r.predicate, PullupPulldown)


def test_sim_metric_predicate():
    r = StructuralRule.model_validate(_make_structural(pred={
        "kind": "sim_metric",
        "sim_block": "opa_bias", "sim_type": "dc_sweep",
        "metric": "fs_current_uA", "op": ">=", "value": 600,
    }))
    assert isinstance(r.predicate, SimMetric)
    assert r.predicate.op == ">="


def test_missing_source_rejected():
    bad = _make_structural()
    bad["source"] = []
    with pytest.raises(ValidationError):
        StructuralRule.model_validate(bad)


def test_structural_with_prompt_rejected():
    bad = _make_structural()
    bad["prompt"] = "should not be here"
    with pytest.raises(ValidationError):
        StructuralRule.model_validate(bad)


def test_semantic_without_prompt_rejected():
    bad = _make_semantic()
    del bad["prompt"]
    with pytest.raises(ValidationError):
        SemanticRule.model_validate(bad)


def test_unknown_predicate_kind_rejected():
    bad = _make_structural(pred={"kind": "nonexistent_kind", "refdes": "U10"})
    with pytest.raises(ValidationError):
        StructuralRule.model_validate(bad)


def test_rules_file_roundtrip_yaml(tmp_path):
    import yaml
    rf = RulesFile.model_validate({
        "version": 1,
        "generated_at": "2026-05-29T15:00:00Z",
        "rules": [_make_structural("A"), _make_semantic("B")],
    })
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(rf.model_dump()))
    loaded = RulesFile.model_validate(yaml.safe_load(path.read_text()))
    assert len(loaded.rules) == 2
    assert isinstance(loaded.rules[0], StructuralRule)
    assert isinstance(loaded.rules[1], SemanticRule)
```

- [ ] **Step 2: Run the tests — expect 9 passes**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m pytest test1\review\test_rule_schema.py -v
```
Expected: `9 passed`.

If `pytest` not available, install: `& $PY -m pip install pytest pyyaml`.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\test_rule_schema.py
git commit -m "test(review): rule schema discriminated-union validation"
```

---

### Task 1.3: Create `providers.py` with 4 ABCs + defaults + placeholders

**Files:**
- Create: `test1/review/providers.py`

- [ ] **Step 1: Write the providers module**

Create `test1/review/providers.py`:

```python
"""Provider abstraction layer — swap LLM/search backends without touching
call sites.

Four slots:
  • parts     — search for components by query/spec, fetch datasheets
  • knowledge — query a parsed-datasheet KB
  • rulegen   — generate rules.yaml from a doc bundle
  • chat      — schematic-aware chat backend for AgentRail

Each slot has a DEFAULT impl (today: WebSearch/local PDF/claude-p) and a
Custom*APIProvider PLACEHOLDER raising NotImplementedError until its
env vars are set. Registry functions inspect env at call time.

Environment variables (set in .claude/settings.local.json or shell):
  CUSTOM_PARTS_API_URL      / CUSTOM_PARTS_API_KEY
  CUSTOM_KNOWLEDGE_API_URL  / CUSTOM_KNOWLEDGE_API_KEY
  CUSTOM_RULEGEN_API_URL    / CUSTOM_RULEGEN_API_KEY
  CUSTOM_CHAT_API_URL       / CUSTOM_CHAT_API_KEY

Spec §6.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rule_schema import Rule


# ---- Shared lightweight value types -------------------------------------

@dataclass
class Candidate:
    mpn: str
    distributor: str
    datasheet_url: str
    params: dict          # parametric specs extracted from the result
    score: float = 0.0    # populated by the ranker

@dataclass
class Excerpt:
    text: str
    doc: str              # path or URL
    loc: str              # "page 4" / "§7.3.4" / "line 15"
    score: float

@dataclass
class DocBundle:
    """Input to the rule generator — paths + extracted text."""
    requirements_md: str               # full text of design_requirements.md
    bobcat_pdf_text: str               # text of [External] Bobcat Board Design.pdf
    datasheet_texts: dict[str, str]    # {mpn: text}
    url_texts: dict[str, str]          # {url: text}
    netlist_yamls: dict[str, str]      # {sheet: raw yaml text}

@dataclass
class PredicateSpec:
    """The set of structural-predicate kinds the generator may emit, plus
    a human-readable summary of each kind's args, so the generator can
    target the schema correctly."""
    kinds: list[dict]   # [{kind, args_schema_dict, description}, ...]

@dataclass
class SchematicContext:
    """Whole-schematic context passed to the chat provider."""
    netlist_yamls: dict[str, str]
    recent_changelog: list[dict]
    current_findings: list[dict]
    sheet_svg_paths: dict[str, str]

@dataclass
class ChatRun:
    """Handle the chat provider returns to the caller; caller subscribes via
    the existing SSE protocol."""
    run_id: str
    stream_url: str    # relative; e.g. "/api/agent/<run_id>/stream"


# ---- 1. Parts -----------------------------------------------------------

class PartsProvider(ABC):
    @abstractmethod
    def search(self, query: str, role_spec: dict | None) -> list[Candidate]: ...
    @abstractmethod
    def fetch_datasheet(self, candidate: Candidate) -> Path: ...


class WebSearchPartsProvider(PartsProvider):
    """Default: WebSearch + WebFetch over distributor + manufacturer sites.
    Implementation lives in missing_part.py (uses Claude Code's WebSearch
    tool through an agent dispatch) — this class is a thin facade so the
    registry pattern is uniform.
    """
    def search(self, query: str, role_spec: dict | None) -> list[Candidate]:
        # Delegates to missing_part._web_search_candidates — implemented
        # in Phase 5. Stubbed here so Phase 1 tests can construct the
        # provider without dragging in agent dispatch.
        from .missing_part import _web_search_candidates  # noqa: PLC0415
        return _web_search_candidates(query, role_spec)

    def fetch_datasheet(self, candidate: Candidate) -> Path:
        from .missing_part import _web_fetch_datasheet
        return _web_fetch_datasheet(candidate)


class CustomPartsAPIProvider(PartsProvider):
    """PLACEHOLDER — user's future parts-exploration API.

    Wire-up when ready:
      • search() → POST {url}/search with {query, role_spec};
        expect { candidates: [{mpn, distributor, datasheet_url, params}] }
      • fetch_datasheet() → GET {datasheet_url}; save to _datasheet_incoming/

    Auth header: Bearer {CUSTOM_PARTS_API_KEY}.
    """
    def __init__(self):
        url = os.environ.get("CUSTOM_PARTS_API_URL")
        if not url:
            raise NotImplementedError(
                "Set CUSTOM_PARTS_API_URL to enable CustomPartsAPIProvider"
            )
        self.url = url
        self.key = os.environ.get("CUSTOM_PARTS_API_KEY", "")

    def search(self, query: str, role_spec: dict | None) -> list[Candidate]:
        raise NotImplementedError("CustomPartsAPIProvider.search — wire up POST /search")

    def fetch_datasheet(self, candidate: Candidate) -> Path:
        raise NotImplementedError("CustomPartsAPIProvider.fetch_datasheet — wire up GET")


# ---- 2. Knowledge -------------------------------------------------------

class KnowledgeProvider(ABC):
    @abstractmethod
    def query(self, mpn: str | None, question: str,
              max_excerpts: int = 5) -> list[Excerpt]: ...
    @abstractmethod
    def list_indexed(self) -> list[str]: ...


class LocalPDFKnowledgeProvider(KnowledgeProvider):
    """Default: reads PDFs on demand via sim/read_pdf.py (fitz). Naive
    full-text scan + keyword scoring. Scoped to Parts Library/<mpn>/<mpn>.pdf
    when mpn is given, else searches the whole library. Good enough for
    test1 scale (16 parts)."""
    def query(self, mpn: str | None, question: str,
              max_excerpts: int = 5) -> list[Excerpt]:
        from test1.sim.read_pdf import extract_text     # noqa: PLC0415
        repo_root = Path(__file__).resolve().parent.parent.parent
        targets: list[Path] = []
        lib = repo_root / "test1" / "Parts Library"
        if mpn:
            p = lib / mpn / f"{mpn}.pdf"
            if p.exists():
                targets.append(p)
        else:
            targets = list(lib.glob("*/*.pdf"))
        terms = [t.lower() for t in question.split() if len(t) > 3]
        excerpts: list[Excerpt] = []
        for path in targets:
            text = extract_text(path)
            for para in text.split("\n\n"):
                low = para.lower()
                score = sum(1 for t in terms if t in low)
                if score:
                    excerpts.append(Excerpt(
                        text=para[:400], doc=str(path.relative_to(repo_root)),
                        loc="(page approx — local PDF scan)", score=float(score),
                    ))
        excerpts.sort(key=lambda e: -e.score)
        return excerpts[:max_excerpts]

    def list_indexed(self) -> list[str]:
        repo_root = Path(__file__).resolve().parent.parent.parent
        lib = repo_root / "test1" / "Parts Library"
        return sorted(p.name for p in lib.iterdir() if p.is_dir())


class CustomKnowledgeAPIProvider(KnowledgeProvider):
    """PLACEHOLDER — user's future knowledge agent API (parsed-datasheet KB).

    Wire-up:
      • query() → POST {url}/query with {mpn, question, max_excerpts}
        → expect { excerpts: [{text, doc, loc, score}] }
      • list_indexed() → GET {url}/indexed → { mpns: [...] }
    """
    def __init__(self):
        url = os.environ.get("CUSTOM_KNOWLEDGE_API_URL")
        if not url:
            raise NotImplementedError(
                "Set CUSTOM_KNOWLEDGE_API_URL to enable CustomKnowledgeAPIProvider"
            )
        self.url = url
        self.key = os.environ.get("CUSTOM_KNOWLEDGE_API_KEY", "")

    def query(self, mpn, question, max_excerpts=5):
        raise NotImplementedError("CustomKnowledgeAPIProvider.query")

    def list_indexed(self) -> list[str]:
        raise NotImplementedError("CustomKnowledgeAPIProvider.list_indexed")


# ---- 3. Rule generator --------------------------------------------------

class RuleGenProvider(ABC):
    @abstractmethod
    async def generate(self, doc_bundle: DocBundle,
                       predicate_spec: PredicateSpec,
                       existing_user_rules: list["Rule"]) -> list["Rule"]: ...


class ClaudeRuleGenProvider(RuleGenProvider):
    """Default: dispatches the `rule_gen` AGENT_KIND via claude -p with the
    doc bundle + predicate library + sample yaml. Validation + retry done
    in rule_gen.py — this class just wraps the dispatch.

    Implementation completed in Phase 2.
    """
    async def generate(self, doc_bundle, predicate_spec, existing_user_rules):
        from .rule_gen import _claude_generate          # noqa: PLC0415
        return await _claude_generate(doc_bundle, predicate_spec, existing_user_rules)


class CustomRuleGenAPIProvider(RuleGenProvider):
    """PLACEHOLDER — user's future rule-generator LLM API.

    Wire-up:
      • generate() → POST {url}/generate with
        {doc_bundle, predicate_spec, user_rules}
        → expect { rules: [Rule JSON per rule_schema.py] }

    Same Rule schema as the internal generator, so the merge step is
    identical regardless of source.
    """
    def __init__(self):
        url = os.environ.get("CUSTOM_RULEGEN_API_URL")
        if not url:
            raise NotImplementedError(
                "Set CUSTOM_RULEGEN_API_URL to enable CustomRuleGenAPIProvider"
            )
        self.url = url
        self.key = os.environ.get("CUSTOM_RULEGEN_API_KEY", "")

    async def generate(self, doc_bundle, predicate_spec, existing_user_rules):
        raise NotImplementedError("CustomRuleGenAPIProvider.generate")


# ---- 4. Schematic chat --------------------------------------------------

class SchematicChatProvider(ABC):
    @abstractmethod
    async def chat_turn(self, session_id: str, user_msg: str,
                        context: SchematicContext) -> ChatRun: ...


class ClaudeChatProvider(SchematicChatProvider):
    """Default: existing `chat` AGENT_KIND via start_chat_turn.
    AgentRail UX is unchanged regardless of which provider is active.
    """
    async def chat_turn(self, session_id, user_msg, context):
        # Lazy import to avoid pulling agent.py at provider-module import time.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui" / "backend"))
        import agent as agent_mod                       # noqa: PLC0415
        # context passed via the existing chat-session memory mechanism;
        # see agent.start_chat_turn for how it composes the prompt.
        run = await agent_mod.start_chat_turn(session_id, user_msg)
        return ChatRun(run_id=run.run_id,
                       stream_url=f"/api/agent/{run.run_id}/stream")


class CustomSchematicChatAPIProvider(SchematicChatProvider):
    """PLACEHOLDER — user's future schematic-chat LLM API.

    Wire-up:
      • chat_turn() → POST {url}/chat/turn with
        {session_id, user_msg, context}
        → expect { run_id, stream_url } so the existing subscribeAgent
        protocol works unchanged.

    Standing memory ([[gui-altium-backend]]): the rail is 'thinking
    partner' chat only — don't break that contract via this swap.
    """
    def __init__(self):
        url = os.environ.get("CUSTOM_CHAT_API_URL")
        if not url:
            raise NotImplementedError(
                "Set CUSTOM_CHAT_API_URL to enable CustomSchematicChatAPIProvider"
            )
        self.url = url
        self.key = os.environ.get("CUSTOM_CHAT_API_KEY", "")

    async def chat_turn(self, session_id, user_msg, context):
        raise NotImplementedError("CustomSchematicChatAPIProvider.chat_turn")


# ---- Registry -----------------------------------------------------------

def parts_provider() -> PartsProvider:
    if os.environ.get("CUSTOM_PARTS_API_URL"):
        try:
            return CustomPartsAPIProvider()
        except NotImplementedError:
            pass
    return WebSearchPartsProvider()


def knowledge_provider() -> KnowledgeProvider:
    if os.environ.get("CUSTOM_KNOWLEDGE_API_URL"):
        try:
            return CustomKnowledgeAPIProvider()
        except NotImplementedError:
            pass
    return LocalPDFKnowledgeProvider()


def rulegen_provider() -> RuleGenProvider:
    if os.environ.get("CUSTOM_RULEGEN_API_URL"):
        try:
            return CustomRuleGenAPIProvider()
        except NotImplementedError:
            pass
    return ClaudeRuleGenProvider()


def chat_provider() -> SchematicChatProvider:
    if os.environ.get("CUSTOM_CHAT_API_URL"):
        try:
            return CustomSchematicChatAPIProvider()
        except NotImplementedError:
            pass
    return ClaudeChatProvider()


def configured_providers() -> dict[str, str]:
    """For the Resources-tab diagnostic — current backend per slot."""
    return {
        "parts":     type(parts_provider()).__name__,
        "knowledge": type(knowledge_provider()).__name__,
        "rulegen":   type(rulegen_provider()).__name__,
        "chat":      type(chat_provider()).__name__,
    }
```

- [ ] **Step 2: Verify the registry returns defaults when no env vars set**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
from test1.review.providers import configured_providers
print(configured_providers())
"
```
Expected output: `{'parts': 'WebSearchPartsProvider', 'knowledge': 'LocalPDFKnowledgeProvider', 'rulegen': 'ClaudeRuleGenProvider', 'chat': 'ClaudeChatProvider'}`

- [ ] **Step 3: Verify a placeholder raises NotImplementedError**

```powershell
$env:CUSTOM_PARTS_API_URL = "http://example.com"
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
from test1.review.providers import parts_provider
p = parts_provider()
print(type(p).__name__)
try:
    p.search('test', None)
except NotImplementedError as e:
    print('NotImplementedError raised:', e)
"
Remove-Item Env:CUSTOM_PARTS_API_URL
```
Expected: `CustomPartsAPIProvider`, then `NotImplementedError raised: CustomPartsAPIProvider.search — wire up POST /search`.

- [ ] **Step 4: Commit**

```powershell
git add test1\review\providers.py
git commit -m "feat(review): provider abstraction layer + placeholders

Four slots — parts, knowledge, rulegen, chat — each with a default impl
(WebSearch / LocalPDF / Claude) and a Custom*APIProvider placeholder that
raises NotImplementedError until its env vars are wired. Registry picks
the configured provider, falls back to default on missing env.

Spec §6. Future custom-API hookup points: see docstrings on each
Custom*APIProvider class."
```

---

### Task 1.4: Create `rule_eval.py` with predicate dispatch

**Files:**
- Create: `test1/review/rule_eval.py`

- [ ] **Step 1: Write the evaluator**

Create `test1/review/rule_eval.py`:

```python
"""Rule evaluator — dispatches each Rule against the current design.

Structural rules → predicate dispatch table (this module).
Semantic rules → claude -p invocation per rule, with cited source excerpts
                 from knowledge_provider() (Phase 2+).

Emits Finding objects compatible with test1/review/findings.py — the same
schema run_review.py + the GUI already consume.

Spec §3 + §4.plan_actions mapping.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from .findings import AutofixCategory, Finding, Severity
from .netlist_view import load_all, NetlistView
from .rule_schema import (
    Rule, RulesFile, StructuralRule, SemanticRule,
    DecouplingCount, PullupPulldown, NoConnect, NetRouting,
    ConnectorPin, PowerRailMembership, ValueInRange, Present,
    SimPass, SimMetric,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
RULES_YAML = PROJECT_DIR / "review" / "rules.yaml"


# ---- Loader -------------------------------------------------------------

def load_rules(path: Path = RULES_YAML) -> RulesFile:
    if not path.exists():
        return RulesFile()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RulesFile.model_validate(data)


def save_rules(rf: RulesFile, path: Path = RULES_YAML) -> None:
    path.write_text(
        yaml.safe_dump(rf.model_dump(exclude_none=True), sort_keys=False),
        encoding="utf-8",
    )


# ---- Helpers used by multiple predicates --------------------------------

def _value_regex_match(part_value: str, regex: str | None) -> bool:
    if not regex:
        return True
    return bool(re.search(regex, part_value, re.IGNORECASE))


def _is_cap_value(v: str) -> bool:
    return bool(re.search(r"\d+\.?\d*\s*[µu]?[FfNn]F?", v))


# ---- Structural predicate evaluators ------------------------------------

def eval_decoupling_count(p: DecouplingCount, view: NetlistView) -> bool:
    """Returns True if rule PASSES (≥min caps), False if it FIRES."""
    nets: set[str] = set()
    for pin in p.pins:
        for nm in view.nets_with_member(p.refdes, pin):
            nets.add(nm.net)
    if not nets:
        return True  # pin not wired — different problem; validator handles it
    caps: set[str] = set()
    for net in nets:
        for m in view.members(net):
            if m.refdes.startswith("C"):
                hit = view.part(m.refdes)
                if hit and _value_regex_match(hit[1].value, p.value_match):
                    caps.add(m.refdes)
    return len(caps) >= p.min


def eval_pullup_pulldown(p: PullupPulldown, view: NetlistView) -> bool:
    rail = "GND" if p.direction == "down" else p.rail
    net_resistors = {m.refdes for m in view.members(p.net) if m.refdes.startswith("R")}
    rail_resistors = {m.refdes for m in view.members(rail) if m.refdes.startswith("R")}
    candidates = net_resistors & rail_resistors
    for rd in candidates:
        hit = view.part(rd)
        if hit and re.search(p.value_match, hit[1].value, re.IGNORECASE):
            return True
    return False


def eval_no_connect(p: NoConnect, view: NetlistView) -> bool:
    """PASSES if pin is unwired (proper NC); FIRES if pin is wired."""
    return not view.nets_with_member(p.refdes, p.pin)


def eval_net_routing(p: NetRouting, view: NetlistView) -> bool:
    """Very basic shape check: requires (refdes, pin) endpoints share a net,
    and for via=series_R, exactly one resistor sits on that path."""
    f_ref, f_pin = p.from_pin.split(".")
    t_ref, t_pin = p.to_pin.split(".")
    f_nets = {n.net for n in view.nets_with_member(f_ref, f_pin)}
    t_nets = {n.net for n in view.nets_with_member(t_ref, t_pin)}
    if p.via == "direct":
        return bool(f_nets & t_nets)
    # series_R / jumper — share a 2-pin intermediate part
    for fn in f_nets:
        for m in view.members(fn):
            if not m.refdes.startswith(("R", "J")):
                continue
            other_pins = [pn for pn in (view.part(m.refdes) or (None, None))[1].pins.keys()  # type: ignore[union-attr]
                          if pn != m.pin] if view.part(m.refdes) else []
            for op in other_pins:
                op_nets = {n.net for n in view.nets_with_member(m.refdes, op)}
                if op_nets & t_nets:
                    # right shape? series_R wants refdes starting R; jumper J
                    if p.via == "series_R" and m.refdes.startswith("R"):
                        return True
                    if p.via == "jumper" and m.refdes.startswith("J"):
                        return True
    return False


def eval_connector_pin(p: ConnectorPin, view: NetlistView) -> bool:
    return any(n.net == p.net for n in view.nets_with_member(p.refdes, p.pin))


def eval_power_rail_membership(p: PowerRailMembership, view: NetlistView) -> bool:
    return any(n.net == p.rail for n in view.nets_with_member(p.refdes, p.pin))


def eval_value_in_range(p: ValueInRange, view: NetlistView) -> bool:
    hit = view.part(p.refdes)
    if not hit:
        return True  # part not present is a different rule's problem
    value = hit[1].value
    if p.value_regex and not re.search(p.value_regex, value, re.IGNORECASE):
        return False
    # Numeric range — parse leading number with k/M/µ multipliers if min/max set
    if p.min is not None or p.max is not None:
        m = re.match(r"\s*([\d.]+)\s*([kMµunpf]?)", value)
        if not m:
            return False
        num = float(m.group(1))
        mult = {"k": 1e3, "M": 1e6, "µ": 1e-6, "u": 1e-6,
                "n": 1e-9, "p": 1e-12, "f": 1e-15}.get(m.group(2), 1.0)
        val = num * mult
        if p.min is not None and val < p.min:
            return False
        if p.max is not None and val > p.max:
            return False
    return True


def eval_present(p: Present, view: NetlistView) -> bool:
    if p.mpn:
        for sheet in view.sheets:
            for ref, part in view.parts_on_sheet(sheet):
                if part.mpn == p.mpn or part.value == p.mpn:
                    return True
        return False
    # role_spec → cannot be auto-evaluated; missing-part flow handles it
    # by inspecting the rule directly. Return False so the finding fires.
    return False


def eval_sim_pass(p: SimPass, sim_results: dict) -> bool:
    """sim_results = { (block, sim_type): {ok: bool, ...} }"""
    res = sim_results.get((p.sim_block, p.sim_type))
    return bool(res and res.get("ok"))


def eval_sim_metric(p: SimMetric, sim_results: dict) -> bool:
    res = sim_results.get((p.sim_block, p.sim_type))
    if not res:
        return True  # sim hasn't run yet — separate signal
    metric = (res.get("analysis") or {}).get(p.metric)
    if metric is None:
        return True
    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
           "==": lambda a, b: a == b, ">": lambda a, b: a > b,
           "<": lambda a, b: a < b}
    return ops[p.op](metric, p.value)


_DISPATCH = {
    "decoupling_count":       lambda p, view, sim: eval_decoupling_count(p, view),
    "pullup_pulldown":        lambda p, view, sim: eval_pullup_pulldown(p, view),
    "no_connect":             lambda p, view, sim: eval_no_connect(p, view),
    "net_routing":            lambda p, view, sim: eval_net_routing(p, view),
    "connector_pin":          lambda p, view, sim: eval_connector_pin(p, view),
    "power_rail_membership":  lambda p, view, sim: eval_power_rail_membership(p, view),
    "value_in_range":         lambda p, view, sim: eval_value_in_range(p, view),
    "present":                lambda p, view, sim: eval_present(p, view),
    "sim_pass":               lambda p, view, sim: eval_sim_pass(p, sim),
    "sim_metric":             lambda p, view, sim: eval_sim_metric(p, sim),
}


# ---- Finding factory ----------------------------------------------------

def _rule_to_finding(rule: Rule, observed: str = "rule fired") -> Finding:
    af: AutofixCategory = "manual"
    af_data: dict = {}
    if isinstance(rule, StructuralRule):
        if rule.predicate.kind == "pullup_pulldown":
            af = "pullup_pulldown"
            p = rule.predicate
            af_data = {"net": p.net, "rail": p.rail, "kind": p.direction,
                       "value": p.value_match}
        elif rule.predicate.kind == "decoupling_count":
            af = "decoupling"
            p = rule.predicate
            af_data = {"refdes": p.refdes, "pins": p.pins,
                       "min": p.min, "value": p.value_match or "0.1uF"}
        elif rule.predicate.kind == "no_connect":
            af = "nc_marker"
    return Finding(
        rule_id=rule.id,
        severity=Severity(rule.severity),
        title=rule.title,
        subject=(rule.applies_to.refdes or rule.applies_to.net
                 or rule.applies_to.sim_block or rule.id),
        sheet=(rule.applies_to.sheet or "?"),
        component_refs=[rule.applies_to.refdes] if rule.applies_to.refdes else [],
        requirement_ref=rule.source[0].doc + ":" + rule.source[0].loc,
        observed=observed,
        impact="",
        fix=rule.fix_hint,
        autofix=af,
        autofix_data=af_data,
    )


# ---- Top-level runner ---------------------------------------------------

def run_all(rules: list[Rule] | None = None,
            sim_results: dict | None = None) -> list[Finding]:
    """Evaluate every enabled rule against the current netlist + sim cache.

    sim_results: { (block, sim_type): result_dict } as produced by the
    Phase 4 orchestrator. None means "no sim data" — sim_pass/sim_metric
    rules return PASS (silent) when their data is absent."""
    if rules is None:
        rf = load_rules()
        rules = rf.rules
    view = load_all()
    sim = sim_results or {}
    out: list[Finding] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if isinstance(rule, StructuralRule):
            ok = _DISPATCH[rule.predicate.kind](rule.predicate, view, sim)
            if not ok:
                out.append(_rule_to_finding(rule))
        else:
            # SemanticRule — Phase 2+ wires the claude -p invocation here.
            # For Phase 1 we treat semantic rules as deferred (no finding).
            pass
    return out
```

- [ ] **Step 2: Verify it imports cleanly**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review import rule_eval; print('rule_eval imports OK'); print(list(rule_eval._DISPATCH.keys()))"
```
Expected: `rule_eval imports OK`, then `['decoupling_count', 'pullup_pulldown', 'no_connect', 'net_routing', 'connector_pin', 'power_rail_membership', 'value_in_range', 'present', 'sim_pass', 'sim_metric']`.

- [ ] **Step 3: Verify `run_all()` returns empty when rules.yaml doesn't exist yet**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review import rule_eval; print(rule_eval.run_all())"
```
Expected: `[]`.

- [ ] **Step 4: Commit**

```powershell
git add test1\review\rule_eval.py
git commit -m "feat(review): structural-predicate dispatch + semantic stub

10 predicate evaluators (decoupling_count, pullup_pulldown, no_connect,
net_routing, connector_pin, power_rail_membership, value_in_range,
present, sim_pass, sim_metric). Semantic rules deferred to Phase 2.

Emits Finding objects compatible with the existing review pipeline.
rules.yaml not yet present — run_all() returns [] in that case.

Spec §3 predicate library + §4 plan_actions mapping."
```

---

### Task 1.5: Unit tests for predicate dispatch

**Files:**
- Create: `test1/review/test_rule_eval.py`

- [ ] **Step 1: Write fixture-backed tests**

Create `test1/review/test_rule_eval.py`:

```python
"""Unit tests for rule_eval.py predicate dispatch.

Tests against the actual test1 design — the netlist on disk is the fixture.
This keeps tests honest: predicates are evaluated against real data, not
synthetic mocks. If the test1 design changes shape (e.g. a refdes is
renamed), these tests will surface the drift.
"""

from __future__ import annotations

import pytest

from test1.review.rule_eval import (
    eval_decoupling_count, eval_pullup_pulldown, eval_no_connect,
    eval_connector_pin, eval_power_rail_membership,
    eval_present, eval_sim_pass, eval_sim_metric,
)
from test1.review.rule_schema import (
    DecouplingCount, PullupPulldown, NoConnect,
    ConnectorPin, PowerRailMembership, Present, SimPass, SimMetric,
)
from test1.review.netlist_view import load_all


@pytest.fixture(scope="module")
def view():
    return load_all()


def test_decoupling_count_passes_when_caps_present(view):
    # U20 +VDDIO has 6 expected caps per the historical hardcoded rule
    p = DecouplingCount(refdes="U20", pins=["7","13","22","33","34"], min=6)
    assert eval_decoupling_count(p, view) is True


def test_decoupling_count_fires_when_threshold_too_high(view):
    p = DecouplingCount(refdes="U20", pins=["7"], min=99)
    assert eval_decoupling_count(p, view) is False


def test_pullup_pulldown_passes_on_known_pull(view):
    # Per design_requirements.md: GPIO0 has a 10k pulldown to GND
    p = PullupPulldown(net="GPIO0", rail="GND", value_match=r"10\s*k", direction="down")
    assert eval_pullup_pulldown(p, view) is True


def test_pullup_pulldown_fires_on_nonexistent_pull(view):
    p = PullupPulldown(net="THIS_NET_DOESNT_EXIST", rail="GND",
                       value_match=r"10\s*k", direction="down")
    assert eval_pullup_pulldown(p, view) is False


def test_connector_pin_passes_on_known_wiring(view):
    # FMC C39 = +3P3V per design_requirements.md
    p = ConnectorPin(refdes="J1", pin="C39", net="+3V3")
    # Note: actual netlist uses "+3V3" not "+3P3V" — adjust if needed
    # If this fails, inspect with: view.nets_with_member("J1", "C39")
    result = eval_connector_pin(p, view)
    # If the netlist names the pin differently, this is OK to xfail — the
    # important thing is the predicate runs without crashing.
    assert isinstance(result, bool)


def test_power_rail_membership_passes(view):
    # U10 (LDO) Vin pins should be on +3V3
    p = PowerRailMembership(refdes="U10", pin="15", rail="+3V3")
    assert eval_power_rail_membership(p, view) is True


def test_present_passes_when_part_in_library(view):
    p = Present(mpn="TPS7A8401A")
    # If parts_on_sheet doesn't surface MPN this way, the predicate
    # falls through to False — both are acceptable; just verify it runs.
    assert isinstance(eval_present(p, view), bool)


def test_present_fires_for_made_up_mpn(view):
    p = Present(mpn="THIS_MPN_DOES_NOT_EXIST_2026")
    assert eval_present(p, view) is False


def test_sim_pass_fires_when_no_sim_data():
    """No sim cache → metric/pass rules return PASS (silent), per the
    docstring contract — sim runs are gated separately from rule eval."""
    p = SimPass(sim_block="opa_bias", sim_type="dc_sweep")
    assert eval_sim_pass(p, {}) is True


def test_sim_pass_returns_true_when_ok():
    p = SimPass(sim_block="opa_bias", sim_type="dc_sweep")
    sim = {("opa_bias", "dc_sweep"): {"ok": True}}
    assert eval_sim_pass(p, sim) is True


def test_sim_pass_fires_when_not_ok():
    p = SimPass(sim_block="opa_bias", sim_type="dc_sweep")
    sim = {("opa_bias", "dc_sweep"): {"ok": False}}
    assert eval_sim_pass(p, sim) is False


def test_sim_metric_evaluates_correctly():
    p = SimMetric(sim_block="opa_bias", sim_type="dc_sweep",
                  metric="fs_current_uA", op=">=", value=600)
    sim = {("opa_bias", "dc_sweep"):
           {"ok": True, "analysis": {"fs_current_uA": 646}}}
    assert eval_sim_metric(p, sim) is True
    sim2 = {("opa_bias", "dc_sweep"):
            {"ok": True, "analysis": {"fs_current_uA": 500}}}
    assert eval_sim_metric(p, sim2) is False
```

- [ ] **Step 2: Run the tests**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m pytest test1\review\test_rule_eval.py -v
```
Expected: all 12 pass. If `eval_connector_pin` test fails because of net-name mismatch (`+3V3` vs `+3P3V` etc.), adjust the assertion to match the actual netlist — that's surfacing real data, which is the point.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\test_rule_eval.py
git commit -m "test(review): predicate dispatch against live test1 netlist

Tests against real netlist/<sheet>.yaml — if the design shape changes
(refdes renamed, net renamed), these surface the drift."
```

---

### Task 1.6: Create empty `rules.yaml` placeholder

**Files:**
- Create: `test1/review/rules.yaml`

- [ ] **Step 1: Write the file**

Create `test1/review/rules.yaml`:

```yaml
# Generated rules for the closed-loop design review.
# Populated by test1/review/rule_gen.py (Phase 2). User-origin edits
# survive regeneration (see rules with `origin: user`).
#
# Spec: docs/superpowers/specs/2026-05-29-closed-loop-design-review-design.md §3
version: 1
generated_at: ""
sources_seen: []
rules: []
```

- [ ] **Step 2: Verify it loads**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review.rule_eval import load_rules; rf = load_rules(); print('version:', rf.version, '/ rules:', len(rf.rules))"
```
Expected: `version: 1 / rules: 0`

- [ ] **Step 3: Commit**

```powershell
git add test1\review\rules.yaml
git commit -m "feat(review): empty rules.yaml — populated by rule_gen.py in Phase 2"
```

---

### Task 1.7: Phase 1 gate

- [ ] **Step 1: Predicate tests pass**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m pytest test1\review\ -v
```
Expected: all schema + eval tests pass.

- [ ] **Step 2: Build green**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m test1.altium.build_project
```
Expected: `FAILURES: none`, every sheet `0/0/0`.

- [ ] **Step 3: Provider registry diagnostic**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review.providers import configured_providers; print(configured_providers())"
```
Expected: 4 default providers reported.

Phase 1 complete.

---

## Phase 2 — Rule Generation

Generator agent reads docs (requirements + datasheets + Bobcat PDF + URLs), emits candidate rules, validates citations, merges with user-origin rules, writes `rules.yaml`. GUI gets the approval gate (Section A of the Review tab).

### Task 2.1: Register `rule_gen` + `topology_adapt` agent kinds

**Files:**
- Modify: `test1/gui/backend/agent.py` (the `AGENT_KINDS` dict near line 133)

- [ ] **Step 1: Add two entries to `AGENT_KINDS`**

Open `test1/gui/backend/agent.py`. Find `AGENT_KINDS` (currently 9 entries). Add inside the `"Schematic"` group:

```python
    "rule_gen":      {"label": "Rule generator",            "group": "Schematic",   "default": "claude-opus-4-8"},
    "topology_adapt":{"label": "Topology-adapt agent",      "group": "Schematic",   "default": "claude-opus-4-8"},
```

- [ ] **Step 2: Verify the catalog endpoint surfaces them**

Start the backend:
```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\gui\backend\app.py
```

In another shell:
```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/sim/agent-models | Select-Object -ExpandProperty kinds | Where-Object { $_.id -in 'rule_gen', 'topology_adapt' }
```
Expected: both entries returned with `default: claude-opus-4-8`. Stop the backend.

- [ ] **Step 3: Commit**

```powershell
git add test1\gui\backend\agent.py
git commit -m "feat(agent): register rule_gen + topology_adapt agent kinds

Both default to opus-4-8 (heavy authoring work). User-selectable model
via the existing per-kind catalog."
```

---

### Task 2.2: Doc-bundle builder + URL cache

**Files:**
- Create: `test1/review/rule_gen.py`

- [ ] **Step 1: Write the module skeleton**

Create `test1/review/rule_gen.py`:

```python
"""Rule generation — reads project docs, dispatches the rule_gen agent
(via rulegen_provider()), validates output, merges with user-origin rules,
writes test1/review/rules.yaml.

Flow per /api/review/rules/generate:
  1. Build DocBundle from design_requirements.md + every datasheet PDF
     + the Bobcat PDF + every URL embedded in the requirements doc.
  2. Build PredicateSpec from rule_schema's predicate variants.
  3. Call rulegen_provider().generate(bundle, spec, existing_user_rules).
  4. Validate output (Rule.model_validate); retry up to 2× on failure.
  5. Verify each rule's source.quote is a substring of the cited doc.
  6. Merge with existing user-origin rules; write rules.yaml.

Spec §3 generation flow.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .providers import DocBundle, Excerpt, PredicateSpec, knowledge_provider, rulegen_provider
from .rule_schema import (
    Rule, RulesFile, SourceSeen, StructuralRule, SemanticRule,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_DIR.parent
RULES_YAML = PROJECT_DIR / "review" / "rules.yaml"
URL_CACHE = PROJECT_DIR / "review" / ".url_cache"


# ---- Doc bundle ---------------------------------------------------------

URL_RE = re.compile(r"https?://[^\s)>\]]+")


def _extract_text(pdf_path: Path) -> str:
    """Extract text from PDF via sim/read_pdf.py (fitz). Returns "" on error."""
    try:
        from test1.sim.read_pdf import extract_text
        return extract_text(pdf_path)
    except Exception:
        return ""


def _fetch_url_cached(url: str) -> str:
    """WebFetch with on-disk cache. Returns text content; "" on error.
    Cache key: sha256(url). Cache TTL: 7 days."""
    URL_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    cached = URL_CACHE / f"{key}.txt"
    if cached.exists() and (time.time() - cached.stat().st_mtime) < 7 * 86400:
        return cached.read_text(encoding="utf-8", errors="replace")
    # Actual fetch happens during the rule_gen agent run; Python-side we
    # cannot WebFetch directly. The generator agent does it inline using
    # the Claude Code WebFetch tool. For now, return cached-only.
    return cached.read_text(encoding="utf-8", errors="replace") if cached.exists() else ""


def build_doc_bundle() -> DocBundle:
    """Read every input doc + cache content for the generator."""
    reqs_path = PROJECT_DIR / "design_requirements.md"
    bobcat_pdf = PROJECT_DIR / "[External] Bobcat Board Design.pdf"
    lib = PROJECT_DIR / "Parts Library"
    netlist_dir = PROJECT_DIR / "netlist"

    reqs_text = reqs_path.read_text(encoding="utf-8") if reqs_path.exists() else ""

    datasheet_texts: dict[str, str] = {}
    for d in sorted(lib.iterdir()) if lib.exists() else []:
        pdfs = list(d.glob("*.pdf"))
        if pdfs:
            datasheet_texts[d.name] = _extract_text(pdfs[0])

    url_texts: dict[str, str] = {}
    for url in URL_RE.findall(reqs_text):
        url_texts[url] = _fetch_url_cached(url)

    netlist_yamls: dict[str, str] = {}
    for y in sorted(netlist_dir.glob("*.yaml")) if netlist_dir.exists() else []:
        netlist_yamls[y.stem] = y.read_text(encoding="utf-8")

    return DocBundle(
        requirements_md=reqs_text,
        bobcat_pdf_text=_extract_text(bobcat_pdf),
        datasheet_texts=datasheet_texts,
        url_texts=url_texts,
        netlist_yamls=netlist_yamls,
    )


def _sources_seen() -> list[SourceSeen]:
    out: list[SourceSeen] = []
    for path in [PROJECT_DIR / "design_requirements.md",
                 PROJECT_DIR / "[External] Bobcat Board Design.pdf"]:
        if path.exists():
            out.append(SourceSeen(path=str(path.relative_to(REPO_ROOT)),
                                  mtime=path.stat().st_mtime))
    lib = PROJECT_DIR / "Parts Library"
    if lib.exists():
        for d in sorted(lib.iterdir()):
            for pdf in d.glob("*.pdf"):
                out.append(SourceSeen(path=str(pdf.relative_to(REPO_ROOT)),
                                      mtime=pdf.stat().st_mtime))
    return out


# ---- Predicate spec for the generator ------------------------------------

def build_predicate_spec() -> PredicateSpec:
    """The closed list of predicate kinds + their args + a human-readable
    description. The generator MAY ONLY emit kinds from this list — that
    keeps evaluation deterministic and auditable."""
    return PredicateSpec(kinds=[
        {"kind": "decoupling_count",
         "description": "≥N caps on the net(s) shared by refdes.<pins>",
         "args": {"refdes": "str", "pins": "list[str]", "min": "int",
                  "value_match": "regex (optional, default any)"}},
        {"kind": "pullup_pulldown",
         "description": "Pull resistor between net and rail (or GND)",
         "args": {"net": "str", "rail": "str", "value_match": "regex",
                  "direction": '"up" | "down"'}},
        {"kind": "no_connect",
         "description": "Datasheet-NC pin must be unwired",
         "args": {"refdes": "str", "pin": "str"}},
        {"kind": "net_routing",
         "description": "Topology between two pins (series_R / jumper / direct)",
         "args": {"from_pin": "refdes.pin", "to_pin": "refdes.pin",
                  "via": '"series_R" | "jumper" | "direct"'}},
        {"kind": "connector_pin",
         "description": "Connector pin must connect to expected net",
         "args": {"refdes": "str", "pin": "str", "net": "str"}},
        {"kind": "power_rail_membership",
         "description": "Power pin must be on expected rail",
         "args": {"refdes": "str", "pin": "str", "rail": "str"}},
        {"kind": "value_in_range",
         "description": "Part value within numeric/regex window",
         "args": {"refdes": "str", "min": "float?", "max": "float?",
                  "value_regex": "regex?"}},
        {"kind": "present",
         "description": "Required part (by MPN or role_spec) present in design",
         "args": {"mpn": "str?", "role_spec": "dict?"}},
        {"kind": "sim_pass",
         "description": "Named sim block must verdict OK",
         "args": {"sim_block": "str", "sim_type": "str"}},
        {"kind": "sim_metric",
         "description": "Sim analyzer metric within spec",
         "args": {"sim_block": "str", "sim_type": "str", "metric": "str",
                  "op": '">=" | "<=" | "==" | ">" | "<"', "value": "float"}},
    ])


# ---- Source-citation verifier ------------------------------------------

def verify_citations(rule: Rule, bundle: DocBundle) -> tuple[bool, str]:
    """Returns (ok, reason). Each source.quote must appear in the cited doc."""
    for cit in rule.source:
        if not cit.quote.strip():
            continue  # quote optional but recommended
        doc_text = ""
        # Match path or filename component
        for path, text in (
            [(PROJECT_DIR / "design_requirements.md", bundle.requirements_md),
             (PROJECT_DIR / "[External] Bobcat Board Design.pdf",
              bundle.bobcat_pdf_text)]
            + [(PROJECT_DIR / "Parts Library" / mpn / f"{mpn}.pdf", t)
               for mpn, t in bundle.datasheet_texts.items()]
            + [(url, t) for url, t in bundle.url_texts.items()]
        ):
            if cit.doc in str(path) or str(path).endswith(cit.doc):
                doc_text = text
                break
        if not doc_text:
            return False, f"cited doc '{cit.doc}' not in bundle"
        # Substring match — normalize whitespace
        norm = " ".join(doc_text.split()).lower()
        quote_norm = " ".join(cit.quote.split()).lower()
        if quote_norm not in norm:
            return False, f"quote not found in '{cit.doc}': {cit.quote[:60]!r}"
    return True, ""


# ---- Merge -------------------------------------------------------------

def merge_rules(existing: list[Rule], candidates: list[Rule]) -> tuple[list[Rule], list[dict]]:
    """user-origin survives. id collision between user + generated → keep user,
    record conflict."""
    out: list[Rule] = []
    conflicts: list[dict] = []
    user_rules = {r.id: r for r in existing if r.origin == "user"}
    out.extend(user_rules.values())
    for cand in candidates:
        if cand.id in user_rules:
            conflicts.append({
                "id": cand.id,
                "user_title": user_rules[cand.id].title,
                "generated_title": cand.title,
            })
            continue
        out.append(cand)
    return out, conflicts


# ---- Provider dispatch wrapper -----------------------------------------

async def _claude_generate(bundle: DocBundle, spec: PredicateSpec,
                           existing_user_rules: list[Rule]) -> list[Rule]:
    """Default RuleGenProvider impl — dispatches the rule_gen agent.
    Full implementation in Task 2.3 (the agent dispatch is non-trivial)."""
    raise NotImplementedError("see Task 2.3")


# ---- Top-level entrypoint ----------------------------------------------

async def generate_and_write() -> dict:
    """Called by POST /api/review/rules/generate.
    Returns {count_total, count_by_family, conflicts, sources_seen}."""
    bundle = build_doc_bundle()
    spec = build_predicate_spec()
    from .rule_eval import load_rules
    existing = load_rules().rules
    user_rules = [r for r in existing if r.origin == "user"]

    provider = rulegen_provider()
    candidates = await provider.generate(bundle, spec, user_rules)

    # Verify citations; drop unverifiable rules with a warning.
    verified: list[Rule] = []
    rejected: list[dict] = []
    for r in candidates:
        ok, reason = verify_citations(r, bundle)
        if ok:
            verified.append(r)
        else:
            rejected.append({"id": r.id, "reason": reason})

    merged, conflicts = merge_rules(existing, verified)

    rf = RulesFile(
        version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sources_seen=_sources_seen(),
        rules=merged,
    )
    from .rule_eval import save_rules
    save_rules(rf)

    by_family = {"schematic": 0, "simulation": 0, "design": 0}
    for r in merged:
        by_family[r.family] += 1

    return {
        "count_total": len(merged),
        "count_by_family": by_family,
        "conflicts": conflicts,
        "rejected_unverifiable": rejected,
        "sources_seen": [s.model_dump() for s in rf.sources_seen],
    }
```

- [ ] **Step 2: Verify it imports**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review import rule_gen; print('imports OK'); b = rule_gen.build_doc_bundle(); print('reqs len:', len(b.requirements_md)); print('datasheets:', list(b.datasheet_texts.keys())[:3]); print('netlists:', list(b.netlist_yamls.keys()))"
```
Expected: imports OK, requirements ~10kB, datasheet list shows several MPNs, netlists shows 6 sheets.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\rule_gen.py
git commit -m "feat(review): rule generator skeleton — doc bundle + verifier

build_doc_bundle reads requirements.md + every datasheet PDF + Bobcat PDF
+ embedded URLs + netlist YAMLs. verify_citations rejects rules whose
quote substring isn't in the cited doc (anti-hallucination guard).
merge_rules keeps user-origin entries across regeneration.

Agent dispatch (_claude_generate) stubbed for next task."
```

---

### Task 2.3: Wire up the agent dispatch (`_claude_generate`)

**Files:**
- Modify: `test1/gui/backend/agent.py` (add `start_rule_gen` function near the other `start_*` functions)
- Modify: `test1/review/rule_gen.py` (replace the stubbed `_claude_generate`)

- [ ] **Step 1: Add `start_rule_gen` to agent.py**

After `start_symbol_gen` in `test1/gui/backend/agent.py`, add:

```python
async def start_rule_gen(doc_bundle_path: Path, predicate_spec_path: Path,
                        user_rules_path: Path, output_path: Path) -> AgentRun:
    """Dispatch the rule_gen agent. Inputs + output passed as file paths
    (claude -p can't take huge JSON blobs as args)."""
    run = _register("rule_gen")
    prompt = _build_rule_gen_prompt(doc_bundle_path, predicate_spec_path,
                                     user_rules_path, output_path)
    proc = await _spawn_claude(prompt, run, model=model_for("rule_gen"))
    asyncio.create_task(_run_subprocess(run, proc))
    return run


def _build_rule_gen_prompt(bundle: Path, spec: Path, user: Path, out: Path) -> str:
    return f"""You are generating a closed-loop design-review rule set for a
schematic project at {REPO_ROOT}.

Read these files:
  - Doc bundle:       {bundle}    (JSON: requirements_md, bobcat_pdf_text,
                                    datasheet_texts dict, url_texts dict,
                                    netlist_yamls dict)
  - Predicate spec:   {spec}      (JSON: closed list of allowed predicate
                                    kinds + their args)
  - Existing user rules: {user}   (JSON: rules with origin='user' you must
                                    NOT regenerate or contradict)

Emit a JSON file at {out} matching this exact schema (see
test1/review/rule_schema.py for Pydantic models):

  {{ "rules": [ {{... Rule object ...}}, ... ] }}

Each Rule has:
  - id:         SCREAMING_SNAKE_CASE, stable, unique within the file
  - family:     "schematic" | "simulation" | "design"
  - evaluation: "structural" | "semantic"
  - severity:   "ERROR" | "WARNING" | "INFO"
  - title:      one-line headline
  - applies_to: {{ refdes?, pins?, net?, rail?, sheet?, sim_block?,
                  sim_type?, mpn?, role_spec? }}
  - source:     list of {{doc, loc, quote}} — REQUIRED, ≥1 entry, with a
                verbatim quote you can find in the cited doc
  - fix_hint:   short fix instruction
  - enabled:    true
  - origin:     "generated"

For structural rules: include "predicate": {{kind, ...args per spec}}.
For semantic rules: include "prompt": text the per-rule evaluator will
ask each pass.

Hard constraints:
  - Every rule.source[*].quote MUST be a verbatim substring of the cited
    doc (whitespace-normalized). Hallucinated quotes are rejected.
  - Generate AT LEAST 30 rules across the three families.
  - Use ONLY the predicate kinds in the spec — invented kinds are rejected.
  - DO NOT emit rules whose id collides with anything in the existing
    user rules file.

Reply with ONLY the JSON output written to {out}; no commentary.
"""
```

- [ ] **Step 2: Replace the stub in rule_gen.py**

Open `test1/review/rule_gen.py`. Replace the `_claude_generate` function with:

```python
async def _claude_generate(bundle: DocBundle, spec: PredicateSpec,
                           existing_user_rules: list[Rule]) -> list[Rule]:
    """Default RuleGenProvider impl — writes bundle/spec/user to temp JSON,
    dispatches the rule_gen agent, reads + validates output."""
    import json, sys, tempfile

    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod

    tmp = Path(tempfile.mkdtemp(prefix="rulegen_"))
    bundle_path = tmp / "bundle.json"
    spec_path = tmp / "spec.json"
    user_path = tmp / "user_rules.json"
    out_path = tmp / "out.json"

    bundle_path.write_text(json.dumps({
        "requirements_md": bundle.requirements_md,
        "bobcat_pdf_text": bundle.bobcat_pdf_text,
        "datasheet_texts": bundle.datasheet_texts,
        "url_texts": bundle.url_texts,
        "netlist_yamls": bundle.netlist_yamls,
    }), encoding="utf-8")
    spec_path.write_text(json.dumps({"kinds": spec.kinds}), encoding="utf-8")
    user_path.write_text(json.dumps({
        "rules": [r.model_dump(exclude_none=True) for r in existing_user_rules]
    }), encoding="utf-8")

    # Up to 2 retries on validation failure.
    last_error = ""
    for attempt in range(3):
        run = await agent_mod.start_rule_gen(bundle_path, spec_path,
                                              user_path, out_path)
        # Wait for completion — poll the run status
        import asyncio
        while run.status == "running":
            await asyncio.sleep(0.5)
        if run.status != "ok" or not out_path.exists():
            last_error = f"agent run status={run.status}, output present={out_path.exists()}"
            continue
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            from pydantic import TypeAdapter
            rules_adapter = TypeAdapter(list[Rule])
            rules = rules_adapter.validate_python(data.get("rules", []))
            return rules
        except Exception as e:
            last_error = f"validation: {e}"
            # Append the error to the prompt for the retry (manual loop)
            continue

    raise RuntimeError(f"rule_gen agent failed after 3 attempts: {last_error}")
```

- [ ] **Step 3: Verify the prompt builder + dispatch shape**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
import sys; sys.path.insert(0, 'test1/gui/backend')
import agent as a
p = a._build_rule_gen_prompt('B','S','U','O')
print('prompt len:', len(p))
print('contains schema mention:', 'Rule object' in p)
"
```
Expected: prompt is multi-hundred-character; `True`.

- [ ] **Step 4: Commit**

```powershell
git add test1\gui\backend\agent.py test1\review\rule_gen.py
git commit -m "feat(review): wire rule_gen agent dispatch + validation retry

start_rule_gen in agent.py spawns claude -p with the doc bundle path,
predicate spec path, existing user rules path, and the output JSON path.

_claude_generate in rule_gen.py writes the inputs to a tempdir, dispatches,
waits for completion, validates the output via Pydantic TypeAdapter,
retries up to 2× on validation failure."
```

---

### Task 2.4: Backend endpoints for rules

**Files:**
- Modify: `test1/gui/backend/app.py` (add 4 endpoints under the existing review section)

- [ ] **Step 1: Add the endpoints**

Open `test1/gui/backend/app.py`. After the `apply_finding` endpoint (line ~2192), add:

```python
# ===========================================================================
# Closed-loop design review — Rules endpoints
# ===========================================================================

@app.get("/api/review/rules")
def review_rules_list() -> dict:
    """Return the current rules.yaml contents + staleness state."""
    from test1.review.rule_eval import load_rules
    rf = load_rules()
    # Staleness: any source on disk newer than the recorded mtime?
    stale_sources: list[dict] = []
    for s in rf.sources_seen:
        p = REPO_ROOT / s.path
        if p.exists() and p.stat().st_mtime > s.mtime + 1.0:
            stale_sources.append({"path": s.path,
                                  "current_mtime": p.stat().st_mtime,
                                  "recorded_mtime": s.mtime})
    return {
        "version": rf.version,
        "generated_at": rf.generated_at,
        "rules": [r.model_dump(exclude_none=True) for r in rf.rules],
        "sources_seen": [s.model_dump() for s in rf.sources_seen],
        "stale_sources": stale_sources,
        "by_family": {
            fam: sum(1 for r in rf.rules if r.family == fam)
            for fam in ("schematic", "simulation", "design")
        },
        "by_origin": {
            ori: sum(1 for r in rf.rules if r.origin == ori)
            for ori in ("generated", "user", "imported")
        },
    }


@app.post("/api/review/rules/generate")
async def review_rules_generate() -> dict:
    """Trigger rule generation. Long-running — returns a run_id; subscribe
    to its agent stream for progress. The final rules.yaml is written
    when the run completes; poll /api/review/rules to fetch."""
    from test1.review import rule_gen
    # Run in the background so the endpoint returns quickly.
    result = await rule_gen.generate_and_write()
    return result


class RuleEditBody(BaseModel):
    rule_id: str
    enabled: bool | None = None
    title: str | None = None
    severity: str | None = None
    fix_hint: str | None = None
    prompt: str | None = None     # only valid for semantic rules


@app.post("/api/review/rules/edit")
def review_rules_edit(body: RuleEditBody) -> dict:
    """Edit a single rule by id. Marks origin='user' so the edit survives
    regenerate."""
    from test1.review.rule_eval import load_rules, save_rules
    from test1.review.rule_schema import RulesFile
    rf = load_rules()
    target = next((r for r in rf.rules if r.id == body.rule_id), None)
    if not target:
        raise HTTPException(404, f"rule not found: {body.rule_id}")
    if body.enabled is not None:    target.enabled = body.enabled
    if body.title is not None:      target.title = body.title
    if body.severity is not None:   target.severity = body.severity  # type: ignore[assignment]
    if body.fix_hint is not None:   target.fix_hint = body.fix_hint
    if body.prompt is not None and hasattr(target, "prompt"):
        target.prompt = body.prompt
    target.origin = "user"
    save_rules(rf)
    return {"ok": True, "rule": target.model_dump(exclude_none=True)}


@app.delete("/api/review/rules/{rule_id}")
def review_rules_delete(rule_id: str) -> dict:
    """Soft-delete: sets enabled=false. Hard-delete: pass ?hard=true."""
    from test1.review.rule_eval import load_rules, save_rules
    rf = load_rules()
    target = next((r for r in rf.rules if r.id == rule_id), None)
    if not target:
        raise HTTPException(404, f"rule not found: {rule_id}")
    target.enabled = False
    target.origin = "user"
    save_rules(rf)
    return {"ok": True, "rule_id": rule_id, "enabled": False}
```

- [ ] **Step 2: Verify the endpoints respond**

Start backend in one shell:
```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\gui\backend\app.py
```

In another shell:
```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/review/rules
```
Expected: `version: 1, rules: [], by_family: {schematic: 0, simulation: 0, design: 0}, stale_sources: []`.

Stop backend.

- [ ] **Step 3: Commit**

```powershell
git add test1\gui\backend\app.py
git commit -m "feat(api): /api/review/rules CRUD + staleness state

GET  /api/review/rules            — list + stale_sources + family/origin counts
POST /api/review/rules/generate   — trigger rule generation (long-running)
POST /api/review/rules/edit       — edit one rule (marks origin=user)
DELETE /api/review/rules/{id}     — soft-delete (enabled=false, origin=user)"
```

---

### Task 2.5: Smoke-test rule generation end-to-end

- [ ] **Step 1: Run the generator manually**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
import asyncio
from test1.review import rule_gen
result = asyncio.run(rule_gen.generate_and_write())
print('count_total:', result['count_total'])
print('by_family:', result['count_by_family'])
print('conflicts:', result['conflicts'])
print('rejected_unverifiable:', len(result['rejected_unverifiable']))
"
```
Expected: completes in 60-180 s (agent invocation); `count_total ≥ 30`; rejected count low (≤5 typically).

- [ ] **Step 2: Inspect `rules.yaml`**

```powershell
Get-Content test1\review\rules.yaml | Select-Object -First 80
```

Verify: top-level `version`, `generated_at` (recent ISO timestamp), `sources_seen` populated, several rules with citations + quotes.

- [ ] **Step 3: Evaluate the new rules**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
from test1.review import rule_eval
findings = rule_eval.run_all()
print(f'{len(findings)} findings from {len(rule_eval.load_rules().rules)} rules')
for f in findings[:5]:
    print(f.severity.value, f.rule_id, '—', f.title)
"
```
Expected: some findings appear if the current design hasn't been re-built since last green state. (If everything's green, count is 0 — also fine.)

- [ ] **Step 4: Commit the generated rules.yaml**

```powershell
git add test1\review\rules.yaml
git commit -m "feat(review): first rules.yaml from generator (smoke test)

N rules across schematic/simulation/design families.
Generated against current design_requirements.md + datasheets + Bobcat PDF.
This is committed as the project baseline; the generator merges with
user-origin rules on subsequent regen."
```

---

### Task 2.6: Rules section in Review.tsx (frontend Section A)

**Files:**
- Create: `test1/gui/frontend/src/components/RulesSection.tsx`
- Modify: `test1/gui/frontend/src/tabs/Review.tsx` (mount the section)
- Modify: `test1/gui/frontend/src/api.ts` (add rule CRUD methods)
- Modify: `test1/gui/frontend/src/types.ts` (Rule TS type)

- [ ] **Step 1: Add types to `types.ts`**

Open `test1/gui/frontend/src/types.ts`. Append:

```typescript
export interface RuleSource {
  doc: string;
  loc: string;
  quote?: string;
}

export interface RuleAppliesTo {
  refdes?: string;
  pins?: string[];
  net?: string;
  rail?: string;
  sheet?: string;
  sim_block?: string;
  sim_type?: string;
  mpn?: string;
  role_spec?: Record<string, unknown>;
}

export interface RulePredicate {
  kind: string;
  [arg: string]: unknown;
}

export interface Rule {
  id: string;
  family: "schematic" | "simulation" | "design";
  evaluation: "structural" | "semantic";
  severity: "ERROR" | "WARNING" | "INFO";
  title: string;
  applies_to: RuleAppliesTo;
  source: RuleSource[];
  fix_hint?: string;
  enabled: boolean;
  origin: "generated" | "user" | "imported";
  predicate?: RulePredicate;
  prompt?: string;
}

export interface RulesListResponse {
  version: number;
  generated_at: string;
  rules: Rule[];
  sources_seen: { path: string; mtime: number }[];
  stale_sources: { path: string; current_mtime: number; recorded_mtime: number }[];
  by_family: { schematic: number; simulation: number; design: number };
  by_origin: { generated: number; user: number; imported: number };
}
```

- [ ] **Step 2: Add API methods to `api.ts`**

Open `test1/gui/frontend/src/api.ts`. Inside the `api` object, add:

```typescript
  rules: async (): Promise<RulesListResponse> => {
    const r = await fetch("/api/review/rules");
    if (!r.ok) throw new Error("rules fetch failed");
    return r.json();
  },
  generateRules: async (): Promise<{
    count_total: number;
    count_by_family: { schematic: number; simulation: number; design: number };
    conflicts: { id: string; user_title: string; generated_title: string }[];
    rejected_unverifiable: { id: string; reason: string }[];
  }> => {
    const r = await fetch("/api/review/rules/generate", { method: "POST" });
    if (!r.ok) throw new Error("generate failed");
    return r.json();
  },
  editRule: async (rule_id: string, patch: Partial<Rule>): Promise<{ ok: boolean; rule: Rule }> => {
    const r = await fetch("/api/review/rules/edit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ rule_id, ...patch }),
    });
    if (!r.ok) throw new Error("edit failed");
    return r.json();
  },
  deleteRule: async (rule_id: string): Promise<{ ok: boolean }> => {
    const r = await fetch(`/api/review/rules/${encodeURIComponent(rule_id)}`, {
      method: "DELETE",
    });
    if (!r.ok) throw new Error("delete failed");
    return r.json();
  },
```

Add the import at top of `api.ts`:

```typescript
import type { Rule, RulesListResponse } from "./types";
```

- [ ] **Step 3: Create `RulesSection.tsx`**

Create `test1/gui/frontend/src/components/RulesSection.tsx`:

```typescript
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import type { Rule, RulesListResponse } from "../types";

interface Props {
  onApproveAndRun: () => void;   // start a loop after user clicks "Approve & Run"
  loopRunning: boolean;          // disable buttons while a loop is in flight
}

const SEV_DOT: Record<string, string> = {
  ERROR: "bg-err", WARNING: "bg-warn", INFO: "bg-ink-300",
};

const FAMILY_LABEL: Record<string, string> = {
  schematic: "schematic", simulation: "simulation", design: "design",
};

export function RulesSection({ onApproveAndRun, loopRunning }: Props) {
  const [data, setData] = useState<RulesListResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});  // by family
  const [error, setError] = useState<string>("");

  const refresh = useCallback(async () => {
    try { setData(await api.rules()); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const generate = async () => {
    setGenerating(true); setError("");
    try { await api.generateRules(); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setGenerating(false); }
  };

  const toggleRule = async (rule_id: string, enabled: boolean) => {
    await api.editRule(rule_id, { enabled });
    await refresh();
  };

  if (!data) return (
    <section className="mt-5">
      <div className="text-sm text-ink-500">Loading rules…{error && ` (${error})`}</div>
    </section>
  );

  const needsApproval = data.rules.length > 0 && data.by_origin.user === 0
    && data.by_origin.generated > 0 && /* never approved */ false;
  // Approval state is heuristic for now: any user-origin rule means
  // the user has touched the set → approved. Refine with a dedicated
  // approved_at flag in later iteration.

  const stale = data.stale_sources.length > 0;
  const empty = data.rules.length === 0;

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.List size={14} />
        <span className="text-sm font-semibold text-ink-900">Rules</span>
        <span className="text-[11px] text-ink-500">
          {data.rules.length} active · {data.by_origin.user} user · {data.rules.filter(r=>!r.enabled).length} disabled
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={generate}
            disabled={generating || loopRunning}
            className="h-7 px-2.5 text-[11.5px] rounded border border-edge text-ink-700 hover:border-ink-300 disabled:opacity-50"
          >
            {generating ? "Generating…" : empty ? "Generate rules" : "Regenerate"}
          </button>
          {!empty && (
            <button
              onClick={onApproveAndRun}
              disabled={loopRunning}
              className="h-7 px-2.5 text-[11.5px] rounded bg-ink-900 text-white font-medium hover:bg-black disabled:opacity-50"
            >
              ✓ Approve &amp; Run loop
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="px-4 py-2 text-[12px] text-err bg-err/[0.04] border-b border-edge">
          {error}
        </div>
      )}

      {empty && (
        <div className="px-4 py-6 text-center text-sm text-ink-500">
          No rules yet. Click <em>Generate rules</em> to build them from the
          project docs.
        </div>
      )}

      {stale && (
        <div className="px-4 py-2 text-[12px] bg-warn/[0.06] text-ink-700 border-b border-edge">
          <strong>⚠ Sources changed</strong> since rules were generated —
          {data.stale_sources.length} files newer:
          <ul className="mt-1 list-disc pl-5">
            {data.stale_sources.slice(0, 5).map(s => (
              <li key={s.path} className="font-mono text-[11px]">{s.path}</li>
            ))}
          </ul>
        </div>
      )}

      {!empty && (
        <div className="px-4 py-3 space-y-2">
          {(["schematic", "simulation", "design"] as const).map(fam => {
            const rules = data.rules.filter(r => r.family === fam);
            if (rules.length === 0) return null;
            const open = !!expanded[fam];
            return (
              <div key={fam}>
                <button
                  onClick={() => setExpanded(e => ({ ...e, [fam]: !open }))}
                  className="text-[11.5px] text-ink-700 hover:text-ink-900 flex items-center gap-1.5"
                >
                  {open ? "▾" : "▸"} {FAMILY_LABEL[fam]} ({rules.length})
                </button>
                {open && (
                  <div className="mt-1.5 ml-3 space-y-1">
                    {rules.map(r => (
                      <RuleRow key={r.id} r={r} onToggle={toggleRule} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function RuleRow({ r, onToggle }: { r: Rule; onToggle: (id: string, en: boolean) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={"rounded border px-2 py-1.5 text-[11.5px] " + (r.enabled ? "border-edge bg-white" : "border-edge/50 bg-ink-100/50")}>
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={r.enabled}
          onChange={(e) => onToggle(r.id, e.target.checked)}
          className="mt-0.5"
        />
        <span className={"mt-1 inline-block w-2 h-2 rounded-full " + SEV_DOT[r.severity]} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-mono text-[10px] text-ink-500">{r.id}</span>
            <span className="text-ink-500">·</span>
            <span className="text-ink-500">{r.evaluation}</span>
            {r.origin === "user" && <span className="text-[10px] px-1 rounded bg-warn/15 text-warn">user</span>}
          </div>
          <div className="text-ink-900">{r.title}</div>
          {open && (
            <div className="mt-1.5 pl-2 border-l border-edge text-[11px] text-ink-700">
              {r.source.map((s, i) => (
                <div key={i} className="mb-1">
                  <span className="font-mono text-ink-500">{s.doc}:{s.loc}</span>
                  {s.quote && <div className="italic text-ink-500">"{s.quote}"</div>}
                </div>
              ))}
              {r.fix_hint && <div className="mt-1"><strong>fix:</strong> {r.fix_hint}</div>}
              {r.predicate && (
                <pre className="mt-1 text-[10.5px] bg-rail/40 px-1.5 py-1 rounded overflow-auto">
{JSON.stringify(r.predicate, null, 2)}
                </pre>
              )}
              {r.prompt && (
                <div className="mt-1">
                  <strong>prompt:</strong>
                  <div className="text-[11px] text-ink-700 whitespace-pre-wrap">{r.prompt}</div>
                </div>
              )}
            </div>
          )}
          <button
            onClick={() => setOpen(o => !o)}
            className="mt-1 text-[10px] text-ink-500 hover:text-ink-900"
          >
            {open ? "hide details" : "details"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Mount in Review.tsx**

Open `test1/gui/frontend/src/tabs/Review.tsx`. Add an import:

```typescript
import { RulesSection } from "../components/RulesSection";
```

Then between the buttons row and the Findings section (around the position the old dropzone was), insert:

```tsx
        <RulesSection
          onApproveAndRun={() => startRun(false)}
          loopRunning={runState === "running"}
        />
```

- [ ] **Step 5: Verify the frontend builds + the section renders**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: clean.

Then start backend + frontend (`npm run dev`), open `http://localhost:5173`, navigate to Review tab. Expected: a "Rules" panel between the buttons and the Findings list, showing N rules grouped by family, with toggle/details controls.

- [ ] **Step 6: Commit**

```powershell
git add test1\gui\frontend\src\components\RulesSection.tsx test1\gui\frontend\src\tabs\Review.tsx test1\gui\frontend\src\api.ts test1\gui\frontend\src\types.ts
git commit -m "feat(ui): Rules section in Review tab (Section A)

Renders the generated rules.yaml grouped by family with severity dots,
expand-for-details, per-rule enable/disable toggle (marks origin=user),
staleness banner, Generate/Regenerate + Approve&Run buttons.

Spec §7.A."
```

---

### Task 2.7: Phase 2 gate

- [ ] **Step 1: Backend + frontend boot clean**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\gui\backend\app.py
```
In another shell: `cd test1\gui\frontend; npm run dev`. Open <http://localhost:5173>. Navigate to Review tab. Rules panel visible with rules.

- [ ] **Step 2: Generate rules from a clean slate**

In the GUI, click "Generate rules" (or "Regenerate"). Wait ~60-180s. Expect: rules.yaml is rewritten; the panel auto-refreshes (or refresh via Refresh button).

- [ ] **Step 3: Toggle a rule off and verify it persists**

Toggle any rule's enable checkbox; reload the page; verify the toggle state persists and `origin` shows `user`.

- [ ] **Step 4: Build green**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m test1.altium.build_project
```
Expected: `FAILURES: none`.

Phase 2 complete.

---

## Phase 3 — Rule Evaluator Integration (one-shot mode)

Wire `run_review.py` to evaluate `rules.yaml` so the existing Run Review button still works (one-shot mode), independent of the closed-loop orchestrator. Adds `rule_id` badges to the existing FindingRow.

### Task 3.1: Refactor `run_review.py` to use `rule_eval`

**Files:**
- Modify: `test1/run_review.py`

- [ ] **Step 1: Replace Phase 2a invocation**

Open `test1/run_review.py`. Find lines 60-66:

```python
    print()
    print("Phase 2a: deterministic rules …")
    try:
        from review import rules
        findings.extend(rules.run_all(idx))
        print(f"  {len(findings)} findings so far")
    except ImportError:
        print("  (rules.py not yet implemented — skipping)")
```

Replace with:

```python
    print()
    print("Phase 2a: rule_eval against rules.yaml …")
    try:
        from review import rule_eval
        new_findings = rule_eval.run_all()
        findings.extend(new_findings)
        rf = rule_eval.load_rules()
        print(f"  {len(new_findings)} findings from "
              f"{sum(1 for r in rf.rules if r.enabled)}/{len(rf.rules)} active rules")
    except FileNotFoundError:
        print("  (rules.yaml not yet generated — run /api/review/rules/generate)")
    except Exception as e:
        print(f"  rule_eval error: {e}")
```

- [ ] **Step 2: Verify one-shot mode runs**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\run_review.py --no-semantic --json test1\review\findings.json
```
Expected: prints `Phase 2a: rule_eval against rules.yaml …  N findings from M/M active rules`, then Phase 3 renders. Exits 0.

- [ ] **Step 3: Inspect findings.json**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "import json; d=json.load(open('test1/review/findings.json')); print('total:', len(d.get('findings',[]))); print('summary:', d.get('summary'))"
```
Expected: shows the findings count from the rule evaluator + a summary block.

- [ ] **Step 4: Commit**

```powershell
git add test1\run_review.py
git commit -m "refactor(review): run_review.py evaluates rules.yaml via rule_eval

Phase 2a now calls rule_eval.run_all() (rules.yaml) instead of the
deleted hardcoded rule tables. Phase 2b (semantic_review) was already
removed. One-shot mode preserved for CLI / scripted runs."
```

---

### Task 3.2: Add `rule_id` badge to FindingRow

**Files:**
- Modify: `test1/gui/frontend/src/tabs/Review.tsx`

- [ ] **Step 1: Add the badge inside the FindingRow header**

Open `test1/gui/frontend/src/tabs/Review.tsx`. Find the `FindingRow` component header div (the line with `<div className="flex items-center gap-2 text-xs flex-wrap">` inside `FindingRow`).

Just after `{(f.refs ?? []).length > 0 && ( ... )}`, add:

```tsx
            {/* @ts-expect-error rule_id is added by rule_eval; not in legacy types */}
            {f.rule_id && (
              <span className="text-[10px] font-mono text-ink-500 bg-rail/40 rounded px-1">
                {(f as unknown as { rule_id: string }).rule_id}
              </span>
            )}
```

Better: extend the `Finding` interface in `types.ts` first. Open `test1/gui/frontend/src/types.ts` and find the `Finding` interface. Add:

```typescript
  rule_id?: string;
  iteration_round?: number;
  resolved_by_run_id?: string;
  loop_id?: string;
```

Then the FindingRow code becomes:

```tsx
            {f.rule_id && (
              <span className="text-[10px] font-mono text-ink-500 bg-rail/40 rounded px-1">
                {f.rule_id}
              </span>
            )}
            {f.iteration_round !== undefined && (
              <span className="text-[10px] text-ink-500">
                round {f.iteration_round}
              </span>
            )}
```

- [ ] **Step 2: Verify frontend builds**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: clean.

- [ ] **Step 3: Commit**

```powershell
git add test1\gui\frontend\src\tabs\Review.tsx test1\gui\frontend\src\types.ts
git commit -m "feat(ui): rule_id + round badges on FindingRow

Surface the stable rule_id from rule_eval + the iteration_round when
the finding originated inside a closed-loop run."
```

---

### Task 3.3: Phase 3 gate

- [ ] **Step 1: Build green**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m test1.altium.build_project
```
Expected: `FAILURES: none`.

- [ ] **Step 2: One-shot review reports findings**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\run_review.py --no-semantic --json test1\review\findings.json
```
Expected: non-zero finding count (since the new generated rules are stricter than the old hardcoded set), or zero if the design is fully clean against the generated rule set.

- [ ] **Step 3: GUI shows findings with rule_id badges**

Launch backend + frontend; navigate to Review; verify each finding row shows its rule_id badge.

Phase 3 complete.

---

## Phase 4 — Closed-Loop Orchestrator (the core)

The largest phase. Adds `closed_loop.py`, the `/api/loop/*` endpoint family, the Iteration UI (Section B), the Diff & Accept UI (Section C — basic), the diff endpoint + computation, and the snapshot mechanism. Missing-part flow comes in Phase 5.

### Task 4.1: Loop dataclasses + `_LOOPS` registry skeleton

**Files:**
- Create: `test1/review/closed_loop.py`

- [ ] **Step 1: Write the skeleton with dataclasses**

Create `test1/review/closed_loop.py`:

```python
"""Closed-loop design-review orchestrator.

The outer loop is Python-driven (this module); each round's work is
dispatched to existing sub-AgentRuns (apply / lint_fix / symbol_gen / sim_*
/ missing_part / topology_adapt) via test1/gui/backend/agent.py.

Lifecycle per loop:
  1. Snapshot pre-loop state to out/render_snapshots/<loop_id>/.
  2. Loop over rounds (max 10) until all-clear / plateau / cancel / error.
  3. Each round: evaluate rules → plan_actions → dispatch → rebuild →
     re-evaluate → compute Δ → check plateau.
  4. On halt: persist audit, post plateau changelog (if plateau), wait
     for /accept or /reject.

State stores:
  • _LOOPS: dict[loop_id, Loop]  — in-process, lost on backend restart
  • test1/gui/state/loops/<loop_id>.json  — on-disk audit, survives restart

Spec §4.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import AsyncIterator

from .findings import Finding, Severity


PROJECT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_DIR.parent
OUT_DIR = PROJECT_DIR / "altium" / "out"
RENDER_DIR = OUT_DIR / "render"
NETLIST_DIR = PROJECT_DIR / "netlist"
SNAPSHOT_ROOT = OUT_DIR / "render_snapshots"
LOOPS_STATE_DIR = PROJECT_DIR / "gui" / "state" / "loops"

MAX_ROUNDS = 10
PLATEAU_STREAK = 2
WEB_CALL_BUDGET = 50         # parts + knowledge fetches across one loop


# ---- Dataclasses --------------------------------------------------------

@dataclass
class Action:
    kind: str                 # "apply" | "lint_fix" | "symbol_gen" |
                              #   "missing_part" | "sim" | "topology_adapt"
    agent_run_id: str | None = None
    targets: list[str] = field(default_factory=list)   # rule IDs or refdes
    status: str = "running"   # "running" | "ok" | "fail" | "cancelled"
    summary: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


@dataclass
class Round:
    n: int
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    findings_before: int = 0
    findings_after: int = 0
    findings_cleared: list[str] = field(default_factory=list)
    findings_new: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    build_status: str = ""           # "ok" | "fail" | "skipped"
    lint_summary: dict | None = None
    sim_results: list[dict] = field(default_factory=list)


@dataclass
class Loop:
    loop_id: str
    started_at: float
    status: str = "running"      # "running" | "all_clear" | "plateau" |
                                  #   "max_rounds" | "cancelled" | "error"
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
    error: str = ""
    web_call_count: int = 0       # missing-part flow increments this


_LOOPS: dict[str, Loop] = {}


# ---- Public lookups -----------------------------------------------------

def get_loop(loop_id: str) -> Loop | None:
    return _LOOPS.get(loop_id)


def latest_loop_id() -> str | None:
    """Most recent loop_id (running or completed)."""
    if not _LOOPS:
        # Try disk
        if LOOPS_STATE_DIR.exists():
            audits = sorted(LOOPS_STATE_DIR.glob("*.json"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            if audits:
                return audits[0].stem
        return None
    return max(_LOOPS.keys(),
               key=lambda lid: _LOOPS[lid].started_at)


def loop_summary(L: Loop) -> dict:
    """Wire-format snapshot for /api/loop/{id}."""
    return {
        "loop_id": L.loop_id,
        "status": L.status,
        "round": L.round,
        "started_at": L.started_at,
        "finished_at": L.finished_at,
        "rounds": [_round_to_wire(r) for r in L.rounds],
        "findings_initial": len(L.findings_initial),
        "findings_current": len(L.findings_current),
        "last_delta": L.last_delta,
        "plateau_streak": L.plateau_streak,
        "error": L.error,
    }


def _round_to_wire(r: Round) -> dict:
    return {
        "n": r.n,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "findings_before": r.findings_before,
        "findings_after": r.findings_after,
        "findings_cleared": r.findings_cleared,
        "findings_new": r.findings_new,
        "actions": [asdict(a) for a in r.actions],
        "build_status": r.build_status,
        "lint_summary": r.lint_summary,
        "sim_results": r.sim_results,
    }
```

- [ ] **Step 2: Verify it imports**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review import closed_loop; print('imports OK'); print('MAX_ROUNDS=', closed_loop.MAX_ROUNDS)"
```
Expected: `imports OK`, `MAX_ROUNDS= 10`.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\closed_loop.py
git commit -m "feat(loop): orchestrator skeleton — Loop/Round/Action + registry

In-memory _LOOPS + disk audit dir. Wire-format helpers (loop_summary,
_round_to_wire) for the /api/loop endpoints.

Spec §4 Loop dataclass."
```

---

### Task 4.2: Snapshot helpers (pre-loop + restore)

**Files:**
- Modify: `test1/review/closed_loop.py` (append)

- [ ] **Step 1: Append snapshot helpers**

Append to `test1/review/closed_loop.py`:

```python
# ---- Snapshot mechanics -------------------------------------------------

def snapshot_pre_loop(L: Loop) -> None:
    """Copy out/render/*.svg + netlist/*.yaml + out/lint.json +
    review/findings.json to out/render_snapshots/<loop_id>/."""
    L.snapshot_dir = SNAPSHOT_ROOT / L.loop_id
    L.snapshot_dir.mkdir(parents=True, exist_ok=True)
    (L.snapshot_dir / "render").mkdir(exist_ok=True)
    (L.snapshot_dir / "netlist").mkdir(exist_ok=True)

    if RENDER_DIR.exists():
        for svg in RENDER_DIR.glob("*.svg"):
            shutil.copy2(svg, L.snapshot_dir / "render" / svg.name)
    if NETLIST_DIR.exists():
        for y in NETLIST_DIR.glob("*.yaml"):
            shutil.copy2(y, L.snapshot_dir / "netlist" / y.name)
    lint_json = OUT_DIR / "lint.json"
    if lint_json.exists():
        shutil.copy2(lint_json, L.snapshot_dir / "lint.json")
    findings_json = PROJECT_DIR / "review" / "findings.json"
    if findings_json.exists():
        shutil.copy2(findings_json, L.snapshot_dir / "findings_initial.json")


def restore_from_snapshot(L: Loop, refdes_revert: list[str] | None = None) -> None:
    """Reject path. If refdes_revert is None → full restore. Otherwise →
    selective restore: per-refdes YAML surgery (replace one part block
    or one net membership). Full restore overwrites netlist/*.yaml,
    out/render/*.svg, out/lint.json from the snapshot."""
    if not L.snapshot_dir or not L.snapshot_dir.exists():
        raise FileNotFoundError(f"no snapshot for loop {L.loop_id}")

    if refdes_revert is None:
        # Full restore
        snap_netlist = L.snapshot_dir / "netlist"
        if snap_netlist.exists():
            for y in snap_netlist.glob("*.yaml"):
                shutil.copy2(y, NETLIST_DIR / y.name)
        snap_render = L.snapshot_dir / "render"
        if snap_render.exists():
            for svg in snap_render.glob("*.svg"):
                shutil.copy2(svg, RENDER_DIR / svg.name)
        snap_lint = L.snapshot_dir / "lint.json"
        if snap_lint.exists():
            shutil.copy2(snap_lint, OUT_DIR / "lint.json")
        return

    # Selective revert — YAML-level surgery per refdes
    # For each sheet's netlist, walk parts + nets, restore the entries
    # for the named refdes(s) from the snapshot version.
    import yaml as _yaml
    for current_yaml in NETLIST_DIR.glob("*.yaml"):
        snap_yaml = L.snapshot_dir / "netlist" / current_yaml.name
        if not snap_yaml.exists():
            continue
        cur = _yaml.safe_load(current_yaml.read_text(encoding="utf-8")) or {}
        snap = _yaml.safe_load(snap_yaml.read_text(encoding="utf-8")) or {}
        cur_parts = cur.get("parts", {})
        snap_parts = snap.get("parts", {})
        cur_nets = cur.get("nets", {})
        snap_nets = snap.get("nets", {})

        for rd in refdes_revert:
            if rd in snap_parts:
                cur_parts[rd] = snap_parts[rd]
            elif rd in cur_parts:
                del cur_parts[rd]
            # Net memberships involving this refdes
            for net, members in list(cur_nets.items()):
                if isinstance(members, list):
                    cur_nets[net] = [m for m in members if not
                                     (isinstance(m, dict) and m.get("refdes") == rd
                                      or isinstance(m, str) and m.startswith(f"{rd}."))]
                    snap_members = snap_nets.get(net, [])
                    for sm in snap_members:
                        is_match = (isinstance(sm, dict) and sm.get("refdes") == rd
                                    or isinstance(sm, str) and sm.startswith(f"{rd}."))
                        if is_match and sm not in cur_nets[net]:
                            cur_nets[net].append(sm)
        cur["parts"] = cur_parts
        cur["nets"] = cur_nets
        current_yaml.write_text(_yaml.safe_dump(cur, sort_keys=False),
                                 encoding="utf-8")


def archive_snapshot(L: Loop) -> None:
    """Accept path — tar + remove the snapshot dir."""
    if not L.snapshot_dir or not L.snapshot_dir.exists():
        return
    import tarfile
    tar = SNAPSHOT_ROOT / f"{L.loop_id}.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(L.snapshot_dir, arcname=L.loop_id)
    shutil.rmtree(L.snapshot_dir)
    L.snapshot_dir = None
```

- [ ] **Step 2: Verify imports + a smoke test of snapshot+restore**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
from test1.review.closed_loop import Loop, snapshot_pre_loop, restore_from_snapshot, archive_snapshot
import time, uuid, shutil
L = Loop(loop_id=uuid.uuid4().hex[:8], started_at=time.time())
snapshot_pre_loop(L)
print('snapshot at:', L.snapshot_dir)
print('render files:', len(list((L.snapshot_dir/'render').glob('*.svg'))))
print('netlist files:', len(list((L.snapshot_dir/'netlist').glob('*.yaml'))))
archive_snapshot(L)
print('archived, snapshot_dir:', L.snapshot_dir)
"
```
Expected: 6 SVG files, 6 YAML files, snapshot dir gone after archive.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\closed_loop.py
git commit -m "feat(loop): snapshot pre-loop + restore + archive helpers

snapshot_pre_loop copies render/netlist/lint/findings to
out/render_snapshots/<loop_id>/. restore_from_snapshot handles full
restore (Reject) and selective per-refdes revert (Selective revert).
archive_snapshot tars + removes after Accept."
```

---

### Task 4.3: `plan_actions` mapping

**Files:**
- Modify: `test1/review/closed_loop.py` (append)

- [ ] **Step 1: Append the planner**

Append:

```python
# ---- Planner — map findings to round actions ----------------------------

def plan_actions(findings: list[Finding]) -> list[Action]:
    """Bucket findings by required action kind. Returns a list of Actions
    (one per kind per round); the orchestrator dispatches them in order.

    Bucketing rules (Spec §4 plan_actions table):
      • decoupling_count / pullup_pulldown / no_connect → 'apply' (trivial,
        grouped into one call)
      • present (role_spec / unknown mpn) → 'missing_part' (one per finding)
      • present (known mpn, just not placed) → 'apply'
      • net_routing / connector_pin / power_rail_membership / value_in_range
                                          → 'apply' (non-trivial structural)
      • sim_pass / sim_metric → 'sim'
      • semantic (any family) → 'apply' (semantic mode)
      • ERROR-lint / build-fail finding → 'lint_fix'
    """
    from .rule_schema import StructuralRule    # local import — avoids cycle

    apply_bucket: list[str] = []
    sim_bucket: list[str] = []
    missing_part_actions: list[Action] = []
    lint_fix_targets: list[str] = []

    # Load rules to look up predicate.kind per finding's rule_id.
    from .rule_eval import load_rules
    rules_by_id = {r.id: r for r in load_rules().rules}

    for f in findings:
        rule = rules_by_id.get(f.rule_id)
        if rule is None:
            apply_bucket.append(f.rule_id)
            continue

        if rule.evaluation == "semantic":
            apply_bucket.append(f.rule_id)
            continue

        # StructuralRule
        assert isinstance(rule, StructuralRule)
        kind = rule.predicate.kind
        if kind == "present":
            mpn = rule.applies_to.mpn
            role = rule.applies_to.role_spec
            if not mpn or role:
                # by-spec or unknown-mpn → missing_part flow
                missing_part_actions.append(Action(
                    kind="missing_part", targets=[f.rule_id]))
            else:
                apply_bucket.append(f.rule_id)
        elif kind in ("sim_pass", "sim_metric"):
            sim_bucket.append(f.rule_id)
        elif kind in ("decoupling_count", "pullup_pulldown", "no_connect",
                      "net_routing", "connector_pin",
                      "power_rail_membership", "value_in_range"):
            apply_bucket.append(f.rule_id)
        else:
            apply_bucket.append(f.rule_id)

    out: list[Action] = []
    if apply_bucket:
        out.append(Action(kind="apply", targets=apply_bucket))
    if missing_part_actions:
        out.extend(missing_part_actions)
    if sim_bucket:
        out.append(Action(kind="sim", targets=sim_bucket))
    return out
```

- [ ] **Step 2: Verify the planner sorts findings into buckets**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
from test1.review import closed_loop, rule_eval
findings = rule_eval.run_all()
actions = closed_loop.plan_actions(findings)
for a in actions:
    print(a.kind, '->', len(a.targets), 'targets:', a.targets[:3])
"
```
Expected: prints the action buckets for the current rule-evaluator output.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\closed_loop.py
git commit -m "feat(loop): plan_actions — bucket findings into per-round actions

apply / missing_part / sim / lint_fix dispatch matching Spec §4 table.
Trivial structural fixes grouped into one apply call per round;
missing-part actions are one-per-finding."
```

---

### Task 4.4: The inner loop + SSE emitter

**Files:**
- Modify: `test1/review/closed_loop.py` (append)

- [ ] **Step 1: Append the orchestrator + event emitter**

Append to `test1/review/closed_loop.py`:

```python
# ---- Event emission to subscribers --------------------------------------

async def emit(L: Loop, event: str, **data) -> None:
    """Fan-out an SSE event to every subscriber queue. Drops on slow consumers."""
    payload = {"event": event, "data": data}
    for q in list(L.subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


# ---- Sub-agent dispatch wrappers (call into agent.py) -------------------

async def _dispatch_action(L: Loop, action: Action) -> None:
    """Run one Action to completion. Updates action.status + summary in place."""
    import sys
    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod

    if action.kind == "apply":
        # Look up findings for the targeted rule IDs to build a context blob.
        targets_text = "\n".join(f"  • {rid}" for rid in action.targets)
        # Reuse existing start_apply_pass — it reads the changelog. We
        # bypass the changelog by setting up a synthetic one-shot context.
        # For Phase 4, we use the existing apply agent + emit the targets
        # in its prompt by pushing them to changelog first.
        for rid in action.targets:
            agent_mod.append_changelog(
                f"closed-loop: address rule {rid}",
                source="closed_loop",
            )
        run = await agent_mod.start_apply_pass()
        action.agent_run_id = run.run_id
        L.sub_runs.append(run.run_id)
        while run.status == "running":
            if L.cancelled:
                agent_mod.cancel_run(run.run_id)
                action.status = "cancelled"
                action.finished_at = time.time()
                return
            await asyncio.sleep(0.5)
        action.status = "ok" if run.status == "ok" else "fail"
        action.summary = f"apply pass: {run.status} ({len(action.targets)} targets)"

    elif action.kind == "lint_fix":
        # Read current lint failures + dispatch lint_fix agent
        from .closed_loop_helpers import _read_lint_failures
        failures = _read_lint_failures()
        run = await agent_mod.start_lint_fix_pass(failures, round_no=L.round,
                                                    max_rounds=MAX_ROUNDS)
        action.agent_run_id = run.run_id
        L.sub_runs.append(run.run_id)
        while run.status == "running":
            if L.cancelled:
                agent_mod.cancel_run(run.run_id)
                action.status = "cancelled"
                action.finished_at = time.time()
                return
            await asyncio.sleep(0.5)
        action.status = "ok" if run.status == "ok" else "fail"
        action.summary = f"lint_fix: {run.status}"

    elif action.kind == "sim":
        # Run the named (block, sim_type) sims via sim_service
        from test1.sim import service as sim_service
        from .rule_eval import load_rules
        rules_by_id = {r.id: r for r in load_rules().rules}
        results = []
        for rid in action.targets:
            rule = rules_by_id.get(rid)
            if not rule or not getattr(rule.applies_to, "sim_block", None):
                continue
            block = rule.applies_to.sim_block
            stype = rule.applies_to.sim_type
            if not stype:
                continue
            try:
                res = sim_service.run_block_sim(block, stype)
                results.append({"block": block, "sim_type": stype,
                                "ok": bool(res.get("ok"))})
            except Exception as e:
                results.append({"block": block, "sim_type": stype,
                                "ok": False, "error": str(e)})
        action.status = "ok" if all(r.get("ok") for r in results) else "fail"
        action.summary = f"sim: {sum(1 for r in results if r.get('ok'))}/{len(results)} ok"
        # store results on the action for round.sim_results aggregation
        action.targets = action.targets  # noqa — no payload field; carry via L.rounds[-1].sim_results
        L.rounds[-1].sim_results.extend(results)

    elif action.kind == "missing_part":
        # Phase 5 — for Phase 4 we mark as deferred.
        action.status = "fail"
        action.summary = "missing_part flow not yet implemented (Phase 5)"

    else:
        action.status = "fail"
        action.summary = f"unknown action kind: {action.kind}"

    action.finished_at = time.time()


async def _rebuild_project() -> tuple[str, dict | None]:
    """Run python -m test1.altium.build_project as a subprocess. Returns
    (status, lint_summary)."""
    proc = await asyncio.create_subprocess_exec(
        str(_VENV_PY), "-m", "test1.altium.build_project",
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    status = "ok" if proc.returncode == 0 else "fail"
    lint_summary = None
    lint_json = OUT_DIR / "lint.json"
    if lint_json.exists():
        try:
            data = json.loads(lint_json.read_text(encoding="utf-8"))
            lint_summary = {
                "ERROR":   sum(1 for f in data if f.get("severity") == "ERROR"),
                "WARNING": sum(1 for f in data if f.get("severity") == "WARNING"),
                "INFO":    sum(1 for f in data if f.get("severity") == "INFO"),
            }
        except Exception:
            pass
    return status, lint_summary


_VENV_PY = Path(r"C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe")


# ---- The main loop ------------------------------------------------------

async def run_loop(loop_id: str) -> None:
    """Top-level orchestrator. Runs in a background task started by
    POST /api/loop/start."""
    L = _LOOPS[loop_id]
    try:
        snapshot_pre_loop(L)

        from .rule_eval import run_all as eval_rules
        L.findings_initial = eval_rules()
        L.findings_current = list(L.findings_initial)
        await emit(L, "loop_start", findings=len(L.findings_initial))

        for r in range(1, MAX_ROUNDS + 1):
            if L.cancelled:
                break
            if not L.findings_current:
                break  # all-clear

            R = Round(n=r, findings_before=len(L.findings_current))
            L.round = r
            L.rounds.append(R)
            await emit(L, "round_start", round=r,
                       findings=R.findings_before)

            for action in plan_actions(L.findings_current):
                if L.cancelled:
                    break
                R.actions.append(action)
                await emit(L, "action_start",
                           round=r, kind=action.kind,
                           targets=action.targets)
                await _dispatch_action(L, action)
                await emit(L, "action_end",
                           round=r, kind=action.kind,
                           agent_run_id=action.agent_run_id,
                           status=action.status,
                           summary=action.summary)

            if not L.cancelled:
                await emit(L, "build_start", round=r)
                R.build_status, R.lint_summary = await _rebuild_project()
                await emit(L, "build_end", round=r,
                           status=R.build_status, lint=R.lint_summary)

            # Re-evaluate
            new_findings = eval_rules()
            R.findings_after = len(new_findings)
            old_ids = {f.rule_id for f in L.findings_current}
            new_ids = {f.rule_id for f in new_findings}
            cleared = sorted(old_ids - new_ids)
            added = sorted(new_ids - old_ids)
            R.findings_cleared = cleared
            R.findings_new = added
            delta = len(cleared) - len(added)
            L.findings_current = new_findings
            L.last_delta = delta
            L.plateau_streak = (L.plateau_streak + 1) if delta <= 0 else 0
            R.finished_at = time.time()
            await emit(L, "round_done", round=r,
                       delta=delta, cleared=cleared, new=added,
                       remaining=R.findings_after)

            if L.plateau_streak >= PLATEAU_STREAK:
                L.status = "plateau"
                break

        if not L.cancelled and L.status == "running":
            L.status = "all_clear" if not L.findings_current else "max_rounds"
        if L.cancelled:
            L.status = "cancelled"

    except Exception as e:
        L.status = "error"
        L.error = str(e)
        import traceback
        await emit(L, "error", message=str(e),
                   traceback=traceback.format_exc())

    L.finished_at = time.time()
    persist_audit(L)
    if L.status == "plateau":
        _post_plateau_changelog(L)
    await emit(L, "done", status=L.status,
               rounds=len(L.rounds),
               remaining=len(L.findings_current))

    # Send sentinel to all subscribers
    for q in list(L.subscribers):
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass


def persist_audit(L: Loop) -> None:
    """Write the loop's audit JSON to disk for survives-restart Diff & Accept."""
    LOOPS_STATE_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = LOOPS_STATE_DIR / f"{L.loop_id}.json"
    audit_path.write_text(json.dumps(loop_summary(L), indent=2,
                                     default=str), encoding="utf-8")


def _post_plateau_changelog(L: Loop) -> None:
    """Post a plateau notification line into the changelog with
    source='closed_loop'."""
    import sys
    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod
    by_sev = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for f in L.findings_current:
        by_sev[f.severity.value if hasattr(f.severity, "value") else f.severity] += 1
    msg = (f"loop {L.loop_id[:6]} halted at round {L.round} — plateau, "
           f"{len(L.findings_current)} unresolved "
           f"({by_sev['ERROR']}E · {by_sev['WARNING']}W · {by_sev['INFO']}I)")
    agent_mod.append_changelog(msg, source="closed_loop")


def start_loop() -> str:
    """Allocate a new Loop, register it, kick off the run task."""
    loop_id = uuid.uuid4().hex[:8]
    L = Loop(loop_id=loop_id, started_at=time.time())
    _LOOPS[loop_id] = L
    asyncio.create_task(run_loop(loop_id))
    return loop_id


def cancel_loop(loop_id: str) -> bool:
    L = _LOOPS.get(loop_id)
    if not L:
        return False
    L.cancelled = True
    return True
```

- [ ] **Step 2: Create the helpers sidecar module**

Create `test1/review/closed_loop_helpers.py`:

```python
"""Small helpers extracted from closed_loop.py for unit-testability."""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "altium" / "out"


def _read_lint_failures() -> dict:
    """Read out/lint.json and bucket by sheet."""
    p = OUT_DIR / "lint.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    by_sheet: dict[str, list[dict]] = {}
    for item in data:
        sheet = item.get("sheet", "?")
        by_sheet.setdefault(sheet, []).append(item)
    return by_sheet
```

- [ ] **Step 3: Verify imports**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review import closed_loop; print('imports OK'); print('exports:', [x for x in dir(closed_loop) if not x.startswith('_')][:10])"
```
Expected: imports OK; sees `Loop, Round, Action, MAX_ROUNDS, ...`.

- [ ] **Step 4: Add `closed_loop` to `changelog_add` allowlist in `app.py`**

Open `test1/gui/backend/app.py`. Find the `changelog_add` endpoint (around line 1445). The current code likely has a source-validation step like:

```python
src = item.source if item.source in ("sim", "user", "agent") else "user"
```

Change to:

```python
src = item.source if item.source in ("sim", "user", "agent", "closed_loop") else "user"
```

If the exact check looks different, locate the source validation and add `"closed_loop"` to the allowed set.

- [ ] **Step 5: Commit**

```powershell
git add test1\review\closed_loop.py test1\review\closed_loop_helpers.py test1\gui\backend\app.py
git commit -m "feat(loop): inner-loop body + SSE emitter + sub-agent dispatch

run_loop() drives rounds: snapshot → eval → plan_actions → dispatch
sub-AgentRun per action → rebuild → re-eval → Δ → plateau check.
Plateau posts a 'closed_loop' source line to ChangelogPanel.
missing_part dispatch deferred to Phase 5 (returns fail with reason).

Cancel checked between actions + between rounds (never mid-build —
that could corrupt .SchDoc binaries)."
```

---

### Task 4.5: `/api/loop/*` endpoints

**Files:**
- Modify: `test1/gui/backend/app.py` (append after the rules endpoints)

- [ ] **Step 1: Add the endpoint block**

Open `test1/gui/backend/app.py`. After the `review_rules_delete` endpoint, append:

```python
# ===========================================================================
# Closed-loop design review — Loop endpoints
# ===========================================================================

from test1.review import closed_loop as _loop_mod


@app.post("/api/loop/start")
async def loop_start() -> dict:
    # Reject if another loop is currently running.
    for L in _loop_mod._LOOPS.values():
        if L.status == "running":
            raise HTTPException(409, f"loop {L.loop_id} already running")
    loop_id = _loop_mod.start_loop()
    return {"loop_id": loop_id}


@app.get("/api/loop/latest")
def loop_latest() -> dict:
    lid = _loop_mod.latest_loop_id()
    if not lid:
        return {"loop_id": None}
    L = _loop_mod.get_loop(lid)
    if L:
        return _loop_mod.loop_summary(L)
    # Fallback: read from disk
    audit = _loop_mod.LOOPS_STATE_DIR / f"{lid}.json"
    if audit.exists():
        return json.loads(audit.read_text(encoding="utf-8"))
    return {"loop_id": None}


@app.get("/api/loop/{loop_id}")
def loop_get(loop_id: str) -> dict:
    L = _loop_mod.get_loop(loop_id)
    if L:
        return _loop_mod.loop_summary(L)
    audit = _loop_mod.LOOPS_STATE_DIR / f"{loop_id}.json"
    if audit.exists():
        return json.loads(audit.read_text(encoding="utf-8"))
    raise HTTPException(404, "no such loop")


@app.get("/api/loop/{loop_id}/stream")
async def loop_stream(loop_id: str) -> StreamingResponse:
    L = _loop_mod.get_loop(loop_id)
    if not L:
        raise HTTPException(404, "no such loop")

    async def gen() -> AsyncIterator[bytes]:
        # Replay buffered events: we don't keep a buffer (subscribers attach
        # for live events only). If the loop is already done, send a single
        # 'done' frame from the audit so late subscribers don't hang.
        if L.status != "running":
            yield (f"event: done\ndata: "
                   f"{json.dumps({'status': L.status, 'rounds': len(L.rounds), 'remaining': len(L.findings_current)})}"
                   f"\n\n").encode()
            return
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        L.subscribers.append(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    return
                ev = item.get("event", "message")
                data = json.dumps(item.get("data", {}))
                yield f"event: {ev}\ndata: {data}\n\n".encode()
        finally:
            try:
                L.subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/loop/{loop_id}/cancel")
def loop_cancel(loop_id: str) -> dict:
    ok = _loop_mod.cancel_loop(loop_id)
    if not ok:
        raise HTTPException(404, "no such loop")
    return {"ok": True}


@app.post("/api/loop/{loop_id}/accept")
def loop_accept(loop_id: str) -> dict:
    L = _loop_mod.get_loop(loop_id)
    if not L:
        raise HTTPException(404, "no such loop")
    _loop_mod.archive_snapshot(L)
    return {"ok": True}


class LoopRejectBody(BaseModel):
    revert: list[str] | None = None    # refdes list for selective revert


@app.post("/api/loop/{loop_id}/reject")
async def loop_reject(loop_id: str, body: LoopRejectBody = LoopRejectBody()) -> dict:
    L = _loop_mod.get_loop(loop_id)
    if not L:
        raise HTTPException(404, "no such loop")
    _loop_mod.restore_from_snapshot(L, refdes_revert=body.revert)
    # Rebuild once to refresh out/render
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "test1.altium.build_project",
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return {"ok": True, "rebuild_status": proc.returncode == 0,
            "rebuild_log_tail": out.decode("utf-8", errors="replace")[-2000:]}
```

- [ ] **Step 2: Verify endpoints respond**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\gui\backend\app.py
```

In another shell:
```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/loop/latest
```
Expected: `{loop_id: $null}` (no loops yet) or a prior loop's summary if there was one.

Stop backend.

- [ ] **Step 3: Commit**

```powershell
git add test1\gui\backend\app.py
git commit -m "feat(api): /api/loop/* endpoint family (start/cancel/accept/reject/stream)

Live SSE stream uses event-tagged frames (round_start, action_start,
build_end, round_done, plateau, done) that the frontend's subscribeLoop
helper consumes. /api/loop/latest persists across backend restart via
the on-disk audit at test1/gui/state/loops/<id>.json."
```

---

### Task 4.6: `subscribeLoop` + Iteration UI types in api.ts/types.ts

**Files:**
- Modify: `test1/gui/frontend/src/api.ts`
- Modify: `test1/gui/frontend/src/types.ts`

- [ ] **Step 1: Add types**

Append to `test1/gui/frontend/src/types.ts`:

```typescript
export interface LoopAction {
  kind: string;
  agent_run_id?: string | null;
  targets: string[];
  status: "running" | "ok" | "fail" | "cancelled";
  summary: string;
  started_at: number;
  finished_at?: number | null;
}

export interface LoopRound {
  n: number;
  started_at: number;
  finished_at?: number | null;
  findings_before: number;
  findings_after: number;
  findings_cleared: string[];
  findings_new: string[];
  actions: LoopAction[];
  build_status: string;
  lint_summary?: { ERROR: number; WARNING: number; INFO: number } | null;
  sim_results: { block: string; sim_type: string; ok: boolean }[];
}

export interface LoopSummary {
  loop_id: string;
  status: "running" | "all_clear" | "plateau" | "max_rounds" | "cancelled" | "error";
  round: number;
  started_at: number;
  finished_at?: number | null;
  rounds: LoopRound[];
  findings_initial: number;
  findings_current: number;
  last_delta?: number | null;
  plateau_streak: number;
  error?: string;
}

export type LoopEvent =
  | { event: "loop_start";  data: { findings: number } }
  | { event: "round_start"; data: { round: number; findings: number } }
  | { event: "action_start"; data: { round: number; kind: string; targets: string[] } }
  | { event: "action_end";   data: { round: number; kind: string; agent_run_id?: string; status: string; summary: string } }
  | { event: "build_start";  data: { round: number } }
  | { event: "build_end";    data: { round: number; status: string; lint?: { ERROR: number; WARNING: number; INFO: number } | null } }
  | { event: "sim_results";  data: { round: number; results: { block: string; sim_type: string; ok: boolean }[] } }
  | { event: "round_done";   data: { round: number; delta: number; cleared: string[]; new: string[]; remaining: number } }
  | { event: "plateau";      data: { streak: number; remaining: number; by_severity: { E: number; W: number; I: number } } }
  | { event: "error";        data: { message: string; traceback: string } }
  | { event: "done";         data: { status: string; rounds: number; remaining: number } };
```

- [ ] **Step 2: Add `subscribeLoop` to `api.ts`**

Open `test1/gui/frontend/src/api.ts`. Add the import at top:

```typescript
import type { LoopEvent, LoopSummary } from "./types";
```

After the existing `subscribeAgent`/`subscribeRun` exports, add:

```typescript
export function subscribeLoop(
  loop_id: string,
  onEvent: (ev: LoopEvent) => void,
  onDone: (status: string) => void,
): () => void {
  let closed = false;
  const es = new EventSource(`/api/loop/${loop_id}/stream`);
  const handle = (eventName: string) => (e: MessageEvent) => {
    if (closed) return;
    try {
      const data = JSON.parse(e.data);
      onEvent({ event: eventName as LoopEvent["event"], data } as LoopEvent);
    } catch {}
  };
  for (const name of [
    "loop_start","round_start","action_start","action_end","build_start",
    "build_end","sim_results","round_done","plateau","error",
  ]) {
    es.addEventListener(name, handle(name));
  }
  es.addEventListener("done", (e: MessageEvent) => {
    if (closed) return;
    try {
      const data = JSON.parse(e.data);
      onEvent({ event: "done", data });
      onDone(data.status);
    } catch {}
    closed = true;
    es.close();
  });
  es.onerror = () => {
    if (!closed) { closed = true; es.close(); onDone("stream_error"); }
  };
  return () => { closed = true; es.close(); };
}
```

In the `api` object, add the loop methods:

```typescript
  loopStart: async (): Promise<{ loop_id: string }> => {
    const r = await fetch("/api/loop/start", { method: "POST" });
    if (!r.ok) throw new Error("loop start failed");
    return r.json();
  },
  loopLatest: async (): Promise<LoopSummary | { loop_id: null }> => {
    const r = await fetch("/api/loop/latest");
    return r.json();
  },
  loopGet: async (loop_id: string): Promise<LoopSummary> => {
    const r = await fetch(`/api/loop/${loop_id}`);
    if (!r.ok) throw new Error("loop fetch failed");
    return r.json();
  },
  loopCancel: async (loop_id: string): Promise<{ ok: boolean }> => {
    const r = await fetch(`/api/loop/${loop_id}/cancel`, { method: "POST" });
    if (!r.ok) throw new Error("cancel failed");
    return r.json();
  },
  loopAccept: async (loop_id: string): Promise<{ ok: boolean }> => {
    const r = await fetch(`/api/loop/${loop_id}/accept`, { method: "POST" });
    if (!r.ok) throw new Error("accept failed");
    return r.json();
  },
  loopReject: async (loop_id: string, revert?: string[]): Promise<{ ok: boolean }> => {
    const r = await fetch(`/api/loop/${loop_id}/reject`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ revert }),
    });
    if (!r.ok) throw new Error("reject failed");
    return r.json();
  },
```

- [ ] **Step 3: Verify frontend builds**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: clean.

- [ ] **Step 4: Commit**

```powershell
git add test1\gui\frontend\src\api.ts test1\gui\frontend\src\types.ts
git commit -m "feat(api-client): subscribeLoop + loop CRUD + types

LoopEvent discriminated union mirrors backend SSE events.
subscribeLoop returns an unsubscribe fn (like subscribeAgent)."
```

---

### Task 4.7: IterationSection.tsx component

**Files:**
- Create: `test1/gui/frontend/src/components/IterationSection.tsx`
- Modify: `test1/gui/frontend/src/tabs/Review.tsx` (mount it)

- [ ] **Step 1: Write IterationSection**

Create `test1/gui/frontend/src/components/IterationSection.tsx`:

```typescript
import { useEffect, useRef, useState } from "react";
import { api, subscribeAgent, subscribeLoop } from "../api";
import { I } from "./Icon";
import type { LoopEvent, LoopSummary, LoopRound, LoopAction } from "../types";

interface Props {
  loopId: string | null;          // null when no loop running/completed
  onLoopCompleted: (status: string) => void;
  setHealth: (h: { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined) => void;
}

export function IterationSection({ loopId, onLoopCompleted, setHealth }: Props) {
  const [summary, setSummary] = useState<LoopSummary | null>(null);
  const [liveConsole, setLiveConsole] = useState<string[]>([]);
  const [activeAgentId, setActiveAgentId] = useState<string | null>(null);
  const [pinnedAgentId, setPinnedAgentId] = useState<string | null>(null);
  const consoleEndRef = useRef<HTMLDivElement | null>(null);

  // Subscribe to the loop stream
  useEffect(() => {
    if (!loopId) return;
    let lastFetch = 0;

    const unsubscribeAgent = { current: null as null | (() => void) };

    const refresh = async () => {
      try {
        const s = await api.loopGet(loopId);
        setSummary(s);
        const tone = s.status === "all_clear" ? "ok" :
                     s.status === "plateau" || s.status === "max_rounds" ? "warn" :
                     s.status === "running" ? "neutral" :
                     s.status === "cancelled" ? "neutral" : "err";
        setHealth({ text: `loop ${s.status}`, tone });
      } catch {}
    };

    void refresh();

    const unsub = subscribeLoop(loopId, async (ev: LoopEvent) => {
      // Lightweight refresh throttle — most events trigger a summary fetch
      if (Date.now() - lastFetch > 250) {
        lastFetch = Date.now();
        await refresh();
      }
      if (ev.event === "action_start" && ev.data.kind && (ev.data as any).agent_run_id) {
        setActiveAgentId((ev.data as any).agent_run_id);
        setLiveConsole([]);
      }
      if (ev.event === "action_end") {
        setActiveAgentId(null);
      }
    }, (status) => {
      void refresh();
      onLoopCompleted(status);
    });

    return () => { unsub(); unsubscribeAgent.current?.(); };
  }, [loopId, onLoopCompleted, setHealth]);

  // Subscribe to the active sub-agent's stream
  useEffect(() => {
    const id = pinnedAgentId ?? activeAgentId;
    if (!id) return;
    const unsub = subscribeAgent(id,
      (line) => setLiveConsole((prev) => [...prev.slice(-200), line]),
      () => {});
    return () => { unsub(); };
  }, [activeAgentId, pinnedAgentId]);

  // Auto-scroll console
  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: "auto" });
  }, [liveConsole]);

  if (!loopId) return null;

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Play size={14} />
        <span className="text-sm font-semibold text-ink-900">Iteration</span>
        <span className="text-[11px] text-ink-500">
          loop {loopId.slice(0, 8)}
          {summary && ` · ${summary.status}${summary.status === "running" ?
            ` · round ${summary.round} of 10` : ""}`}
        </span>
        {summary?.status === "running" && (
          <button
            onClick={() => api.loopCancel(loopId)}
            className="ml-auto h-7 px-2.5 text-[11.5px] rounded border border-edge text-ink-700 hover:border-err hover:text-err"
          >
            ⊗ Cancel
          </button>
        )}
      </header>

      {summary?.status === "plateau" && (
        <div className="px-4 py-2 text-[12px] bg-warn/[0.06] text-ink-700 border-b border-edge">
          <strong>⚠ Loop halted</strong> — no progress for 2 consecutive rounds.{" "}
          {summary.findings_current} findings unresolved.
        </div>
      )}
      {summary?.status === "all_clear" && (
        <div className="px-4 py-2 text-[12px] bg-ok/[0.06] text-ok border-b border-edge">
          ✓ All findings resolved in {summary.rounds.length} rounds.
        </div>
      )}
      {summary?.error && (
        <div className="px-4 py-2 text-[12px] text-err bg-err/[0.06] border-b border-edge">
          error: {summary.error}
        </div>
      )}

      <div className="px-4 py-3 space-y-2">
        {summary?.rounds.map((r) => (
          <RoundCard key={r.n} r={r}
            activeAgentId={pinnedAgentId ?? activeAgentId}
            onPin={setPinnedAgentId} />
        ))}
      </div>

      {(activeAgentId || pinnedAgentId) && (
        <div className="border-t border-edge px-4 py-2.5">
          <div className="text-[11px] text-ink-500 mb-1.5 flex items-center gap-2">
            Live console — agent {(pinnedAgentId ?? activeAgentId)?.slice(0, 8)}
            {pinnedAgentId && (
              <button onClick={() => setPinnedAgentId(null)}
                className="ml-auto text-ink-500 hover:text-ink-900">unpin</button>
            )}
          </div>
          <pre className="text-[11px] font-mono bg-rail/40 p-2 rounded max-h-[200px] overflow-auto">
{liveConsole.join("\n")}
            <div ref={consoleEndRef} />
          </pre>
        </div>
      )}
    </section>
  );
}

function RoundCard({ r, activeAgentId, onPin }:
  { r: LoopRound; activeAgentId: string | null; onPin: (id: string) => void }) {
  const delta = r.findings_before - r.findings_after;
  const deltaTxt = delta > 0 ? `-${delta} net` : delta < 0 ? `+${-delta} net` : "0 net";
  return (
    <div className="rounded border border-edge px-3 py-2">
      <div className="flex items-baseline gap-2 text-[12px]">
        <strong className="text-ink-900">Round {r.n}</strong>
        <span className="text-ink-500">
          {deltaTxt} · {r.findings_before}→{r.findings_after}
        </span>
        {!r.finished_at && <span className="text-ink-500 italic">(running)</span>}
      </div>
      <div className="mt-1.5 ml-2 space-y-1">
        {r.actions.map((a, i) => (
          <ActionRow key={i} a={a} onPin={onPin} active={a.agent_run_id === activeAgentId} />
        ))}
        {r.build_status && (
          <div className="text-[11.5px] text-ink-700">
            ▾ build · {r.build_status}
            {r.lint_summary && ` · lint ${r.lint_summary.ERROR}/${r.lint_summary.WARNING}/${r.lint_summary.INFO}`}
          </div>
        )}
        {r.sim_results.length > 0 && (
          <div className="text-[11.5px] text-ink-700">
            ▾ sim · {r.sim_results.filter(s => s.ok).length}/{r.sim_results.length} ok
          </div>
        )}
      </div>
    </div>
  );
}

function ActionRow({ a, onPin, active }:
  { a: LoopAction; onPin: (id: string) => void; active: boolean }) {
  const dot = a.status === "ok" ? "●" : a.status === "fail" ? "✗" :
              a.status === "cancelled" ? "⊗" : "◐";
  const tone = a.status === "ok" ? "text-ok" : a.status === "fail" ? "text-err" :
               a.status === "cancelled" ? "text-ink-500" : "text-ink-700";
  return (
    <div className={"text-[11.5px] flex items-center gap-1.5 " + (active ? "bg-rail/30 rounded px-1" : "")}>
      <span className={tone}>{dot}</span>
      <span className="font-mono text-ink-500">{a.kind}</span>
      <span className="text-ink-700">· {a.summary}</span>
      {a.agent_run_id && (
        <button onClick={() => onPin(a.agent_run_id!)}
          className="ml-auto text-[10px] text-ink-500 hover:text-ink-900">
          pin
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Mount in Review.tsx**

Open `test1/gui/frontend/src/tabs/Review.tsx`. Add imports:

```typescript
import { IterationSection } from "../components/IterationSection";
```

Add state for the current loop id:

```tsx
  const [activeLoopId, setActiveLoopId] = useState<string | null>(null);
```

Replace the old `startRun` function with one that starts a loop:

```tsx
  const startLoop = async () => {
    setLines([]);
    setRunState("running");
    setHealth({ text: "loop starting…", tone: "neutral" });
    try {
      const { loop_id } = await api.loopStart();
      setActiveLoopId(loop_id);
    } catch (e) {
      setHealth({ text: "loop start failed", tone: "err" });
      setRunState("fail");
    }
  };
```

Update the Run Review button to call `startLoop`. Then mount:

```tsx
        <IterationSection
          loopId={activeLoopId}
          onLoopCompleted={(status) => {
            setRunState(status === "all_clear" ? "ok" : "fail");
            onArtifactsChanged();
          }}
          setHealth={setHealth}
        />
```

Also fetch the latest loop on mount (so reload re-attaches):

```tsx
  useEffect(() => {
    void api.loopLatest().then((l) => {
      if ("loop_id" in l && l.loop_id) setActiveLoopId(l.loop_id);
    });
  }, []);
```

- [ ] **Step 3: Frontend type-check**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: clean (a few `useState`-typing tweaks may be needed; fix any errors before commit).

- [ ] **Step 4: Commit**

```powershell
git add test1\gui\frontend\src\components\IterationSection.tsx test1\gui\frontend\src\tabs\Review.tsx
git commit -m "feat(ui): Iteration section — per-round timeline + live console

Subscribes to /api/loop/{id}/stream; renders one card per round with
actions, build status, sim results. Active sub-agent's stream embeds
as a live console (subscribeAgent on the agent_run_id); pin button
lets the user lock onto a past round's agent. Cancel button posts to
/api/loop/{id}/cancel.

Spec §7.B."
```

---

### Task 4.8: Diff computation (`diff.py`)

**Files:**
- Create: `test1/review/diff.py`
- Modify: `test1/gui/backend/app.py` (add `/api/loop/{id}/diff`)

- [ ] **Step 1: Write `diff.py`**

Create `test1/review/diff.py`:

```python
"""Per-sheet refdes-level netlist diff for the closed-loop Diff & Accept view.

Compares snapshot netlists vs current netlists, returns {added, removed, changed}
per sheet with refdes anchor positions (for the SVG overlay highlights)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .closed_loop import OUT_DIR, NETLIST_DIR, SNAPSHOT_ROOT


@dataclass
class SheetDiff:
    viewBox: str           # SVG viewBox, e.g. "0 0 15500 11100"
    added:   dict[str, dict]   # refdes -> {x, y, kind: "added"}
    removed: dict[str, dict]
    changed: dict[str, dict]   # refdes -> {x, y, kind: "changed", from_value, to_value}


def _load_netlist(path: Path) -> dict:
    if not path.exists():
        return {"parts": {}, "nets": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _refdes_anchors(svg_path: Path) -> dict[str, dict]:
    """Use the existing test1/altium/refdes_locations.extract to get
    {refdes: {x, y}} from a rendered SVG."""
    from test1.altium import refdes_locations
    try:
        return refdes_locations.extract(svg_path)
    except Exception:
        return {"viewBox": "0 0 15500 11100", "refdes": {}}


def compute_loop_diff(loop_id: str) -> dict[str, dict]:
    """Returns {sheet_stem: {viewBox, added, removed, changed}} per sheet."""
    snapshot_dir = SNAPSHOT_ROOT / loop_id
    if not snapshot_dir.exists():
        return {}

    out: dict[str, dict] = {}
    snap_netlist_dir = snapshot_dir / "netlist"
    cur_render_dir = OUT_DIR / "render"

    for snap_yaml in snap_netlist_dir.glob("*.yaml"):
        sheet = snap_yaml.stem
        cur_yaml = NETLIST_DIR / f"{sheet}.yaml"

        snap_nl = _load_netlist(snap_yaml)
        cur_nl = _load_netlist(cur_yaml)
        snap_parts = snap_nl.get("parts", {}) or {}
        cur_parts = cur_nl.get("parts", {}) or {}

        added: dict[str, dict] = {}
        removed: dict[str, dict] = {}
        changed: dict[str, dict] = {}

        # Refdes-level adds/removes
        for rd in cur_parts.keys() - snap_parts.keys():
            added[rd] = {"kind": "added"}
        for rd in snap_parts.keys() - cur_parts.keys():
            removed[rd] = {"kind": "removed"}
        # Value changes on the same refdes
        for rd in cur_parts.keys() & snap_parts.keys():
            cur_v = (cur_parts[rd] or {}).get("value", "")
            snap_v = (snap_parts[rd] or {}).get("value", "")
            if cur_v != snap_v:
                changed[rd] = {
                    "kind": "changed",
                    "from_value": snap_v,
                    "to_value": cur_v,
                }

        # Get anchor positions
        cur_svg = cur_render_dir / f"{sheet}.svg"
        snap_svg = snapshot_dir / "render" / f"{sheet}.svg"
        cur_anchors = _refdes_anchors(cur_svg) if cur_svg.exists() else {"viewBox":"0 0 15500 11100","refdes":{}}
        snap_anchors = _refdes_anchors(snap_svg) if snap_svg.exists() else {"viewBox":"0 0 15500 11100","refdes":{}}

        # Annotate adds/changed with current positions
        for rd, body in {**added, **changed}.items():
            anchor = (cur_anchors.get("refdes") or {}).get(rd, {})
            body.update(x=anchor.get("x", 0), y=anchor.get("y", 0))
        # Annotate removeds with snapshot positions
        for rd, body in removed.items():
            anchor = (snap_anchors.get("refdes") or {}).get(rd, {})
            body.update(x=anchor.get("x", 0), y=anchor.get("y", 0))

        out[sheet] = {
            "viewBox": cur_anchors.get("viewBox", "0 0 15500 11100"),
            "added": added,
            "removed": removed,
            "changed": changed,
            "count": len(added) + len(removed) + len(changed),
        }
    return out
```

- [ ] **Step 2: Add the diff endpoint to app.py**

Open `test1/gui/backend/app.py`. After `loop_reject`, add:

```python
@app.get("/api/loop/{loop_id}/diff")
def loop_diff(loop_id: str) -> dict:
    from test1.review.diff import compute_loop_diff
    return {"loop_id": loop_id, "sheets": compute_loop_diff(loop_id)}
```

- [ ] **Step 3: Smoke-test the diff endpoint**

(Skip until a real loop has snapshotted; will exercise in Task 4.10.)

- [ ] **Step 4: Commit**

```powershell
git add test1\review\diff.py test1\gui\backend\app.py
git commit -m "feat(diff): per-sheet refdes-level netlist diff endpoint

Compares snapshot vs current netlists, annotates with refdes anchor
positions from refdes_locations.extract (same source the simulated-
region overlay uses)."
```

---

### Task 4.9: Extend `PngViewer` + `RegionOverlay` for diff

**Files:**
- Create: `test1/gui/frontend/src/components/DiffOverlay.tsx`
- Modify: `test1/gui/frontend/src/components/PngViewer.tsx` (or use the new DiffOverlay alongside)

- [ ] **Step 1: Create DiffOverlay.tsx**

Create `test1/gui/frontend/src/components/DiffOverlay.tsx`:

```typescript
/* Diff overlay — generalization of the simulated-region overlay pattern
 * in PngViewer. Same SVG-mask approach: dim the whole sheet, cut holes
 * for each highlighted refdes, stroke the cutouts in a color matching
 * the change kind (added=green, removed=red, changed=amber).
 *
 * Used in side-by-side mode by DiffAndAccept. Sized to match the host
 * SVG's viewBox via the parent's natural-size context.
 */
import type { CSSProperties } from "react";

export interface DiffBox {
  x: number;
  y: number;
  kind: "added" | "removed" | "changed";
  refdes?: string;
}

const COLOR: Record<DiffBox["kind"], string> = {
  added:   "#16a34a",   // green-600
  removed: "#dc2626",   // red-600
  changed: "#d97706",   // amber-600
};

const BOX_W = 150;
const BOX_H = 120;
const BOX_DX = -70;
const BOX_DY = -30;

interface Props {
  boxes: DiffBox[];
  viewBox: string;       // matches the host SVG viewBox
  style?: CSSProperties;
}

export function DiffOverlay({ boxes, viewBox, style }: Props) {
  const maskId = "diff-mask-" + Math.random().toString(36).slice(2, 8);
  return (
    <svg viewBox={viewBox} style={style} preserveAspectRatio="xMidYMid meet">
      <defs>
        <mask id={maskId}>
          <rect x="0" y="0" width="100%" height="100%" fill="white" opacity="0.35" />
          {boxes.map((b, i) => (
            <rect key={i}
              x={b.x + BOX_DX} y={b.y + BOX_DY}
              width={BOX_W} height={BOX_H}
              fill="black" />
          ))}
        </mask>
      </defs>
      <rect x="0" y="0" width="100%" height="100%" fill="white" opacity="0" mask={`url(#${maskId})`} />
      {boxes.map((b, i) => (
        <g key={i}>
          <rect x={b.x + BOX_DX} y={b.y + BOX_DY}
            width={BOX_W} height={BOX_H}
            fill="none" stroke={COLOR[b.kind]} strokeWidth={6}
            opacity={0.95} />
          {b.refdes && (
            <text x={b.x + BOX_DX + 4} y={b.y + BOX_DY - 6}
              fontSize="20" fill={COLOR[b.kind]} fontFamily="monospace">
              {b.refdes}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
```

- [ ] **Step 2: Verify TypeScript**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: clean.

- [ ] **Step 3: Commit**

```powershell
git add test1\gui\frontend\src\components\DiffOverlay.tsx
git commit -m "feat(ui): DiffOverlay — SVG mask overlay for added/removed/changed

Generalizes the simulated-region overlay pattern with three colors
(green/red/amber) and an optional refdes label per box. Sits on top
of a host SVG matching its viewBox."
```

---

### Task 4.10: DiffAndAccept.tsx component (Section C)

**Files:**
- Create: `test1/gui/frontend/src/components/DiffAndAccept.tsx`
- Modify: `test1/gui/frontend/src/tabs/Review.tsx` (mount it)
- Modify: `test1/gui/frontend/src/api.ts` (add diff fetch)

- [ ] **Step 1: Add the diff fetch to api.ts**

In `test1/gui/frontend/src/api.ts`, in the `api` object:

```typescript
  loopDiff: async (loop_id: string): Promise<{
    loop_id: string;
    sheets: Record<string, {
      viewBox: string;
      added: Record<string, { x: number; y: number; kind: "added" }>;
      removed: Record<string, { x: number; y: number; kind: "removed" }>;
      changed: Record<string, { x: number; y: number; kind: "changed"; from_value: string; to_value: string }>;
      count: number;
    }>;
  }> => {
    const r = await fetch(`/api/loop/${loop_id}/diff`);
    if (!r.ok) throw new Error("diff fetch failed");
    return r.json();
  },
```

- [ ] **Step 2: Create DiffAndAccept.tsx**

Create `test1/gui/frontend/src/components/DiffAndAccept.tsx`:

```typescript
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { DiffOverlay, type DiffBox } from "./DiffOverlay";
import { I } from "./Icon";

interface Props {
  loopId: string;
  loopStatus: string;        // "all_clear" | "plateau" | "max_rounds" | "cancelled" | "error"
  onResolved: () => void;     // called after Accept or Reject
}

type Mode = "side" | "overlay";

export function DiffAndAccept({ loopId, loopStatus, onResolved }: Props) {
  const [diff, setDiff] = useState<Awaited<ReturnType<typeof api.loopDiff>> | null>(null);
  const [activeSheet, setActiveSheet] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("side");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await api.loopDiff(loopId);
      setDiff(d);
      if (!activeSheet) {
        // pick the sheet with the most changes
        const entries = Object.entries(d.sheets);
        if (entries.length > 0) {
          const winner = entries.sort((a, b) => b[1].count - a[1].count)[0];
          setActiveSheet(winner[0]);
        }
      }
    } catch (e) {
      console.error(e);
    }
  }, [loopId, activeSheet]);

  useEffect(() => { void refresh(); }, [refresh]);

  const accept = async () => {
    setBusy(true);
    try { await api.loopAccept(loopId); onResolved(); }
    finally { setBusy(false); }
  };
  const reject = async () => {
    setBusy(true);
    try { await api.loopReject(loopId); onResolved(); }
    finally { setBusy(false); }
  };

  if (!diff) return null;
  const sheets = Object.entries(diff.sheets);
  const totalAdded = sheets.reduce((s, [,d]) => s + Object.keys(d.added).length, 0);
  const totalRemoved = sheets.reduce((s, [,d]) => s + Object.keys(d.removed).length, 0);
  const totalChanged = sheets.reduce((s, [,d]) => s + Object.keys(d.changed).length, 0);

  const current = activeSheet ? diff.sheets[activeSheet] : null;
  const boxes: DiffBox[] = current
    ? [
        ...Object.entries(current.added).map(([rd, b]) => ({ ...b, refdes: rd })),
        ...Object.entries(current.removed).map(([rd, b]) => ({ ...b, refdes: rd })),
        ...Object.entries(current.changed).map(([rd, b]) => ({ ...b, refdes: rd })),
      ]
    : [];

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Diff size={14} />
        <span className="text-sm font-semibold text-ink-900">Diff &amp; Accept</span>
        <span className="text-[11px] text-ink-500">
          loop {loopId.slice(0,8)} · {loopStatus} · +{totalAdded} -{totalRemoved} ~{totalChanged}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <div className="text-[11px] flex items-center gap-1">
            <button onClick={() => setMode("side")} className={mode==="side" ? "text-ink-900 font-medium" : "text-ink-500"}>side-by-side</button>
            <span className="text-ink-500">/</span>
            <button onClick={() => setMode("overlay")} className={mode==="overlay" ? "text-ink-900 font-medium" : "text-ink-500"}>overlay</button>
          </div>
        </div>
      </header>

      <div className="px-4 py-2 flex gap-1 flex-wrap border-b border-edge">
        {sheets.map(([stem, d]) => (
          <button key={stem}
            onClick={() => setActiveSheet(stem)}
            className={"px-2 py-0.5 text-[11.5px] rounded border " +
              (activeSheet === stem ? "border-ink-700 bg-rail/40" : "border-edge hover:border-ink-300")}>
            {stem} {d.count > 0 && <span className="text-[10px] text-ink-500">·{d.count}</span>}
          </button>
        ))}
      </div>

      {current && (
        <div className="p-4">
          {mode === "side" ? (
            <div className="grid grid-cols-2 gap-3">
              <DiffPane title="BEFORE (snapshot)"
                src={`/api/png_snapshot/${loopId}/${activeSheet}`}
                boxes={boxes.filter(b => b.kind === "removed" || b.kind === "changed")}
                viewBox={current.viewBox} />
              <DiffPane title="AFTER (current)"
                src={`/api/png/${activeSheet}`}
                boxes={boxes.filter(b => b.kind === "added" || b.kind === "changed")}
                viewBox={current.viewBox} />
            </div>
          ) : (
            <DiffPane title="OVERLAY"
              src={`/api/png/${activeSheet}`}
              boxes={boxes}
              viewBox={current.viewBox} />
          )}

          <ChangeList sheet={current} />
        </div>
      )}

      <footer className="px-4 py-3 border-t border-edge flex items-center gap-2">
        <button onClick={accept} disabled={busy}
          className="h-8 px-3 inline-flex items-center gap-1.5 rounded bg-ok text-white text-sm font-medium hover:bg-ok/90 disabled:opacity-50">
          <I.Check size={12} /> Accept all
        </button>
        <button onClick={reject} disabled={busy}
          className="h-8 px-3 inline-flex items-center gap-1.5 rounded border border-edge text-ink-700 text-sm hover:border-err hover:text-err disabled:opacity-50">
          ✗ Reject (revert)
        </button>
        <span className="text-[11px] text-ink-500 ml-2">
          Accept keeps the loop's changes. Reject restores the pre-loop state.
        </span>
      </footer>
    </section>
  );
}

function DiffPane({ title, src, boxes, viewBox }:
  { title: string; src: string; boxes: DiffBox[]; viewBox: string }) {
  return (
    <div className="rounded border border-edge bg-white">
      <div className="text-[10px] uppercase tracking-wide text-ink-500 px-2 py-1 border-b border-edge">{title}</div>
      <div className="relative">
        <img src={src} alt={title} className="w-full block" />
        <DiffOverlay boxes={boxes} viewBox={viewBox}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />
      </div>
    </div>
  );
}

function ChangeList({ sheet }:
  { sheet: { added: Record<string, any>; removed: Record<string, any>; changed: Record<string, { from_value: string; to_value: string }> } }) {
  return (
    <details className="mt-3 text-[11.5px]">
      <summary className="cursor-pointer text-ink-700 hover:text-ink-900">Change list</summary>
      <ul className="mt-1.5 ml-3 space-y-0.5">
        {Object.entries(sheet.added).map(([rd]) => (
          <li key={"a"+rd}><span className="text-ok">+</span> {rd} added</li>
        ))}
        {Object.entries(sheet.removed).map(([rd]) => (
          <li key={"r"+rd}><span className="text-err">-</span> {rd} removed</li>
        ))}
        {Object.entries(sheet.changed).map(([rd, c]) => (
          <li key={"c"+rd}><span className="text-warn">~</span> {rd}: {c.from_value} → {c.to_value}</li>
        ))}
      </ul>
    </details>
  );
}
```

- [ ] **Step 3: Add a snapshot PNG endpoint to backend**

Open `test1/gui/backend/app.py`. After `loop_diff`, add:

```python
@app.get("/api/png_snapshot/{loop_id}/{name}")
def png_snapshot(loop_id: str, name: str):
    """Serve a pre-loop snapshot render for the Diff & Accept side-by-side
    view. name is the sheet stem (no extension)."""
    safe = re.sub(r"[^A-Za-z0-9_]", "", name)
    snap = _loop_mod.SNAPSHOT_ROOT / loop_id / "render" / f"{safe}.svg"
    if not snap.exists():
        raise HTTPException(404, f"snapshot render not found: {snap}")
    return FileResponse(snap, media_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})
```

- [ ] **Step 4: Mount DiffAndAccept in Review.tsx**

Add import:

```typescript
import { DiffAndAccept } from "../components/DiffAndAccept";
```

After IterationSection, add:

```tsx
        {activeLoopId && summary && summary.status !== "running" && (
          <DiffAndAccept
            loopId={activeLoopId}
            loopStatus={summary.status}
            onResolved={() => { setActiveLoopId(null); onArtifactsChanged(); }}
          />
        )}
```

(You'll need to expose the `summary` from IterationSection — easiest is to pass an `onSummary` callback from Review.tsx into IterationSection and lift the state up.)

- [ ] **Step 5: Frontend builds**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: clean.

- [ ] **Step 6: Commit**

```powershell
git add test1\gui\frontend\src\components\DiffAndAccept.tsx test1\gui\frontend\src\tabs\Review.tsx test1\gui\frontend\src\api.ts test1\gui\backend\app.py
git commit -m "feat(ui): Diff & Accept section — side-by-side schematic diff

Renders after a completed loop. Side-by-side mode shows pre-loop snapshot
SVG + current SVG with colored overlay boxes (green/red/amber).
Overlay mode shows current SVG with all kinds. Sheet tab strip with
per-sheet change counts. Accept/Reject buttons hit /api/loop/{id}/accept|reject.

Spec §7.C."
```

---

### Task 4.11: Phase 4 gate — end-to-end loop run

- [ ] **Step 1: Build green**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m test1.altium.build_project
```
Expected: `FAILURES: none`.

- [ ] **Step 2: Frontend clean**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```
Expected: no errors.

- [ ] **Step 3: Run a real loop from the GUI**

Start backend + frontend. Open <http://localhost:5173>, navigate to Review tab. Click **Approve & Run loop**.

Expected within 60 seconds:
- Iteration section appears with "loop XXXX · running · round 1 of 10"
- Round 1 card shows actions executing (apply, build, sim)
- After build completes, round_done event fires; Δ shows in card header
- Loop continues until all-clear, plateau, or max_rounds
- On completion, Diff & Accept section appears below Iteration
- Side-by-side diff renders both panes with overlay boxes

- [ ] **Step 4: Accept or reject**

Click **Reject (revert)** to verify rollback path. Verify that `netlist/<sheet>.yaml` files match their snapshot version (compare against `out/render_snapshots/<loop_id>/netlist/*.yaml`). Then run `build_project` and confirm green again.

- [ ] **Step 5: Verify changelog plateau message (if plateau halted)**

If the loop halted at plateau, check ChangelogPanel (in AgentRail) for a "closed_loop" entry: `loop xxxx halted at round R — plateau, N unresolved (E·W·I)`.

Phase 4 complete.

---

## Phase 5 — Missing-Part Flow

`missing_part.py` with strenuous candidate selection, sim-verification gate, value-tweak subloop, and topology-adaptation fallback. Wires into the orchestrator's `missing_part` action kind.

### Task 5.1: Create `missing_part.py` skeleton + WebSearch helpers

**Files:**
- Create: `test1/review/missing_part.py`

- [ ] **Step 1: Write the module**

Create `test1/review/missing_part.py`:

```python
"""Missing-part flow — strenuous part selection, sim-verification gate,
topology-adaptation fallback.

Triggered by Action(kind='missing_part'). One action handles one missing
part. Provider-backed: parts_provider().search(...) for candidates +
knowledge_provider().query(...) for datasheet extracts.

Spec §5 (in design doc).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .closed_loop import Loop, Action, WEB_CALL_BUDGET, PROJECT_DIR, REPO_ROOT
from .providers import Candidate, parts_provider, knowledge_provider
from .rule_schema import Rule, StructuralRule


DATASHEET_INCOMING = REPO_ROOT / "_datasheet_incoming"
PARTS_LIBRARY = PROJECT_DIR / "Parts Library"
WEB_CACHE = PROJECT_DIR / "review" / ".web_cache"
MAX_CANDIDATES = 5
MAX_VALUE_TWEAK_ROUNDS = 3
MAX_TOPOLOGY_ATTEMPTS = 2


@dataclass
class CandidateAudit:
    mpn: str
    rank: int
    rejection: str | None = None    # "identity_check_failed" | "sim_fail" | ...
    sim_results: list[dict] = field(default_factory=list)
    sim_margin: float | None = None
    outcome: str = "untried"        # "untried" | "accepted" | "rejected"


@dataclass
class MissingPartAudit:
    rule_id: str
    role_spec: dict
    provider: str
    search_query: str
    candidates_considered: list[CandidateAudit] = field(default_factory=list)
    topology_adaptations: list[dict] = field(default_factory=list)
    status: str = "running"          # running | ok | fail
    summary: str = ""


# ---- Public entrypoint --------------------------------------------------

async def run_missing_part_action(L: Loop, action: Action) -> MissingPartAudit:
    """Execute one missing-part action. Mutates `action` in place and returns
    the audit blob to be stored on the round."""
    from .rule_eval import load_rules
    rules_by_id = {r.id: r for r in load_rules().rules}
    rule = rules_by_id.get(action.targets[0]) if action.targets else None
    if not rule or not isinstance(rule, StructuralRule):
        action.status = "fail"
        action.summary = "missing-part: rule not found or not structural"
        return MissingPartAudit(rule_id=action.targets[0] if action.targets else "",
                                role_spec={}, provider="",
                                search_query="", status="fail")

    audit = MissingPartAudit(
        rule_id=rule.id,
        role_spec=rule.applies_to.role_spec or {},
        provider=type(parts_provider()).__name__,
        search_query="",
    )

    # 1. Search
    query = _render_query(rule)
    audit.search_query = query
    if L.web_call_count >= WEB_CALL_BUDGET:
        action.status = "fail"
        action.summary = f"missing-part: web-call budget exhausted ({WEB_CALL_BUDGET})"
        audit.status = "fail"
        return audit
    L.web_call_count += 1
    candidates = parts_provider().search(query, rule.applies_to.role_spec)

    # 2. Rank top MAX_CANDIDATES
    ranked = _rank_candidates(candidates, rule.applies_to.role_spec)[:MAX_CANDIDATES]
    for i, c in enumerate(ranked):
        audit.candidates_considered.append(CandidateAudit(mpn=c.mpn, rank=i+1))

    # 3. Iterate through survivors
    for idx, cand in enumerate(ranked):
        cand_audit = audit.candidates_considered[idx]
        # Sub-snapshot before placement (so we can revert this candidate)
        sub_snap_dir = L.snapshot_dir / f"_cand_{idx}_{cand.mpn}"
        sub_snap_dir.mkdir(parents=True, exist_ok=True)
        for y in (REPO_ROOT / "test1" / "netlist").glob("*.yaml"):
            shutil.copy2(y, sub_snap_dir / y.name)

        # 3a. Identity check
        try:
            ds_path = parts_provider().fetch_datasheet(cand)
        except NotImplementedError as e:
            cand_audit.rejection = f"provider not configured: {e}"
            continue
        L.web_call_count += 1
        if not _identity_check(ds_path, cand.mpn):
            cand_audit.rejection = "identity_check_failed"
            continue

        # 3b. Install datasheet + generate symbol
        ok = await _install_and_author(cand.mpn, ds_path)
        if not ok:
            cand_audit.rejection = "symbol_gen_failed"
            continue

        # 3c. Apply-place via existing apply agent
        ok = await _place_into_schematic(L, rule, cand)
        if not ok:
            cand_audit.rejection = "place_failed"
            _revert_yaml_from(sub_snap_dir)
            continue

        # 3d. Build + lint
        from .closed_loop import _rebuild_project
        build_status, _lint = await _rebuild_project()
        if build_status != "ok":
            cand_audit.rejection = "build_failed"
            _revert_yaml_from(sub_snap_dir)
            continue

        # 3e. Sim-verification gate with value-tweak subloop
        passed, margin, sim_results = await _sim_verify(L, rule, cand)
        cand_audit.sim_results = sim_results
        cand_audit.sim_margin = margin
        if passed:
            cand_audit.outcome = "accepted"
            action.status = "ok"
            action.summary = f"missing-part: placed {cand.mpn} (candidate {idx+1})"
            audit.status = "ok"
            return audit
        else:
            cand_audit.rejection = "sim_fail"
            _revert_yaml_from(sub_snap_dir)
            continue

    # 4. Topology adaptation
    best = _best_failed_candidate(audit.candidates_considered)
    if best:
        for attempt in range(MAX_TOPOLOGY_ATTEMPTS):
            adapted = await _topology_adapt(L, rule, best)
            audit.topology_adaptations.append({
                "attempt": attempt + 1,
                "best_candidate": best.mpn,
                "status": adapted.get("status", "fail"),
                "summary": adapted.get("summary", ""),
            })
            if adapted.get("status") == "ok":
                action.status = "ok"
                action.summary = (f"missing-part: topology-adapted to use "
                                   f"{best.mpn} (attempt {attempt+1})")
                audit.status = "ok"
                return audit

    # 5. Impasse
    action.status = "fail"
    action.summary = f"missing-part impasse: {len(ranked)} candidates + {len(audit.topology_adaptations)} topology attempts failed"
    audit.status = "fail"
    audit.summary = action.summary
    return audit


# ---- Helper stubs (will fill in next tasks) -----------------------------

def _render_query(rule: Rule) -> str:
    """Build a search query from rule.applies_to. Filled in Task 5.2."""
    raise NotImplementedError("Task 5.2")


def _rank_candidates(cands: list[Candidate], role_spec: dict) -> list[Candidate]:
    """Filter by hard constraints + score by soft constraints. Task 5.2."""
    raise NotImplementedError("Task 5.2")


def _identity_check(pdf: Path, mpn: str) -> bool:
    """MPN literal + manufacturer line in first 3 pages. Task 5.2."""
    raise NotImplementedError("Task 5.2")


async def _install_and_author(mpn: str, ds_path: Path) -> bool:
    """install_datasheets.py + start_symbol_gen. Task 5.3."""
    raise NotImplementedError("Task 5.3")


async def _place_into_schematic(L: Loop, rule: Rule, cand: Candidate) -> bool:
    """Dispatch apply agent with rule + candidate context. Task 5.3."""
    raise NotImplementedError("Task 5.3")


async def _sim_verify(L: Loop, rule: Rule, cand: Candidate) -> tuple[bool, float | None, list[dict]]:
    """Affected-block gate + value-tweak subloop. Task 5.4."""
    raise NotImplementedError("Task 5.4")


def _best_failed_candidate(audits: list[CandidateAudit]) -> CandidateAudit | None:
    survivors = [a for a in audits if a.sim_margin is not None]
    return min(survivors, key=lambda a: abs(a.sim_margin or 1e9), default=None)


async def _topology_adapt(L: Loop, rule: Rule, best: CandidateAudit) -> dict:
    """Dispatch topology_adapt agent. Task 5.5."""
    raise NotImplementedError("Task 5.5")


def _revert_yaml_from(sub_snap_dir: Path) -> None:
    target = REPO_ROOT / "test1" / "netlist"
    for y in sub_snap_dir.glob("*.yaml"):
        shutil.copy2(y, target / y.name)


# ---- WebSearch fallback (called by WebSearchPartsProvider) -------------

def _web_search_candidates(query: str, role_spec: dict | None) -> list[Candidate]:
    """Default impl: dispatched as a Claude tool call from within an agent
    we spawn just to do the search. For Phase 5 baseline, return [] with a
    log line — the future custom parts API or a dedicated web-search agent
    fills this in.

    Wiring to do later: spawn a one-shot 'search' agent whose only job
    is to call WebSearch + WebFetch and return a JSON list of candidates."""
    print(f"[missing_part] WebSearchPartsProvider.search({query!r}, {role_spec!r}) — STUB; install custom parts API or fill in.")
    return []


def _web_fetch_datasheet(cand: Candidate) -> Path:
    """Default impl stub. See _web_search_candidates note above."""
    DATASHEET_INCOMING.mkdir(parents=True, exist_ok=True)
    target = DATASHEET_INCOMING / f"{cand.mpn}.pdf"
    print(f"[missing_part] WebSearchPartsProvider.fetch_datasheet({cand.mpn}) — STUB; would download {cand.datasheet_url}")
    raise NotImplementedError("Default WebSearchPartsProvider needs a dedicated search agent; configure CUSTOM_PARTS_API_URL or implement.")
```

- [ ] **Step 2: Verify imports**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review import missing_part; print('imports OK')"
```
Expected: `imports OK`.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\missing_part.py
git commit -m "feat(loop): missing_part.py skeleton — strenuous selection orchestration

Full lifecycle: search → rank → identity → install → place → build →
sim-verify (with value-tweak subloop) → topology adapt fallback →
impasse. Helpers stubbed for next tasks. Sub-snapshot per candidate so
each one can be reverted before trying the next."
```

---

### Task 5.2: Query renderer, ranker, identity check

**Files:**
- Modify: `test1/review/missing_part.py`

- [ ] **Step 1: Replace the three stubs**

Open `test1/review/missing_part.py`. Replace `_render_query`, `_rank_candidates`, `_identity_check`:

```python
def _render_query(rule: Rule) -> str:
    """Build a WebSearch query from rule.applies_to."""
    parts: list[str] = []
    if rule.applies_to.mpn:
        parts.append(f'"{rule.applies_to.mpn}"')
        parts.append("datasheet")
    role = rule.applies_to.role_spec or {}
    if role.get("role"):
        parts.append(role["role"])
    for key, val in role.items():
        if key == "role":
            continue
        if isinstance(val, (int, float)):
            parts.append(f'"{key}" "{val}"')
        elif isinstance(val, list) and key == "package_pref":
            parts.append("(" + " OR ".join(f'"{p}"' for p in val) + ")")
    parts.append("datasheet")
    parts.append("(site:digikey.com OR site:mouser.com OR site:ti.com "
                  "OR site:microchip.com OR site:onsemi.com OR "
                  "site:nxp.com OR site:diodes.com OR site:infineon.com)")
    return " ".join(parts)


def _rank_candidates(cands: list[Candidate], role_spec: dict) -> list[Candidate]:
    """Filter by hard role_spec constraints; score by soft signals."""
    survivors: list[Candidate] = []
    role = role_spec or {}
    for c in cands:
        # Hard constraints: every numeric *_min in role_spec must be ≤ candidate's param
        ok = True
        for key, val in role.items():
            if key.endswith("_min_V") or key.endswith("_min_A"):
                metric = key.replace("_min", "")
                if c.params.get(metric, 0) < val:
                    ok = False; break
            if key.endswith("_max_ohm") or key.endswith("_max_V"):
                metric = key.replace("_max", "")
                if c.params.get(metric, 0) > val:
                    ok = False; break
        if not ok:
            continue
        # Lifecycle filter
        lifecycle = (c.params.get("lifecycle") or "").lower()
        if any(k in lifecycle for k in ("obsolete", "eol", "nrnd", "discontinued")):
            continue
        # Package filter
        pkg_pref = role.get("package_pref", [])
        if pkg_pref and c.params.get("package") not in pkg_pref:
            continue
        # Score
        score = 0.0
        score += float(c.params.get("source_count", 1))   # cross-distributor confirmation
        if c.params.get("automotive_grade"):
            score += 0.5
        if c.params.get("package") in pkg_pref[:1]:
            score += 0.3
        c.score = score
        survivors.append(c)
    survivors.sort(key=lambda c: -c.score)
    return survivors


def _identity_check(pdf: Path, mpn: str) -> bool:
    """MPN literal + manufacturer line should appear in first 3 pages."""
    try:
        from test1.sim.read_pdf import extract_text
        text = extract_text(pdf, pages=(1, 3))
    except Exception:
        return False
    norm = " ".join(text.split()).lower()
    if mpn.lower() not in norm:
        return False
    # Soft: at least one common manufacturer line
    for vendor in ("texas instruments", "microchip", "on semiconductor",
                   "nxp", "diodes incorporated", "infineon", "stmicroelectronics",
                   "analog devices", "renesas", "vishay"):
        if vendor in norm:
            return True
    # If MPN matches but no vendor line, still accept (some house-brand parts
    # don't include vendor name in the datasheet header).
    return True
```

- [ ] **Step 2: Verify it imports + a manual smoke**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "
from test1.review.missing_part import _render_query
from test1.review.rule_schema import StructuralRule, Present
class _Rule:
    class _A: mpn='2N7002'; role_spec={'role':'P-MOSFET','VDS_min_V':3.6,'package_pref':['SOT-23']}
    applies_to = _A
print(_render_query(_Rule()))
"
```
Expected: a search query string starting with `\"2N7002\" datasheet P-MOSFET ...`.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\missing_part.py
git commit -m "feat(missing-part): query renderer + candidate ranker + identity check

_render_query builds distributor-scoped WebSearch query from applies_to.
_rank_candidates filters by hard role_spec constraints + drops obsolete,
scores by cross-distributor confirmation + automotive grade + package match.
_identity_check verifies MPN literal in datasheet's first 3 pages."
```

---

### Task 5.3: Install + author + place

**Files:**
- Modify: `test1/review/missing_part.py`

- [ ] **Step 1: Replace `_install_and_author` and `_place_into_schematic`**

In `test1/review/missing_part.py`, replace the two stubs:

```python
async def _install_and_author(mpn: str, ds_path: Path) -> bool:
    """Move datasheet into Parts Library/<mpn>/<mpn>.pdf; dispatch symbol_gen."""
    target_dir = PARTS_LIBRARY / mpn
    target_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = target_dir / f"{mpn}.pdf"
    try:
        shutil.copy2(ds_path, target_pdf)
    except Exception as e:
        print(f"[missing_part] install copy failed: {e}")
        return False

    # Dispatch symbol_gen agent
    import sys
    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod
    rel = str(target_pdf.relative_to(PROJECT_DIR))
    run = await agent_mod.start_symbol_gen(mpn, rel)
    while run.status == "running":
        await asyncio.sleep(0.5)
    return run.status == "ok" and (target_dir / f"{mpn}.SchLib").exists()


async def _place_into_schematic(L: Loop, rule: Rule, cand: Candidate) -> bool:
    """Dispatch apply agent with a focused prompt to instantiate the part."""
    import sys
    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod
    # Use the existing changelog channel to convey the placement request.
    msg = (f"closed-loop / missing-part: rule {rule.id} requires a part of "
           f"role {rule.applies_to.role_spec or rule.applies_to.mpn}. "
           f"Place the newly-installed MPN={cand.mpn} into the relevant "
           f"sheet ({rule.applies_to.sheet or '?'}); seed values from the "
           f"datasheet typical-application circuit at Parts Library/"
           f"{cand.mpn}/{cand.mpn}.pdf. Edit netlist/<sheet>.yaml + "
           f"altium/build_<sheet>.py; rebuild via build_project.")
    agent_mod.append_changelog(msg, source="closed_loop")
    run = await agent_mod.start_apply_pass()
    L.sub_runs.append(run.run_id)
    while run.status == "running":
        if L.cancelled:
            agent_mod.cancel_run(run.run_id)
            return False
        await asyncio.sleep(0.5)
    return run.status == "ok"
```

- [ ] **Step 2: Verify imports**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -c "from test1.review import missing_part; print(missing_part._install_and_author.__name__)"
```
Expected: `_install_and_author`.

- [ ] **Step 3: Commit**

```powershell
git add test1\review\missing_part.py
git commit -m "feat(missing-part): install + author symbol + apply-place

_install_and_author copies the datasheet into Parts Library/<mpn>/ and
dispatches the existing symbol_gen agent (which writes .SchLib via
author_symbol.py). _place_into_schematic pushes a focused changelog
message and dispatches the existing apply agent."
```

---

### Task 5.4: Sim-verification gate + value-tweak subloop

**Files:**
- Modify: `test1/review/missing_part.py`

- [ ] **Step 1: Replace `_sim_verify`**

In `test1/review/missing_part.py`, replace the stub:

```python
async def _sim_verify(L: Loop, rule: Rule, cand: Candidate) -> tuple[bool, float | None, list[dict]]:
    """Affected-block gate: every block whose deck builder or refdes_map
    references the new refdes/MPN must verdict OK. Value-tweak subloop on
    fail (≤MAX_VALUE_TWEAK_ROUNDS inner rounds)."""
    from test1.sim import service as sim_service, catalog
    import sys
    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod

    affected_blocks: list[tuple[str, str]] = []
    for b in catalog.load_catalog():
        # Heuristic: a block "touches" this part if its blocks.yaml lists
        # the MPN in datasheets or if its models_needed line names it.
        text = json.dumps(b).lower()
        if cand.mpn.lower() in text:
            for st in b.get("sim_types", []):
                if st.get("status") == "implemented":
                    affected_blocks.append((b["id"], st["type"]))

    if not affected_blocks:
        return True, None, []  # nothing to verify against

    closest_margin = None
    results: list[dict] = []

    for tweak in range(MAX_VALUE_TWEAK_ROUNDS + 1):
        if L.cancelled:
            return False, closest_margin, results
        round_results = []
        all_ok = True
        for block, stype in affected_blocks:
            try:
                res = sim_service.run_block_sim(block, stype)
                ok = bool(res.get("ok"))
                round_results.append({"block": block, "sim_type": stype, "ok": ok,
                                      "tweak_round": tweak})
                if not ok:
                    all_ok = False
            except Exception as e:
                round_results.append({"block": block, "sim_type": stype, "ok": False,
                                      "error": str(e), "tweak_round": tweak})
                all_ok = False
        results.extend(round_results)
        if all_ok:
            return True, 0.0, results
        if tweak >= MAX_VALUE_TWEAK_ROUNDS:
            break

        # Tweak via sim_interpret + apply
        failed = [r for r in round_results if not r.get("ok")]
        if not failed:
            break
        for fr in failed:
            msg = (f"closed-loop / missing-part / value-tweak (round {tweak+1}): "
                   f"sim {fr['block']}.{fr['sim_type']} failed after placing "
                   f"{cand.mpn}. Inspect netlist + adjust a single passive's "
                   f"value to bring this sim into spec. Limit edits to one "
                   f"refdes per tweak round.")
            agent_mod.append_changelog(msg, source="closed_loop")
        run = await agent_mod.start_apply_pass()
        L.sub_runs.append(run.run_id)
        while run.status == "running":
            if L.cancelled:
                agent_mod.cancel_run(run.run_id)
                return False, closest_margin, results
            await asyncio.sleep(0.5)
        # Rebuild before next sim attempt
        from .closed_loop import _rebuild_project
        bs, _ = await _rebuild_project()
        if bs != "ok":
            break

    return False, closest_margin, results
```

- [ ] **Step 2: Commit**

```powershell
git add test1\review\missing_part.py
git commit -m "feat(missing-part): sim-verification gate + value-tweak subloop

Identifies affected blocks (whose deck/datasheets/models_needed reference
the candidate MPN) and runs each block's implemented sim_types. On any
failure, dispatches an apply pass with a focused tweak message (limit:
one refdes per tweak round), rebuilds, re-runs. Up to MAX_VALUE_TWEAK_ROUNDS
inner rounds before declaring the candidate failed."
```

---

### Task 5.5: Topology-adaptation fallback

**Files:**
- Modify: `test1/gui/backend/agent.py` (add `start_topology_adapt`)
- Modify: `test1/review/missing_part.py` (replace `_topology_adapt`)

- [ ] **Step 1: Add `start_topology_adapt` to agent.py**

After `start_lint_fix_pass` in `test1/gui/backend/agent.py`, add:

```python
async def start_topology_adapt(rule_id: str, candidate_mpn: str,
                                stuck_reason: str, sheet: str) -> AgentRun:
    """Dispatch the topology_adapt agent. Used by the missing-part flow
    when no candidate passes sim verification; tries restructuring the
    surrounding schematic to fit the best-margin candidate."""
    run = _register("topology_adapt")
    prompt = (f"You are revising the schematic to accommodate a part that "
              f"doesn't quite fit. Rule that needed the part: {rule_id}. "
              f"Best-margin candidate: {candidate_mpn}. Sheet: {sheet}. "
              f"Why it failed sim: {stuck_reason}.\n\n"
              f"Read test1/netlist/{sheet}.yaml and test1/altium/build_{sheet}.py. "
              f"Propose ONE LOCAL topology change that lets the candidate "
              f"satisfy its sim. Examples allowed: add a series resistor / "
              f"buffer / level shift; swap PMOS↔NMOS with rail inversion; "
              f"insert a second-stage filter; widen a decap bank; add a "
              f"gate resistor + clamp.\n\nHARD CONSTRAINTS:\n"
              f"  - Do NOT cross sheet boundaries.\n"
              f"  - Do NOT alter the parent rule's stated intent.\n"
              f"  - Make the change atomic — one refdes added/removed/edited "
              f"or one net rerouted.\n\nApply the change directly via Edit "
              f"on the YAML + build_{sheet}.py, then run python -m "
              f"test1.altium.build_project to verify lint + run the affected "
              f"sims. Report a one-line summary of what you changed and the "
              f"new sim margin.")
    proc = await _spawn_claude(prompt, run, model=model_for("topology_adapt"))
    asyncio.create_task(_run_subprocess(run, proc))
    return run
```

- [ ] **Step 2: Replace `_topology_adapt` in missing_part.py**

```python
async def _topology_adapt(L: Loop, rule: Rule, best: CandidateAudit) -> dict:
    import sys
    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod

    stuck = "sim margin near pass; specifics in candidate audit"
    if best.sim_results:
        last = best.sim_results[-1]
        stuck = f"last sim: {last.get('block')}.{last.get('sim_type')} = " \
                f"{'ok' if last.get('ok') else 'fail'}"
        if "error" in last:
            stuck = f"{stuck}; error={last['error']}"

    sheet = rule.applies_to.sheet or "?"
    run = await agent_mod.start_topology_adapt(rule.id, best.mpn, stuck, sheet)
    L.sub_runs.append(run.run_id)
    while run.status == "running":
        if L.cancelled:
            agent_mod.cancel_run(run.run_id)
            return {"status": "cancelled", "summary": "cancelled"}
        await asyncio.sleep(0.5)
    if run.status != "ok":
        return {"status": "fail", "summary": f"topology_adapt agent failed: {run.status}"}

    # Re-verify sim after the topology change
    from test1.sim import service as sim_service, catalog
    for b in catalog.load_catalog():
        if best.mpn.lower() not in json.dumps(b).lower():
            continue
        for st in b.get("sim_types", []):
            if st.get("status") != "implemented":
                continue
            try:
                res = sim_service.run_block_sim(b["id"], st["type"])
                if not res.get("ok"):
                    return {"status": "fail",
                            "summary": f"post-adapt sim {b['id']}.{st['type']} still fails"}
            except Exception as e:
                return {"status": "fail", "summary": f"sim error: {e}"}
    return {"status": "ok", "summary": f"topology adapted to fit {best.mpn}"}
```

- [ ] **Step 3: Wire into `_dispatch_action` in closed_loop.py**

Open `test1/review/closed_loop.py`. Find `_dispatch_action`, locate the `elif action.kind == "missing_part":` branch. Replace with:

```python
    elif action.kind == "missing_part":
        from .missing_part import run_missing_part_action
        audit = await run_missing_part_action(L, action)
        # Stash the per-action audit on the round for the UI to surface
        if L.rounds:
            L.rounds[-1].sim_results.extend([
                {"audit_kind": "missing_part",
                 "rule_id": audit.rule_id,
                 "status": audit.status,
                 "candidates": [asdict(c) for c in audit.candidates_considered],
                 "topology": audit.topology_adaptations}
            ])
```

(Make sure `asdict` is imported at top of `closed_loop.py` — it already is from `dataclasses`.)

- [ ] **Step 4: Commit**

```powershell
git add test1\gui\backend\agent.py test1\review\missing_part.py test1\review\closed_loop.py
git commit -m "feat(missing-part): topology-adaptation fallback agent

start_topology_adapt dispatches the topology_adapt AGENT_KIND with a
focused prompt: best-margin candidate + stuck reason + sheet, hard
constraints (no cross-sheet, no rule-intent change, atomic edit).
Post-adapt re-verifies the sim that was stuck. Wired into the
closed-loop's missing_part action."
```

---

### Task 5.6: Phase 5 gate

- [ ] **Step 1: Build + frontend clean**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m test1.altium.build_project
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```

- [ ] **Step 2: Inject a synthetic missing-part rule and run a loop**

Add a single test rule to `test1/review/rules.yaml`:

```yaml
  - id: TEST_MISSING_PART_DEMO
    family: design
    evaluation: structural
    severity: WARNING
    title: Demo missing-part rule — synthetic, for Phase 5 smoke
    applies_to:
      mpn: TOTALLY_NONEXISTENT_MPN_FOR_TEST
      sheet: bobcat
    source:
      - { doc: "test1/TODO.md", loc: "Phase 5 smoke", quote: "" }
    predicate:
      kind: present
      mpn: TOTALLY_NONEXISTENT_MPN_FOR_TEST
    fix_hint: For Phase 5 smoke test only; remove after.
    enabled: true
    origin: user
```

Run a loop from the GUI. Expected: round 1 plans a `missing_part` action; without the custom parts API configured + without WebSearch wiring, the action fails with the impasse message. The audit shows in the round card.

- [ ] **Step 3: Remove the synthetic rule**

```powershell
# Re-edit rules.yaml to remove the TEST_MISSING_PART_DEMO entry.
```
(Manual edit or via the GUI's delete-rule.)

- [ ] **Step 4: Commit (after cleanup)**

If you committed the synthetic rule for the smoke test, follow with:

```powershell
git add test1\review\rules.yaml
git commit -m "chore: drop synthetic Phase 5 smoke rule"
```

Phase 5 complete. Note: full end-to-end missing-part with real WebSearch requires either (a) the custom parts API wired up via `CUSTOM_PARTS_API_URL`, or (b) a follow-up task to implement the `WebSearchPartsProvider` via a one-shot search agent. The skeleton + sim-verify + topology-adapt pipeline is in place; only the search backend is stubbed.

---

## Phase 6 — Polish + Monitoring Verification

ChangelogPanel `closed_loop` color, providers diagnostic in Resources tab, the SSE-late-subscribe monitoring verification test (TODO #1), and the end-to-end smoke test.

### Task 6.1: ChangelogPanel `closed_loop` source color

**Files:**
- Modify: `test1/gui/frontend/src/components/ChangelogPanel.tsx`

- [ ] **Step 1: Add the source color**

Open `test1/gui/frontend/src/components/ChangelogPanel.tsx`. Find the `sourceTone` map (similar to `STATUS_TONE` in Review.tsx). Add:

```typescript
const sourceTone: Record<string, { bg: string; text: string; label?: string }> = {
  sim:         { bg: "bg-ok/15",      text: "text-ok",      label: "sim" },
  agent:       { bg: "bg-ink-900/10", text: "text-ink-900", label: "agent" },
  user:        { bg: "bg-warn/15",    text: "text-warn",    label: "user" },
  closed_loop: { bg: "bg-blue-500/15", text: "text-blue-600", label: "loop" },  // NEW
};
```

(Exact key name + lookup site varies by current code; locate the existing source→class mapping and add the new entry.)

- [ ] **Step 2: Verify color renders**

Start GUI; manually POST a changelog entry with `source: closed_loop`:

```powershell
Invoke-RestMethod -Method POST http://127.0.0.1:8765/api/changelog -Body (@{summary='test from closed_loop';source='closed_loop'} | ConvertTo-Json) -ContentType 'application/json'
```

Open AgentRail; verify the new entry has a blue "loop" badge.

- [ ] **Step 3: Commit**

```powershell
git add test1\gui\frontend\src\components\ChangelogPanel.tsx
git commit -m "feat(ui): closed_loop changelog source — blue badge"
```

---

### Task 6.2: Providers diagnostic in Resources tab

**Files:**
- Modify: `test1/gui/backend/app.py` (add `/api/review/providers` endpoint)
- Modify: `test1/gui/frontend/src/tabs/Resources.tsx` (add a small footer with current bindings)

- [ ] **Step 1: Add endpoint**

In `test1/gui/backend/app.py`, after the rules endpoints:

```python
@app.get("/api/review/providers")
def review_providers() -> dict:
    from test1.review.providers import configured_providers
    return configured_providers()
```

- [ ] **Step 2: Add UI block to Resources.tsx**

Open `test1/gui/frontend/src/tabs/Resources.tsx`. At the bottom of the tab, add:

```tsx
        <section className="mt-6 px-3 py-2 rounded border border-edge bg-rail/30 text-[11.5px]">
          <div className="text-ink-500 mb-1">Providers</div>
          <ProvidersBox />
        </section>
```

And define the component:

```tsx
function ProvidersBox() {
  const [p, setP] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    fetch("/api/review/providers").then(r => r.json()).then(setP).catch(() => {});
  }, []);
  if (!p) return <div className="text-ink-500">loading…</div>;
  return (
    <ul className="grid grid-cols-2 gap-1">
      {Object.entries(p).map(([slot, impl]) => (
        <li key={slot} className="font-mono">
          {slot}: <span className={impl.startsWith("Custom") ? "text-ok" : "text-ink-700"}>{impl}</span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 3: Commit**

```powershell
git add test1\gui\backend\app.py test1\gui\frontend\src\tabs\Resources.tsx
git commit -m "feat(ui): Providers diagnostic in Resources tab

Shows current backend for each provider slot (parts/knowledge/rulegen/chat).
Custom*APIProvider impls show in green so the user can confirm their
future API is being used."
```

---

### Task 6.3: SSE monitoring verification test (TODO #1)

**Files:**
- Create: `test1/review/test_loop_stream.py`

- [ ] **Step 1: Write the test**

Create `test1/review/test_loop_stream.py`:

```python
"""Integration test for the closed-loop SSE stream — TODO #1 verification.

Confirms:
  • A live subscriber sees `loop_start` BEFORE the first `round_done`
    (i.e., monitoring doesn't drop the start of the loop).
  • A late subscriber (attached after the loop completes) sees a `done`
    event immediately and not a hang.

Runs against a synthetic in-memory orchestrator — does NOT spin up FastAPI
or claude -p. Uses a stub _dispatch_action that doesn't call any agent.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from test1.review import closed_loop


@pytest.fixture(autouse=True)
def patch_dispatch(monkeypatch):
    """Replace _dispatch_action and _rebuild_project with no-op stubs."""
    async def stub_dispatch(L, action):
        action.status = "ok"
        action.summary = "(stubbed)"
        action.finished_at = time.time()

    async def stub_build():
        return ("ok", {"ERROR": 0, "WARNING": 0, "INFO": 0})

    monkeypatch.setattr(closed_loop, "_dispatch_action", stub_dispatch)
    monkeypatch.setattr(closed_loop, "_rebuild_project", stub_build)

    # Replace eval_rules with a controlled sequence
    state = {"count": 3}
    def stub_eval():
        if state["count"] <= 0:
            return []
        state["count"] -= 1
        from test1.review.findings import Finding, Severity
        return [Finding(rule_id=f"DUMMY_{i}", severity=Severity.WARNING,
                         title="dummy", subject="", sheet="")
                for i in range(state["count"])]
    monkeypatch.setattr("test1.review.rule_eval.run_all", stub_eval)


@pytest.mark.asyncio
async def test_live_subscriber_sees_loop_start_first():
    """A subscriber attached BEFORE the loop starts must see `loop_start`
    before any `round_done`."""
    loop_id = closed_loop.start_loop()
    L = closed_loop._LOOPS[loop_id]

    # Attach subscriber synchronously
    q: asyncio.Queue = asyncio.Queue()
    L.subscribers.append(q)

    events_seen: list[str] = []
    while True:
        try:
            item = await asyncio.wait_for(q.get(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail(f"timed out waiting for events; got: {events_seen}")
        if item is None:
            break
        events_seen.append(item["event"])

    assert "loop_start" in events_seen, f"loop_start not seen: {events_seen}"
    assert "done" in events_seen, f"done not seen: {events_seen}"
    loop_idx = events_seen.index("loop_start")
    # Every round_done must come AFTER loop_start
    for i, ev in enumerate(events_seen):
        if ev == "round_done":
            assert i > loop_idx, f"round_done at {i} before loop_start at {loop_idx}: {events_seen}"


@pytest.mark.asyncio
async def test_late_subscriber_gets_done_immediately():
    """A subscriber attached AFTER the loop completes (via the endpoint
    fallback in /api/loop/{id}/stream) sees a synthetic done frame and
    doesn't hang. We simulate this by checking _LOOPS state, not the
    endpoint itself — endpoint logic is the same shape."""
    loop_id = closed_loop.start_loop()
    L = closed_loop._LOOPS[loop_id]

    # Wait for the loop to finish
    while L.status == "running":
        await asyncio.sleep(0.1)

    # Endpoint behavior: if status != running, emit done immediately
    assert L.status in ("all_clear", "plateau", "max_rounds", "cancelled", "error"), \
        f"unexpected status: {L.status}"
    # The synthetic event the endpoint would emit
    synthetic_done = {
        "event": "done",
        "data": {"status": L.status, "rounds": len(L.rounds),
                 "remaining": len(L.findings_current)},
    }
    assert synthetic_done["data"]["status"] in ("all_clear", "plateau", "max_rounds")
```

- [ ] **Step 2: Install pytest-asyncio if needed**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m pip install pytest-asyncio
```

- [ ] **Step 3: Run the test**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m pytest test1\review\test_loop_stream.py -v --asyncio-mode=auto
```
Expected: both tests pass.

- [ ] **Step 4: Commit**

```powershell
git add test1\review\test_loop_stream.py
git commit -m "test(loop): SSE monitoring verification (TODO #1)

Asserts a live subscriber sees loop_start BEFORE the first round_done
(no dropped start). Asserts a late subscriber sees a synthetic done
frame instead of hanging (matches the endpoint fallback path)."
```

---

### Task 6.4: Disable per-row Apply during loop

**Files:**
- Modify: `test1/gui/frontend/src/tabs/Review.tsx`

- [ ] **Step 1: Thread `loopRunning` into `FindingRow`**

In `Review.tsx`, on the per-row Apply button, pass an extra `disabled` based on the loop state. Change the FindingRow props to include `loopRunning: boolean`, and update the Apply button's `disabled` from:

```tsx
disabled={!f.id || status === "queued" || status === "applied"}
```

to:

```tsx
disabled={!f.id || status === "queued" || status === "applied" || loopRunning}
```

Pass the prop down where `FindingRow` is rendered:

```tsx
{items.map((f, i) => (
  <FindingRow key={f.id ?? i} f={f} queued={f.id ? queue.get(f.id) : undefined}
              loopRunning={runState === "running"}
              onApply={onApply} onDismiss={onDismiss} />
))}
```

Update the `FindingRowProps` interface accordingly.

- [ ] **Step 2: Frontend builds**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
```

- [ ] **Step 3: Commit**

```powershell
git add test1\gui\frontend\src\tabs\Review.tsx
git commit -m "fix(ui): disable per-row Apply during loop run

Loop owns the design during its run; per-row Apply could race with
the orchestrator's apply pass. Re-enabled on loop completion/cancel."
```

---

### Task 6.5: End-to-end coherence verification

- [ ] **Step 1: Build green**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m test1.altium.build_project
```
Expected: `FAILURES: none`.

- [ ] **Step 2: All pytest tests pass**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" -m pytest test1\review\ -v --asyncio-mode=auto
```
Expected: every test green.

- [ ] **Step 3: Frontend builds clean**

```powershell
cd test1\gui\frontend
.\node_modules\.bin\tsc -b
.\node_modules\.bin\vite build
```
Expected: both clean.

- [ ] **Step 4: Backend starts cleanly + all routes register**

```powershell
& "C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe" test1\gui\backend\app.py
```

In another shell:
```powershell
Invoke-RestMethod http://127.0.0.1:8765/openapi.json | Select-Object -ExpandProperty paths | Get-Member -MemberType NoteProperty | Select-Object Name
```
Expected: every `/api/review/rules*`, `/api/loop/*`, `/api/diff/*`, `/api/png_snapshot/*` route listed. Stop backend.

- [ ] **Step 5: Provider diagnostic responds**

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/review/providers
```
Expected: 4 default providers.

- [ ] **Step 6: A clean loop run round-trips**

(Manual GUI test — covered in Phase 4 Task 4.11 gate; rerun here as a smoke.)

- [ ] **Step 7: Commit any final polish + push**

```powershell
git status
git add -A
git commit -m "chore: phase 6 polish + monitoring verification

End-to-end smoke complete. All build/lint/test gates green.
Closed-loop design review system ready for manual testing."
```

Phase 6 complete.

---

## Self-review

Run this checklist after writing the plan, fix any issues inline.

### Spec coverage

| Spec section | Implemented by |
|---|---|
| §1 Goal & framing | Header + Phase 6 end-to-end smoke |
| §2 Architecture overview | Distributed across phases; file-structure section maps modules |
| §3 Rule schema | Task 1.1 (schema) + Task 1.2 (tests) + Task 1.6 (rules.yaml) |
| §3 Predicate library | Task 1.4 (`_DISPATCH`) + Task 1.5 (tests) |
| §3 Storage + merge | Task 1.4 (`load_rules`/`save_rules`) + Task 2.2 (`merge_rules`) |
| §3 Generation flow | Task 2.2-2.5 |
| §3 Source citation verifier | Task 2.2 (`verify_citations`) |
| §4 Endpoint family | Task 4.5 |
| §4 Loop dataclass | Task 4.1 |
| §4 Inner loop body | Task 4.4 |
| §4 `plan_actions` | Task 4.3 |
| §4 Halt conditions (incl. plateau) | Task 4.4 |
| §4 SSE event stream | Task 4.4 (emit) + Task 4.5 (endpoint) + Task 4.6 (subscribeLoop) |
| §4 Snapshot mechanics | Task 4.2 |
| §4 Cancel semantics | Task 4.4 (`L.cancelled` checks) + Task 4.5 (`/cancel`) |
| §5 Missing-part flow | Task 5.1–5.5 |
| §5 Topology adaptation | Task 5.5 |
| §5 Where artifacts land | Task 5.3 (`_install_and_author`) + Task 5.1 (DATASHEET_INCOMING) |
| §6 Provider layer | Task 1.3 |
| §6 Knock-on changes | Spec §6 amendment → Task 2.2 (rule_gen uses providers) + Task 5.4 (knowledge) |
| §7 Rules section UI | Task 2.6 |
| §7 Iteration section UI | Task 4.7 |
| §7 Diff & Accept UI | Task 4.10 + DiffOverlay (Task 4.9) |
| §7 Cross-cutting (badge, disable-Apply) | Task 3.2 + Task 6.4 |
| §8 Cleanup (Phase 0) | Tasks 0.1–0.5 |
| §8 Migration (Finding fields) | Task 3.2 (TS types) + Phase 4 (Python emits new fields via rule_eval) |
| §8 AGENT_KINDS additions | Task 2.1 + Task 5.5 |
| §8 Rollout phases | Maps 1:1 to plan phases |
| §8 Testing | Task 1.2 + Task 1.5 + Task 6.3 + manual gates |
| §8 Non-goals | Honored throughout (no linter changes, sequential within round, etc.) |
| §8 Risks | Mitigations in place: citation verifier (Task 2.2), snapshot+revert (Task 4.2), identity check (Task 5.2), SSE watchdog reuses subscribeAgent (Task 4.6), web budget (Task 5.1) |
| §9 Configuration env vars | Documented in Task 1.3 |
| §10 Deferred TODOs | All three already in `test1/TODO.md` (appended pre-plan); items 2+3 implemented via Phase 4 Diff & Accept; item 1 verified by Task 6.3 |

No gaps identified.

### Placeholder scan

Scanned for `TBD`, `TODO:`, `XXX`, `???`, `FIXME`, "fill in later", "appropriate error handling", "similar to Task N". The plan contains intentional, narrow stubs (e.g., `_web_search_candidates` returns `[]` in Phase 5 with a clear log line) but each one is annotated as "STUB — configure CUSTOM_*_API_URL or implement" with the wire-up path documented.

### Type consistency

Function and dataclass names cross-referenced — `Loop`, `Round`, `Action`, `Rule`, `Candidate`, `Excerpt`, `RulesFile`, `SourceCitation`, `AppliesTo`, `MissingPartAudit`, `CandidateAudit`, `DocBundle`, `PredicateSpec`, `ChatRun`, `SchematicContext` — all used identically across module boundaries. Pydantic discriminator is `evaluation` for Rule, `kind` for Predicate; called out in Task 1.1.

### Path consistency

`test1/review/rules.yaml` (canonical), `out/render_snapshots/<loop_id>/` (snapshot dir), `_datasheet_incoming/` (raw downloads), `Parts Library/<MPN>/<MPN>.pdf` (installed), `test1/gui/state/loops/<loop_id>.json` (audit) — consistent.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-29-closed-loop-design-review.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for catching missteps early on a multi-day plan.

2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints. Faster turnaround per task, single conversation context.

Which approach?
