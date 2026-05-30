"""Polymorphic Rule schema for the closed-loop design review.

A Rule is a check DEFINITION; a Finding (in findings.py) is the check RESULT.
Rules are persisted in test1/review/rules.yaml and dispatched by rule_eval.py.

Two evaluation modes — discriminated union via the `evaluation` field:
  • structural: Python predicate evaluated against netlist/sim result.
  • semantic:   LLM agent reads cited source + design, emits a verdict.

Family tag (schematic / simulation / design) picks which evaluator subsystem
runs the rule:
  • schematic  → predicates over netlist/<sheet>.yaml + built .SchDoc.
  • simulation → predicates over sim_service.run_block_sim results.
  • design     → cross-cutting; predicate may touch either subsystem.

Origin tag controls regen merge: user-origin rules survive regenerate.

Spec: docs/superpowers/specs/2026-05-29-closed-loop-design-review-design.md §3.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


Severity = Literal["ERROR", "WARNING", "INFO"]
# `block` — boundary-validation rules for one functional block (bias, ldo,
# loadsw, pdn …). They stress the block's operating LIMITS against datasheet
# specs, component tolerances, and EE first principles (e.g. op-amp output
# headroom capping the bias full-scale current, sense-R tolerance eating the
# accuracy budget). Evaluated by the same sim_review / semantic machinery as
# the other families; surfaced as its own category in the harness + GUI.
Family   = Literal["schematic", "simulation", "design", "block"]
Origin   = Literal["generated", "user", "imported"]


class SourceCitation(BaseModel):
    doc:   str
    loc:   str
    quote: str = ""


class AppliesTo(BaseModel):
    refdes:    str | None      = None
    pins:      list[str]       = []
    net:       str | None      = None
    rail:      str | None      = None
    sheet:     str | None      = None
    sim_block: str | None      = None
    sim_type:  str | None      = None
    mpn:       str | None      = None
    role_spec: dict            = {}
    # Functional block this rule belongs to (block-family rules). Drives the
    # Blocks dropdown grouping in the GUI and the harness's per-block report. A
    # block may map to a sim block (opa_bias), a sheet (eeprom), or a logical
    # sub-circuit; it is the stable grouping key independent of sim_block/sheet.
    block:     str | None      = None


# ---- Predicate variants (structural) -----------------------------------

class _PredBase(BaseModel):
    pass

class DecouplingCount(_PredBase):
    kind: Literal["decoupling_count"] = "decoupling_count"
    refdes: str
    pins: list[str]
    min: int
    value_match: str | None = None

class PullupPulldown(_PredBase):
    kind: Literal["pullup_pulldown"] = "pullup_pulldown"
    net: str
    rail: str
    value_match: str
    direction: Literal["up", "down"]

class NoConnect(_PredBase):
    kind: Literal["no_connect"] = "no_connect"
    refdes: str
    pin: str

class NetRouting(_PredBase):
    kind: Literal["net_routing"] = "net_routing"
    from_pin: str        # "refdes.pin"
    to_pin: str
    via: Literal["series_R", "jumper", "direct"]

class ConnectorPin(_PredBase):
    kind: Literal["connector_pin"] = "connector_pin"
    refdes: str
    pin: str
    net: str

class PowerRailMembership(_PredBase):
    kind: Literal["power_rail_membership"] = "power_rail_membership"
    refdes: str
    pin: str
    rail: str

class ValueInRange(_PredBase):
    kind: Literal["value_in_range"] = "value_in_range"
    refdes: str
    min: float | None = None
    max: float | None = None
    value_regex: str | None = None

class Present(_PredBase):
    kind: Literal["present"] = "present"
    mpn: str | None = None
    role_spec: dict = {}

class SimPass(_PredBase):
    kind: Literal["sim_pass"] = "sim_pass"
    sim_block: str
    sim_type: str

class SimMetric(_PredBase):
    kind: Literal["sim_metric"] = "sim_metric"
    sim_block: str
    sim_type: str
    metric: str
    op: Literal[">=", "<=", "==", ">", "<"]
    value: float

class SimReview(_PredBase):
    """Agent-judged sim check. The evaluator RUNS the real sim block (deriving
    params from requirements if the scenario is stale, iterating if needed) and
    hands the result + analysis dict to claude -p to judge against `criterion`.
    Avoids brittle metric-key matching against the deck's analysis schema."""
    kind: Literal["sim_review"] = "sim_review"
    sim_block: str
    sim_type: str
    criterion: str = ""   # requirement to judge the sim result against


Predicate = Annotated[
    Union[
        DecouplingCount, PullupPulldown, NoConnect, NetRouting,
        ConnectorPin, PowerRailMembership, ValueInRange, Present,
        SimPass, SimMetric, SimReview,
    ],
    Field(discriminator="kind"),
]


# ---- Rule (discriminated by evaluation mode) ----------------------------

class RuleBase(BaseModel):
    id:         str
    family:     Family
    severity:   Severity
    title:      str
    applies_to: AppliesTo
    source:     list[SourceCitation] = Field(min_length=1)
    fix_hint:   str = ""
    enabled:    bool = True
    origin:     Origin = "generated"


class StructuralRule(RuleBase):
    evaluation: Literal["structural"] = "structural"
    predicate:  Predicate
    prompt:     None = None


class SemanticRule(RuleBase):
    evaluation: Literal["semantic"] = "semantic"
    predicate:  None = None
    prompt:     str


Rule = Annotated[
    Union[StructuralRule, SemanticRule],
    Field(discriminator="evaluation"),
]


# ---- Top-level rules.yaml shape -----------------------------------------

class SourceSeen(BaseModel):
    """Doc / URL the generator read, with its mtime at read time. Drives the
    staleness banner: if the current mtime is newer, the rule set is stale."""
    path: str
    mtime: float


class RulesFile(BaseModel):
    version: int = 1
    generated_at: str = ""           # ISO-8601 UTC
    sources_seen: list[SourceSeen] = []
    rules: list[Rule] = []
