"""Load and validate factory contract documents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files

from jsonschema import Draft202012Validator


SCHEMA_FILES = {
    "commander-intent": "commander-intent.schema.json",
    "agent-blueprint": "agent-blueprint.schema.json",
    "factory-job": "factory-job.schema.json",
    "review-report": "review-report.schema.json",
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str
    code: str
    message: str


def load_schema(kind: str) -> dict:
    """Return a freshly loaded schema for a known contract kind."""
    try:
        filename = SCHEMA_FILES[kind]
    except KeyError as exc:
        raise ValueError(f"unknown contract kind: {kind}") from exc

    resource = files("factory.contracts").joinpath(filename)
    return json.loads(resource.read_text(encoding="utf-8"))


def _pointer(path: object) -> str:
    tokens = [str(token).replace("~", "~0").replace("/", "~1") for token in path]
    return "/" if not tokens else "/" + "/".join(tokens)


def validate_document(kind: str, data: Mapping) -> tuple[ValidationIssue, ...]:
    """Return normalized, deterministically ordered validation issues."""
    validator = Draft202012Validator(load_schema(kind))
    issues = (
        ValidationIssue(
            path=_pointer(error.absolute_path),
            code=str(error.validator),
            message=error.message,
        )
        for error in validator.iter_errors(data)
    )
    return tuple(sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message)))
