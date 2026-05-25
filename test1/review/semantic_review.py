"""Phase 2b: LLM-driven per-IC semantic review.

Why a manifest instead of direct calls
--------------------------------------
A Python process can't launch Claude Code subagents. So this module's
`run()` produces a *manifest* — a JSON file at
`review/semantic_manifest.json` listing one review task per IC, with
everything the subagent needs (datasheet path, schematic snippet refs,
requirements text). The user (or me, the agent driving the session)
then dispatches one Agent call per IC. Each subagent's response is
written to `review/semantic_findings.json`, which run_review.py picks
up on a subsequent run to merge into error_log.md.

Run flow:
  1. `python3 run_review.py`                            → emits manifest
  2. (Claude in chat) runs Agent per IC                 → semantic_findings.json
  3. `python3 run_review.py --semantic-merge`           → merges into error_log.md

The manifest entries are deliberately compact — each Agent gets the
exact file paths to read, the exact question to answer, and a
schema for its response.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .findings import Finding, Severity
from .netlist_view import load_all
from .part_fingerprint import datasheet_paths
from .requirements_index import RequirementsIndex

PROJECT_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_DIR / "review" / "semantic_manifest.json"
FINDINGS_PATH = PROJECT_DIR / "review" / "semantic_findings.json"


# ICs we want per-part semantic review for. (refdes, mpn, why).
# refdes → tells us which sheet/netlist to scope. mpn → finds datasheet.
SEMANTIC_TARGETS = [
    ("U10", "TPS7A8401A", "ANY-OUT config, SNS/FB Kelvin sense, BIAS bypass, PG topology"),
    ("U11", "TPS22916", "EN drive, quick-output discharge, VIN/VOUT bulk caps"),
    ("U20", "Bobcat",   "DUT power pin coverage, pull network completeness, NC pins"),
    ("U30", "24AA08",   "I²C addressing, A0/A1/A2 strap, WP pin"),
    ("U40", "MCP4728",  "VREF source (VDD vs internal 2.048V), EEPROM default state, /LDAC, /RDY"),
    ("U41", "OPA2388",  "Unity-gain stability for V-to-I loop, input common-mode, output range"),
    ("Q40", "PMZ1200UPEYL", "VGS/VDS rating vs 3.3V rail, RDS(on), polarity (P-channel for source-into-pin)"),
    ("Q41", "PMZ1200UPEYL", "VGS/VDS rating vs 3.3V rail, RDS(on), polarity"),
]


@dataclass
class ReviewTask:
    refdes: str
    mpn: str
    why: str
    sheet: str
    datasheet_paths: list[str]
    netlist_path: str
    schematic_path: str
    requirements_quote: str
    prompt: str = ""


def _requirements_snippet(idx: RequirementsIndex, mpn: str) -> str:
    """Find the chunk of `Parts to implement` that mentions this MPN."""
    p = idx.part(mpn)
    if p:
        return f"### {p.name}\n{p.raw_text}"
    return f"(no '{mpn}' entry in design_requirements.md 'Parts to implement')"


_PROMPT_TEMPLATE = """\
You are auditing the wiring of {refdes} ({mpn}) in a KiCad schematic
against its datasheet and the project's design_requirements.md.

READ ONLY — do not edit any files. Return findings as JSON.

Scope:
  {why}

Resources:
  - Datasheet(s): {datasheet_list}
  - Netlist YAML: {netlist_path}
  - Schematic builder: {schematic_path}
  - Project requirements quote: see below

Requirements quote
------------------
{requirements_quote}

Procedure
---------
1. Read the netlist YAML for this sheet — that's the declarative source
   of truth for parts and nets. Note every net {refdes} appears in.
2. Read the relevant section of the schematic builder for context on
   layout intent (cluster names, design comments).
3. Open the datasheet PDF(s). Walk the pinout table; for each pin of
   {refdes}, verify the wiring matches the datasheet's expected use.
4. Check application-circuit recommendations: decoupling values,
   bypass caps, pull-ups on open-drain outputs, NC pins, strap pins.
5. Verify the part is correctly rated for this application (abs-max
   ratings vs operating voltages, current rating vs expected load).

Output JSON schema (return ONE list, even if empty)
---------------------------------------------------
Each finding object:
  {{
    "rule_id": "SEM_<SCREAMING_SNAKE>",    // stable across runs
    "severity": "ERROR" | "WARNING" | "INFO",
    "title": "<one-line headline>",
    "subject": "<refdes or refdes.pin or net name>",
    "component_refs": ["<refdes>", ...],
    "datasheet_ref": "<MPN doc-id §section or page>",
    "requirement_ref": "<design_requirements.md:line if applicable>",
    "observed": "<what the schematic does, with file:line>",
    "impact": "<what breaks or is suboptimal>",
    "fix": "<one-line concise fix instruction>",
    "autofix": "manual"                     // sem checks default to manual
  }}

Severity rules
--------------
  ERROR   — board won't function or risks the DUT
  WARNING — design violates a datasheet recommendation or req-doc statement
  INFO    — observation only; no fix needed

Use stable IDs so re-runs produce the same finding identifier when the
underlying issue is the same. Bad: "SEM_BAD_WIRING_1". Good:
"SEM_PG_NO_PULLUP" or "SEM_VREF_WRONG_SOURCE".

Reply with ONLY the JSON list, no prose.
"""


def build_manifest(idx: RequirementsIndex) -> list[ReviewTask]:
    view = load_all()
    tasks: list[ReviewTask] = []
    for refdes, mpn, why in SEMANTIC_TARGETS:
        hit = view.part(refdes)
        if hit is None:
            continue
        sheet, _part = hit
        ds_paths = [str(p.relative_to(PROJECT_DIR)) for p in datasheet_paths(mpn)]
        nlpath = f"test1/netlist/{sheet}.yaml"
        schpath = f"test1/gen/build_{sheet}.py"
        rq = _requirements_snippet(idx, mpn)
        prompt = _PROMPT_TEMPLATE.format(
            refdes=refdes,
            mpn=mpn,
            why=why,
            datasheet_list=", ".join(ds_paths) or "(no datasheet found in Parts Library/)",
            netlist_path=nlpath,
            schematic_path=schpath,
            requirements_quote=rq,
        )
        tasks.append(ReviewTask(
            refdes=refdes, mpn=mpn, why=why, sheet=sheet,
            datasheet_paths=ds_paths,
            netlist_path=nlpath, schematic_path=schpath,
            requirements_quote=rq, prompt=prompt,
        ))
    return tasks


def write_manifest(tasks: list[ReviewTask]) -> Path:
    payload = [asdict(t) for t in tasks]
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2))
    return MANIFEST_PATH


def load_semantic_findings() -> list[Finding]:
    """Read review/semantic_findings.json (populated by Agent subagents).

    Returns [] if the file doesn't exist — the manifest hasn't been
    dispatched yet, which is the default state at first run.
    """
    if not FINDINGS_PATH.exists():
        return []
    data = json.loads(FINDINGS_PATH.read_text())
    out: list[Finding] = []
    for d in data:
        out.append(Finding(
            rule_id=d.get("rule_id", "SEM_UNKNOWN"),
            severity=Severity(d.get("severity", "INFO")),
            title=d.get("title", ""),
            subject=d.get("subject", ""),
            sheet=d.get("sheet", "?"),
            component_refs=d.get("component_refs", []),
            requirement_ref=d.get("requirement_ref", ""),
            datasheet_ref=d.get("datasheet_ref", ""),
            observed=d.get("observed", ""),
            impact=d.get("impact", ""),
            fix=d.get("fix", ""),
            autofix=d.get("autofix", "manual"),
            autofix_data=d.get("autofix_data", {}),
        ))
    return out


def run(idx: RequirementsIndex) -> list[Finding]:
    """Entry called by run_review.py.

    Default behavior: writes the manifest, returns whatever findings are
    in semantic_findings.json (may be empty if no Agent run has happened
    yet). This keeps Phase 3 rendering coherent — once the agent
    populates findings, the next `python3 run_review.py` picks them up.
    """
    tasks = build_manifest(idx)
    write_manifest(tasks)
    print(f"  semantic manifest: {len(tasks)} per-IC tasks "
          f"(wrote {MANIFEST_PATH.relative_to(PROJECT_DIR.parent)})")
    findings = load_semantic_findings()
    if findings:
        print(f"  semantic findings cached: {len(findings)}")
    else:
        print("  (no cached semantic findings — dispatch the manifest "
              "via Agent to populate review/semantic_findings.json)")
    return findings
