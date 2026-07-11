"""Read-only verification of an injected Agent Factory repository root."""

from __future__ import annotations

import ast
import fnmatch
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from factory.governance.policy import (
    validate_production_gate_policy,
    validate_state_machine_policy,
)


_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_SCHEMA_PATHS = (
    "factory/contracts/commander-intent.schema.json",
    "factory/contracts/agent-blueprint.schema.json",
    "factory/contracts/factory-job.schema.json",
    "factory/contracts/review-report.schema.json",
)
_POLICY_PATHS = (
    "factory/governance/production-gates.yaml",
    "factory/governance/state-machine.yaml",
)
_TEMPLATE_PATHS = (
    "templates/job/JOB.md.tmpl",
    "templates/job/COMMANDER_INTENT.md.tmpl",
)
_WORKSHOP_FILES = (
    "workshop/README.md",
    "workshop/jobs/.gitkeep",
    "workshop/reviews/.gitkeep",
)
_WORKSHOP_RULES = (
    "jobs/*",
    "reviews/*",
    "!jobs/.gitkeep",
    "!reviews/.gitkeep",
)
_DEPENDENCY_NAME = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[([^\]]+)\])?\s*(.*)$"
)
_MINIMUM_VERSION = re.compile(r"(?:^|,)\s*>=\s*([0-9]+(?:\.[0-9]+)*)")


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Stable, immutable result of one repository verification pass."""

    ok: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]


def _path(root: Path, relative: str) -> Path:
    return root.joinpath(*relative.split("/"))


def _read_text(
    root: Path,
    relative: str,
    failures: list[str],
) -> str | None:
    candidate = _path(root, relative)
    try:
        if not candidate.is_file():
            failures.append(f"missing:{relative}")
            return None
        return candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        failures.append(f"malformed:{relative}:invalid-utf8")
    except OSError:
        failures.append(f"unreadable:{relative}")
    return None


def _strict_json(text: str) -> object:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-standard JSON constant: {constant}")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
        document: dict[str, object] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError(f"duplicate JSON object key: {key}")
            document[key] = value
        return document

    return json.loads(
        text,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicate_keys,
    )


def _verify_schemas(
    root: Path,
    checks: list[str],
    failures: list[str],
) -> dict[str, Mapping[str, Any]]:
    loaded_schemas: dict[str, Mapping[str, Any]] = {}
    for relative in _SCHEMA_PATHS:
        text = _read_text(root, relative, failures)
        if text is None:
            continue
        try:
            document = _strict_json(text)
        except (json.JSONDecodeError, ValueError):
            failures.append(f"malformed:{relative}:invalid-json")
            continue
        if not isinstance(document, Mapping):
            failures.append(f"malformed:{relative}:not-mapping")
            continue
        if document.get("$schema") != _DRAFT_2020_12:
            failures.append(f"malformed:{relative}:wrong-draft")
            continue
        try:
            Draft202012Validator.check_schema(document)
        except SchemaError:
            failures.append(f"malformed:{relative}:invalid-schema")
            continue
        except Exception:
            failures.append(f"malformed:{relative}:schema-check-failed")
            continue
        loaded_schemas[relative] = document
        checks.append(f"verified:{relative}")
    return loaded_schemas


def _compact_detail(error: Exception) -> str:
    detail = re.sub(r"\s+", " ", str(error)).strip()
    return detail or error.__class__.__name__


def _verify_policies(
    root: Path,
    schemas: Mapping[str, Mapping[str, Any]],
    checks: list[str],
    failures: list[str],
) -> None:
    for relative in _POLICY_PATHS:
        text = _read_text(root, relative, failures)
        if text is None:
            continue
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError:
            failures.append(f"malformed:{relative}:invalid-yaml")
            continue
        if not isinstance(document, Mapping):
            failures.append(f"malformed:{relative}:not-mapping")
            continue
        try:
            if relative.endswith("production-gates.yaml"):
                validate_production_gate_policy(document)
            else:
                factory_job_schema = schemas.get(
                    "factory/contracts/factory-job.schema.json"
                )
                if factory_job_schema is None:
                    failures.append(
                        f"unverified:{relative}:factory-job-schema-unavailable"
                    )
                    continue
                validate_state_machine_policy(
                    document,
                    factory_job_schema=factory_job_schema,
                )
        except Exception as exc:
            failures.append(
                f"malformed:{relative}:invalid-policy:{_compact_detail(exc)}"
            )
            continue
        checks.append(f"verified:{relative}")


def _canonical_dependency_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in value.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _dependency_meets_minimum(
    dependencies: object,
    expected_name: str,
    expected_minimum: str,
    *,
    required_extra: str | None = None,
) -> bool:
    if not isinstance(dependencies, list):
        return False
    canonical_expected = _canonical_dependency_name(expected_name)
    for item in dependencies:
        if not isinstance(item, str):
            continue
        requirement, _, _marker = item.partition(";")
        match = _DEPENDENCY_NAME.fullmatch(requirement)
        if match is None:
            continue
        name, raw_extras, specifiers = match.groups()
        if _canonical_dependency_name(name) != canonical_expected:
            continue
        extras = {
            extra.strip().lower()
            for extra in (raw_extras or "").split(",")
            if extra.strip()
        }
        if required_extra is not None and required_extra.lower() not in extras:
            continue
        minimums = _MINIMUM_VERSION.findall(specifiers)
        if any(
            _version_tuple(minimum) >= _version_tuple(expected_minimum)
            for minimum in minimums
        ):
            return True
    return False


def _declares_python_311_floor(requirement: object) -> bool:
    if not isinstance(requirement, str):
        return False
    minimums = _MINIMUM_VERSION.findall(requirement)
    return any(_version_tuple(value) == (3, 11) for value in minimums)


def _patterns_cover(filename: str, patterns: object) -> bool:
    return isinstance(patterns, list) and any(
        isinstance(pattern, str) and fnmatch.fnmatchcase(filename, pattern)
        for pattern in patterns
    )


def _assigned_version(text: str) -> str | None:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return None
    for statement in module.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in targets
        ):
            continue
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def _verify_metadata(
    root: Path,
    checks: list[str],
    failures: list[str],
) -> None:
    pyproject_text = _read_text(root, "pyproject.toml", failures)
    pyproject: Mapping[str, Any] | None = None
    project_version: str | None = None
    metadata_failures: list[str] = []
    if pyproject_text is not None:
        try:
            parsed = tomllib.loads(pyproject_text)
        except tomllib.TOMLDecodeError:
            failures.append("malformed:pyproject.toml:invalid-toml")
        else:
            if not isinstance(parsed, Mapping):
                failures.append("malformed:pyproject.toml:not-mapping")
            else:
                pyproject = parsed

    if pyproject is not None:
        project = pyproject.get("project")
        if not isinstance(project, Mapping):
            metadata_failures.append("invalid:pyproject.toml:project")
            project = {}
        if project.get("name") != "commander-intent-agent-factory":
            metadata_failures.append("invalid:pyproject.toml:project.name")
        raw_version = project.get("version")
        if not isinstance(raw_version, str) or not raw_version.strip():
            metadata_failures.append("invalid:pyproject.toml:project.version")
        else:
            project_version = raw_version
        requires_python = project.get("requires-python")
        if not _declares_python_311_floor(requires_python):
            metadata_failures.append(
                "invalid:pyproject.toml:project.requires-python"
            )
        dependencies = project.get("dependencies")
        if not _dependency_meets_minimum(dependencies, "PyYAML", "6.0"):
            metadata_failures.append(
                "invalid:pyproject.toml:project.dependencies:PyYAML"
            )
        if not _dependency_meets_minimum(
            dependencies,
            "jsonschema",
            "4.21",
            required_extra="format",
        ):
            metadata_failures.append(
                "invalid:pyproject.toml:project.dependencies:jsonschema[format]"
            )

        scripts = project.get("scripts")
        if (
            not isinstance(scripts, Mapping)
            or scripts.get("commander-factory") != "factory.cli.main:main"
        ):
            metadata_failures.append(
                "invalid:pyproject.toml:project.scripts.commander-factory"
            )

        tool = pyproject.get("tool")
        setuptools = tool.get("setuptools") if isinstance(tool, Mapping) else None
        package_data = (
            setuptools.get("package-data")
            if isinstance(setuptools, Mapping)
            else None
        )
        find_config = (
            setuptools.get("packages", {}).get("find")
            if isinstance(setuptools, Mapping)
            and isinstance(setuptools.get("packages"), Mapping)
            else None
        )
        includes = (
            find_config.get("include")
            if isinstance(find_config, Mapping)
            else None
        )
        if not isinstance(includes, list) or not any(
            isinstance(pattern, str)
            and fnmatch.fnmatchcase("factory", pattern)
            for pattern in includes
        ):
            metadata_failures.append(
                "invalid:pyproject.toml:package-discovery:factory"
            )

        package_requirements = (
            ("factory.contracts", _SCHEMA_PATHS),
            ("factory.governance", _POLICY_PATHS),
        )
        for package, paths in package_requirements:
            patterns = (
                package_data.get(package)
                if isinstance(package_data, Mapping)
                else None
            )
            for relative in paths:
                filename = relative.rsplit("/", 1)[-1]
                if not _patterns_cover(filename, patterns):
                    metadata_failures.append(
                        f"invalid:pyproject.toml:package-data:{relative}"
                    )

        data_files = (
            setuptools.get("data-files")
            if isinstance(setuptools, Mapping)
            else None
        )
        template_target = "share/commander-intent-agent-factory/templates/job"
        template_entries = (
            data_files.get(template_target)
            if isinstance(data_files, Mapping)
            else None
        )
        for relative in _TEMPLATE_PATHS:
            if (
                not isinstance(template_entries, list)
                or relative not in template_entries
            ):
                metadata_failures.append(
                    f"invalid:pyproject.toml:data-files:{relative}"
                )

        if not metadata_failures:
            checks.append("verified:pyproject.toml")
        failures.extend(metadata_failures)

    init_text = _read_text(root, "factory/__init__.py", failures)
    if init_text is not None:
        package_version = _assigned_version(init_text)
        if package_version is None:
            failures.append("malformed:factory/__init__.py:version")
        elif project_version is not None and package_version != project_version:
            failures.append("mismatch:factory/__init__.py:version")
        elif project_version is not None:
            checks.append("verified:factory/__init__.py-version")

    for relative in _TEMPLATE_PATHS:
        template_text = _read_text(root, relative, failures)
        if template_text is None:
            continue
        if not template_text.strip():
            failures.append(f"malformed:{relative}:empty")
            continue
        checks.append(f"verified:{relative}")


def _effective_ignore_lines(text: str) -> tuple[str, ...]:
    return tuple(
        stripped
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    )


def _gitignore_state(patterns: Sequence[str], relative: str) -> bool:
    ignored = False
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        pattern = pattern.removeprefix("/")
        if not pattern:
            continue
        if fnmatch.fnmatchcase(relative, pattern):
            ignored = not negated
    return ignored


def _verify_workshop(
    root: Path,
    checks: list[str],
    failures: list[str],
) -> None:
    for relative in _WORKSHOP_FILES:
        text = _read_text(root, relative, failures)
        if text is None:
            continue
        if relative.endswith("README.md") and not text.strip():
            failures.append(f"malformed:{relative}:empty")
            continue
        checks.append(f"verified:{relative}")

    relative = "workshop/.gitignore"
    ignore_text = _read_text(root, relative, failures)
    if ignore_text is None:
        return
    patterns = _effective_ignore_lines(ignore_text)
    local_failures: list[str] = []
    for required in _WORKSHOP_RULES:
        if required not in patterns:
            local_failures.append(
                f"invalid:{relative}:missing-rule:{required}"
            )

    semantic_examples = (
        ("jobs/private-job/status.json", True),
        ("reviews/private-review/status.json", True),
        ("jobs/.gitkeep", False),
        ("reviews/.gitkeep", False),
    )
    for sample, expected in semantic_examples:
        actual = _gitignore_state(patterns, sample)
        if actual == expected:
            continue
        outcome = "must-be-ignored" if expected else "must-not-be-ignored"
        local_failures.append(f"invalid:{relative}:{outcome}:{sample}")

    if local_failures:
        failures.extend(local_failures)
        return
    checks.append(f"verified:{relative}")
    checks.append("verified:workshop-ignore-semantics")


def verify_repository(root: Path) -> VerificationReport:
    """Verify repository structure at ``root`` without writing or fallback."""
    injected_root = Path(root)
    checks: list[str] = []
    failures: list[str] = []
    schemas = _verify_schemas(injected_root, checks, failures)
    _verify_policies(injected_root, schemas, checks, failures)
    _verify_metadata(injected_root, checks, failures)
    _verify_workshop(injected_root, checks, failures)
    return VerificationReport(
        ok=not failures,
        checks=tuple(checks),
        failures=tuple(failures),
    )


__all__ = ["VerificationReport", "verify_repository"]
