from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from factory.cli.main import main
from factory.cli.verify import verify_repository


ROOT = Path(__file__).resolve().parents[2]


def _public_copy(tmp_path: Path) -> Path:
    target = tmp_path / "public-copy"
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", "*.pyc"),
    )
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(["git", "add", "."], cwd=target, check=True)
    return target


def test_public_repository_verification_passes_without_writing(capsys) -> None:
    before = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout

    report = verify_repository(ROOT, public=True)

    after = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    assert report.ok is True, report.failures
    assert "verified:public-privacy" in report.checks
    assert "verified:skills/commander-agent-factory" in report.checks
    assert main(["verify-repo", str(ROOT), "--public"]) == 0
    assert "verified:public-privacy" in capsys.readouterr().out
    assert after == before


def test_public_repository_verification_rejects_tracked_secret(tmp_path: Path) -> None:
    root = _public_copy(tmp_path)
    secret = "gh" + "p_" + "A" * 24
    (root / "leak.txt").write_text(secret, encoding="utf-8")
    subprocess.run(["git", "add", "leak.txt"], cwd=root, check=True)

    report = verify_repository(root, public=True)

    assert report.ok is False
    assert any(item.startswith("privacy:leak.txt:secret_pattern:") for item in report.failures)
    assert secret not in "\n".join(report.failures)


def test_public_repository_verification_fails_closed_outside_git(tmp_path: Path) -> None:
    report = verify_repository(tmp_path, public=True)

    assert report.ok is False
    assert "unverified:public-tracked-files" in report.failures


def test_public_repository_verification_rejects_index_worktree_mismatch(tmp_path: Path) -> None:
    root = _public_copy(tmp_path)
    path = root / "README.md"
    secret = "gh" + "p_" + "B" * 24
    path.write_text(secret, encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    path.write_text("clean working tree copy\n", encoding="utf-8")

    report = verify_repository(root, public=True)

    assert report.ok is False
    assert "unverified:public-index-worktree-mismatch" in report.failures


def test_public_script_uses_same_fail_closed_gate(tmp_path: Path) -> None:
    root = _public_copy(tmp_path)
    path = root / "README.md"
    path.write_text("staged version\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    path.write_text("different working version\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/verify_public.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "unverified:public-index-worktree-mismatch" in result.stderr
