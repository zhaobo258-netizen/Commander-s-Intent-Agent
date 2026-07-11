from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from factory.errors import ContractValidationError, FactoryError, UnsafePathError
from factory.contracts import validate_document
from factory.governance import transition
from factory.production import load_job, save_checkpoint
from factory.production.blueprint import build_blueprint
from factory.production.generator import generate_candidate
from factory.serialization import strict_yaml_load


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates" / "agent"
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _producing_job(tmp_path: Path, name: str = "candidate-agent") -> Path:
    from factory.production import create_job

    job_dir = create_job(
        tmp_path / "workshop",
        "CREATE",
        name,
        NOW,
        job_id=f"job-{name}",
    )
    job = load_job(job_dir)
    for offset, target in enumerate(
        (
            "DISCOVERY",
            "INTERVIEWING",
            "INTENT_CONFIRMATION",
            "READY",
            "BLUEPRINTING",
            "PRODUCING",
        ),
        start=1,
    ):
        ref = f"evidence/{offset}-{target.lower()}.md"
        job = transition(
            job,
            target,
            trigger=f"test_{target.lower()}",
            evidence=[ref],
            now=NOW + timedelta(seconds=offset),
        )
        save_checkpoint(
            job_dir,
            job,
            {
                "kind": "state_transition",
                "ref": ref,
                "status": "verified",
                "at": job["updated_at"],
            },
        )
        job = load_job(job_dir)
    return job_dir


def _blueprint(
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision,
) -> dict:
    return build_blueprint(production_ready_intent, valid_design, ready_decision)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_generator_creates_declared_components_and_truthful_manifest(
    tmp_path: Path,
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision,
) -> None:
    valid_design["resources"]["tools"] = []
    blueprint = _blueprint(production_ready_intent, valid_design, ready_decision)
    job_dir = _producing_job(tmp_path)

    result = generate_candidate(job_dir, production_ready_intent, blueprint, TEMPLATES)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert validate_document("factory-manifest", manifest) == ()
    assert (result.output_path / "README.md").is_file()
    assert (result.output_path / "COMMANDER_INTENT.md").is_file()
    assert (result.output_path / "AGENT_SPEC.yaml").is_file()
    assert (result.output_path / "ARCHITECTURE.md").is_file()
    assert (result.output_path / "WORKFLOW.md").is_file()
    assert (result.output_path / "adapters/codex/SKILL.md").is_file()
    assert (result.output_path / "adapters/codex/agents/openai.yaml").is_file()
    assert not (result.output_path / "tools").exists()
    assert manifest["omitted_components"]["tools"] == "not_declared"
    assert manifest["omitted_components"]["prompts"] == "not_modeled"
    assert manifest["omitted_components"]["deployment"] == "not_modeled"
    assert manifest["status_layers"] == {
        "local_generated": True,
        "local_validated": False,
        "installed": False,
        "published": False,
        "real_usage_verified": False,
    }
    actual_paths = tuple(sorted(_tree_bytes(result.output_path)))
    assert result.created_paths == actual_paths
    assert tuple(manifest["created_paths"]) == actual_paths
    assert strict_yaml_load(
        (result.output_path / "AGENT_SPEC.yaml").read_text(encoding="utf-8")
    ) == blueprint
    assert load_job(job_dir)["status_layers"]["local_generated"] is False


def test_invalid_blueprint_leaves_no_partial_candidate_or_staging(
    tmp_path: Path,
    production_ready_intent: dict,
    valid_blueprint: dict,
) -> None:
    job_dir = _producing_job(tmp_path)
    invalid = copy.deepcopy(valid_blueprint)
    invalid.pop("workflow")

    with pytest.raises(ContractValidationError):
        generate_candidate(job_dir, production_ready_intent, invalid, TEMPLATES)

    assert not any((job_dir / "output").iterdir())


def test_same_input_is_idempotent_but_drifted_output_is_never_overwritten(
    tmp_path: Path,
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision,
) -> None:
    blueprint = _blueprint(production_ready_intent, valid_design, ready_decision)
    job_dir = _producing_job(tmp_path)
    first = generate_candidate(job_dir, production_ready_intent, blueprint, TEMPLATES)
    before = _tree_bytes(first.output_path)

    second = generate_candidate(job_dir, production_ready_intent, blueprint, TEMPLATES)
    assert second == first
    assert _tree_bytes(first.output_path) == before

    readme = first.output_path / "README.md"
    readme.write_text("drifted\n", encoding="utf-8")
    with pytest.raises(FactoryError, match="drift|collision"):
        generate_candidate(job_dir, production_ready_intent, blueprint, TEMPLATES)
    assert readme.read_text(encoding="utf-8") == "drifted\n"


def test_generation_is_deterministic_across_job_roots(
    tmp_path: Path,
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision,
) -> None:
    blueprint = _blueprint(production_ready_intent, valid_design, ready_decision)
    one = generate_candidate(
        _producing_job(tmp_path / "one", "same-agent"),
        production_ready_intent,
        blueprint,
        TEMPLATES,
    )
    two = generate_candidate(
        _producing_job(tmp_path / "two", "same-agent"),
        production_ready_intent,
        blueprint,
        TEMPLATES,
    )

    assert _tree_bytes(one.output_path) == _tree_bytes(two.output_path)


def test_unknown_adapter_fails_closed_without_partial_output(
    tmp_path: Path,
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision,
) -> None:
    valid_design["adapters"] = [{"name": "unknown-platform", "status": "declared"}]
    blueprint = _blueprint(production_ready_intent, valid_design, ready_decision)
    job_dir = _producing_job(tmp_path)

    with pytest.raises(ContractValidationError, match="unsupported adapter"):
        generate_candidate(job_dir, production_ready_intent, blueprint, TEMPLATES)

    assert not any((job_dir / "output").iterdir())


def test_symlinked_output_root_is_rejected_without_outside_write(
    tmp_path: Path,
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision,
) -> None:
    blueprint = _blueprint(production_ready_intent, valid_design, ready_decision)
    job_dir = _producing_job(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    output = job_dir / "output"
    output.rmdir()
    output.symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        generate_candidate(job_dir, production_ready_intent, blueprint, TEMPLATES)

    assert not any(outside.iterdir())


def test_dead_process_lock_is_recovered_for_resume(
    tmp_path: Path,
    production_ready_intent: dict,
    valid_design: dict,
    ready_decision,
) -> None:
    blueprint = _blueprint(production_ready_intent, valid_design, ready_decision)
    job_dir = _producing_job(tmp_path)
    output_root = job_dir / "output"
    from factory.production.generator import _slug

    lock = output_root / f"{_slug(blueprint['metadata']['name'])}.lock"
    lock.write_text(
        json.dumps({"pid": 999_999_999, "created_at": "2026-07-11T00:00:00+00:00"}),
        encoding="utf-8",
    )

    result = generate_candidate(job_dir, production_ready_intent, blueprint, TEMPLATES)

    assert result.manifest_path.is_file()
    assert not lock.exists()
