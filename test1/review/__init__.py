"""Design review pipeline for test1 (Bobcat carrier board).

Distinct from `gen/` (which generates the schematic) and from
`gen/validator.py` + `gen/layout_lint.py` (which gate the build for
generator bugs). The review pipeline audits *design correctness*:
- Pass 1: cross-reference component wiring against datasheets.
- Pass 2: cross-reference wiring against design_requirements.md.

Modules:
  requirements_index — parse design_requirements.md into a dict
  part_fingerprint   — build/load parts/<MPN>.json cache from datasheets
  rules              — deterministic Python checks (pull-ups, NCs, decoupling)
  semantic_review    — LLM-driven per-IC review (spawns Explore subagent)
  findings           — Finding dataclass + stable-ID assignment + severity
  render             — emit error_log.md (latest snapshot) + history MD
  autofix            — trivial auto-applied fixes (NC, decoupling, pull-up/down)
  propose            — non-trivial diffs surfaced for user approval
"""
