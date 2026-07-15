"""Create an approved optimization candidate without modifying its source."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from factory.contracts import validate_document
from factory.errors import ContractValidationError, FactoryError, GateBlockedError, UnsafePathError
from factory.review.snapshot import snapshot_tree


@dataclass(frozen=True, slots=True)
class CandidateManifest:
    source_path: Path
    source_hash: str
    candidate_path: Path
    plan_hash: str


def _plan_hash(plan: Mapping) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _approved(job: Mapping, identifier: str) -> bool:
    return any(item.get("id") == identifier and item.get("status") == "approved" for item in job.get("approvals", ()) if isinstance(item, Mapping))


def prepare_candidate(job: Mapping, plan: Mapping, output: Path) -> CandidateManifest:
    if job.get("mode") != "OPTIMIZE" or job.get("status") != "OPTIMIZATION_APPROVED":
        raise GateBlockedError("job must be OPTIMIZATION_APPROVED")
    issues = validate_document("optimization-plan", plan)
    if issues:
        raise ContractValidationError("invalid optimization plan: " + ", ".join(f"{i.path}:{i.code}" for i in issues))
    if not plan["approved_by_user"] or not _approved(job, "optimization-approval"):
        raise GateBlockedError("optimization plan lacks user approval")
    if plan["intent_change"] and not _approved(job, "new-intent-confirmed"):
        raise GateBlockedError("mission change requires confirmed new intent")

    source = Path(plan["target"])
    before = snapshot_tree(source)
    if before.skipped_links or before.skipped_unreadable:
        raise UnsafePathError("optimization source must contain only readable regular files")
    if before.tree_hash != plan["baseline_hash"]:
        raise GateBlockedError("optimization baseline hash has drifted")
    output_root = Path(output)
    if output_root.is_symlink():
        raise UnsafePathError("optimization output must not be a symlink")
    source_real = source.resolve()
    output_real = output_root.resolve(strict=False)
    if output_real == source_real or output_real.is_relative_to(source_real) or source_real.is_relative_to(output_real):
        raise UnsafePathError("optimization source and output trees must be separate")
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"candidate-{_plan_hash(plan)[:12]}"
    candidate = output_root / name
    if candidate.exists() or candidate.is_symlink():
        raise FileExistsError(f"optimization candidate already exists: {candidate}")
    staging = Path(tempfile.mkdtemp(prefix=f".{name}.staging-", dir=output_root))
    try:
        shutil.rmtree(staging)
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns(".git"))
        if snapshot_tree(source).tree_hash != before.tree_hash:
            raise FactoryError("optimization source changed during candidate copy")
        os.rename(staging, candidate)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return CandidateManifest(source_real, before.tree_hash, candidate, _plan_hash(plan))
