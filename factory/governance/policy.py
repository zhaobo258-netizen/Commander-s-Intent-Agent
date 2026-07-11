"""Safely load and structurally validate production gate policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib.resources import files
from typing import Any

import yaml

from factory.contracts import load_schema


_POLICY_KEYS = {
    "schema_version",
    "threshold",
    "confirmed_source_types",
    "critical_paths",
    "sections",
}
_SECTION_KEYS = {"id", "points", "required_paths"}
_APPROVED_CONFIRMED_SOURCE_TYPES = frozenset(
    {"user_confirmed", "observed_file", "tool_result"}
)
_REQUIRED_CRITICAL_PATHS = (
    "/mission",
    "/user",
    "/desired_end_state",
    "/resources",
    "/authority",
    "/acceptance",
)
_STATE_MACHINE_POLICY_KEYS = {"schema_version", "modes"}
_MODE_POLICY_KEYS = {"terminal_states", "transitions"}


def _policy_error(message: str) -> ValueError:
    return ValueError(f"malformed production policy: {message}")


def _governance_policy_error(name: str, message: str) -> ValueError:
    return ValueError(f"malformed governance policy {name}: {message}")


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


def validate_production_gate_policy(policy: Mapping[str, Any]) -> None:
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

    confirmed_source_types = _require_string_list(
        policy["confirmed_source_types"],
        "confirmed_source_types",
        allow_empty=False,
    )
    if not set(confirmed_source_types).issubset(
        _APPROVED_CONFIRMED_SOURCE_TYPES
    ):
        raise _policy_error(
            "confirmed_source_types must contain only approved source types"
        )

    critical_paths = _require_paths(
        policy["critical_paths"],
        "critical_paths",
        allow_empty=True,
    )
    if tuple(critical_paths) != _REQUIRED_CRITICAL_PATHS:
        raise _policy_error(
            "critical_paths must contain exactly the approved paths in canonical order"
        )

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


def _state_machine_error(message: str) -> ValueError:
    return ValueError(f"malformed state-machine policy: {message}")


def _require_state_machine_keys(
    value: Mapping[str, Any],
    expected: set[str],
    location: str,
) -> None:
    missing = sorted(expected - set(value))
    if missing:
        raise _state_machine_error(
            f"{location} missing keys: {', '.join(missing)}"
        )

    unknown = sorted(set(value) - expected, key=str)
    if unknown:
        rendered = ", ".join(str(key) for key in unknown)
        raise _state_machine_error(
            f"{location} has unknown keys: {rendered}"
        )


def _require_state_list(value: object, location: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _state_machine_error(f"{location} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise _state_machine_error(
            f"{location} must contain non-empty state names"
        )
    if len(value) != len(set(value)):
        raise _state_machine_error(f"{location} must not contain duplicates")
    return value


def _factory_job_enums() -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        schema = load_schema("factory-job")
        modes = schema["properties"]["mode"]["enum"]
        states = schema["$defs"]["factory_state"]["enum"]
    except (KeyError, TypeError) as exc:
        raise _state_machine_error(
            "factory-job schema does not expose mode and state enums"
        ) from exc

    if (
        not isinstance(modes, list)
        or not modes
        or any(not isinstance(mode, str) or not mode for mode in modes)
        or len(modes) != len(set(modes))
    ):
        raise _state_machine_error("factory-job mode enum is invalid")
    if (
        not isinstance(states, list)
        or not states
        or any(not isinstance(state, str) or not state for state in states)
        or len(states) != len(set(states))
    ):
        raise _state_machine_error("factory-job state enum is invalid")
    return tuple(modes), tuple(states)


def validate_state_machine_policy(policy: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` when a factory state-machine policy is unsafe."""
    if not isinstance(policy, Mapping):
        raise _state_machine_error("document must be a mapping")
    _require_state_machine_keys(policy, _STATE_MACHINE_POLICY_KEYS, "document")

    if policy["schema_version"] != "1.0":
        raise _state_machine_error("schema_version must be '1.0'")

    expected_modes, factory_states = _factory_job_enums()
    modes = policy["modes"]
    if not isinstance(modes, Mapping):
        raise _state_machine_error("modes must be a mapping")

    missing_modes = sorted(set(expected_modes) - set(modes))
    unknown_modes = sorted(set(modes) - set(expected_modes), key=str)
    if missing_modes:
        raise _state_machine_error(
            f"modes missing schema modes: {', '.join(missing_modes)}"
        )
    if unknown_modes:
        rendered = ", ".join(str(mode) for mode in unknown_modes)
        raise _state_machine_error(f"modes contain unknown schema modes: {rendered}")

    known_states = frozenset(factory_states)
    for mode in expected_modes:
        mode_policy = modes[mode]
        location = f"modes.{mode}"
        if not isinstance(mode_policy, Mapping):
            raise _state_machine_error(f"{location} must be a mapping")
        _require_state_machine_keys(mode_policy, _MODE_POLICY_KEYS, location)

        terminal_states = _require_state_list(
            mode_policy["terminal_states"],
            f"{location}.terminal_states",
        )
        unknown_terminal_states = sorted(set(terminal_states) - known_states)
        if unknown_terminal_states:
            raise _state_machine_error(
                f"{location}.terminal_states contains unknown state: "
                f"{', '.join(unknown_terminal_states)}"
            )
        if "CANCELLED" not in terminal_states:
            raise _state_machine_error(
                f"{location}.terminal_states must include CANCELLED"
            )
        if "NEW" in terminal_states or "BLOCKED" in terminal_states:
            raise _state_machine_error(
                f"{location}.terminal_states cannot include NEW or BLOCKED"
            )

        transitions = mode_policy["transitions"]
        if not isinstance(transitions, Mapping) or not transitions:
            raise _state_machine_error(
                f"{location}.transitions must be a non-empty mapping"
            )

        transition_states = set(transitions)
        unknown_sources = sorted(transition_states - known_states, key=str)
        if unknown_sources:
            rendered = ", ".join(str(state) for state in unknown_sources)
            raise _state_machine_error(
                f"{location}.transitions contains unknown state: {rendered}"
            )
        forbidden_sources = transition_states & (
            set(terminal_states) | {"BLOCKED", "CANCELLED"}
        )
        if forbidden_sources:
            raise _state_machine_error(
                f"{location}.transitions defines terminal or automatic state: "
                f"{', '.join(sorted(forbidden_sources))}"
            )

        targeted_states: set[str] = set()
        for source, raw_targets in transitions.items():
            targets = _require_state_list(
                raw_targets,
                f"{location}.transitions.{source}",
            )
            unknown_targets = sorted(set(targets) - known_states)
            if unknown_targets:
                raise _state_machine_error(
                    f"{location}.transitions.{source} contains unknown state: "
                    f"{', '.join(unknown_targets)}"
                )
            automatic_targets = set(targets) & {"BLOCKED", "CANCELLED"}
            if automatic_targets:
                raise _state_machine_error(
                    f"{location}.transitions.{source} repeats automatic target: "
                    f"{', '.join(sorted(automatic_targets))}"
                )
            targeted_states.update(targets)

        if "NEW" not in transition_states:
            raise _state_machine_error(
                f"{location}.transitions missing transition table for NEW"
            )
        missing_tables = sorted(
            targeted_states - set(terminal_states) - transition_states
        )
        if missing_tables:
            raise _state_machine_error(
                f"{location}.transitions missing transition tables for states: "
                f"{', '.join(missing_tables)}"
            )

        reachable = {"NEW"}
        pending = ["NEW"]
        while pending:
            source = pending.pop()
            for target in transitions.get(source, ()):
                if target not in reachable:
                    reachable.add(target)
                    if target in transitions:
                        pending.append(target)

        unreachable_sources = sorted(transition_states - reachable)
        if unreachable_sources:
            raise _state_machine_error(
                f"{location}.transitions has unreachable transition source: "
                f"{', '.join(unreachable_sources)}"
            )

        successful_terminals = set(terminal_states) - {"CANCELLED"}
        if not successful_terminals & reachable:
            raise _state_machine_error(
                f"{location}.transitions must reach a reachable successful terminal"
            )


PolicyValidator = Callable[[Mapping[str, Any]], None]
POLICY_REGISTRY: dict[str, tuple[str, PolicyValidator]] = {
    "production-gates": (
        "production-gates.yaml",
        validate_production_gate_policy,
    ),
    "state-machine": (
        "state-machine.yaml",
        validate_state_machine_policy,
    ),
}


def load_policy(name: str) -> dict:
    """Return a freshly loaded policy validated for its registered shape."""
    try:
        filename, validator = POLICY_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"unknown governance policy: {name}") from exc

    try:
        resource = files("factory.governance").joinpath(filename)
        loaded = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _governance_policy_error(
            name,
            f"could not load {filename}: {exc}",
        ) from exc

    if not isinstance(loaded, Mapping):
        raise _governance_policy_error(name, "document must be a mapping")
    policy = dict(loaded)
    validator(policy)
    return policy
