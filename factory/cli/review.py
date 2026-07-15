from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from factory.production import create_job
from factory.review.pipeline import run_review
from factory.errors import UnsafePathError


def _require_separate_paths(target: Path, workshop: Path) -> None:
    target_real = Path(target).resolve(strict=True)
    workshop_real = Path(workshop).resolve(strict=False)
    if (
        target_real == workshop_real
        or workshop_real.is_relative_to(target_real)
        or target_real.is_relative_to(workshop_real)
    ):
        raise UnsafePathError("review target and workshop must be separate trees")


def review_payload(target: Path, workshop: Path, job_id: str, name: str) -> dict:
    _require_separate_paths(target, workshop)
    job_dir = create_job(workshop, "REVIEW", name, datetime.now(timezone.utc), job_id=job_id)
    result = run_review(job_dir, target)
    return {
        "job_dir": str(job_dir),
        "json_report": str(result.json_path),
        "markdown_report": str(result.markdown_path),
        "baseline_hash": result.report.baseline_hash,
        "finding_count": len(result.report.findings),
        "grade": result.report.quality["grade"],
    }
