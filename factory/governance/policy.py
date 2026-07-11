"""Safely load and structurally validate production gate policies."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files
from typing import Any

import yaml


POLICY_FILES = {"commander-intent": "production-gates.yaml"}
_POLICY_KEYS = {
    "schema_version",
    "threshold",
    "confirmed_source_types",
    "critical_paths",
    "sections",
}
_SECTION_KEYS = {"id", "points", "required_paths"}


def _policy_error(message: str) -> ValueError:
    return ValueError(f"malformed production policy: {message}")


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    location: str,
) -> None:
    missing = sorted(expected - set(value))
    if missing:
        raise _policy_error(f"{location} missing keys: {', '.join(missing)}")

    unknown = sorted(set(value) - expected, key=str)
    if unknown:
        rendered = ", ".join(str(key) for key in unknown)
        raise _policy_error(f"{location} has unknown keys: {rendered}")


def _require_string_list(
    value: object,
    location: str,
    *,
    allow_empty: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise _policy_error(f"{location} must be a list")
    if not allow_empty and not value:
        raise _policy_error(f"{location} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise _policy_error(f"{location} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise _policy_error(f"{location} must not contain duplicates")
    return value


def _require_paths(value: object, location: str, *, allow_empty: bool) -> list[str]:
    paths = _require_string_list(value, location, allow_empty=allow_empty)
    if any(not path.startswith("/") for path in paths):
        raise _policy_error(f"{location} entries must be absolute paths")
    return paths


def validate_policy(policy: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` when a policy is structurally unsafe to evaluate."""
    if not isinstance(policy, Mapping):
        raise _policy_error("document must be a mapping")

    _require_exact_keys(policy, _POLICY_KEYS, "document")

    if policy["schema_version"] != "1.0":
        raise _policy_error("schema_version must be '1.0'")

    threshold = policy["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        raise _policy_error("threshold must be an integer")
    if not 0 <= threshold <= 100:
        raise _policy_error("threshold must be between 0 and 100")

    _require_string_list(
        policy["confirmed_source_types"],
        "confirmed_source_types",
        allow_empty=False,
    )
    _require_paths(policy["critical_paths"], "critical_paths", allow_empty=True)

    sections = policy["sections"]
    if not isinstance(sections, list) or not sections:
        raise _policy_error("sections must be a non-empty list")

    section_ids: list[str] = []
    maximum_score = 0
    for index, section in enumerate(sections):
        location = f"sections[{index}]"
        if not isinstance(section, Mapping):
            raise _policy_error(f"{location} must be a mapping")
        _require_exact_keys(section, _SECTION_KEYS, location)

        section_id = section["id"]
        if not isinstance(section_id, str) or not section_id.strip():
            raise _policy_error(f"{location}.id must be a non-empty string")
        section_ids.append(section_id)

        points = section["points"]
        if isinstance(points, bool) or not isinstance(points, int) or points <= 0:
            raise _policy_error(f"{location}.points must be a positive integer")
        maximum_score += points

        _require_paths(
            section["required_paths"],
            f"{location}.required_paths",
            allow_empty=False,
        )

    if len(section_ids) != len(set(section_ids)):
        raise _policy_error("section ids must be unique")
    if threshold > maximum_score:
        raise _policy_error("threshold exceeds the maximum section score")


def load_policy(name: str) -> dict:
    """Return a freshly loaded, structurally validated production policy."""
    try:
        filename = POLICY_FILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown production policy: {name}") from exc

    resource = files("factory.governance").joinpath(filename)
    try:
        loaded = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _policy_error(f"could not load {filename}: {exc}") from exc

    if not isinstance(loaded, Mapping):
        raise _policy_error("document must be a mapping")
    policy = dict(loaded)
    validate_policy(policy)
    return policy
