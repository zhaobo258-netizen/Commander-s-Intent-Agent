from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from factory.contracts import validate_document
from factory.errors import ContractValidationError
from factory.review.models import ReviewReport


@dataclass(frozen=True, slots=True)
class WrittenReview:
    report: ReviewReport
    json_path: Path
    markdown_path: Path


def _document(report: ReviewReport) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    evidence = []
    findings = []
    for finding in report.findings:
        finding_evidence = []
        for ref in finding.evidence:
            item = {
                "kind": "review_file",
                "ref": f"{ref.path}:{ref.sha256}",
                "status": ref.status,
                "at": now,
                "path": ref.path,
                "line_start": ref.line_start,
                "line_end": ref.line_end,
                "sha256": ref.sha256,
            }
            finding_evidence.append(item)
            evidence.append(item)
        findings.append({
            "id": finding.id,
            "severity": finding.severity,
            "title": finding.title,
            "impact": finding.impact,
            "recommendation": finding.recommendation,
            "evidence": finding_evidence,
            "evidence_status": finding.evidence_status,
        })
    layers = [
        {"name": name, "status": details["status"], "notes": f"score={details['score']}"}
        for name, details in report.quality.items()
        if name != "grade"
    ]
    return {
        "schema_version": "1.0",
        "target": {"kind": "directory", "ref": report.target},
        "scope": list(report.scope),
        "evidence": evidence,
        "findings": findings,
        "quality": {"layers": layers},
        "verdict": "blocked" if any(f.severity in {"P0", "P1"} for f in report.findings) else "provisional",
        "status_layers": report.status_layers,
        "unverified": list(report.unverified),
    }


def write_review_report(job_dir: Path, report: ReviewReport) -> WrittenReview:
    reports = Path(job_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    document = _document(report)
    issues = validate_document("review-report", document)
    if issues:
        raise ContractValidationError("invalid review report: " + ", ".join(f"{i.path}:{i.code}" for i in issues))
    json_path = reports / "review-report.json"
    markdown_path = reports / "review-report.md"
    json_path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    verdict = document["verdict"]
    lines = [f"# Review verdict: {verdict}", "", f"Baseline: `{report.baseline_hash}`", "", "## Findings", ""]
    lines.extend(f"- **{f.severity} {f.title}** — {f.impact} Recommendation: {f.recommendation}" for f in report.findings)
    if not report.findings:
        lines.append("- No structural findings.")
    lines += ["", "## Quality", "", "Grade: provisional", "", "## Unverified", ""]
    lines.extend(f"- {item}" for item in report.unverified)
    lines += ["", "## Truth layers", ""]
    lines.extend(f"- `{key}`: `{str(value).lower()}`" for key, value in report.status_layers.items())
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return WrittenReview(report, json_path, markdown_path)
