from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from factory.errors import FactoryError, GateBlockedError
from factory.governance import load_policy, transition
from factory.production import load_job, save_checkpoint
from factory.review.evaluator import review_agent
from factory.review.report import WrittenReview, write_review_report
from factory.review.snapshot import snapshot_tree, verify_unchanged


def _advance(job_dir: Path, job: dict, target: str, evidence: list[str]) -> dict:
    now = datetime.now(timezone.utc)
    previous = datetime.fromisoformat(job["updated_at"])
    if now <= previous:
        now = previous + timedelta(microseconds=1)
    updated = transition(job, target, trigger=f"review_{target.lower()}", evidence=evidence, now=now)
    save_checkpoint(job_dir, updated, {"kind": "review_state", "ref": evidence[0], "status": "verified", "at": updated["updated_at"]})
    return load_job(job_dir)


def run_review(job_dir: Path, target: Path) -> WrittenReview:
    job = load_job(job_dir)
    if job["mode"] != "REVIEW":
        raise GateBlockedError("review pipeline requires a REVIEW job")
    if job["status"] == "NEW":
        job = _advance(job_dir, job, "REVIEW_INTAKE", [str(Path(target))])
    if job["status"] != "REVIEW_INTAKE":
        raise GateBlockedError("review job must be in REVIEW_INTAKE")
    before = snapshot_tree(target)
    job = _advance(job_dir, job, "REVIEWING", [before.tree_hash])
    report = review_agent(target, load_policy("evaluation-policy"))
    written = write_review_report(job_dir, report)
    after = snapshot_tree(target)
    if not verify_unchanged(before, after):
        raise FactoryError("review target changed during read-only review")
    _advance(job_dir, job, "REVIEW_READY", [before.tree_hash, after.tree_hash, str(written.json_path)])
    return written
