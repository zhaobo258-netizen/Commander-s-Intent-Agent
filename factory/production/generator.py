"""Deterministically render an Agent candidate through an atomic staging tree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from string import Formatter

import yaml

from factory import __version__
from factory.contracts import ValidationIssue, validate_document
from factory.errors import ContractValidationError, FactoryError, GateBlockedError, UnsafePathError
from factory.governance import evaluate_production_gate, load_policy
from factory.production.blueprint import validate_blueprint_traceability
from factory.production.jobs import load_job
from factory.serialization import strict_json_loads


_TEMPLATE_FIELDS = {
    "README.md.tmpl": {"agent_name", "mission", "user_role", "user_scenario"},
    "COMMANDER_INTENT.md.tmpl": {"intent_yaml"},
    "ARCHITECTURE.md.tmpl": {
        "capabilities_markdown",
        "skills_markdown",
        "resources_yaml",
    },
    "WORKFLOW.md.tmpl": {"workflow_markdown"},
}
_STATUS_LAYERS = {
    "local_generated": True,
    "local_validated": False,
    "installed": False,
    "published": False,
    "real_usage_verified": False,
}
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class GenerationResult:
    output_path: Path
    manifest_path: Path
    created_paths: tuple[str, ...]


def _issues_message(kind: str, issues: tuple[ValidationIssue, ...]) -> str:
    rendered = ", ".join(f"{issue.path}:{issue.code}" for issue in issues)
    return f"invalid {kind} contract: {rendered}"


def _canonical_json(value: object, label: str) -> tuple[object, bytes]:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        payload = text.encode("utf-8")
        normalized = strict_json_loads(text)
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ContractValidationError(f"{label} must be JSON-compatible UTF-8") from exc
    return normalized, payload


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip()
    try:
        encoded = normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError("Agent name must be valid UTF-8") from exc
    base = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    base = base[:40].rstrip("-") or "agent"
    if base in _WINDOWS_RESERVED:
        base = f"agent-{base}"
    return f"{base}-{hashlib.sha256(encoded).hexdigest()[:8]}"


def _require_valid_document(kind: str, value: object) -> dict:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{kind} must be a mapping")
    normalized, _ = _canonical_json(value, kind)
    if not isinstance(normalized, dict):
        raise ContractValidationError(f"{kind} must be a mapping")
    issues = validate_document(kind, normalized)
    if issues:
        raise ContractValidationError(_issues_message(kind, issues))
    return normalized


def _validate_sources(intent: object, blueprint: object) -> tuple[dict, dict, dict[str, str]]:
    intent_snapshot = _require_valid_document("commander-intent", intent)
    blueprint_snapshot = _require_valid_document("agent-blueprint", blueprint)
    decision = evaluate_production_gate(intent_snapshot, load_policy("production-gates"))
    if not decision.ready:
        raise GateBlockedError("commander intent is not production-ready")
    expected_ref = {
        "name": intent_snapshot["metadata"]["name"],
        "version": intent_snapshot["metadata"]["version"],
    }
    if blueprint_snapshot["commander_intent_ref"] != expected_ref:
        raise ContractValidationError("blueprint commander intent reference does not match")
    validate_blueprint_traceability(blueprint_snapshot, intent_snapshot)
    for adapter in blueprint_snapshot["adapters"]:
        if adapter != {"name": "codex", "status": "declared"}:
            raise ContractValidationError(
                f"unsupported adapter declaration: {adapter.get('name', '<missing>')}"
            )
    _, intent_bytes = _canonical_json(intent_snapshot, "commander-intent")
    _, blueprint_bytes = _canonical_json(blueprint_snapshot, "agent-blueprint")
    return intent_snapshot, blueprint_snapshot, {
        "commander_intent": _sha256(intent_bytes),
        "agent_blueprint": _sha256(blueprint_bytes),
    }


def _validate_job_output(job_dir: Path) -> tuple[dict, Path]:
    path = Path(job_dir)
    if path.is_symlink():
        raise UnsafePathError("factory job directory must not be a symlink")
    job = load_job(path)
    resumable_states = {"PRODUCING", "VALIDATING", "CANDIDATE_READY"}
    if job["mode"] != "CREATE" or job["status"] not in resumable_states:
        raise GateBlockedError(
            "candidate generation requires a CREATE job in a generation state"
        )
    output_root = path / "output"
    if output_root.is_symlink():
        raise UnsafePathError("job output directory must not be a symlink")
    if not output_root.is_dir():
        raise FactoryError("job output directory is missing")
    try:
        output_root.resolve().relative_to(path.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise UnsafePathError("job output directory escapes the factory job") from exc
    return job, output_root


def _load_templates(template_root: Path) -> tuple[dict[str, str], str]:
    root = Path(template_root)
    if root.is_symlink() or not root.is_dir():
        raise UnsafePathError("Agent template root must be a real directory")
    resolved_root = root.resolve()
    loaded: dict[str, str] = {}
    digest = hashlib.sha256()
    for filename, allowed_fields in sorted(_TEMPLATE_FIELDS.items()):
        candidate = root / filename
        if candidate.is_symlink():
            raise UnsafePathError(f"Agent template must not be a symlink: {filename}")
        try:
            candidate.resolve(strict=True).relative_to(resolved_root)
            raw = candidate.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError) as exc:
            raise FactoryError(f"could not load Agent template: {filename}") from exc
        fields: set[str] = set()
        try:
            for _, field, format_spec, conversion in Formatter().parse(text):
                if field is None:
                    continue
                if not field or format_spec or conversion or not field.isidentifier():
                    raise ValueError("unsafe placeholder")
                fields.add(field)
        except ValueError as exc:
            raise ContractValidationError(f"invalid Agent template placeholders: {filename}") from exc
        if fields != allowed_fields:
            raise ContractValidationError(f"invalid Agent template placeholders: {filename}")
        digest.update(len(filename).to_bytes(4, "big"))
        digest.update(filename.encode("utf-8"))
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        loaded[filename] = text
    return loaded, f"sha256:{digest.hexdigest()}"


def _yaml(value: object) -> str:
    return yaml.safe_dump(
        value,
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    )


def _markdown_items(items: list[dict], detail_key: str) -> str:
    if not items:
        return "_None declared._"
    return "\n".join(
        f"- **{item['id']} — {item['name']}**: {item[detail_key]}"
        for item in items
    )


def _render_values(intent: dict, blueprint: dict) -> dict[str, str]:
    steps = blueprint["workflow"]["steps"]
    workflow = "\n".join(
        f"{index}. **{step['name']}** — {step['action']}"
        for index, step in enumerate(steps, start=1)
    ) or "_No workflow steps declared._"
    return {
        "agent_name": blueprint["metadata"]["name"],
        "mission": intent["mission"]["statement"],
        "user_role": intent["user"]["role"],
        "user_scenario": intent["user"]["scenario"],
        "intent_yaml": _yaml(intent),
        "capabilities_markdown": _markdown_items(
            blueprint["capabilities"], "description"
        ),
        "skills_markdown": _markdown_items(blueprint["skills"], "description"),
        "resources_yaml": _yaml(blueprint["resources"]),
        "workflow_markdown": workflow,
    }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _render_codex_adapter(root: Path, intent: dict, blueprint: dict) -> None:
    name = _slug(blueprint["metadata"]["name"])
    mission = " ".join(intent["mission"]["statement"].split())
    description = f"Use when carrying out this generated Agent mission: {mission}"
    skill = (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "---\n\n"
        f"# {blueprint['metadata']['name']}\n\n"
        "Read `COMMANDER_INTENT.md` and `AGENT_SPEC.yaml` before acting. "
        "Stay within declared authority, use only declared resources, and request human review at the configured stages.\n"
    )
    openai = (
        "interface:\n"
        f"  display_name: {json.dumps(blueprint['metadata']['name'], ensure_ascii=False)}\n"
        '  short_description: "Run this generated Agent with evidence-backed boundaries"\n'
        f"  default_prompt: {json.dumps(f'Use ${name} to carry out the confirmed mission within its declared authority.', ensure_ascii=False)}\n"
    )
    _write_text(root / "adapters" / "codex" / "SKILL.md", skill)
    _write_text(root / "adapters" / "codex" / "agents" / "openai.yaml", openai)


def _render_tree(
    staging: Path,
    intent: dict,
    blueprint: dict,
    templates: Mapping[str, str],
) -> dict[str, str]:
    values = _render_values(intent, blueprint)
    for template_name, output_name in (
        ("README.md.tmpl", "README.md"),
        ("COMMANDER_INTENT.md.tmpl", "COMMANDER_INTENT.md"),
        ("ARCHITECTURE.md.tmpl", "ARCHITECTURE.md"),
        ("WORKFLOW.md.tmpl", "WORKFLOW.md"),
    ):
        _write_text(staging / output_name, templates[template_name].format_map(values))
    _write_text(staging / "AGENT_SPEC.yaml", _yaml(blueprint))

    omitted = {"prompts": "not_modeled", "deployment": "not_modeled"}
    if blueprint["skills"]:
        _write_text(staging / "skills" / "catalog.yaml", _yaml(blueprint["skills"]))
    else:
        omitted["skills"] = "not_declared"
    if blueprint["resources"]["tools"]:
        _write_text(staging / "tools" / "tools.yaml", _yaml(blueprint["resources"]["tools"]))
    else:
        omitted["tools"] = "not_declared"
    if blueprint["resources"]["data"] or blueprint["resources"]["knowledge"]:
        _write_text(
            staging / "knowledge" / "resources.yaml",
            _yaml(
                {
                    "data": blueprint["resources"]["data"],
                    "knowledge": blueprint["resources"]["knowledge"],
                }
            ),
        )
    else:
        omitted["knowledge"] = "not_declared"
    if blueprint["evaluation"]["cases"]:
        _write_text(
            staging / "evaluation" / "cases.yaml",
            _yaml(blueprint["evaluation"]["cases"]),
        )
    else:
        omitted["evaluation"] = "not_declared"
    if blueprint["adapters"]:
        _render_codex_adapter(staging, intent, blueprint)
    else:
        omitted["adapters"] = "not_declared"
    return dict(sorted(omitted.items()))


def _tree_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            if (current_path / directory).is_symlink():
                raise UnsafePathError("candidate tree contains a symlink")
        for filename in filenames:
            path = current_path / filename
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise UnsafePathError("candidate tree contains a non-regular file")
            files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path.read_bytes())
        for path in _tree_files(root)
        if path.name != "factory-manifest.json"
    }


def _manifest(
    staging: Path,
    source_hashes: Mapping[str, str],
    template_hash: str,
    omitted: Mapping[str, str],
) -> dict:
    file_hashes = _file_hashes(staging)
    created_paths = sorted((*file_hashes, "factory-manifest.json"))
    return {
        "schema_version": "1.0",
        "generator_version": __version__,
        "source_hashes": dict(source_hashes),
        "template_set_hash": template_hash,
        "created_paths": created_paths,
        "file_hashes": file_hashes,
        "omitted_components": dict(omitted),
        "status_layers": dict(_STATUS_LAYERS),
    }


def _write_manifest(path: Path, manifest: Mapping) -> None:
    issues = validate_document("factory-manifest", manifest)
    if issues:
        raise ContractValidationError(_issues_message("factory-manifest", issues))
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    _write_text(path, payload)


def _existing_result(
    output: Path,
    source_hashes: Mapping[str, str],
    template_hash: str,
) -> GenerationResult:
    manifest_path = output / "factory-manifest.json"
    try:
        loaded = strict_json_loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("manifest is not an object")
        if validate_document("factory-manifest", loaded):
            raise ValueError("manifest contract drift")
        actual_paths = tuple(
            path.relative_to(output).as_posix() for path in _tree_files(output)
        )
        expected_paths = tuple(loaded["created_paths"])
        if actual_paths != expected_paths:
            raise ValueError("created path drift")
        if loaded["source_hashes"] != dict(source_hashes):
            raise ValueError("source drift")
        if loaded["template_set_hash"] != template_hash:
            raise ValueError("template drift")
        if loaded["status_layers"] != _STATUS_LAYERS:
            raise ValueError("status drift")
        if loaded["file_hashes"] != _file_hashes(output):
            raise ValueError("file drift")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise FactoryError("candidate output collision or drift detected") from exc
    return GenerationResult(output, manifest_path, actual_paths)


def generate_candidate(
    job_dir: Path,
    intent: Mapping,
    blueprint: Mapping,
    template_root: Path,
) -> GenerationResult:
    """Generate or verify one deterministic candidate without mutating job status."""
    _, output_root = _validate_job_output(Path(job_dir))
    intent_snapshot, blueprint_snapshot, source_hashes = _validate_sources(intent, blueprint)
    templates, template_hash = _load_templates(Path(template_root))
    output = output_root / _slug(blueprint_snapshot["metadata"]["name"])
    if output.is_symlink():
        raise UnsafePathError("candidate output must not be a symlink")
    if output.exists():
        if not output.is_dir():
            raise FactoryError("candidate output collision detected")
        return _existing_result(output, source_hashes, template_hash)

    lock = output.with_name(f"{output.name}.lock")
    lock_descriptor: int | None = None
    staging: Path | None = None
    try:
        try:
            lock_descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise FactoryError("candidate generation is already in progress") from exc
        if output.exists() or output.is_symlink():
            raise FactoryError("candidate output collision detected")
        staging = Path(
            tempfile.mkdtemp(prefix=f"{output.name}.staging-", dir=output_root)
        )
        omitted = _render_tree(staging, intent_snapshot, blueprint_snapshot, templates)
        manifest = _manifest(staging, source_hashes, template_hash, omitted)
        _write_manifest(staging / "factory-manifest.json", manifest)
        if tuple(manifest["created_paths"]) != tuple(
            path.relative_to(staging).as_posix() for path in _tree_files(staging)
        ):
            raise FactoryError("generated manifest does not match candidate tree")
        if output.exists() or output.is_symlink():
            raise FactoryError("candidate output collision detected")
        os.rename(staging, output)
        staging = None
    except BaseException:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if lock_descriptor is not None:
            os.close(lock_descriptor)
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass
    return _existing_result(output, source_hashes, template_hash)


__all__ = ["GenerationResult", "generate_candidate"]
