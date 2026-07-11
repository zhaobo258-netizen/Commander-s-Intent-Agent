"""Fail-closed, redacted scanning for files intended to become public."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


_MAX_PUBLIC_BYTES = 2_000_000
_PRIVATE_PREFIXES = ("workshop/jobs/", "workshop/reviews/")
_PUBLIC_WORKSHOP_SENTINELS = {
    "workshop/jobs/.gitkeep",
    "workshop/reviews/.gitkeep",
}
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]{12,}=*"),
)


@dataclass(frozen=True, slots=True)
class PrivacyFinding:
    path: str
    code: str
    line: int | None
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PrivacyReport:
    ok: bool
    findings: tuple[PrivacyFinding, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def _fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _line_number(payload: bytes, offset: int) -> int:
    return payload.count(b"\n", 0, offset) + 1


def scan_public_tree(
    root: Path,
    tracked_paths: Iterable[str],
    *,
    max_file_bytes: int = _MAX_PUBLIC_BYTES,
) -> PrivacyReport:
    base = Path(root).resolve(strict=True)
    findings: list[PrivacyFinding] = []
    for raw_path in sorted(set(tracked_paths)):
        normalized = PurePosixPath(raw_path).as_posix()
        if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
            findings.append(PrivacyFinding(normalized, "unsafe_path", None, _fingerprint(normalized.encode("utf-8"))))
            continue
        lower = normalized.lower()
        private = (
            lower.startswith(_PRIVATE_PREFIXES)
            and lower not in _PUBLIC_WORKSHOP_SENTINELS
        ) or PurePosixPath(lower).name == ".env" or PurePosixPath(lower).name.startswith(".env.")
        if private:
            findings.append(PrivacyFinding(normalized, "private_path", None, _fingerprint(normalized.encode("utf-8"))))
        path = base.joinpath(*PurePosixPath(normalized).parts)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(base)
            if path.is_symlink() or not path.is_file():
                findings.append(PrivacyFinding(normalized, "unsafe_file", None, _fingerprint(normalized.encode("utf-8"))))
                continue
            size = path.stat().st_size
            if size > max_file_bytes:
                findings.append(PrivacyFinding(normalized, "file_too_large", None, _fingerprint(normalized.encode("utf-8"))))
                continue
            payload = path.read_bytes()
        except (OSError, RuntimeError, ValueError):
            findings.append(PrivacyFinding(normalized, "unreadable", None, _fingerprint(normalized.encode("utf-8"))))
            continue
        if b"\x00" in payload:
            continue
        for pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(payload):
                findings.append(PrivacyFinding(normalized, "secret_pattern", _line_number(payload, match.start()), _fingerprint(match.group(0))))
    ordered = tuple(sorted(findings, key=lambda item: (item.path, item.code, item.line or 0, item.fingerprint)))
    return PrivacyReport(not ordered, ordered)
