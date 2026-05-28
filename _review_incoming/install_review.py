"""Parse Voltai component-review PDFs into the GUI Review-tab findings schema.

Drop the review PDF(s) into `_review_incoming/` and run this. Each PDF is
parsed into structured `Finding` objects that the existing
`test1/review/findings.json` -> `GET /api/findings` -> Review tab pipeline
already consumes — so no GUI changes are needed for the parsed findings to
appear (the upload/apply UX is a separate next pass).

Report layout this parser assumes (per the May 2026 Voltai format):

  Project Report [<project>]
  <email> • <YYYY-MM-DD HH:MM:SS>
  FILTERED EXPORT <filter>        ← optional banner
  TABLE OF CONTENTS
  • <component>                   ← list of component scopes
  <component>                     ← component section
  <Category Name>                 ← e.g. "Pin Connectivity ..."
  FAIL (n)                        ← severity + raw count
    <rule statement>
    RULE EXPLANATION
    <prose>
    REVIEW DETAILS
    <prose lead>
    • <bullet> — <body>
    ...
    [next finding in this category — many are verbatim duplicates]
    ✓ Action Items
    • **Fix —**  <suggested fix>
    • **Alt —**  <alternative>
    • **Verify —** <verification step>

Dedup key is `(component, category, rule)` because the source tool fires each
rule 3-5 times with identical text. The Action Items list belongs to the
category and is attached to every finding in that category.

Severity mapping: FAIL -> ERROR, WARN -> WARNING, PASS -> INFO.

Inline structured tags (`@P:pin`, `@D:device`, `@N:net`, `@G:ground`,
`@PO:power_obj`) are extracted into `refs[]` so the GUI can filter/link.

Run:  python install_review.py                # parses every PDF in this folder
      python install_review.py <file.pdf>     # parses just one
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz  # PyMuPDF (in the spike venv)

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent / "test1"
FINDINGS_JSON = PROJECT / "review" / "findings.json"
PROCESSED_DIR = HERE / "_processed"

# FAIL/WARN/PASS line at the top of a category, e.g. "FAIL (18)"
SEV_HEADER_RE = re.compile(r"^(FAIL|WARN|WARNING|PASS|INFO)\s*\((\d+)\)\s*$")
SEV_MAP = {"FAIL": "ERROR", "WARN": "WARNING", "WARNING": "WARNING",
           "PASS": "INFO", "INFO": "INFO"}

# Inline structured tags: @P:U41.OUTB, @D:U41, @N:Net_+3V3, @G:GND, @PO:+3V3
TAG_RE = re.compile(r"@(P|D|N|G|PO):([A-Za-z0-9_+.\-]+)")

# Action items start after this marker (the ✓ glyph extracts as a checkmark
# in fitz — make it optional so we match on the literal "Action Items" anchor)
ACTION_HEAD_RE = re.compile(r"(?:✓\s*)?Action Items\s*$", re.IGNORECASE)

# Action lines: "**Fix —**  body" or "Fix —  body" (PDF rendering varies)
ACTION_LINE_RE = re.compile(
    r"^\s*[*•\-]*\s*\*{0,2}(Fix|Alt|Verify)\s*[—\-:]\s*\*{0,2}\s*(.+?)\s*$",
    re.IGNORECASE,
)

# Major boilerplate that mustn't be confused with categories
BOILERPLATE = {
    "TABLE OF CONTENTS", "RULE EXPLANATION", "REVIEW DETAILS",
    "PROJECT REPORT", "FILTERED EXPORT", "ACTION ITEMS",
}


@dataclass
class Action:
    kind: str        # "fix" | "alt" | "verify"
    text: str


@dataclass
class Finding:
    id: str                                       # stable hash of dedup key
    severity: str                                 # ERROR | WARNING | INFO
    component: str                                # e.g. "U41"
    category: str                                 # e.g. "Pin Connectivity ..."
    rule: str                                     # the shall/imperative line
    message: str                                  # short summary (first sentence)
    detail: str                                   # RULE EXPLANATION + REVIEW DETAILS
    refs: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    fix_hint: str = ""                            # first Fix action, for the
                                                  # existing Review-tab schema
    source: str = "voltai-review"
    source_pdf: str = ""
    fired_count: int = 1                          # how many times the source
                                                  # tool emitted this finding
    status: str = "pending"                       # pending | applied | dismissed


def _extract_text(pdf_path: Path) -> str:
    """Page-joined plain text with explicit page separators dropped (the
    'Page N of M' footers are noise for parsing)."""
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        t = page.get_text()
        # Drop "Page N of M" footers/headers that fitz extracts.
        t = re.sub(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", "",
                   t, flags=re.MULTILINE)
        pages.append(t)
    doc.close()
    return "\n".join(pages)


def _refs_from(*texts: str) -> list[str]:
    """Extract every @X:value tag from the given texts, dedup, preserve
    first-seen order."""
    seen: list[str] = []
    for t in texts:
        for _kind, val in TAG_RE.findall(t):
            if val not in seen:
                seen.append(val)
    return seen


def _dedup_id(component: str, category: str, rule: str) -> str:
    h = hashlib.sha1(f"{component}|{category}|{rule}".encode()).hexdigest()
    return h[:12]


# A "bullet line" inside REVIEW DETAILS looks like "Label words — body". The
# label is 1-6 capitalized/lowercase words, separated by " — " (em-dash) from
# the body. We use this to know where the rule statement ends and bullets begin.
BULLET_LINE_RE = re.compile(r"^[A-Z][A-Za-z][A-Za-z /+\-]{1,60}\s+[—\-]\s+")

# Lines that BEGIN a rule statement. Rules in this report always open with
# either a structured tag (`@P:`, `@D:`, `@N:`, `@G:`, `@PO:`) or one of a
# small set of canonical conditional/imperative openers ("If ", "Any ", "All ",
# "When ", "Each ", "Pin ", "Channel ", "The ", "At ", "For ", "No ").
RULE_START_RE = re.compile(
    r"^(?:@[A-Z]{1,2}:|If\s|Any\s|All\s|When\s|Each\s|Pin\s|Channel\s|"
    r"The\s|At\s|For\s|No\s|Every\s)"
)

# A "component header" is a compact refdes-like token alone on a line (e.g.
# "U41", "Q40", "R10"). Used both for TOC parsing and to identify the
# component scope above each category heading.
COMPONENT_LINE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,8}$")


def _split_components(text: str, project: str) -> dict[str, list[str]]:
    """Split the report into per-component sections.

    Strategy: find every "component header" (refdes-like line) AFTER the
    TABLE OF CONTENTS. The first occurrence of each refdes inside the TOC is
    a bullet; subsequent occurrences delimit that component's section.
    Falls back to one bucket keyed by project name if no headers are found.
    """
    lines = text.split("\n")
    toc_idx = next((i for i, ln in enumerate(lines)
                    if ln.strip().upper() == "TABLE OF CONTENTS"), -1)
    if toc_idx < 0:
        return {project: lines}

    # Walk forward from TOC to collect bullet refdes lines until we hit a
    # line that doesn't look like a bullet (a category-name or blank).
    toc_bullets: list[str] = []
    i = toc_idx + 1
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if COMPONENT_LINE_RE.match(s):
            toc_bullets.append(s)
            i += 1
            continue
        break
    if not toc_bullets:
        return {project: lines}

    # The TOC itself contains the FIRST occurrence of each refdes; component
    # SECTIONS start at the SECOND occurrence.
    section_starts: list[tuple[str, int]] = []
    seen_first: dict[str, bool] = {b: False for b in toc_bullets}
    for j, ln in enumerate(lines[toc_idx + 1:], start=toc_idx + 1):
        s = ln.strip()
        if s in seen_first:
            if not seen_first[s]:
                seen_first[s] = True  # first hit = TOC bullet, skip
            else:
                section_starts.append((s, j))
                seen_first[s] = False  # tolerate a 3rd if it appears
    if not section_starts:
        return {project: lines}

    out: dict[str, list[str]] = {}
    for k, (comp, start) in enumerate(section_starts):
        end = section_starts[k + 1][1] if k + 1 < len(section_starts) else len(lines)
        out[comp] = lines[start + 1:end]   # skip the header line itself
    return out


def _split_categories(lines: list[str]) -> list[tuple[str, str, int, list[str]]]:
    """Yield (category_name, severity, raw_count, body_lines) for each
    FAIL/WARN/PASS group inside a component section.

    A category is the line directly preceding a `FAIL (n)` / `WARN (n)` /
    `PASS (n)` line. Body runs from after the severity header to before the
    next category's name line.
    """
    sev_idxs: list[tuple[int, str, int]] = []
    for i, ln in enumerate(lines):
        m = SEV_HEADER_RE.match(ln.strip())
        if m:
            sev_idxs.append((i, SEV_MAP[m.group(1).upper()], int(m.group(2))))

    out: list[tuple[str, str, int, list[str]]] = []
    for j, (sev_i, sev, n) in enumerate(sev_idxs):
        # Category name = the closest non-blank, non-boilerplate line above.
        cat = ""
        k = sev_i - 1
        while k >= 0:
            s = lines[k].strip()
            if s and s.upper() not in BOILERPLATE and not SEV_HEADER_RE.match(s):
                cat = s
                break
            k -= 1
        # Body end = the line just before the NEXT category's name line, OR
        # the end of section.
        if j + 1 < len(sev_idxs):
            next_sev_i = sev_idxs[j + 1][0]
            end = next_sev_i - 1
            while end > sev_i and not lines[end].strip():
                end -= 1
            # `end` now points at the next category's name; trim before it.
        else:
            end = len(lines)
        out.append((cat, sev, n, lines[sev_i + 1:end]))
    return out


def _split_actions(body_lines: list[str]) -> tuple[list[str], list[Action]]:
    """Pull the trailing 'Action Items' block out of a category body.
    Returns (body_without_actions, actions)."""
    cut = None
    for i, ln in enumerate(body_lines):
        if ACTION_HEAD_RE.match(ln.strip()):
            cut = i
            break
    if cut is None:
        return body_lines, []
    actions: list[Action] = []
    for ln in body_lines[cut + 1:]:
        m = ACTION_LINE_RE.match(ln)
        if m:
            kind = m.group(1).lower()
            text = m.group(2).strip()
            # Strip stray asterisks left over from "**Fix —**" markup.
            text = text.lstrip("*").rstrip("*").strip()
            if text:
                actions.append(Action(kind=kind, text=text))
    return body_lines[:cut], actions


def _split_findings(body_lines: list[str], component: str, category: str,
                    severity: str, actions: list[Action],
                    source_pdf: str) -> list[Finding]:
    """Within a category body, split on the 'RULE EXPLANATION' line. For
    each occurrence, the rule statement is the contiguous run of non-bullet
    non-blank lines immediately preceding it; the detail is everything from
    that line through the next RULE EXPLANATION (or end-of-body)."""
    rex_idxs = [i for i, ln in enumerate(body_lines)
                if ln.strip() == "RULE EXPLANATION"]
    if not rex_idxs:
        return []
    findings: list[Finding] = []
    for k, rex_i in enumerate(rex_idxs):
        # Find the rule START by walking back from rex_i to the closest line
        # that matches RULE_START_RE. Then collect from there to rex_i - 1
        # (skipping blanks) and join — that is the rule statement, which can
        # span 1-3 wrapped lines.
        rule_start = None
        for j in range(rex_i - 1, -1, -1):
            s = body_lines[j].strip()
            if RULE_START_RE.match(s):
                rule_start = j
                break
            if BULLET_LINE_RE.match(s) or s.upper() in BOILERPLATE:
                # We've walked past where the rule should be; abort to avoid
                # misattribution.
                break
        if rule_start is None:
            continue
        rule_lines = [body_lines[j].strip() for j in range(rule_start, rex_i)
                      if body_lines[j].strip()]
        rule = re.sub(r"\s+", " ", " ".join(rule_lines)).strip()
        # Detail body: RULE EXPLANATION line through (next RULE EXPLANATION
        # or end-of-body).
        detail_end = rex_idxs[k + 1] if k + 1 < len(rex_idxs) else len(body_lines)
        # Trim trailing lines that belong to the NEXT finding's rule.
        # The next rule starts at the first non-bullet line walking back
        # from detail_end (same logic as above, mirrored).
        if k + 1 < len(rex_idxs):
            # Strip the next finding's rule lines from the end.
            t = detail_end - 1
            while t > rex_i and body_lines[t].strip() \
                  and not BULLET_LINE_RE.match(body_lines[t].strip()):
                t -= 1
            detail_end = t + 1
        detail = "\n".join(body_lines[rex_i:detail_end]).strip()
        msg = rule.split(". ")[0].rstrip(".") + "." if rule else ""
        refs = _refs_from(rule, detail)
        if component not in refs:
            refs.insert(0, component)
        fid = _dedup_id(component, category, rule)
        fix_hint = next((a.text for a in actions if a.kind == "fix"), "")
        findings.append(Finding(
            id=fid, severity=severity, component=component, category=category,
            rule=rule, message=msg, detail=detail, refs=refs,
            actions=list(actions), fix_hint=fix_hint, source_pdf=source_pdf,
        ))
    return findings


def _dedup_findings(findings: list[Finding]) -> list[Finding]:
    """Collapse duplicates (same id) and bump `fired_count`."""
    by_id: dict[str, Finding] = {}
    for f in findings:
        if f.id in by_id:
            by_id[f.id].fired_count += 1
        else:
            by_id[f.id] = f
    return list(by_id.values())


def parse_report(pdf_path: Path) -> dict:
    """Parse one PDF into the findings.json shape the Review tab expects."""
    text = _extract_text(pdf_path)
    # Pull project name from the title, e.g. "Project Report [test1_schdoc]".
    m = re.search(r"Project Report\s*\[([^\]]+)\]", text)
    project = m.group(1) if m else pdf_path.stem
    components = _split_components(text, project)
    all_findings: list[Finding] = []
    for comp, comp_lines in components.items():
        for (cat, sev, _n, body_lines) in _split_categories(comp_lines):
            if not cat:
                continue
            body_no_actions, actions = _split_actions(body_lines)
            f_list = _split_findings(body_no_actions, comp, cat, sev,
                                     actions, pdf_path.name)
            all_findings.extend(f_list)
    all_findings = _dedup_findings(all_findings)

    summary = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for f in all_findings:
        summary[f.severity] = summary.get(f.severity, 0) + 1
    return {
        "project": project,
        "source_pdf": pdf_path.name,
        "findings": [_finding_json(f) for f in all_findings],
        "semantic": [],
        "summary": summary,
    }


def _finding_json(f: Finding) -> dict:
    """Serialise a Finding to the existing review-tab dict shape (plus the
    new fields the Apply-fix UX will read once the GUI is extended)."""
    d = asdict(f)
    d["actions"] = [asdict(a) for a in f.actions]
    return d


def main(argv: list[str]) -> int:
    if argv:
        pdfs = [Path(a) for a in argv]
    else:
        pdfs = sorted(p for p in HERE.iterdir()
                      if p.is_file() and p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"no PDFs in {HERE} (drop the review PDF here and rerun)")
        return 0

    # Merge findings across all PDFs (each PDF can be one or many components).
    merged: dict = {"project": "", "findings": [], "semantic": [],
                    "summary": {"ERROR": 0, "WARNING": 0, "INFO": 0},
                    "sources": []}
    for pdf in pdfs:
        rep = parse_report(pdf)
        if not merged["project"]:
            merged["project"] = rep["project"]
        merged["findings"].extend(rep["findings"])
        merged["sources"].append(rep["source_pdf"])
        for sev, n in rep["summary"].items():
            merged["summary"][sev] = merged["summary"].get(sev, 0) + n

    FINDINGS_JSON.parent.mkdir(parents=True, exist_ok=True)
    FINDINGS_JSON.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    # Move processed PDFs out of the drop folder so the next run is clean.
    # If a same-named file already exists in _processed/, overwrite it so a
    # rerun with the same PDF doesn't crash.
    PROCESSED_DIR.mkdir(exist_ok=True)
    for pdf in pdfs:
        if pdf.is_relative_to(HERE):
            dest = PROCESSED_DIR / pdf.name
            if dest.exists():
                dest.unlink()
            pdf.rename(dest)

    s = merged["summary"]
    print(f"parsed {len(pdfs)} PDF(s) -> {FINDINGS_JSON}")
    print(f"  {len(merged['findings'])} unique findings  "
          f"({s['ERROR']}E / {s['WARNING']}W / {s['INFO']}I)")
    for f in merged["findings"][:5]:
        print(f"  [{f['severity']}] {f['component']} :: {f['category']}")
        print(f"           {f['rule'][:90]}")
    if len(merged["findings"]) > 5:
        print(f"  ... +{len(merged['findings']) - 5} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
