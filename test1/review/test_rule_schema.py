"""Unit tests for rule_schema.py — discriminated-union routing + validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from test1.review.rule_schema import (
    Rule, RulesFile, StructuralRule, SemanticRule,
    DecouplingCount, PullupPulldown, SimMetric,
)


def _make_structural(rule_id="R1", pred=None):
    return {
        "id": rule_id,
        "family": "schematic",
        "evaluation": "structural",
        "severity": "ERROR",
        "title": "t",
        "applies_to": {"refdes": "U10"},
        "source": [{"doc": "d", "loc": "l"}],
        "predicate": pred or {
            "kind": "decoupling_count",
            "refdes": "U10", "pins": ["1"], "min": 1,
        },
    }


def _make_semantic(rule_id="R2", prompt="check that thing"):
    return {
        "id": rule_id,
        "family": "design",
        "evaluation": "semantic",
        "severity": "WARNING",
        "title": "t",
        "applies_to": {"refdes": "U41"},
        "source": [{"doc": "d", "loc": "l"}],
        "prompt": prompt,
    }


def test_structural_rule_routes_correctly():
    r = Rule.__metadata__[0].discriminator    # noqa — sanity check union exists
    rf = RulesFile.model_validate({"rules": [_make_structural()]})
    assert isinstance(rf.rules[0], StructuralRule)
    assert rf.rules[0].predicate.kind == "decoupling_count"


def test_semantic_rule_routes_correctly():
    rf = RulesFile.model_validate({"rules": [_make_semantic()]})
    assert isinstance(rf.rules[0], SemanticRule)
    assert rf.rules[0].prompt == "check that thing"


def test_predicate_discriminator_picks_right_subclass():
    r = StructuralRule.model_validate(_make_structural(pred={
        "kind": "pullup_pulldown",
        "net": "SCL", "rail": "+3V3",
        "value_match": "10k", "direction": "up",
    }))
    assert isinstance(r.predicate, PullupPulldown)


def test_sim_metric_predicate():
    r = StructuralRule.model_validate(_make_structural(pred={
        "kind": "sim_metric",
        "sim_block": "opa_bias", "sim_type": "dc_sweep",
        "metric": "fs_current_uA", "op": ">=", "value": 600,
    }))
    assert isinstance(r.predicate, SimMetric)
    assert r.predicate.op == ">="


def test_missing_source_rejected():
    bad = _make_structural()
    bad["source"] = []
    with pytest.raises(ValidationError):
        StructuralRule.model_validate(bad)


def test_structural_with_prompt_rejected():
    bad = _make_structural()
    bad["prompt"] = "should not be here"
    with pytest.raises(ValidationError):
        StructuralRule.model_validate(bad)


def test_semantic_without_prompt_rejected():
    bad = _make_semantic()
    del bad["prompt"]
    with pytest.raises(ValidationError):
        SemanticRule.model_validate(bad)


def test_unknown_predicate_kind_rejected():
    bad = _make_structural(pred={"kind": "nonexistent_kind", "refdes": "U10"})
    with pytest.raises(ValidationError):
        StructuralRule.model_validate(bad)


def test_rules_file_roundtrip_yaml(tmp_path):
    import yaml
    rf = RulesFile.model_validate({
        "version": 1,
        "generated_at": "2026-05-29T15:00:00Z",
        "rules": [_make_structural("A"), _make_semantic("B")],
    })
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(rf.model_dump()))
    loaded = RulesFile.model_validate(yaml.safe_load(path.read_text()))
    assert len(loaded.rules) == 2
    assert isinstance(loaded.rules[0], StructuralRule)
    assert isinstance(loaded.rules[1], SemanticRule)
