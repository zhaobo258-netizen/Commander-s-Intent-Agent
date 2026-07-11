from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from factory.production import create_job
from factory.review.pipeline import run_review


def review_payload(target: Path, workshop: Path, job_id: str, name: str) -> dict:
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
