"""Finding dataclass — what every review check emits.

A Finding is the canonical record format. Both deterministic rules
(`rules.py`) and the LLM semantic reviewer (`semantic_review.py`) yield
Findings; the renderer (`render.py`) groups them by severity and emits
the human-readable error_log.md.

Stable IDs:
  Each Finding carries a `rule_id` (a short, stable string identifying
  WHICH check produced it) plus a `subject` (refdes / net name / pin).
  The renderer hashes (rule_id, subject) into an E1/W1/I1-style ordinal
  for the current run. Two consecutive runs with the same findings
  produce the same ordinals → error_log.md diffs cleanly in git.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


# Categories — used by the auto-fix dispatcher to decide whether a
# finding is in the trivial-auto-apply bucket (NC, decoupling, pull-up/down)
# or in the propose-with-approval bucket (everything else).
AutofixCategory = Literal[
    "nc_marker",       # add (no_connect …) on a datasheet-NC pin
    "decoupling",      # add a 0.1µF cap near an IC power pin
    "pullup_pulldown", # add a pull-up/pull-down on a named net
    "manual",          # not in the auto-fix bucket — surface to user
]


@dataclass
class Finding:
    rule_id: str                # stable identifier, e.g. "MISSING_PULLUP"
    severity: Severity
    title: str                  # one-line headline, used as section header
    subject: str                # refdes / net / pin — must be stable across runs
    sheet: str                  # source sheet name (e.g. "bias", "power")
    component_refs: list[str] = field(default_factory=list)  # e.g. ["U10", "R12"]
    requirement_ref: str = ""   # quote-and-cite, e.g. "design_requirements.md:15"
    datasheet_ref: str = ""     # e.g. "TPS7A8401A SBVS210 §7.3.4"
    observed: str = ""          # what the schematic actually does (with file:line)
    impact: str = ""            # what breaks
    fix: str = ""               # one-line concise fix instruction
    autofix: AutofixCategory = "manual"
    autofix_data: dict = field(default_factory=dict)  # payload for autofix.py

    def stable_key(self) -> tuple[str, str]:
        """Used to assign deterministic ordinals across runs."""
        return (self.rule_id, self.subject)
