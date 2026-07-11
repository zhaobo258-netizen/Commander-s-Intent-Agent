"""Capture no-follow, immutable evidence from an Agent directory."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from factory.errors import FactoryError, UnsafePathError
from factory.review.models import FileSnapshot, TreeSnapshot


def snapshot_tree(root: Path, max_file_bytes: int = 1_000_000) -> TreeSnapshot:
    path = Path(root)
    if path.is_symlink() or not path.is_dir():
        raise UnsafePathError("review target must be a real directory")
    resolved = path.resolve()
    files: list[FileSnapshot] = []
    links: list[str] = []
    unreadable: list[str] = []
    for current, directories, filenames in os.walk(path, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(directories):
            child = current_path / name
            relative = child.relative_to(path).as_posix()
            if child.is_symlink():
                links.append(relative)
            else:
                kept.append(name)
        directories[:] = kept
        for name in sorted(filenames):
            child = current_path / name
            relative = child.relative_to(path).as_posix()
            try:
                info = child.lstat()
                if stat.S_ISLNK(info.st_mode):
                    links.append(relative)
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_size > max_file_bytes:
                    unreadable.append(relative)
                    continue
                payload = child.read_bytes()
            except OSError:
                unreadable.append(relative)
                continue
            try:
                text = payload.decode("utf-8")
                line_count = len(text.splitlines())
            except UnicodeDecodeError:
                line_count = None
            files.append(
                FileSnapshot(
                    path=relative,
                    size=len(payload),
                    line_count=line_count,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
    files.sort(key=lambda item: item.path)
    digest = hashlib.sha256()
    for item in files:
        for record in (item.path.encode("utf-8"), item.sha256.encode("ascii")):
            digest.update(len(record).to_bytes(8, "big"))
            digest.update(record)
    for prefix, values in ((b"link", sorted(links)), (b"unreadable", sorted(unreadable))):
        for value in values:
            digest.update(prefix)
            digest.update(value.encode("utf-8"))
    return TreeSnapshot(
        root=str(resolved),
        files=tuple(files),
        skipped_links=tuple(sorted(links)),
        skipped_unreadable=tuple(sorted(unreadable)),
        tree_hash=digest.hexdigest(),
    )


def verify_unchanged(before: TreeSnapshot, after: TreeSnapshot) -> bool:
    return before.root == after.root and before.tree_hash == after.tree_hash
