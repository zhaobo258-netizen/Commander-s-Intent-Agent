from __future__ import annotations

import copy

import pytest
import yaml

import factory.governance.gates as gates_module
import factory.governance.policy as policy_module
from factory.governance.gates import GateDecision, evaluate_production_gate
from factory.governance.policy import load_policy, validate_production_gate_policy


CRITICAL_PATHS = (
    "/mission",
    "/user",
    "/desired_end_state",
    "/resources",
    "/authority",
    "/acceptance",
)


@pytest.fixture
def production_policy() -> dict:
    return load_policy("production-gates")


@pytest.fixture
def production_ready_intent(valid_intent: dict) -> dict:
    intent = copy.deepcopy(valid_intent)
    intent["provenance"] = [
        {
            "path": path,
            "source_type": "user_confirmed",
            "reference": f"confirmed:{path}",
        }
        for path in CRITICAL_PATHS
    ]
    intent["confirmed"] = True
    return intent


def test_loads_exact_commander_intent_production_policy() -> None:
    policy = load_policy("production-gates")

    assert policy["schema_version"] == "1.0"
    assert policy["threshold"] == 80
    assert policy["confirmed_source_types"] == [
        "user_confirmed",
        "observed_file",
        "tool_result",
    ]
    assert policy["critical_paths"] == list(CRITICAL_PATHS)
    assert [
        (section["id"], section["points"], section["required_paths"])
        for section in policy["sections"]
    ] == [
        ("mission", 15, ["/mission/statement", "/mission/problem"]),
        ("user", 15, ["/user/role", "/user/scenario"]),
        (
            "desired_end_state",
            20,
            [
                "/desired_end_state/before",
                "/desired_end_state/after",
                "/desired_end_state/success_metrics",
            ],
        ),
        ("key_tasks", 10, ["/key_tasks"]),
        (
            "resources",
            15,
            ["/resources/data", "/resources/knowledge", "/resources/tools"],
        ),
        (
            "authority",
            15,
            [
                "/authority/allowed_actions",
                "/authority/forbidden_actions",
                "/authority/human_review",
            ],
        ),
        ("acceptance", 10, ["/acceptance/criteria"]),
    ]


@pytest.mark.parametrize(
    "critical_paths",
    [
        [],
        list(CRITICAL_PATHS[:-1]),
        list(reversed(CRITICAL_PATHS)),
        [*CRITICAL_PATHS, "/metadata"],
    ],
)
def test_production_policy_requires_exact_canonical_critical_paths(
    production_policy: dict,
    critical_paths: list[str],
) -> None:
    policy = copy.deepcopy(production_policy)
    policy["critical_paths"] = critical_paths

    with pytest.raises(ValueError, match="critical_paths.*exactly.*canonical order"):
        validate_production_gate_policy(policy)


@pytest.mark.parametrize("unsafe_type", ["assumption", "inference", "unknown"])
def test_production_policy_rejects_unsafe_confirmed_source_type(
    production_policy: dict,
    unsafe_type: str,
) -> None:
    policy = copy.deepcopy(production_policy)
    policy["confirmed_source_types"].append(unsafe_type)

    with pytest.raises(ValueError, match="confirmed_source_types.*approved"):
        validate_production_gate_policy(policy)


def test_production_policy_allows_nonempty_safe_confirmed_source_subset(
    production_policy: dict,
) -> None:
    policy = copy.deepcopy(production_policy)
    policy["confirmed_source_types"] = ["tool_result"]

    validate_production_gate_policy(policy)


def test_production_ready_intent_scores_100_and_is_ready(
    production_ready_intent: dict,
    production_policy: dict,
) -> None:
    decision = evaluate_production_gate(production_ready_intent, production_policy)

    assert decision == GateDecision(
        score=100,
        blockers=(),
        missing_sources=(),
        ready=True,
    )


def test_contract_valid_intent_without_critical_sources_is_not_ready(
    valid_intent: dict,
    production_policy: dict,
) -> None:
    decision = evaluate_production_gate(valid_intent, production_policy)

    assert decision.score == 100
    assert decision.missing_sources == CRITICAL_PATHS
    assert decision.blockers == tuple(
        f"missing_confirmed_source:{path}" for path in CRITICAL_PATHS
    )
    assert decision.ready is False


def test_missing_authority_source_blocks_an_otherwise_ready_intent(
    production_ready_intent: dict,
    production_policy: dict,
) -> None:
    production_ready_intent["provenance"] = [
        record
        for record in production_ready_intent["provenance"]
        if record["path"] != "/authority"
    ]

    decision = evaluate_production_gate(production_ready_intent, production_policy)

    assert decision.score >= 80
    assert decision.missing_sources == ("/authority",)
    assert decision.blockers == ("missing_confirmed_source:/authority",)
    assert decision.ready is False


def test_unconfirmed_intent_is_blocked(
    production_ready_intent: dict,
    production_policy: dict,
) -> None:
    production_ready_intent["confirmed"] = False

    decision = evaluate_production_gate(production_ready_intent, production_policy)

    assert decision.score == 100
    assert decision.blockers == ("intent_not_confirmed",)
    assert decision.missing_sources == ()
    assert decision.ready is False


def test_contract_invalid_intent_is_blocked_even_above_threshold(
    production_ready_intent: dict,
    production_policy: dict,
) -> None:
    del production_ready_intent["mission"]["statement"]

    decision = evaluate_production_gate(production_ready_intent, production_policy)

    assert decision.score == 85
    assert decision.score >= production_policy["threshold"]
    assert decision.blockers == ("contract_invalid:/mission:required",)
    assert decision.ready is False


@pytest.mark.parametrize("source_type", ["inference", "assumption"])
def test_unconfirmed_provenance_types_do_not_satisfy_critical_sources(
    production_ready_intent: dict,
    production_policy: dict,
    source_type: str,
) -> None:
    authority_record = next(
        record
        for record in production_ready_intent["provenance"]
        if record["path"] == "/authority"
    )
    authority_record["source_type"] = source_type

    decision = evaluate_production_gate(production_ready_intent, production_policy)

    assert decision.missing_sources == ("/authority",)
    assert "missing_confirmed_source:/authority" in decision.blockers
    assert decision.ready is False


def test_parent_provenance_covers_critical_descendants() -> None:
    assert gates_module._source_covers(
        "/authority",
        "/authority/allowed_actions",
    )
    assert gates_module._source_covers(
        "/authority",
        "/authority/forbidden_actions",
    )


def test_child_provenance_does_not_cover_parent_or_sibling() -> None:
    child = "/authority/allowed_actions"

    assert gates_module._source_covers(child, "/authority") is False
    assert gates_module._source_covers(child, "/authority/forbidden_actions") is False


@pytest.mark.parametrize(
    ("path", "value"),
    [("/confirmed", False), ("/metadata/version", 0)],
)
def test_false_and_zero_are_material_values_for_scoring(
    production_ready_intent: dict,
    production_policy: dict,
    path: str,
    value: object,
) -> None:
    key_path = path.removeprefix("/").split("/")
    target: dict = production_ready_intent
    for key in key_path[:-1]:
        target = target[key]
    target[key_path[-1]] = value
    policy = copy.deepcopy(production_policy)
    policy["sections"] = [
        {"id": "material_scalar", "points": 100, "required_paths": [path]}
    ]

    decision = evaluate_production_gate(production_ready_intent, policy)

    assert decision.score == 100


@pytest.mark.parametrize("empty_value", [None, "", [], {}])
def test_empty_values_do_not_score(
    production_ready_intent: dict,
    production_policy: dict,
    empty_value: object,
) -> None:
    production_ready_intent["metadata"]["version"] = empty_value
    policy = copy.deepcopy(production_policy)
    policy["sections"] = [
        {
            "id": "material_value",
            "points": 100,
            "required_paths": ["/metadata/version"],
        }
    ]

    decision = evaluate_production_gate(production_ready_intent, policy)

    assert decision.score == 0


def test_evaluation_does_not_mutate_intent_or_policy(
    production_ready_intent: dict,
    production_policy: dict,
) -> None:
    original_intent = copy.deepcopy(production_ready_intent)
    original_policy = copy.deepcopy(production_policy)

    evaluate_production_gate(production_ready_intent, production_policy)

    assert production_ready_intent == original_intent
    assert production_policy == original_policy


def test_contract_invalid_provenance_fails_closed_without_crashing(
    production_ready_intent: dict,
    production_policy: dict,
) -> None:
    authority_record = next(
        record
        for record in production_ready_intent["provenance"]
        if record["path"] == "/authority"
    )
    authority_record["source_type"] = []

    decision = evaluate_production_gate(production_ready_intent, production_policy)

    assert "contract_invalid:/provenance/4/source_type:enum" in decision.blockers
    assert decision.missing_sources == ("/authority",)
    assert decision.ready is False


def test_load_policy_rejects_consumer_identifier() -> None:
    with pytest.raises(
        ValueError,
        match="unknown governance policy: commander-intent",
    ):
        load_policy("commander-intent")


def test_load_policy_dispatches_to_the_registered_policy_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = {"schema_version": "test-policy"}
    validated: list[dict] = []

    def validate_test_policy(policy: dict) -> None:
        validated.append(copy.deepcopy(policy))

    monkeypatch.setitem(
        policy_module.POLICY_REGISTRY,
        "test-policy",
        ("test-policy.yaml", validate_test_policy),
    )

    class FakeResource:
        def joinpath(self, filename: str) -> "FakeResource":
            assert filename == "test-policy.yaml"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return yaml.safe_dump(document)

    monkeypatch.setattr(policy_module, "files", lambda _package: FakeResource())

    loaded = load_policy("test-policy")

    assert loaded == document
    assert validated == [document]


def test_load_policy_rejects_malformed_policy_with_useful_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = load_policy("production-gates")
    malformed["threshold"] = "eighty"

    class FakeResource:
        def joinpath(self, _filename: str) -> "FakeResource":
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return yaml.safe_dump(malformed)

    monkeypatch.setattr(policy_module, "files", lambda _package: FakeResource())

    with pytest.raises(ValueError, match="threshold.*integer"):
        load_policy("production-gates")


def test_load_policy_normalizes_non_string_unknown_key_to_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = load_policy("production-gates")
    malformed[7] = "unexpected"

    class FakeResource:
        def joinpath(self, _filename: str) -> "FakeResource":
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return yaml.safe_dump(malformed)

    monkeypatch.setattr(policy_module, "files", lambda _package: FakeResource())

    with pytest.raises(ValueError, match="unknown keys.*7"):
        load_policy("production-gates")
