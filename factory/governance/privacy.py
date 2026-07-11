"""Fail-closed, redacted scanning for files intended to become public.

The scan detects known secret signatures, sensitive paths, and unsafe
files. It is deliberately rule-based and deterministic; it does not claim
to recognize every possible secret.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


_MAX_PUBLIC_BYTES = 2_000_000
_PRIVATE_PREFIXES = ("workshop/jobs/", "workshop/reviews/")
_SENSITIVE_PREFIXES = ("workshop/private/", "workshop/customer-data/")
_SENSITIVE_FILENAMES = frozenset({"secrets.json", "credentials.json"})
_SENSITIVE_SUFFIXES = (".key", ".pem", ".p12")
_PUBLIC_WORKSHOP_SENTINELS = {
    "workshop/jobs/.gitkeep",
    "workshop/reviews/.gitkeep",
}
_PEM_HEADER = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_SECRET_RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("secret_pattern:private_key", _PEM_HEADER),
    ("secret_pattern:github_token", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("secret_pattern:github_token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("secret_pattern:gitlab_token", re.compile(rb"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("secret_pattern:slack_token", re.compile(rb"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("secret_pattern:openai_key", re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("secret_pattern:stripe_live_key", re.compile(rb"\bsk_live_[A-Za-z0-9]{10,}")),
    ("secret_pattern:google_api_key", re.compile(rb"\bAIza[0-9A-Za-z_\-]{35}")),
    ("secret_pattern:aws_access_key", re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}")),
    (
        "secret_pattern:authorization_header",
        re.compile(rb"(?i)authorization\s*:\s*(?:bearer|basic|token)\s+[A-Za-z0-9._~+/\-]{8,}=*"),
    ),
    (
        "secret_pattern:jwt",
        re.compile(rb"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    ),
)
# Deterministic decode only: candidate base64 runs are decoded and matched
# against the PEM private-key header. No generic entropy heuristics.
_BASE64_RUN = re.compile(rb"[A-Za-z0-9+/]{40,}={0,2}")
_BASE64_LINE = re.compile(rb"\A[A-Za-z0-9+/=]{4,}\Z")
# Control characters (except newline) are removed from the scan copy so
# they cannot split a credential token; newlines are kept so reported
# line numbers stay meaningful.
_CONTROL_CHARS = re.compile(rb"[\x00-\x09\x0b-\x1f\x7f]")


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


def _normalize_for_scan(payload: bytes) -> bytes:
    """Return a scan copy with control characters removed, newlines kept."""
    return _CONTROL_CHARS.sub(b"", payload)


def _decode_base64_strict(blob: bytes) -> bytes | None:
    if len(blob) % 4 != 0:
        return None
    try:
        return base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError):
        return None


def _encoded_pem_findings(path: str, payload: bytes) -> list[PrivacyFinding]:
    findings: list[PrivacyFinding] = []
    seen: set[tuple[int, str]] = set()

    def _record(blob: bytes, line: int) -> None:
        decoded = _decode_base64_strict(blob)
        if decoded is None or not _PEM_HEADER.search(decoded):
            return
        key = (line, _fingerprint(blob))
        if key not in seen:
            seen.add(key)
            findings.append(PrivacyFinding(path, "secret_pattern:encoded_private_key", line, key[1]))

    for match in _BASE64_RUN.finditer(payload):
        _record(match.group(0), _line_number(payload, match.start()))

    block: list[bytes] = []
    block_line = 1
    offset = 0
    for line in payload.split(b"\n"):
        stripped = line.strip()
        if stripped and _BASE64_LINE.match(stripped):
            if not block:
                block_line = _line_number(payload, offset)
            block.append(stripped)
        else:
            if len(block) > 1:
                _record(b"".join(block), block_line)
            block = []
        offset += len(line) + 1
    if len(block) > 1:
        _record(b"".join(block), block_line)
    return findings


def _sensitive_path_code(normalized: str) -> str | None:
    lower = normalized.lower()
    if lower.startswith(_SENSITIVE_PREFIXES):
        return "sensitive_path"
    name = PurePosixPath(lower).name
    if name in _SENSITIVE_FILENAMES or name.endswith(_SENSITIVE_SUFFIXES):
        return "sensitive_path"
    return None


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
        sensitive_code = _sensitive_path_code(normalized)
        if sensitive_code:
            findings.append(PrivacyFinding(normalized, sensitive_code, None, _fingerprint(normalized.encode("utf-8"))))
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
        scannable = _normalize_for_scan(payload)
        for code, pattern in _SECRET_RULES:
            for match in pattern.finditer(scannable):
                findings.append(PrivacyFinding(normalized, code, _line_number(scannable, match.start()), _fingerprint(match.group(0))))
        findings.extend(_encoded_pem_findings(normalized, scannable))
    ordered = tuple(sorted(findings, key=lambda item: (item.path, item.code, item.line or 0, item.fingerprint)))
    return PrivacyReport(not ordered, ordered)
