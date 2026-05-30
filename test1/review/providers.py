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
