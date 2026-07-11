"""Evaluate fail-closed production readiness for commander intents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from factory.contracts import validate_document
from factory.governance.policy import validate_policy


_MISSING = object()


@dataclass(frozen=True, slots=True)
class GateDecision:
    score: int
    blockers: tuple[str, ...]
    missing_sources: tuple[str, ...]
    ready: bool


def _decode_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _resolve_path(document: object, path: str) -> object:
    current = document
    for raw_token in path.removeprefix("/").split("/"):
        token = _decode_pointer_token(raw_token)
        if isinstance(current, Mapping):
            if token not in current:
                return _MISSING
            current = current[token]
            continue

        if isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            try:
                index = int(token)
            except ValueError:
                return _MISSING
            if index < 0 or index >= len(current):
                return _MISSING
            current = current[index]
            continue

        return _MISSING
    return current


def _is_material(value: object) -> bool:
    if value is _MISSING or value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence, bytes, bytearray)):
        return len(value) > 0
    return True


def _source_covers(source_path: str, target_path: str) -> bool:
    return source_path == target_path or target_path.startswith(f"{source_path}/")


def _confirmed_source_paths(intent: Mapping, policy: Mapping) -> tuple[str, ...]:
    confirmed_types = frozenset(policy["confirmed_source_types"])
    provenance = intent.get("provenance", ())
    if not isinstance(provenance, Sequence) or isinstance(provenance, (str, bytes)):
        return ()

    paths: list[str] = []
    for record in provenance:
        if not isinstance(record, Mapping):
            continue
        path = record.get("path")
        source_type = record.get("source_type")
        if (
            isinstance(path, str)
            and path.startswith("/")
            and isinstance(source_type, str)
            and source_type in confirmed_types
        ):
            paths.append(path)
    return tuple(paths)


def evaluate_production_gate(intent: Mapping, policy: Mapping) -> GateDecision:
    """Return a deterministic, fail-closed production-readiness decision."""
    contract_blockers = tuple(
        f"contract_invalid:{issue.path}:{issue.code}"
        for issue in validate_document("commander-intent", intent)
    )
    validate_policy(policy)

    score = sum(
        section["points"]
        for section in policy["sections"]
        if all(
            _is_material(_resolve_path(intent, required_path))
            for required_path in section["required_paths"]
        )
    )

    confirmed_paths = _confirmed_source_paths(intent, policy)
    missing_sources = tuple(
        critical_path
        for critical_path in policy["critical_paths"]
        if not any(
            _source_covers(source_path, critical_path)
            for source_path in confirmed_paths
        )
    )

    blockers = contract_blockers
    if intent.get("confirmed") is not True:
        blockers += ("intent_not_confirmed",)
    blockers += tuple(
        f"missing_confirmed_source:{critical_path}"
        for critical_path in missing_sources
    )

    ready = score >= policy["threshold"] and not blockers
    return GateDecision(
        score=score,
        blockers=blockers,
        missing_sources=missing_sources,
        ready=ready,
    )
