"""Thin command handlers for the M2 CREATE and Codex-skill pipeline."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from factory.errors import ContractValidationError, GateBlockedError
from factory.governance import evaluate_production_gate, load_policy, transition
from factory.interview import next_question
from factory.production import (
    build_blueprint,
    check_codex_skill,
    generate_candidate,
    install_codex_skill,
    load_job,
    mark_status_layer,
    save_checkpoint,
    uninstall_codex_skill,
)
from factory.serialization import strict_json_loads, strict_yaml_load


def load_mapping(path: Path, label: str) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
        loaded = (
            strict_json_loads(text)
            if Path(path).suffix.lower() == ".json"
            else strict_yaml_load(text)
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractValidationError(f"could not load {label}: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise ContractValidationError(f"{label} must be a mapping")
    return dict(loaded)


def intent_decision(intent_path: Path):
    intent = load_mapping(intent_path, "commander intent")
    decision = evaluate_production_gate(intent, load_policy("production-gates"))
    return intent, decision


def next_question_payload(intent_path: Path) -> dict:
    intent, decision = intent_decision(intent_path)
    question = next_question(intent, decision)
    return {
        "decision": asdict(decision),
        "question": asdict(question) if question is not None else None,
    }


def validate_intent_payload(intent_path: Path) -> tuple[dict, int]:
    _, decision = intent_decision(intent_path)
    return asdict(decision), 0 if decision.ready else 2


def _save_transition(job_dir: Path, job: dict, target: str, ref: str) -> dict:
    now = datetime.now(timezone.utc)
    previous = datetime.fromisoformat(job["updated_at"])
    if now <= previous:
        now = previous + timedelta(microseconds=1)
    updated = transition(
        job,
        target,
        trigger=f"cli_generate_{target.lower()}",
        evidence=[ref],
        now=now,
    )
    save_checkpoint(
        job_dir,
        updated,
        {
            "kind": "state_transition",
            "ref": ref,
            "status": "verified",
            "at": updated["updated_at"],
        },
    )
    return load_job(job_dir)


def _advance_to_producing(job_dir: Path, job: dict, evidence_ref: str) -> dict:
    path = (
        "DISCOVERY",
        "INTERVIEWING",
        "INTENT_CONFIRMATION",
        "READY",
        "BLUEPRINTING",
        "PRODUCING",
    )
    if job["status"] == "PRODUCING":
        return job
    if job["status"] not in ("NEW", *path):
        raise GateBlockedError(f"CREATE job cannot generate from state {job['status']}")
    start = -1 if job["status"] == "NEW" else path.index(job["status"])
    for target in path[start + 1 :]:
        job = _save_transition(job_dir, job, target, evidence_ref)
    return job


def generate_payload(
    job_dir: Path,
    intent_path: Path,
    design_path: Path,
    template_root: Path,
) -> dict:
    intent, decision = intent_decision(intent_path)
    if not decision.ready:
        raise GateBlockedError("commander intent is not production-ready")
    design = load_mapping(design_path, "Agent design")
    blueprint = build_blueprint(intent, design, decision)
    job = load_job(job_dir)
    if job["mode"] != "CREATE":
        raise GateBlockedError("generate requires a CREATE job")
    evidence_ref = f"intent:{Path(intent_path).name};design:{Path(design_path).name}"
    job = _advance_to_producing(Path(job_dir), job, evidence_ref)
    result = generate_candidate(job_dir, intent, blueprint, template_root)

    if not job["status_layers"]["local_generated"]:
        job = mark_status_layer(job, "local_generated", str(result.manifest_path))
        save_checkpoint(
            job_dir,
            job,
            {
                "kind": "candidate_manifest",
                "ref": str(result.manifest_path),
                "status": "verified",
                "at": job["updated_at"],
            },
        )
        job = load_job(job_dir)
    if job["status"] == "PRODUCING":
        job = _save_transition(job_dir, job, "VALIDATING", str(result.manifest_path))
    if not job["status_layers"]["local_validated"]:
        job = mark_status_layer(job, "local_validated", str(result.manifest_path))
        save_checkpoint(
            job_dir,
            job,
            {
                "kind": "candidate_validation",
                "ref": str(result.manifest_path),
                "status": "verified",
                "at": job["updated_at"],
            },
        )
        job = load_job(job_dir)
    if job["status"] == "VALIDATING":
        job = _save_transition(job_dir, job, "CANDIDATE_READY", str(result.manifest_path))
    return {
        "job_state": job["status"],
        "output_path": str(result.output_path),
        "manifest_path": str(result.manifest_path),
        "created_paths": list(result.created_paths),
        "status_layers": job["status_layers"],
    }


def skill_install_payload(source: Path, codex_home: Path, mode: str) -> dict:
    target = install_codex_skill(source, codex_home, mode)
    return {"status": "installed", "target": str(target), "mode": mode}


def skill_check_payload(source: Path, codex_home: Path) -> dict:
    check = check_codex_skill(source, codex_home)
    payload = asdict(check)
    payload["target"] = str(check.target)
    return payload


def skill_uninstall_payload(source: Path, codex_home: Path) -> dict:
    uninstall_codex_skill(source, codex_home)
    return {"status": "not_installed"}


def json_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
