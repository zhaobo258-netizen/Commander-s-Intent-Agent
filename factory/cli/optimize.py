from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from factory.cli.create import load_mapping
from factory.errors import GateBlockedError
from factory.governance import transition
from factory.optimization import CandidateManifest, compare_trees, finalize_optimization, prepare_candidate
from factory.production import load_job, save_checkpoint


def _advance(job_dir: Path, job: dict, target: str, ref: str) -> dict:
    now = datetime.now(timezone.utc)
    prior = datetime.fromisoformat(job["updated_at"])
    if now <= prior:
        now = prior + timedelta(microseconds=1)
    updated = transition(job, target, trigger=f"cli_optimize_{target.lower()}", evidence=[ref], now=now)
    save_checkpoint(job_dir, updated, {"kind": "optimization_state", "ref": ref, "status": "verified", "at": updated["updated_at"]})
    return load_job(job_dir)


def _to_proposed(job_dir: Path, job: dict, plan_ref: str) -> dict:
    path = ("REVIEW_INTAKE", "REVIEWING", "REVIEW_READY", "OPTIMIZATION_PROPOSED")
    if job["status"] == "OPTIMIZATION_PROPOSED":
        return job
    start = -1 if job["status"] == "NEW" else path.index(job["status"])
    for target in path[start + 1:]:
        job = _advance(job_dir, job, target, plan_ref)
    return job


def optimize_prepare_payload(job_dir: Path, plan_path: Path, output: Path, approve: bool) -> dict:
    plan = load_mapping(plan_path, "optimization plan")
    job = load_job(job_dir)
    if job["mode"] != "OPTIMIZE":
        raise GateBlockedError("optimize-prepare requires an OPTIMIZE job")
    # Approval is validated before any state transition, checkpoint, or
    # candidate directory is created, so a blocked request leaves the job
    # exactly as it was.
    if not approve or not plan.get("approved_by_user"):
        raise GateBlockedError("optimization requires explicit --approve and approved plan")
    job = _to_proposed(job_dir, job, str(plan_path))
    if job["status"] == "OPTIMIZATION_PROPOSED":
        timestamp = datetime.now(timezone.utc).isoformat()
        job["approvals"].append({"id": "optimization-approval", "status": "approved", "requested_at": timestamp, "resolved_at": timestamp, "ref": str(plan_path)})
        save_checkpoint(job_dir, job, {"kind": "user_approval", "ref": str(plan_path), "status": "verified", "at": job["updated_at"]})
        job = load_job(job_dir)
        job = _advance(job_dir, job, "OPTIMIZATION_APPROVED", str(plan_path))
    manifest = prepare_candidate(job, plan, output)
    job = _advance(job_dir, job, "OPTIMIZING", str(manifest.candidate_path))
    manifest_path = Path(job_dir) / "reports" / "optimization-candidate.json"
    manifest_path.write_text(json.dumps({"source_path": str(manifest.source_path), "source_hash": manifest.source_hash, "candidate_path": str(manifest.candidate_path), "plan_hash": manifest.plan_hash}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"candidate_path": str(manifest.candidate_path), "manifest_path": str(manifest_path), "job_state": job["status"], "source_hash": manifest.source_hash}


def optimize_diff_payload(baseline: Path, candidate: Path) -> dict:
    return asdict(compare_trees(baseline, candidate))


def optimize_finalize_payload(job_dir: Path) -> dict:
    data = json.loads((Path(job_dir) / "reports" / "optimization-candidate.json").read_text(encoding="utf-8"))
    manifest = CandidateManifest(Path(data["source_path"]), data["source_hash"], Path(data["candidate_path"]), data["plan_hash"])
    result = finalize_optimization(job_dir, manifest)
    return {"ready": result.ready, "job_state": result.job["status"], "diff": asdict(result.diff), "validation_errors": list(result.validation_errors), "status_layers": result.job["status_layers"]}
