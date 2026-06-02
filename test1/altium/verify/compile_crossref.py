"""Cross-reference Altium's compile violations against our own layout-lint, so we
can see whether our pipeline PREDICTS Altium's compile result -- and surface the
Altium error CLASSES our lint does not yet catch (candidate new rules).

Inputs (both already produced by the existing flow; no fragile scripting API):
  - Altium's Messages export: out/MessageListReport.html  (File > right-click
    Messages panel > Export, or the OutJob "Report Outputs"). Has the full text.
  - Our lint: out/lint.json  (written by build_project every build).

What it does:
  1. Parse Altium messages -> (severity, document, source, message).
  2. Classify each into a CLASS (the message with refs/coords stripped) so e.g.
     "Net +VDDA1 has only one pin (Pin J11-2)" -> "Net <net> has only one pin".
  3. Map each Altium class to the lint rule that would catch it (KNOWN_MAP), and
     report:
       - classes our lint ALREADY mirrors (good: pipeline predicts Altium),
       - Altium classes with NO lint rule yet (candidate rules to add),
       - lint rules with no corresponding Altium error this run (info).

    python -m test1.altium.verify.compile_crossref [MessageListReport.html] [lint.json]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from ..config import OUT_DIR

# Altium message CLASS (regex on the normalized text) -> our lint rule id (or None
# if we intentionally don't mirror it, e.g. footprints = no PCB lib in this flow).
# This is the living "common compile errors -> rules" table the user asked for.
# Patterns match EITHER the per-instance Long string (Messages-panel export, e.g.
# "Net X has only one pin (Pin Y)") OR the class-level Short string from
# IViolation.DM_ShortDescriptorString (headless altium_compile export, e.g.
# "Nets with only one pin", "Missing component models"). Keep both wordings.
KNOWN_MAP: list[tuple[str, str | None, str]] = [
    (r"has only one pin|Nets with only one pin",
                                           "single_pin_net",        "single-pin net"),
    (r"contains floating input pins|floating input",
                                           "single_pin_net",        "floating input"),
    (r"Off[- ]?grid",                      "off_grid",              "off-grid object/port"),
    (r"multiple drivers|Output Port and Bidirectional|Nets with multiple drivers",
                                           "port_direction_conflict", "port direction / multi-driver"),
    (r"Output Port and .* Port objects",  "port_direction_conflict", "port IO conflict"),
    (r"Power Pin and Input Port",         None,                    "power-pin meets port (benign here)"),
    (r"no driving source|Nets with no driving source",
                                           None,                    "no driver (follows single-pin)"),
    (r"unused sub-part|Unused sub-part in component",
                                           None,                    "multi-unit partial use (accepted)"),
    (r"Footprint .* cannot be found|Missing component models|Component .* has no model",
                                           None,                    "no PCB footprint/model lib (schematic-only flow)"),
    (r"Unconnected (Pin|Port)",            "single_pin_net",        "unconnected pin/port"),
    (r"Duplicate",                         None,                    "duplicate (review case-by-case)"),
]


def _norm(msg: str) -> str:
    """Strip refdes/pin/coords so messages collapse to a CLASS."""
    s = msg
    s = re.sub(r"\(Pin [^)]*\)", "", s)
    s = re.sub(r"\bat \d+mil,\d+mil\b", "", s)
    s = re.sub(r"\b[+]?[A-Za-z_]*\d+[-:\w]*\b", "<ref>", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_messages(html_path: Path) -> list[dict]:
    if not html_path.exists():
        return []
    html = html_path.read_text(encoding="utf-8", errors="replace")
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        cells = [c for c in cells if c]
        # data rows look like: [Error]|doc|Compiler|message|time|date|no
        if len(cells) >= 4 and cells[0].startswith("[") and cells[0].endswith("]"):
            out.append({
                "severity": cells[0].strip("[]"),
                "document": cells[1],
                "source": cells[2],
                "message": cells[3],
            })
    return out


def classify(msg: str) -> tuple[str | None, str]:
    """Return (lint_rule_id_or_None, human_class) for an Altium message."""
    for patt, rule, label in KNOWN_MAP:
        if re.search(patt, msg, re.I):
            return rule, label
    return ("UNMAPPED", _norm(msg)[:60])


def load_lint(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def main() -> int:
    html = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR / "MessageListReport.html"
    lintp = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT_DIR / "lint.json"

    msgs = parse_messages(html)
    if not msgs:
        print(f"No Altium messages parsed from {html}.")
        print("Export the Messages panel (right-click > Export, or OutJob report) to")
        print(f"{html} after a Validate, then re-run.")
        return 2
    lint = load_lint(lintp)
    lint_rules_hit = {i.get("rule") for i in (lint.get("issues") or [])}

    # Tally Altium messages by (severity, mapped rule, label)
    by_class: Counter = Counter()
    mapped_rules: set = set()
    unmapped: Counter = Counter()
    for m in msgs:
        rule, label = classify(m["message"])
        by_class[(m["severity"], label, rule)] += 1
        if rule == "UNMAPPED":
            unmapped[label] += 1
        elif rule is not None:
            mapped_rules.add(rule)

    nerr = sum(1 for m in msgs if m["severity"].lower() == "error")
    nwarn = sum(1 for m in msgs if m["severity"].lower() == "warning")
    # The headless altium_compile export tags every row "[Violation]" (IViolation's
    # DM_*DescriptorString accessors don't expose severity), so error/warning split
    # is only meaningful for a real Messages-panel export. Suppress the misleading
    # "0 error, 0 warning" when no row carried a true Error/Warning severity.
    if nerr or nwarn:
        print(f"Altium messages: {len(msgs)}  ({nerr} error, {nwarn} warning)")
    else:
        print(f"Altium violations: {len(msgs)}  (severity not exposed by headless compile)")
    print(f"Our lint.json: status={lint.get('status')} rules_hit={sorted(lint_rules_hit)}\n")

    print("=== Altium message classes -> our lint mapping ===")
    for (sev, label, rule), c in sorted(by_class.items(), key=lambda x: (-x[1],)):
        if rule == "UNMAPPED":
            tag = "  *** NO LINT RULE (candidate to add) ***"
        elif rule is None:
            tag = "  (intentionally not mirrored)"
        else:
            seen = "covered by our lint THIS build" if rule in lint_rules_hit else \
                   "rule exists but did not fire this build"
            tag = f"  -> lint:{rule} ({seen})"
        print(f"  {c:4} [{sev}] {label}{tag}")

    if unmapped:
        print("\n=== UNMAPPED Altium classes (consider adding a lint rule) ===")
        for label, c in unmapped.most_common():
            print(f"  {c:4} x {label}")
    else:
        print("\nAll Altium message classes are mapped (covered or intentionally not mirrored).")

    print(f"\nSummary: {len(unmapped)} unmapped class(es); "
          f"{len(mapped_rules)} Altium classes map to existing lint rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
