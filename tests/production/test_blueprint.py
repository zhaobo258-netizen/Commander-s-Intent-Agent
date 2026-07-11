from __future__ import annotations

import copy

import pytest

from factory.errors import ContractValidationError, GateBlockedError
from factory.governance.gates import GateDecision
from factory.production.blueprint import build_blueprint


def test_blocked_intent_short_circuits_before_malformed_design(
    valid_intent: dict,
    blocked_decision: GateDecision,
) -> None:
    with pytest.raises(GateBlockedError):
        build_blueprint(valid_intent, None, blocked_decision)


def test_blueprint_preserves_explicit_design_and_traceability(
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision: GateDecision,
) -> None:
    intent_before = copy.deepcopy(production_ready_intent)
    design_before = copy.deepcopy(valid_design)

    blueprint = build_blueprint(
        production_ready_intent,
        valid_design,
        ready_decision,
    )

    assert blueprint["commander_intent_ref"] == {
        "name": production_ready_intent["metadata"]["name"],
        "version": production_ready_intent["metadata"]["version"],
    }
    for key in (
        "metadata",
        "capabilities",
        "skills",
        "workflow",
        "resources",
        "harness",
        "evaluation",
        "adapters",
    ):
        assert blueprint[key] == valid_design[key]
    assert production_ready_intent == intent_before
    assert valid_design == design_before

    blueprint["capabilities"][0]["name"] = "changed"
    assert valid_design["capabilities"][0]["name"] == "Preparation gap detection"


def test_forged_ready_decision_cannot_bypass_current_gate(
    valid_intent: dict,
    valid_design: dict,
) -> None:
    forged = GateDecision(100, (), (), True)

    with pytest.raises(GateBlockedError, match="stale|does not match|not production-ready"):
        build_blueprint(valid_intent, valid_design, forged)


def test_stale_decision_is_rejected_after_intent_changes(
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision: GateDecision,
) -> None:
    production_ready_intent["authority"]["human_review"] = []

    with pytest.raises(GateBlockedError, match="stale|does not match|not production-ready"):
        build_blueprint(production_ready_intent, valid_design, ready_decision)


def test_design_top_level_is_exact_and_cannot_override_intent_reference(
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision: GateDecision,
) -> None:
    valid_design["commander_intent_ref"] = {"name": "forged", "version": "9"}

    with pytest.raises(ContractValidationError, match="unknown design keys"):
        build_blueprint(production_ready_intent, valid_design, ready_decision)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda design: design["capabilities"][0].update(intent_paths=["/missing"]),
        lambda design: design["skills"][0].update(intent_paths=["/missing"]),
        lambda design: design["workflow"]["steps"][0].update(intent_paths=["/missing"]),
        lambda design: design["evaluation"]["cases"][0].update(intent_paths=["/missing"]),
    ],
)
def test_every_traceability_location_must_resolve(
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision: GateDecision,
    mutate,
) -> None:
    mutate(valid_design)

    with pytest.raises(ContractValidationError, match="intent path.*does not resolve"):
        build_blueprint(production_ready_intent, valid_design, ready_decision)


@pytest.mark.parametrize(
    "path",
    [
        "#/key_tasks/0",
        "key_tasks/0",
        "/key_tasks/00",
        "/key_tasks/-1",
        "/key_tasks/-",
        "/key_tasks/9",
        "/key_tasks/0/~2bad",
    ],
)
def test_noncanonical_or_invalid_intent_pointers_fail_closed(
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision: GateDecision,
    path: str,
) -> None:
    valid_design["capabilities"][0]["intent_paths"] = [path]

    with pytest.raises(ContractValidationError, match="intent path|agent-blueprint"):
        build_blueprint(production_ready_intent, valid_design, ready_decision)


@pytest.mark.parametrize("paths", [[], ["/key_tasks/0", "/key_tasks/0"]])
def test_traceability_lists_must_be_nonempty_and_unique(
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision: GateDecision,
    paths: list[str],
) -> None:
    valid_design["capabilities"][0]["intent_paths"] = paths

    with pytest.raises(ContractValidationError, match="agent-blueprint"):
        build_blueprint(production_ready_intent, valid_design, ready_decision)


@pytest.mark.parametrize("intent", [None, [], "intent"])
def test_non_mapping_intent_fails_with_factory_error(
    intent: object,
    valid_design: dict,
) -> None:
    with pytest.raises(ContractValidationError, match="intent must be a mapping"):
        build_blueprint(intent, valid_design, GateDecision(100, (), (), True))
