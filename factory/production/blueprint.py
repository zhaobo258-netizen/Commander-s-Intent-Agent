"""Build explicit, traceable Agent blueprints from confirmed intent."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy

from factory.contracts import ValidationIssue, validate_document
from factory.errors import ContractValidationError, GateBlockedError
from factory.governance import evaluate_production_gate, load_policy
from factory.governance.gates import GateDecision
from factory.serialization import strict_json_loads


_DESIGN_KEYS = {
    "metadata",
    "capabilities",
    "skills",
    "workflow",
    "resources",
    "harness",
    "evaluation",
    "adapters",
}
_MISSING = object()


def _format_issues(kind: str, issues: tuple[ValidationIssue, ...]) -> str:
    rendered = ", ".join(f"{issue.path}:{issue.code}" for issue in issues)
    return f"invalid {kind} contract: {rendered}"


def _reject_non_string_keys(value: object, seen: set[int] | None = None) -> None:
    if seen is None:
        seen = set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            raise ContractValidationError("document must not contain cycles")
        seen.add(identity)
        try:
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise ContractValidationError(
                        "document mappings must use string keys"
                    )
                _reject_non_string_keys(nested, seen)
        finally:
            seen.remove(identity)
    elif isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen:
            raise ContractValidationError("document must not contain cycles")
        seen.add(identity)
        try:
            for nested in value:
                _reject_non_string_keys(nested, seen)
        finally:
            seen.remove(identity)


def _json_snapshot(value: Mapping, label: str) -> dict:
    _reject_non_string_keys(value)
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        payload.encode("utf-8")
        normalized = strict_json_loads(payload)
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ContractValidationError(
            f"{label} must be JSON-compatible UTF-8"
        ) from exc
    if not isinstance(normalized, dict):
        raise ContractValidationError(f"{label} must be a mapping")
    return normalized


def _decode_pointer_token(raw_token: str) -> str:
    index = 0
    while index < len(raw_token):
        if raw_token[index] != "~":
            index += 1
            continue
        if index + 1 >= len(raw_token) or raw_token[index + 1] not in "01":
            raise ContractValidationError("intent path contains an invalid escape")
        index += 2
    return raw_token.replace("~1", "/").replace("~0", "~")


def _resolve_intent_path(intent: object, path: object) -> object:
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        raise ContractValidationError("intent path must be an absolute JSON Pointer")
    try:
        path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError("intent path must be valid UTF-8") from exc

    current = intent
    for raw_token in path[1:].split("/"):
        token = _decode_pointer_token(raw_token)
        if isinstance(current, Mapping):
            if token not in current:
                return _MISSING
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise ContractValidationError(
                    "intent path contains a noncanonical array index"
                )
            index = int(token)
            if index >= len(current):
                return _MISSING
            current = current[index]
            continue
        return _MISSING
    return current


def _traceability_entries(blueprint: Mapping):
    yield from blueprint["capabilities"]
    yield from blueprint["skills"]
    yield from blueprint["workflow"]["steps"]
    yield from blueprint["evaluation"]["cases"]


def validate_blueprint_traceability(blueprint: Mapping, intent: Mapping) -> None:
    """Require every declared intent path to resolve in the confirmed intent."""
    for entry in _traceability_entries(blueprint):
        for path in entry["intent_paths"]:
            if _resolve_intent_path(intent, path) is _MISSING:
                raise ContractValidationError(
                    f"intent path does not resolve in confirmed intent: {path}"
                )


def build_blueprint(
    intent: Mapping,
    design: Mapping,
    decision: GateDecision,
) -> dict:
    """Return a validated blueprint without inventing design content."""
    if not isinstance(intent, Mapping):
        raise ContractValidationError("commander intent must be a mapping")
    if not isinstance(decision, GateDecision):
        raise ContractValidationError("gate decision must be a GateDecision")

    intent_snapshot = _json_snapshot(intent, "commander intent")
    intent_issues = validate_document("commander-intent", intent_snapshot)
    if intent_issues:
        raise ContractValidationError(
            _format_issues("commander-intent", intent_issues)
        )

    actual_decision = evaluate_production_gate(
        intent_snapshot,
        load_policy("production-gates"),
    )
    if decision != actual_decision:
        raise GateBlockedError(
            "provided gate decision is stale or does not match the current intent"
        )
    if not actual_decision.ready:
        raise GateBlockedError("commander intent is not production-ready")

    if not isinstance(design, Mapping):
        raise ContractValidationError("Agent design must be a mapping")
    design_snapshot = _json_snapshot(design, "Agent design")
    missing = sorted(_DESIGN_KEYS - set(design_snapshot))
    unknown = sorted(set(design_snapshot) - _DESIGN_KEYS)
    if missing:
        raise ContractValidationError(f"missing design keys: {', '.join(missing)}")
    if unknown:
        raise ContractValidationError(f"unknown design keys: {', '.join(unknown)}")

    blueprint = {
        "schema_version": "1.0",
        "metadata": deepcopy(design_snapshot["metadata"]),
        "commander_intent_ref": {
            "name": intent_snapshot["metadata"]["name"],
            "version": intent_snapshot["metadata"]["version"],
        },
        "capabilities": deepcopy(design_snapshot["capabilities"]),
        "skills": deepcopy(design_snapshot["skills"]),
        "workflow": deepcopy(design_snapshot["workflow"]),
        "resources": deepcopy(design_snapshot["resources"]),
        "harness": deepcopy(design_snapshot["harness"]),
        "evaluation": deepcopy(design_snapshot["evaluation"]),
        "adapters": deepcopy(design_snapshot["adapters"]),
    }
    issues = validate_document("agent-blueprint", blueprint)
    if issues:
        raise ContractValidationError(_format_issues("agent-blueprint", issues))
    validate_blueprint_traceability(blueprint, intent_snapshot)
    return deepcopy(blueprint)


__all__ = ["build_blueprint", "validate_blueprint_traceability"]
