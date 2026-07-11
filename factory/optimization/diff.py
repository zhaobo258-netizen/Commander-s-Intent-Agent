from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from factory.review.snapshot import snapshot_tree


@dataclass(frozen=True, slots=True)
class DiffReport:
    added: tuple[str, ...]
    modified: tuple[str, ...]
    deleted: tuple[str, ...]
    summary: str


def compare_trees(baseline: Path, candidate: Path) -> DiffReport:
    before = {item.path: item.sha256 for item in snapshot_tree(baseline).files if not item.path.startswith(".git/")}
    after = {item.path: item.sha256 for item in snapshot_tree(candidate).files if not item.path.startswith(".git/")}
    added = tuple(sorted(set(after) - set(before)))
    deleted = tuple(sorted(set(before) - set(after)))
    modified = tuple(sorted(path for path in set(before) & set(after) if before[path] != after[path]))
    parts = [*(f"added:{path}" for path in added), *(f"modified:{path}" for path in modified), *(f"deleted:{path}" for path in deleted)]
    return DiffReport(added, modified, deleted, "; ".join(parts) or "no changes")
