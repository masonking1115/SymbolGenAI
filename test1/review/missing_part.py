"""Missing-part flow — strenuous part selection, sim-verification gate,
topology-adaptation fallback.

Triggered by Action(kind='missing_part'). One action handles one missing
part. Provider-backed: parts_provider().search(...) for candidates +
knowledge_provider().query(...) for datasheet extracts.

Spec section 5 (in design doc).
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
        # Hard constraints: every numeric *_min in role_spec must be <= candidate's param
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
        import fitz  # PyMuPDF
        doc = fitz.open(pdf)
        text_parts: list[str] = []
        for i in range(min(3, doc.page_count)):
            text_parts.append(doc[i].get_text() or "")
        text = "\n".join(text_parts)
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
