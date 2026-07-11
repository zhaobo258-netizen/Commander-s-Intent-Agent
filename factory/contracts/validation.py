"""Load and validate factory contract documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from urllib.parse import unquote

from jsonschema import Draft202012Validator, FormatChecker

from factory.serialization import strict_json_loads


SCHEMA_FILES = {
    "commander-intent": "commander-intent.schema.json",
    "agent-blueprint": "agent-blueprint.schema.json",
    "factory-job": "factory-job.schema.json",
    "factory-manifest": "factory-manifest.schema.json",
    "review-report": "review-report.schema.json",
}


class SchemaReferenceError(ValueError):
    """A schema reference cannot be resolved without leaving the document."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


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
    loaded = strict_json_loads(resource.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"contract schema {kind} must be a JSON object")
    validate_schema_references(loaded)
    return loaded


def _decode_pointer_token(token: str) -> str:
    decoded = unquote(token)
    index = 0
    while index < len(decoded):
        if decoded[index] != "~":
            index += 1
            continue
        if index + 1 >= len(decoded) or decoded[index + 1] not in "01":
            raise SchemaReferenceError(
                "dangling-ref",
                "local JSON pointer contains an invalid escape",
            )
        index += 2
    return decoded.replace("~1", "/").replace("~0", "~")


def resolve_local_reference(document: object, reference: str) -> object:
    """Resolve one local JSON Pointer reference without network access."""
    if reference == "#":
        return document
    if not reference.startswith("#/"):
        kind = "external-ref" if not reference.startswith("#") else "dangling-ref"
        raise SchemaReferenceError(kind, "schema reference is not a local pointer")

    current = document
    for raw_token in reference[2:].split("/"):
        token = _decode_pointer_token(raw_token)
        if isinstance(current, Mapping):
            if token not in current:
                raise SchemaReferenceError(
                    "dangling-ref",
                    "local JSON pointer target does not exist",
                )
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise SchemaReferenceError(
                    "dangling-ref",
                    "local JSON pointer array index is not canonical",
                )
            try:
                position = int(token)
                current = current[position]
            except (IndexError, ValueError) as exc:
                raise SchemaReferenceError(
                    "dangling-ref",
                    "local JSON pointer array target does not exist",
                ) from exc
            continue
        raise SchemaReferenceError(
            "dangling-ref",
            "local JSON pointer traverses a scalar",
        )
    return current


def _walk_json(value: object):
    yield value
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json(nested)


def validate_schema_references(schema: Mapping) -> None:
    """Reject dangling or unregistered external schema references."""
    anchors = {
        anchor: node
        for node in _walk_json(schema)
        if isinstance(node, Mapping)
        for key in ("$anchor", "$dynamicAnchor")
        if isinstance((anchor := node.get(key)), str) and anchor
    }
    for node in _walk_json(schema):
        if not isinstance(node, Mapping):
            continue
        for keyword in ("$ref", "$dynamicRef"):
            if keyword not in node:
                continue
            reference = node[keyword]
            if not isinstance(reference, str):
                raise SchemaReferenceError(
                    "dangling-ref",
                    f"{keyword} must be a string",
                )
            if reference == "#" or reference.startswith("#/"):
                target = resolve_local_reference(schema, reference)
            elif reference.startswith("#"):
                if reference[1:] not in anchors:
                    raise SchemaReferenceError(
                        "dangling-ref",
                        "local schema anchor does not exist",
                    )
                target = anchors[reference[1:]]
            else:
                raise SchemaReferenceError(
                    "external-ref",
                    "external schema references require a registered local resource",
                )
            if not isinstance(target, (Mapping, bool)):
                raise SchemaReferenceError(
                    "invalid-ref-target",
                    "local schema reference target is not a JSON Schema",
                )


def _pointer(path: object) -> str:
    tokens = [str(token).replace("~", "~0").replace("/", "~1") for token in path]
    return "/" if not tokens else "/" + "/".join(tokens)


def validate_document(kind: str, data: Mapping) -> tuple[ValidationIssue, ...]:
    """Return normalized, deterministically ordered validation issues."""
    validator = Draft202012Validator(load_schema(kind), format_checker=FormatChecker())
    issues = (
        ValidationIssue(
            path=_pointer(error.absolute_path),
            code=str(error.validator),
            message=error.message,
        )
        for error in validator.iter_errors(data)
    )
    return tuple(sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message)))
