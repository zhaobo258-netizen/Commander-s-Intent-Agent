from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    path: str
    line_start: int | None
    line_end: int | None
    sha256: str
    status: str


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: str
    size: int
    line_count: int | None
    sha256: str


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    root: str
    files: tuple[FileSnapshot, ...]
    skipped_links: tuple[str, ...]
    skipped_unreadable: tuple[str, ...]
    tree_hash: str


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    severity: str
    title: str
    impact: str
    recommendation: str
    evidence: tuple[EvidenceRef, ...]
    evidence_status: str


@dataclass(frozen=True, slots=True)
class ReviewReport:
    target: str
    baseline_hash: str
    scope: tuple[str, ...]
    findings: tuple[Finding, ...]
    quality: dict
    status_layers: dict[str, bool]
    unverified: tuple[str, ...]
