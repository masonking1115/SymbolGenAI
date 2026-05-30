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
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path

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

async def _claude_generate(bundle: DocBundle, spec: PredicateSpec,
                           existing_user_rules: list[Rule]) -> list[Rule]:
    """Default RuleGenProvider impl - dispatches the rule_gen agent.
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
