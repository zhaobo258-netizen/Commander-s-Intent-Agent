from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from factory.errors import FactoryError, UnsafePathError
from factory.production.codex import (
    check_codex_skill,
    install_codex_skill,
    uninstall_codex_skill,
    validate_codex_skill,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def skill_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "source" / "commander-agent-factory"
    shutil.copytree(ROOT / "skills" / "commander-agent-factory", target)
    return target


def test_copy_install_detects_drift_and_refuses_unsafe_uninstall(
    tmp_path: Path,
    skill_fixture: Path,
) -> None:
    codex_home = tmp_path / ".codex"
    installed = install_codex_skill(skill_fixture, codex_home, mode="copy")
    assert check_codex_skill(skill_fixture, codex_home).status == "current"

    (installed / "SKILL.md").write_text("changed\n", encoding="utf-8")
    assert check_codex_skill(skill_fixture, codex_home).status == "installed_drifted"
    with pytest.raises(FactoryError, match="drift|current"):
        uninstall_codex_skill(skill_fixture, codex_home)
    assert installed.exists()


def test_current_copy_install_can_be_uninstalled(
    tmp_path: Path,
    skill_fixture: Path,
) -> None:
    codex_home = tmp_path / ".codex"
    installed = install_codex_skill(skill_fixture, codex_home, mode="copy")
    uninstall_codex_skill(skill_fixture, codex_home)
    assert not installed.exists()
    assert check_codex_skill(skill_fixture, codex_home).status == "not_installed"


def test_install_refuses_unmanaged_existing_target(
    tmp_path: Path,
    skill_fixture: Path,
) -> None:
    target = tmp_path / ".codex" / "skills" / "commander-agent-factory"
    target.mkdir(parents=True)
    sentinel = target / "foreign.txt"
    sentinel.write_text("keep\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        install_codex_skill(skill_fixture, tmp_path / ".codex", mode="copy")
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_symlink_install_never_writes_marker_into_source(
    tmp_path: Path,
    skill_fixture: Path,
) -> None:
    codex_home = tmp_path / ".codex"
    installed = install_codex_skill(skill_fixture, codex_home, mode="symlink")
    assert installed.is_symlink()
    assert not (skill_fixture / ".commander-factory-install.json").exists()
    assert check_codex_skill(skill_fixture, codex_home).status == "current"

    uninstall_codex_skill(skill_fixture, codex_home)
    assert not installed.exists()
    assert skill_fixture.exists()


def test_source_symlink_is_rejected(tmp_path: Path, skill_fixture: Path) -> None:
    link = tmp_path / "commander-agent-factory"
    link.symlink_to(skill_fixture, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        install_codex_skill(link, tmp_path / ".codex", mode="copy")


def test_symlinked_sidecar_ancestor_cannot_escape_codex_home(
    tmp_path: Path,
    skill_fixture: Path,
) -> None:
    codex_home = tmp_path / ".codex"
    outside = tmp_path / "outside"
    codex_home.mkdir()
    outside.mkdir()
    (codex_home / ".commander-factory").symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(UnsafePathError, match="symlink|escapes"):
        install_codex_skill(skill_fixture, codex_home, mode="symlink")

    assert not any(outside.iterdir())
    assert not (codex_home / "skills" / "commander-agent-factory").exists()


def test_project_skill_validates() -> None:
    assert validate_codex_skill(ROOT / "skills" / "commander-agent-factory") == ()
