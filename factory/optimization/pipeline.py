from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from factory.errors import FactoryError, GateBlockedError
from factory.governance import transition
from factory.optimization.diff import DiffReport, compare_trees
from factory.optimization.workspace import CandidateManifest
from factory.production import load_job, mark_status_layer, save_checkpoint
from factory.review.snapshot import snapshot_tree


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    ready: bool
    job: dict
    diff: DiffReport
    validation_errors: tuple[str, ...]


def _advance(job_dir: Path, job: dict, target: str, refs: list[str]) -> dict:
    now = datetime.now(timezone.utc)
    prior = datetime.fromisoformat(job["updated_at"])
    if now <= prior:
        now = prior + timedelta(microseconds=1)
    updated = transition(job, target, trigger=f"optimize_{target.lower()}", evidence=refs, now=now)
    save_checkpoint(job_dir, updated, {"kind": "optimization_state", "ref": refs[0], "status": "verified", "at": updated["updated_at"]})
    return load_job(job_dir)


def default_candidate_validator(candidate: Path) -> list[str]:
    snapshot = snapshot_tree(candidate)
    paths = {item.path for item in snapshot.files}
    errors = []
    for required in ("COMMANDER_INTENT.md", "AGENT_SPEC.yaml"):
        if required not in paths:
            errors.append(f"missing:{required}")
    if snapshot.skipped_links or snapshot.skipped_unreadable:
        errors.append("unsafe candidate entries")
    return errors


def finalize_optimization(
    job_dir: Path,
    manifest: CandidateManifest,
    validator: Callable[[Path], list[str]] = default_candidate_validator,
) -> OptimizationResult:
    job = load_job(job_dir)
    if job["mode"] != "OPTIMIZE" or job["status"] != "OPTIMIZING":
        raise GateBlockedError("optimization job must be OPTIMIZING")
    if snapshot_tree(manifest.source_path).tree_hash != manifest.source_hash:
        raise FactoryError("optimization source changed before finalization")
    candidate_before = snapshot_tree(manifest.candidate_path)
    diff = compare_trees(manifest.source_path, manifest.candidate_path)
    if snapshot_tree(manifest.candidate_path).tree_hash != candidate_before.tree_hash:
        raise FactoryError("optimization candidate changed while computing diff")
    job = _advance(
        job_dir,
        job,
        "VALIDATING",
        [manifest.source_hash, candidate_before.tree_hash, diff.summary],
    )
    errors = tuple(validator(manifest.candidate_path))
    if not diff.added and not diff.modified and not diff.deleted:
        errors += ("candidate has no changes",)
    candidate_after_validation = snapshot_tree(manifest.candidate_path)
    if candidate_after_validation.tree_hash != candidate_before.tree_hash:
        errors += ("candidate changed during validation",)
    if errors:
        job = _advance(job_dir, job, "BLOCKED", list(errors))
        return OptimizationResult(False, job, diff, errors)
    if snapshot_tree(manifest.source_path).tree_hash != manifest.source_hash:
        raise FactoryError("optimization source changed during validation")
    if not job["status_layers"]["local_generated"]:
        job = mark_status_layer(job, "local_generated", str(manifest.candidate_path))
        save_checkpoint(job_dir, job, {"kind": "optimization_candidate", "ref": str(manifest.candidate_path), "status": "verified", "at": job["updated_at"]})
        job = load_job(job_dir)
    if not job["status_layers"]["local_validated"]:
        job = mark_status_layer(job, "local_validated", candidate_before.tree_hash)
        save_checkpoint(job_dir, job, {"kind": "optimization_validation", "ref": candidate_before.tree_hash, "status": "verified", "at": job["updated_at"]})
        job = load_job(job_dir)
    job = _advance(job_dir, job, "CANDIDATE_READY", [candidate_before.tree_hash, diff.summary])
    return OptimizationResult(True, job, diff, ())
