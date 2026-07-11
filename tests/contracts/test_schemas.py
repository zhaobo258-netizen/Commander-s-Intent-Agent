from __future__ import annotations

import copy

import pytest

from factory.contracts.validation import ValidationIssue, load_schema, validate_document


@pytest.mark.parametrize(
    ("kind", "fixture_name"),
    [
        ("commander-intent", "valid_intent"),
        ("agent-blueprint", "valid_blueprint"),
        ("factory-job", "valid_job"),
        ("review-report", "valid_review"),
    ],
)
def test_valid_contract_fixtures_have_no_issues(
    request: pytest.FixtureRequest,
    kind: str,
    fixture_name: str,
) -> None:
    document = request.getfixturevalue(fixture_name)

    assert validate_document(kind, document) == ()


def test_validation_normalizes_and_orders_multiple_issues(valid_intent: dict) -> None:
    invalid_intent = copy.deepcopy(valid_intent)
    invalid_intent["unknown_top_level"] = True
    invalid_intent["provenance"][0]["source_type"] = "ai_guess"

    issues = validate_document("commander-intent", invalid_intent)

    assert tuple(issue.code for issue in issues) == ("additionalProperties", "enum")
    assert tuple(issue.path for issue in issues) == (
        "/",
        "/provenance/0/source_type",
    )
    assert all(isinstance(issue, ValidationIssue) for issue in issues)


def test_validation_reports_missing_required_field(valid_intent: dict) -> None:
    del valid_intent["mission"]

    issues = validate_document("commander-intent", valid_intent)

    assert len(issues) == 1
    assert issues[0].path == "/"
    assert issues[0].code == "required"


def test_validation_reports_wrong_type(valid_intent: dict) -> None:
    valid_intent["confirmed"] = "yes"

    issues = validate_document("commander-intent", valid_intent)

    assert len(issues) == 1
    assert issues[0].path == "/confirmed"
    assert issues[0].code == "type"


def test_validation_rejects_nested_unknown_governed_key(valid_intent: dict) -> None:
    valid_intent["mission"]["private_note"] = "not part of the contract"

    issues = validate_document("commander-intent", valid_intent)

    assert len(issues) == 1
    assert issues[0].path == "/mission"
    assert issues[0].code == "additionalProperties"


def test_all_contract_schemas_use_draft_2020_12() -> None:
    for kind in (
        "commander-intent",
        "agent-blueprint",
        "factory-job",
        "review-report",
    ):
        assert load_schema(kind)["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_load_schema_rejects_unknown_contract_kind() -> None:
    with pytest.raises(ValueError, match="unknown contract kind"):
        load_schema("unknown")
