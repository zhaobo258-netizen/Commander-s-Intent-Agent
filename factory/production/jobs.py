"""Create, persist, and resume private factory jobs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from sysconfig import get_path
from typing import cast

from factory.contracts import ValidationIssue, validate_document
from factory.errors import (
    ContractValidationError,
    FactoryError,
    TransitionError,
    UnsafePathError,
)
from factory.governance.state_machine import validate_lifecycle_snapshot
from factory.serialization import strict_json_loads


_JOB_DIRECTORIES = ("intake", "evidence", "reports", "output")
_DISTRIBUTION_NAME = "commander-intent-agent-factory"
_DISTRIBUTION_TEMPLATE_PARTS = (
    "share",
    _DISTRIBUTION_NAME,
    "templates",
    "job",
)
_IDENTITY_FIELDS = ("schema_version", "job_id", "mode", "name", "created_at")
_MISSING = object()
_MODE_CONTAINERS = {
    "CREATE": "jobs",
    "REVIEW": "reviews",
    "OPTIMIZE": "reviews",
}
_TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "templates" / "job"
_INSTALLED_TEMPLATE_ROOT = (
    Path(get_path("data"))
    / "share"
    / "commander-intent-agent-factory"
    / "templates"
    / "job"
)


def _target_template_root() -> Path:
    """Return wheel data beside a package installed with ``pip --target``."""
    return (
        Path(__file__).resolve().parents[2]
        / "share"
        / "commander-intent-agent-factory"
        / "templates"
        / "job"
    )


def _metadata_template_paths(filename: str) -> tuple[Path, ...]:
    try:
        installed_distribution = distribution(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return ()

    matches: list[Path] = []
    expected_suffix = (*_DISTRIBUTION_TEMPLATE_PARTS, filename)
    for record in installed_distribution.files or ():
        if tuple(Path(str(record)).parts[-len(expected_suffix) :]) != expected_suffix:
            continue
        try:
            located = Path(installed_distribution.locate_file(record))
            if located.is_file():
                matches.append(located)
        except (OSError, TypeError, ValueError):
            continue
    return tuple(matches)


def _contract_error(
    context: str,
    issues: Sequence[ValidationIssue],
) -> ContractValidationError:
    rendered = ", ".join(f"{issue.path}:{issue.code}" for issue in issues)
    return ContractValidationError(
        f"invalid factory-job contract for {context}: {rendered}"
    )


def _validate_job(job: object, context: str) -> None:
    if not isinstance(job, Mapping):
        raise ContractValidationError(
            f"invalid factory-job contract for {context}: document must be a mapping"
        )
    issues = validate_document("factory-job", job)
    if issues:
        raise _contract_error(context, issues)


def _validate_job_lifecycle(job: Mapping, context: str) -> None:
    try:
        validate_lifecycle_snapshot(job)
    except TransitionError as exc:
        raise ContractValidationError(
            f"invalid lifecycle snapshot for {context}: {exc}"
        ) from exc


def _validate_job_snapshot(job: object, context: str) -> None:
    _validate_job(job, context)
    _validate_job_lifecycle(cast(Mapping, job), context)


def _validate_component(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UnsafePathError(f"unsafe {label}: must be a non-empty string")
    if value != value.strip():
        raise UnsafePathError(f"unsafe {label}: surrounding whitespace is not allowed")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise UnsafePathError(
            f"unsafe {label}: value must be valid UTF-8"
        ) from exc
    if (
        "/" in value
        or "\\" in value
        or ".." in value
        or Path(value).is_absolute()
        or any(ord(character) < 32 for character in value)
    ):
        raise UnsafePathError(f"unsafe {label}: path traversal is not allowed")
    return value


def _require_aware_datetime(now: object) -> datetime:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise ContractValidationError(
            "job creation time must be a timezone-aware datetime"
        )
    return now


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_job_path(
    workshop_root: Path,
    mode: str,
    name: str,
    job_id: str,
) -> tuple[Path, Path]:
    root = Path(workshop_root)
    try:
        resolved_root = root.resolve(strict=False)
        container = root / _MODE_CONTAINERS[mode]
        job_dir = container / f"{job_id}-{name}"
        resolved_container = container.resolve(strict=False)
        resolved_job_dir = job_dir.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise UnsafePathError(f"could not resolve workshop job path: {exc}") from exc

    if not _is_within(resolved_container, resolved_root) or not _is_within(
        resolved_job_dir, resolved_root
    ):
        raise UnsafePathError("unsafe job path: resolved path is outside workshop root")

    if root.exists() and not root.is_dir():
        raise FactoryError(f"workshop root is not a directory: {root}")
    if container.exists() and not container.is_dir():
        raise UnsafePathError(f"unsafe job container: {container}")
    if job_dir.exists() or job_dir.is_symlink():
        raise FactoryError(f"factory job already exists: {job_dir}")
    return root, job_dir


def _render_template(filename: str, values: Mapping[str, str]) -> str:
    candidates = (
        _TEMPLATE_ROOT / filename,
        *_metadata_template_paths(filename),
        _target_template_root() / filename,
        _INSTALLED_TEMPLATE_ROOT / filename,
    )
    for template_path in candidates:
        if not template_path.is_file():
            continue
        try:
            template = template_path.read_text(encoding="utf-8")
            return template.format_map(values)
        except (OSError, KeyError, ValueError) as exc:
            raise FactoryError(
                f"could not render job template {template_path}: {exc}"
            ) from exc
    searched = ", ".join(str(path) for path in candidates)
    raise FactoryError(f"could not find job template {filename}; searched: {searched}")


def _fsync_parent(path: Path) -> None:
    """Best-effort sync of the directory entry after atomic replacement."""
    directory_descriptor: int | None = None
    try:
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        os.fsync(directory_descriptor)
    except OSError:
        # Some filesystems do not support directory fsync. The replaced file is
        # already complete and valid; durability is improved where supported.
        pass
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _atomic_write_json(path: Path, document: Mapping) -> None:
    try:
        payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            f"factory-job status is not JSON-compatible UTF-8: {exc}"
        ) from exc

    temporary_path: Path | None = None
    try:
        file_descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f"{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_parent(path)
    except OSError as exc:
        raise FactoryError(f"atomic status write failed for {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _initial_job(mode: str, name: str, job_id: str, now: datetime) -> dict:
    timestamp = now.isoformat()
    return {
        "schema_version": "1.0",
        "job_id": job_id,
        "mode": mode,
        "name": name,
        "status": "NEW",
        "scope": {
            "summary": f"Private {mode.lower()} factory job for {name}",
            "target_refs": [],
        },
        "created_at": timestamp,
        "updated_at": timestamp,
        "checkpoint": {
            "sequence": 0,
            "state": "NEW",
            "next_action": (
                "begin_discovery" if mode == "CREATE" else "begin_review_intake"
            ),
            "updated_at": timestamp,
            "evidence_ref": None,
        },
        "missing_items": [],
        "approvals": [],
        "status_layers": {
            "local_generated": False,
            "local_validated": False,
            "installed": False,
            "published": False,
            "real_usage_verified": False,
        },
        "evidence": [],
        "transitions": [],
    }


def create_job(
    workshop_root: Path,
    mode: str,
    name: str,
    now: datetime,
    *,
    job_id: str,
) -> Path:
    """Create a new private job directory without overwriting existing work."""
    if mode not in _MODE_CONTAINERS:
        raise ContractValidationError(f"unknown factory job mode: {mode}")
    safe_name = _validate_component(name, "name")
    safe_job_id = _validate_component(job_id, "job_id")
    aware_now = _require_aware_datetime(now)
    root, job_dir = _safe_job_path(
        Path(workshop_root),
        mode,
        safe_name,
        safe_job_id,
    )

    values = {
        "job_id": safe_job_id,
        "name": safe_name,
        "mode": mode,
        "created_at": aware_now.isoformat(),
    }
    rendered_job = _render_template("JOB.md.tmpl", values)
    rendered_intent = _render_template("COMMANDER_INTENT.md.tmpl", values)
    job = _initial_job(mode, safe_name, safe_job_id, aware_now)
    _validate_job_snapshot(job, "new job")

    created_job_dir = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        job_dir.parent.mkdir(parents=True, exist_ok=True)
        job_dir.mkdir(exist_ok=False)
        created_job_dir = True
        for directory in _JOB_DIRECTORIES:
            (job_dir / directory).mkdir()
        (job_dir / "JOB.md").write_text(rendered_job, encoding="utf-8")
        (job_dir / "COMMANDER_INTENT.md").write_text(
            rendered_intent,
            encoding="utf-8",
        )
        _atomic_write_json(job_dir / "status.json", job)
    except FileExistsError as exc:
        raise FactoryError(f"factory job already exists: {job_dir}") from exc
    except Exception:
        if created_job_dir:
            shutil.rmtree(job_dir, ignore_errors=True)
        raise
    return job_dir


def load_job(job_dir: Path) -> dict:
    """Load and validate one persisted factory job status document."""
    status_path = Path(job_dir) / "status.json"
    try:
        raw_status = status_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ContractValidationError(f"missing status for factory job: {status_path}") from exc
    except UnicodeDecodeError as exc:
        raise ContractValidationError(
            f"malformed status for factory job {status_path}: invalid UTF-8"
        ) from exc
    except OSError as exc:
        raise ContractValidationError(
            f"could not read factory-job status {status_path}: {exc}"
        ) from exc

    try:
        loaded = strict_json_loads(raw_status)
    except (json.JSONDecodeError, ValueError) as exc:
        detail = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
        raise ContractValidationError(
            f"malformed status for factory job {status_path}: {detail}"
        ) from exc
    _validate_job_snapshot(loaded, str(status_path))
    return deepcopy(dict(loaded))


def _normalized_evidence(evidence: Mapping, default_at: object) -> dict:
    if not isinstance(evidence, Mapping):
        raise ContractValidationError("checkpoint evidence must be a mapping")
    normalized = deepcopy(dict(evidence))
    normalized.setdefault("status", "unverified")
    normalized.setdefault("at", default_at)
    return normalized


def _require_history_prefix(
    candidate: Mapping,
    persisted: Mapping,
    field: str,
    singular: str,
) -> None:
    candidate_records = candidate.get(field)
    persisted_records = persisted.get(field)
    if not isinstance(candidate_records, list) or not isinstance(
        persisted_records, list
    ):
        raise ContractValidationError(f"invalid {field} collection: must be a list")
    if (
        len(candidate_records) < len(persisted_records)
        or candidate_records[: len(persisted_records)] != persisted_records
    ):
        raise ContractValidationError(
            f"persisted {singular} prefix cannot be removed or rewritten"
        )


def _require_matching_identity(candidate: Mapping, persisted: Mapping) -> None:
    for field in _IDENTITY_FIELDS:
        if candidate.get(field, _MISSING) != persisted.get(field, _MISSING):
            raise ContractValidationError(
                f"factory job identity mismatch for {field}"
            )


def _audit_instant(value: object, field: str) -> datetime:
    try:
        if not isinstance(value, str):
            raise ValueError("timestamp must be a string")
        normalized = (
            f"{value[:-1]}+00:00"
            if value[-1:].lower() == "z"
            else value
        )
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone offset is required")
        return parsed
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            f"invalid audit timestamp for {field}: {value!r}"
        ) from exc


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            f"external_state must be canonical JSON-compatible UTF-8: {exc}"
        ) from exc


def _require_monotonic_snapshot(candidate: Mapping, persisted: Mapping) -> None:
    candidate_checkpoint = candidate["checkpoint"]
    persisted_checkpoint = persisted["checkpoint"]
    if candidate_checkpoint["sequence"] < persisted_checkpoint["sequence"]:
        raise ContractValidationError(
            "checkpoint sequence cannot regress persisted sequence"
        )

    audit_fields = (
        ("updated_at", candidate["updated_at"], persisted["updated_at"]),
        (
            "checkpoint.updated_at",
            candidate_checkpoint["updated_at"],
            persisted_checkpoint["updated_at"],
        ),
    )
    for field, candidate_value, persisted_value in audit_fields:
        if _audit_instant(candidate_value, field) < _audit_instant(
            persisted_value,
            f"persisted {field}",
        ):
            raise ContractValidationError(
                f"audit metadata regression for {field}"
            )

    candidate_has_external = "external_state" in candidate
    persisted_has_external = "external_state" in persisted
    external_matches = candidate_has_external == persisted_has_external
    if external_matches and candidate_has_external:
        external_matches = _canonical_json(candidate["external_state"]) == _canonical_json(
            persisted["external_state"]
        )
    if not external_matches:
        raise ContractValidationError(
            "external_state is resume-owned and must match persisted state exactly"
        )


def save_checkpoint(job_dir: Path, job: Mapping, evidence: Mapping) -> None:
    """Validate and atomically persist a copied job with new evidence."""
    if not isinstance(job, Mapping):
        raise ContractValidationError("checkpoint job must be a mapping")
    existing = load_job(Path(job_dir))
    persisted = deepcopy(dict(job))

    _require_matching_identity(persisted, existing)
    _require_history_prefix(persisted, existing, "evidence", "evidence")
    _require_history_prefix(persisted, existing, "transitions", "transition")

    checkpoint = persisted.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise ContractValidationError("invalid checkpoint: must be a mapping")
    normalized_checkpoint = deepcopy(dict(checkpoint))
    existing_checkpoint = existing["checkpoint"]
    for field in ("state", "updated_at", "evidence_ref"):
        normalized_checkpoint.setdefault(field, existing_checkpoint[field])
    evidence_record = _normalized_evidence(
        evidence,
        normalized_checkpoint.get("updated_at", persisted.get("updated_at")),
    )
    normalized_checkpoint["evidence_ref"] = evidence_record.get("ref")
    persisted["checkpoint"] = normalized_checkpoint

    existing_evidence = persisted.get("evidence")
    if not isinstance(existing_evidence, list):
        raise ContractValidationError("invalid evidence collection: must be a list")
    existing_evidence.append(evidence_record)

    _validate_job(persisted, "checkpoint save")
    _require_monotonic_snapshot(persisted, existing)
    _validate_job_lifecycle(persisted, "checkpoint save")
    _atomic_write_json(Path(job_dir) / "status.json", persisted)


def _require_string_json_keys(value: object, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(
                    f"external probe result requires string object keys at {path}"
                )
            _require_string_json_keys(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _require_string_json_keys(nested, f"{path}[{index}]")


def _json_mapping(value: object) -> dict:
    if not isinstance(value, Mapping):
        raise ContractValidationError("external probe result must be a mapping")
    _require_string_json_keys(value)
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        serialized.encode("utf-8")
        normalized = json.loads(serialized)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            f"external probe result must be JSON-compatible UTF-8: {exc}"
        ) from exc
    if not isinstance(normalized, dict):
        raise ContractValidationError("external probe result must be a JSON object")
    return normalized


def resume_job(
    job_dir: Path,
    external_probe: Callable[[Mapping], Mapping],
) -> dict:
    """Re-probe drifting external state and atomically persist the fresh result."""
    job = load_job(Path(job_dir))
    try:
        probed = external_probe(deepcopy(job))
    except Exception as exc:
        raise FactoryError(f"external probe failed: {exc}") from exc

    resumed = deepcopy(job)
    resumed["external_state"] = _json_mapping(probed)
    _validate_job_snapshot(resumed, "resumed job")
    _atomic_write_json(Path(job_dir) / "status.json", resumed)
    return deepcopy(resumed)
