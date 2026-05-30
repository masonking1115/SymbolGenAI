"""Rule generation — reads project docs, dispatches the rule_gen agent
(via rulegen_provider()), validates output, merges with user-origin rules,
writes test1/review/rules.yaml.

Flow per /api/review/rules/generate:
  1. Build DocBundle from design_requirements.md + every datasheet PDF
     + the Bobcat PDF + every URL embedded in the requirements doc.
  2. Build PredicateSpec from rule_schema's predicate variants.
  3. Call rulegen_provider().generate(bundle, spec, existing_user_rules).
  4. Validate output (Rule.model_validate); retry up to 2x on failure.
  5. Verify each rule's source.quote is a substring of the cited doc.
  6. Merge with existing user-origin rules; write rules.yaml.

Spec section 3 generation flow.

Two entry points:
  - ``generate_and_write()`` -- legacy SYNCHRONOUS path used by tests + any
    scripted caller. Awaits the whole pipeline + returns the final result.
  - ``start_generate_job()`` -- BACKGROUND path used by the GUI. Returns a
    ``job_id`` immediately; the job emits phase events (bundle / dispatch /
    validate / merge / write / done) to SSE subscribers, mirroring
    ``closed_loop._LOOPS`` so the frontend can show a live pipeline strip
    + the dispatched agent's console.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from .providers import DocBundle, PredicateSpec, rulegen_provider
from .rule_schema import Rule, RulesFile, SourceSeen

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
    description. The generator MAY ONLY emit kinds from this list - that
    keeps evaluation deterministic and auditable."""
    return PredicateSpec(kinds=[
        {"kind": "decoupling_count",
         "description": ">=N caps on the net(s) shared by refdes.<pins>",
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
        # Substring match - normalize whitespace
        norm = " ".join(doc_text.split()).lower()
        quote_norm = " ".join(cit.quote.split()).lower()
        if quote_norm not in norm:
            return False, f"quote not found in '{cit.doc}': {cit.quote[:60]!r}"
    return True, ""


# ---- Merge -------------------------------------------------------------

def merge_rules(existing: list[Rule], candidates: list[Rule]) -> tuple[list[Rule], list[dict]]:
    """user-origin survives. id collision between user + generated -> keep user,
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

EmitCb = Callable[[str, dict], Awaitable[None]]


async def _dispatch_rule_gen_agent(
    bundle: DocBundle,
    spec: PredicateSpec,
    existing_user_rules: list[Rule],
    emit_cb: EmitCb | None = None,
) -> list[Rule]:
    """Write inputs to a tempdir, dispatch the rule_gen agent, parse + validate
    the agent's JSON output. Retries up to 3x on validation failure.

    When ``emit_cb`` is provided, emits a ``dispatch`` event with the agent's
    ``run_id`` + attempt number as soon as ``start_rule_gen`` returns -- so a
    live UI can subscribe to the agent's stream immediately. Errors per
    attempt are emitted as ``dispatch_attempt_failed``.
    """
    sys.path.insert(0, str(PROJECT_DIR / "gui" / "backend"))
    import agent as agent_mod                      # noqa: PLC0415

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

    last_error = ""
    for attempt in range(3):
        run = await agent_mod.start_rule_gen(bundle_path, spec_path,
                                             user_path, out_path)
        if emit_cb is not None:
            await emit_cb("dispatch", {
                "agent_run_id": run.run_id,
                "attempt": attempt + 1,
                "max_attempts": 3,
            })
        # Wait for completion - poll the run status
        while run.status == "running":
            await asyncio.sleep(0.5)
        if run.status != "ok" or not out_path.exists():
            last_error = (f"agent run status={run.status}, "
                          f"output present={out_path.exists()}")
            if emit_cb is not None:
                await emit_cb("dispatch_attempt_failed",
                              {"attempt": attempt + 1, "reason": last_error})
            continue
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            from pydantic import TypeAdapter            # noqa: PLC0415
            rules_adapter = TypeAdapter(list[Rule])
            rules = rules_adapter.validate_python(data.get("rules", []))
            return rules
        except Exception as e:
            last_error = f"validation: {e}"
            if emit_cb is not None:
                await emit_cb("dispatch_attempt_failed",
                              {"attempt": attempt + 1, "reason": last_error})
            continue

    raise RuntimeError(f"rule_gen agent failed after 3 attempts: {last_error}")


async def _claude_generate(bundle: DocBundle, spec: PredicateSpec,
                           existing_user_rules: list[Rule]) -> list[Rule]:
    """Default RuleGenProvider impl. Thin wrapper around
    ``_dispatch_rule_gen_agent`` with no emit_cb -- preserves the legacy
    interface that ClaudeRuleGenProvider depends on."""
    return await _dispatch_rule_gen_agent(bundle, spec, existing_user_rules,
                                          emit_cb=None)


# ---- Shared post-dispatch pipeline (validate + merge + write) ----------

def _verify_and_merge(
    candidates: list[Rule],
    existing: list[Rule],
    bundle: DocBundle,
) -> tuple[list[Rule], list[dict], list[dict]]:
    """Verify citations, then merge with user-origin rules. Returns
    (merged_rules, conflicts, rejected_unverifiable)."""
    verified: list[Rule] = []
    rejected: list[dict] = []
    for r in candidates:
        ok, reason = verify_citations(r, bundle)
        if ok:
            verified.append(r)
        else:
            rejected.append({"id": r.id, "reason": reason})
    merged, conflicts = merge_rules(existing, verified)
    return merged, conflicts, rejected


def _write_rules_and_summarize(merged: list[Rule], conflicts: list[dict],
                                rejected: list[dict]) -> dict:
    """Persist rules.yaml + return the result dict shared by both paths."""
    rf = RulesFile(
        version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sources_seen=_sources_seen(),
        rules=merged,
    )
    from .rule_eval import save_rules                  # noqa: PLC0415
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


# ---- Top-level entrypoint (legacy synchronous path) --------------------

async def generate_and_write() -> dict:
    """Synchronous one-shot path: bundle → provider.generate → verify →
    merge → write. Returns {count_total, count_by_family, conflicts,
    rejected_unverifiable, sources_seen}.

    Used by tests / scripted callers. The GUI now uses
    :func:`start_generate_job` (background + SSE phase stream) instead.
    """
    bundle = build_doc_bundle()
    spec = build_predicate_spec()
    from .rule_eval import load_rules                   # noqa: PLC0415
    existing = load_rules().rules
    user_rules = [r for r in existing if r.origin == "user"]

    provider = rulegen_provider()
    candidates = await provider.generate(bundle, spec, user_rules)

    merged, conflicts, rejected = _verify_and_merge(candidates, existing,
                                                    bundle)
    return _write_rules_and_summarize(merged, conflicts, rejected)


# ---- Background-job machinery (GUI path) ===============================
#
# Mirrors ``closed_loop._LOOPS`` -- in-process registry + an SSE-friendly
# subscriber queue per job. State is lost on backend restart, which is fine:
# rule generation is short-lived and the on-disk rules.yaml is the durable
# artifact. The latest finished job is also discoverable via the result on
# the in-memory ``_JOBS`` dict for ~5 s while the UI is auto-refreshing.


PHASES = ("bundle", "dispatch", "validate", "merge", "write", "done", "error")


@dataclass
class RuleGenJob:
    job_id: str
    started_at: float
    phase: str = "bundle"          # one of PHASES
    status: str = "running"        # "running" | "ok" | "fail"
    agent_run_id: str | None = None
    result: dict | None = None
    error: str = ""
    finished_at: float | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)


_JOBS: dict[str, RuleGenJob] = {}


def get_job(job_id: str) -> RuleGenJob | None:
    return _JOBS.get(job_id)


def latest_job_id() -> str | None:
    if not _JOBS:
        return None
    return max(_JOBS.keys(), key=lambda jid: _JOBS[jid].started_at)


def job_summary(J: RuleGenJob) -> dict:
    """Wire-format snapshot for /api/review/rules/generate/{job_id}."""
    return {
        "job_id": J.job_id,
        "phase": J.phase,
        "status": J.status,
        "agent_run_id": J.agent_run_id,
        "result": J.result,
        "error": J.error,
        "started_at": J.started_at,
        "finished_at": J.finished_at,
    }


async def emit_job(J: RuleGenJob, event: str, **data) -> None:
    """Fan-out an SSE event to every subscriber queue. Drops on slow consumers
    (matches ``closed_loop.emit``)."""
    payload = {"event": event, "data": data}
    for q in list(J.subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def _run_job(J: RuleGenJob) -> None:
    """Background runner. Emits one event per phase boundary so the UI can
    light up the corresponding pipeline step. On success, the final ``done``
    event carries the same result dict that :func:`generate_and_write`
    returns; on failure, an ``error`` event carries the message + traceback."""
    try:
        # Phase 1: bundle docs.
        J.phase = "bundle"
        await emit_job(J, "bundle")
        bundle = build_doc_bundle()
        spec = build_predicate_spec()
        from .rule_eval import load_rules                # noqa: PLC0415
        existing = load_rules().rules
        user_rules = [r for r in existing if r.origin == "user"]
        await emit_job(J, "bundle_done",
                       datasheets=len(bundle.datasheet_texts),
                       urls=len(bundle.url_texts),
                       user_rules=len(user_rules))

        # Phase 2: dispatch the rule_gen agent (with retries). We use an
        # emit_cb so the agent_run_id surfaces to subscribers AS SOON as the
        # agent starts -- the frontend then subscribes to its console.
        J.phase = "dispatch"
        await emit_job(J, "dispatch")

        async def _on_agent_event(ev: str, data: dict) -> None:
            if ev == "dispatch" and "agent_run_id" in data:
                J.agent_run_id = data["agent_run_id"]
            await emit_job(J, ev, **data)

        candidates = await _dispatch_rule_gen_agent(
            bundle, spec, user_rules, emit_cb=_on_agent_event)

        # Phase 3: verify citations.
        J.phase = "validate"
        await emit_job(J, "validate", candidates=len(candidates))
        merged, conflicts, rejected = _verify_and_merge(candidates, existing,
                                                        bundle)
        await emit_job(J, "validate_done",
                       verified=len(candidates) - len(rejected),
                       rejected=len(rejected))

        # Phase 4: merge with user-origin rules.
        J.phase = "merge"
        await emit_job(J, "merge", conflicts=len(conflicts))

        # Phase 5: write rules.yaml.
        J.phase = "write"
        await emit_job(J, "write", rules=len(merged))
        result = _write_rules_and_summarize(merged, conflicts, rejected)

        # Done.
        J.phase = "done"
        J.status = "ok"
        J.result = result
        await emit_job(J, "done", **result)

    except Exception as e:
        J.phase = "error"
        J.status = "fail"
        J.error = str(e)
        await emit_job(J, "error",
                       message=str(e), traceback=traceback.format_exc())
    finally:
        J.finished_at = time.time()
        # Sentinel — closes every active SSE stream.
        for q in list(J.subscribers):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass


def start_generate_job() -> str:
    """Allocate a new RuleGenJob, register it, kick off the background runner,
    and return the job_id immediately. Subscribe to
    ``/api/review/rules/generate/{job_id}/stream`` for live phase events."""
    job_id = uuid.uuid4().hex[:8]
    J = RuleGenJob(job_id=job_id, started_at=time.time())
    _JOBS[job_id] = J
    asyncio.create_task(_run_job(J))
    return job_id
