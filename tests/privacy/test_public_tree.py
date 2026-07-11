from pathlib import Path

from factory.governance.privacy import scan_public_tree


def test_private_path_and_fake_secret_are_redacted(tmp_path: Path) -> None:
    private = tmp_path / "workshop/jobs/client/intake.txt"
    private.parent.mkdir(parents=True)
    fake = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    private.write_text(fake, encoding="utf-8")
    report = scan_public_tree(tmp_path, ["workshop/jobs/client/intake.txt"])
    assert {finding.code for finding in report.findings} == {"private_path", "secret_pattern"}
    rendered = report.to_json()
    assert "ghp_" not in rendered
    assert "abcdefghijklmnopqrstuvwxyz" not in rendered


def test_clean_public_document_passes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Use environment variables for credentials.", encoding="utf-8")
    assert scan_public_tree(tmp_path, ["README.md"]).ok is True
