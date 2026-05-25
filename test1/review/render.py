"""Phase 3: emit error_log.md (latest snapshot) + review_history/<ts>.md.

Stable IDs:
  Within a run, findings are sorted by (severity, rule_id, subject) and
  numbered E1..En / W1..Wn / I1..In. Two runs that find the same set
  of (rule_id, subject) pairs produce the same ordinals — so git diff
  on error_log.md shows new/closed findings, not noise.

Independent-reviewer / autocorrector contract:
  - error_log.md is the LATEST snapshot. Always present, always overwritten.
  - review_history/<YYYY-MM-DD_HHMM>.md is the append-only audit trail.
  - Each finding includes a `Fix:` line phrased as a concise imperative
    so the autofix dispatcher (or a human) can act on it directly.
"""

from __future__ import annotations

import datetime as _dt
import json
from collections import defaultdict
from pathlib import Path

from .findings import Finding, Severity

PROJECT_DIR = Path(__file__).resolve().parent.parent
ERROR_LOG_PATH = PROJECT_DIR / "error_log.md"
HISTORY_DIR = PROJECT_DIR / "review_history"


def _assign_ordinals(findings: list[Finding]) -> list[tuple[str, Finding]]:
    """Return [(ordinal, finding), …] sorted by severity then stable_key."""
    by_sev: dict[Severity, list[Finding]] = defaultdict(list)
    for f in findings:
        by_sev[f.severity].append(f)
    ordered: list[tuple[str, Finding]] = []
    for sev, prefix in (
        (Severity.ERROR, "E"),
        (Severity.WARNING, "W"),
        (Severity.INFO, "I"),
    ):
        bucket = sorted(by_sev[sev], key=lambda f: f.stable_key())
        for i, f in enumerate(bucket, start=1):
            ordered.append((f"{prefix}{i}", f))
    return ordered


def _section(findings_with_ids: list[tuple[str, Finding]],
             severity: Severity, header: str) -> str:
    rows = [(oid, f) for oid, f in findings_with_ids if f.severity == severity]
    if not rows:
        return f"## {header}\n\n*(none)*\n"
    out = [f"## {header}\n"]
    for oid, f in rows:
        out.append(f"### {oid}. {f.title}")
        out.append("")
        if f.component_refs:
            out.append(f"**Component(s):** {', '.join(f.component_refs)} "
                       f"(sheet: `{f.sheet}`)")
        if f.requirement_ref:
            out.append(f"**Requirement:** {f.requirement_ref}")
        if f.datasheet_ref:
            out.append(f"**Datasheet:** {f.datasheet_ref}")
        if f.observed:
            out.append(f"**Observed:** {f.observed}")
        if f.impact:
            out.append(f"**Impact:** {f.impact}")
        if f.fix:
            out.append(f"**Fix:** {f.fix}")
        out.append(f"<sub>rule: `{f.rule_id}` · subject: `{f.subject}` · "
                   f"autofix: `{f.autofix}`</sub>")
        out.append("")
    return "\n".join(out)


def _summary(findings: list[Finding]) -> str:
    n_e = sum(1 for f in findings if f.severity == Severity.ERROR)
    n_w = sum(1 for f in findings if f.severity == Severity.WARNING)
    n_i = sum(1 for f in findings if f.severity == Severity.INFO)
    return f"- **{n_e} ERRORs** · **{n_w} WARNINGs** · **{n_i} INFOs**"


def render(findings: list[Finding],
           reviewed_against: list[str] | None = None) -> str:
    """Compose the full error_log.md markdown body."""
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    findings_with_ids = _assign_ordinals(findings)
    parts = [
        "# Design Review Error Log — test1 (Bobcat Carrier Board)",
        "",
        f"Generated: {now}",
        "",
    ]
    if reviewed_against:
        parts.append("Reviewed against:")
        parts.extend(f"- {r}" for r in reviewed_against)
        parts.append("")
    parts.append("## Summary")
    parts.append("")
    parts.append(_summary(findings))
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(_section(findings_with_ids, Severity.ERROR,
                          "ERRORs (must fix)"))
    parts.append("---")
    parts.append("")
    parts.append(_section(findings_with_ids, Severity.WARNING,
                          "WARNINGs (should fix)"))
    parts.append("---")
    parts.append("")
    parts.append(_section(findings_with_ids, Severity.INFO, "INFOs"))
    return "\n".join(parts).rstrip() + "\n"


def write(findings: list[Finding],
          reviewed_against: list[str] | None = None) -> tuple[Path, Path]:
    """Write both error_log.md and a timestamped history file. Returns paths."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    body = render(findings, reviewed_against)
    ERROR_LOG_PATH.write_text(body)
    ts = _dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    hist = HISTORY_DIR / f"{ts}.md"
    hist.write_text(body)
    return ERROR_LOG_PATH, hist


def write_json(findings: list[Finding], path: Path) -> None:
    """Dump findings as JSON for the autofix dispatcher to consume."""
    payload = []
    for f in findings:
        payload.append({
            "rule_id": f.rule_id,
            "severity": f.severity.value,
            "title": f.title,
            "subject": f.subject,
            "sheet": f.sheet,
            "component_refs": f.component_refs,
            "requirement_ref": f.requirement_ref,
            "datasheet_ref": f.datasheet_ref,
            "observed": f.observed,
            "impact": f.impact,
            "fix": f.fix,
            "autofix": f.autofix,
            "autofix_data": f.autofix_data,
        })
    path.write_text(json.dumps(payload, indent=2))
