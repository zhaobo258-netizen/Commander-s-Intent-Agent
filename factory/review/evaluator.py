"""Evaluate only structural evidence observed in an Agent directory."""

from __future__ import annotations

from pathlib import Path

from factory.review.models import EvidenceRef, Finding, ReviewReport
from factory.review.snapshot import snapshot_tree
from factory.serialization import strict_yaml_load


_SCOPE = (
    "intent",
    "traceability",
    "skills",
    "resources",
    "permissions",
    "state_and_recovery",
    "human_review",
    "evaluation_cases",
    "novice_usability",
    "privacy_license_platform",
)


def _evidence(snapshot, path: str) -> EvidenceRef:
    found = next((item for item in snapshot.files if item.path == path), None)
    if found is None:
        return EvidenceRef(".", None, None, snapshot.tree_hash, "verified")
    return EvidenceRef(path, 1, found.line_count, found.sha256, "verified")


def _finding(identifier: str, severity: str, title: str, path: str, snapshot) -> Finding:
    return Finding(
        id=identifier,
        severity=severity,
        title=title,
        impact=f"The Agent cannot reliably demonstrate {title.lower()}.",
        recommendation=f"Add and validate {path} with evidence tied to the Agent mission.",
        evidence=(_evidence(snapshot, path),),
        evidence_status="verified",
    )


def review_agent(target: Path, policy: dict) -> ReviewReport:
    snapshot = snapshot_tree(target)
    present = {item.path for item in snapshot.files}
    required = policy["required_files"]
    findings: list[Finding] = []
    if required["intent"] not in present:
        findings.append(_finding("REV-INTENT-001", "P1", "Commander Intent", required["intent"], snapshot))
    if required["blueprint"] not in present:
        findings.append(_finding("REV-BLUEPRINT-001", "P1", "Agent specification and traceability", required["blueprint"], snapshot))
    if required["readme"] not in present:
        findings.append(_finding("REV-README-001", "P2", "novice-readable usage guidance", required["readme"], snapshot))
    if required["evaluation"] not in present:
        findings.append(_finding("REV-EVAL-001", "P2", "evaluation cases", required["evaluation"], snapshot))
    else:
        try:
            cases = strict_yaml_load((Path(target) / required["evaluation"]).read_text(encoding="utf-8"))
            raw_cases = cases.get("cases", cases) if isinstance(cases, dict) else cases
            case_types = {case.get("type") for case in raw_cases if isinstance(case, dict)} if isinstance(raw_cases, list) else set()
            missing = {"Golden", "Failure", "Boundary", "Unknown"} - case_types
            if missing:
                findings.append(_finding("REV-EVAL-002", "P2", "all four evaluation case classes", required["evaluation"], snapshot))
        except (OSError, UnicodeError, ValueError):
            findings.append(_finding("REV-EVAL-003", "P2", "parseable evaluation evidence", required["evaluation"], snapshot))
    if snapshot.skipped_links:
        findings.append(_finding("REV-LINK-001", "P2", "self-contained evidence without symlinks", snapshot.skipped_links[0], snapshot))

    quality = {
        "intent": {"score": policy["weights"]["intent"] if required["intent"] in present else 0, "status": "evidenced" if required["intent"] in present else "missing"},
        "capability": {"score": policy["weights"]["capability"] if required["blueprint"] in present else 0, "status": "evidenced" if required["blueprint"] in present else "missing"},
        "execution": {"score": policy["weights"]["execution"] if required["evaluation"] in present else 0, "status": "structural_only"},
        "outcome": {"score": None, "status": "not_evidenced"},
        "evolution": {"score": None, "status": "not_evidenced"},
        "grade": "provisional",
    }
    return ReviewReport(
        target=str(Path(target).resolve()),
        baseline_hash=snapshot.tree_hash,
        scope=_SCOPE,
        findings=tuple(findings),
        quality=quality,
        status_layers={
            "local_generated": False,
            "local_validated": False,
            "installed": False,
            "published": False,
            "real_usage_verified": False,
        },
        unverified=("business outcome", "continuous evolution", "real downstream usage"),
    )
