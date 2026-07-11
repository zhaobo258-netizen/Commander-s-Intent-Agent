"""Validate and manage an optional, explicit Codex factory-skill install."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from factory.errors import ContractValidationError, FactoryError, UnsafePathError
from factory.serialization import strict_json_loads, strict_yaml_load


_NAME = "commander-agent-factory"
_MARKER = ".commander-factory-install.json"


@dataclass(frozen=True, slots=True)
class InstallCheck:
    status: str
    source_hash: str | None
    installed_hash: str | None
    target: Path


def _target_identity(target: Path) -> Path:
    """Canonicalize the parent without following a final managed symlink."""
    return target.parent.resolve() / target.name


def _walk_regular(root: Path, *, exclude_marker: bool = False) -> tuple[Path, ...]:
    paths: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise UnsafePathError(f"skill tree contains a symlink: {path}")
        for name in filenames:
            if exclude_marker and name == _MARKER:
                continue
            path = current_path / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise UnsafePathError(f"skill tree contains a special file: {path}")
            paths.append(path)
    return tuple(sorted(paths, key=lambda path: path.relative_to(root).as_posix()))


def _tree_hash(root: Path, *, exclude_marker: bool = False) -> str:
    digest = hashlib.sha256()
    for path in _walk_regular(root, exclude_marker=exclude_marker):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        executable = b"1" if path.stat().st_mode & 0o111 else b"0"
        for record in (relative, b"file", executable, payload):
            digest.update(len(record).to_bytes(8, "big"))
            digest.update(record)
    return f"sha256:{digest.hexdigest()}"


def validate_codex_skill(path: Path) -> tuple[str, ...]:
    failures: list[str] = []
    root = Path(path)
    if root.name != _NAME or root.is_symlink() or not root.is_dir():
        return ("invalid skill root",)
    try:
        _walk_regular(root)
        skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
        parts = skill_text.split("---", 2)
        frontmatter = strict_yaml_load(parts[1]) if len(parts) == 3 else None
        if not isinstance(frontmatter, dict) or set(frontmatter) != {"name", "description"}:
            failures.append("invalid SKILL.md frontmatter")
        elif frontmatter.get("name") != _NAME:
            failures.append("skill name mismatch")
        metadata = strict_yaml_load((root / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        prompt = metadata["interface"]["default_prompt"]
        if f"${_NAME}" not in prompt:
            failures.append("default prompt must name the skill explicitly")
        for reference in (
            "create-workflow.md",
            "review-workflow.md",
            "optimize-workflow.md",
            "status-and-evidence.md",
        ):
            if not (root / "references" / reference).is_file():
                failures.append(f"missing reference: {reference}")
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError) as exc:
        failures.append(f"skill validation failed: {exc.__class__.__name__}")
    return tuple(failures)


def _paths(source: Path, codex_home: Path) -> tuple[Path, Path, Path]:
    source_path = Path(source)
    if source_path.is_symlink():
        raise UnsafePathError("canonical skill source must not be a symlink")
    source_path = source_path.resolve(strict=True)
    home = Path(codex_home)
    if home.is_symlink():
        raise UnsafePathError("Codex home must not be a symlink")
    home.mkdir(parents=True, exist_ok=True)
    skills = home / "skills"
    if skills.is_symlink():
        raise UnsafePathError("Codex skills directory must not be a symlink")
    skills.mkdir(parents=True, exist_ok=True)
    target = skills / _NAME
    try:
        _target_identity(target).relative_to(home.resolve())
    except ValueError as exc:
        raise UnsafePathError("Codex skill target escapes Codex home") from exc
    sidecar = home / ".commander-factory" / "installs" / _NAME / _MARKER
    return source_path, target, sidecar


def _marker(source: Path, target: Path, mode: str, source_hash: str) -> dict:
    return {
        "schema_version": "1.0",
        "name": _NAME,
        "mode": mode,
        "source": str(source),
        "target": str(_target_identity(target)),
        "source_hash": source_hash,
        "installed_hash": source_hash,
    }


def _write_marker(path: Path, marker: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_marker(path: Path) -> dict:
    loaded = strict_json_loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version",
        "name",
        "mode",
        "source",
        "target",
        "source_hash",
        "installed_hash",
    }
    if not isinstance(loaded, dict) or set(loaded) != expected:
        raise ValueError("invalid installation marker")
    return loaded


def install_codex_skill(source: Path, codex_home: Path, mode: str) -> Path:
    if mode not in {"copy", "symlink"}:
        raise ContractValidationError("Codex skill install mode must be copy or symlink")
    source_path, target, sidecar = _paths(source, codex_home)
    failures = validate_codex_skill(source_path)
    if failures:
        raise ContractValidationError("; ".join(failures))
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Codex skill target already exists: {target}")
    source_hash = _tree_hash(source_path)
    marker = _marker(source_path, target, mode, source_hash)

    if mode == "copy":
        staging = Path(tempfile.mkdtemp(prefix=f".{_NAME}.staging-", dir=target.parent))
        try:
            shutil.rmtree(staging)
            shutil.copytree(source_path, staging)
            if _tree_hash(source_path) != source_hash or _tree_hash(staging) != source_hash:
                raise FactoryError("skill source changed during installation")
            _write_marker(staging / _MARKER, marker)
            os.rename(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target

    if sidecar.exists():
        raise FileExistsError(f"Codex skill sidecar already exists: {sidecar}")
    _write_marker(sidecar, marker)
    temporary = target.with_name(f".{_NAME}.link-{os.getpid()}")
    try:
        temporary.symlink_to(source_path, target_is_directory=True)
        os.rename(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        raise
    return target


def check_codex_skill(source: Path, codex_home: Path) -> InstallCheck:
    try:
        source_path, target, sidecar = _paths(source, codex_home)
    except (OSError, UnsafePathError):
        target = Path(codex_home) / "skills" / _NAME
        return InstallCheck("source_missing", None, None, target)
    if not target.exists() and not target.is_symlink():
        return InstallCheck("not_installed", _tree_hash(source_path), None, target)

    marker_path = sidecar if target.is_symlink() else target / _MARKER
    try:
        marker = _read_marker(marker_path)
    except (OSError, ValueError, UnicodeError):
        return InstallCheck("unmanaged", _tree_hash(source_path), None, target)
    if marker["source"] != str(source_path) or marker["target"] != str(_target_identity(target)):
        return InstallCheck("invalid_marker", _tree_hash(source_path), None, target)

    source_hash = _tree_hash(source_path)
    if target.is_symlink():
        try:
            if target.resolve(strict=True) != source_path:
                return InstallCheck("retargeted_symlink", source_hash, None, target)
            installed_hash = _tree_hash(source_path)
        except OSError:
            return InstallCheck("broken_symlink", source_hash, None, target)
    else:
        installed_hash = _tree_hash(target, exclude_marker=True)

    source_changed = source_hash != marker["source_hash"]
    installed_changed = installed_hash != marker["installed_hash"]
    if source_changed and installed_changed:
        status = "both_drifted"
    elif source_changed:
        status = "source_changed"
    elif installed_changed:
        status = "installed_drifted"
    else:
        status = "current"
    return InstallCheck(status, source_hash, installed_hash, target)


def uninstall_codex_skill(source: Path, codex_home: Path) -> None:
    source_path, target, sidecar = _paths(source, codex_home)
    check = check_codex_skill(source_path, codex_home)
    if check.status != "current":
        raise FactoryError(f"refusing to uninstall skill that is not current: {check.status}")
    if target.is_symlink():
        if target.resolve(strict=True) != source_path:
            raise UnsafePathError("managed Codex symlink target changed")
        target.unlink()
        sidecar.unlink(missing_ok=True)
        try:
            sidecar.parent.rmdir()
        except OSError:
            pass
    else:
        shutil.rmtree(target)


__all__ = [
    "InstallCheck",
    "validate_codex_skill",
    "install_codex_skill",
    "check_codex_skill",
    "uninstall_codex_skill",
]
