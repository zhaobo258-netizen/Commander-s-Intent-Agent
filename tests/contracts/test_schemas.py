from __future__ import annotations

import copy
from pathlib import Path

import pytest

import factory.contracts.validation as validation_module
from factory.contracts.validation import (
    SchemaReferenceError,
    ValidationIssue,
    load_schema,
    validate_document,
)


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


def test_factory_job_rejects_invalid_date_time(valid_job: dict) -> None:
    valid_job["created_at"] = "not-a-date-time"

    issues = validate_document("factory-job", valid_job)

    assert len(issues) == 1
    assert issues[0].path == "/created_at"
    assert issues[0].code == "format"


def test_review_report_rejects_invalid_date_time(valid_review: dict) -> None:
    valid_review["evidence"][0]["at"] = "not-a-date-time"

    issues = validate_document("review-report", valid_review)

    assert len(issues) == 1
    assert issues[0].path == "/evidence/0/at"
    assert issues[0].code == "format"


def test_factory_job_rejects_unknown_approval_status(valid_job: dict) -> None:
    valid_job["approvals"][0]["status"] = "banana"

    issues = validate_document("factory-job", valid_job)

    assert len(issues) == 1
    assert issues[0].path == "/approvals/0/status"
    assert issues[0].code == "enum"


def test_factory_job_accepts_optional_mapping_external_state(valid_job: dict) -> None:
    valid_job["external_state"] = {"checked": True, "details": {"count": 2}}

    assert validate_document("factory-job", valid_job) == ()


def test_factory_job_rejects_non_mapping_external_state(valid_job: dict) -> None:
    valid_job["external_state"] = ["stale"]

    issues = validate_document("factory-job", valid_job)

    assert len(issues) == 1
    assert issues[0].path == "/external_state"
    assert issues[0].code == "type"


def test_factory_job_rejects_non_json_nested_external_state(valid_job: dict) -> None:
    valid_job["external_state"] = {"opaque_python_value": {"not-json"}}

    issues = validate_document("factory-job", valid_job)

    assert len(issues) == 1
    assert issues[0].path == "/external_state/opaque_python_value"
    assert issues[0].code == "anyOf"


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


def test_load_schema_rejects_duplicate_json_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path("factory/contracts/commander-intent.schema.json").read_text(
        encoding="utf-8"
    )
    duplicate = source.replace(
        '"title": "Commander Intent",',
        '"title": "Wrong",\n  "title": "Commander Intent",',
        1,
    )

    class FakeResource:
        def joinpath(self, _filename: str) -> "FakeResource":
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return duplicate

    monkeypatch.setattr(validation_module, "files", lambda _package: FakeResource())

    with pytest.raises(ValueError, match="duplicate JSON object key: title"):
        load_schema("commander-intent")


def test_load_schema_rejects_dangling_local_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path("factory/contracts/commander-intent.schema.json").read_text(
        encoding="utf-8"
    )
    dangling = source.replace(
        '"mission": {"$ref": "#/$defs/mission"}',
        '"mission": {"$ref": "#/$defs/missing"}',
        1,
    )

    class FakeResource:
        def joinpath(self, _filename: str) -> "FakeResource":
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return dangling

    monkeypatch.setattr(validation_module, "files", lambda _package: FakeResource())

    with pytest.raises(SchemaReferenceError, match="target does not exist"):
        load_schema("commander-intent")
