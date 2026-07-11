import base64
from pathlib import Path

import pytest

from factory.governance.privacy import scan_public_tree


def test_private_path_and_fake_secret_are_redacted(tmp_path: Path) -> None:
    private = tmp_path / "workshop/jobs/client/intake.txt"
    private.parent.mkdir(parents=True)
    fake = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    private.write_text(fake, encoding="utf-8")
    report = scan_public_tree(tmp_path, ["workshop/jobs/client/intake.txt"])
    codes = {finding.code for finding in report.findings}
    assert "private_path" in codes
    assert any(code.startswith("secret_pattern") for code in codes)
    rendered = report.to_json()
    assert "ghp_" not in rendered
    assert "abcdefghijklmnopqrstuvwxyz" not in rendered


def test_clean_public_document_passes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Use environment variables for credentials.", encoding="utf-8")
    assert scan_public_tree(tmp_path, ["README.md"]).ok is True


def test_nul_bytes_do_not_bypass_secret_scanning(tmp_path: Path) -> None:
    fake = b"gh" + b"p_" + b"A" * 24
    (tmp_path / "mixed.bin").write_bytes(b"\x00" + fake)

    report = scan_public_tree(tmp_path, ["mixed.bin"])

    assert report.ok is False
    assert all(finding.code.startswith("secret_pattern") for finding in report.findings)
    assert fake.decode("ascii") not in report.to_json()


_KNOWN_CREDENTIALS = (
    ("github_fine_grained", "github_pat_" + "11AAAAAAA0" * 4),
    ("github_classic_ghp", "ghp_" + "A1b2C3d4" * 5),
    ("github_oauth_gho", "gho_" + "A1b2C3d4" * 5),
    ("github_user_ghu", "ghu_" + "A1b2C3d4" * 5),
    ("github_server_ghs", "ghs_" + "A1b2C3d4" * 5),
    ("github_refresh_ghr", "ghr_" + "A1b2C3d4" * 5),
    ("gitlab_pat", "glpat-" + "Ab12Cd34Ef56Gh78Ij90"),
    ("slack_bot", "xoxb" + "-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"),
    ("slack_legacy_a", "xoxa" + "-2-123456789012-AbCdEfGhIjKlMnOp"),
    ("slack_user", "xoxp" + "-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"),
    ("slack_refresh", "xoxr" + "-123456789012-AbCdEfGhIjKlMnOpQrStUvWx"),
    ("slack_session", "xoxs" + "-123456789012-AbCdEfGhIjKlMnOpQrStUvWx"),
    ("openai_key", "sk-" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8"),
    ("openai_project_key", "sk-proj-" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8"),
    ("stripe_live", "sk_live_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8"),
    ("google_api", "AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6q"),
    ("aws_access_key", "AKIA" + "ABCDEFGHIJKLMNOP"),
    ("aws_sts_key", "ASIA" + "ABCDEFGHIJKLMNOP"),
    ("bearer_header", "Authorization: " + "Bearer AbCdEf123456.GhIjKl789012"),
    ("basic_header", "Authorization: " + "Basic dXNlcjpwYXNzd29yZDEyMw=="),
    ("token_header", "Authorization: " + "Token AbCdEf123456GhIjKl789012"),
    (
        "jwt",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkFkbWluIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c",
    ),
    ("pem_header", "-----BEGIN RSA " + "PRIVATE KEY-----"),
    ("pem_generic_header", "-----BEGIN " + "PRIVATE KEY-----"),
)


@pytest.mark.parametrize(("rule", "token"), _KNOWN_CREDENTIALS)
def test_known_credential_shapes_are_detected_and_redacted(
    tmp_path: Path, rule: str, token: str
) -> None:
    (tmp_path / "doc.md").write_text(f"note before\nvalue = {token}\nafter\n", encoding="utf-8")

    report = scan_public_tree(tmp_path, ["doc.md"])

    assert report.ok is False, f"missed credential rule: {rule}"
    secret_findings = [f for f in report.findings if f.code.startswith("secret_pattern")]
    assert secret_findings, f"missed credential rule: {rule}"
    assert all(f.line == 2 for f in secret_findings)
    assert token not in report.to_json()


@pytest.mark.parametrize(
    "relative",
    (
        "secrets.json",
        "config/credentials.json",
        "deploy/server.key",
        "deploy/server.pem",
        "deploy/bundle.p12",
        "workshop/private/notes.md",
        "workshop/customer-data/orders.csv",
    ),
)
def test_sensitive_paths_are_flagged(tmp_path: Path, relative: str) -> None:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("placeholder\n", encoding="utf-8")

    report = scan_public_tree(tmp_path, [relative])

    assert report.ok is False
    assert any(
        finding.code in {"sensitive_path", "private_path"} for finding in report.findings
    ), relative


def test_control_characters_inside_token_do_not_split_detection(tmp_path: Path) -> None:
    head = b"gh" + b"p_" + b"A" * 10
    tail = b"B" * 14
    for name, payload in (
        ("nul-split.bin", head + b"\x00" + tail),
        ("esc-split.bin", head + b"\x1b" + tail),
        ("bs-split.bin", head + b"\x08\x08" + tail),
    ):
        (tmp_path / name).write_bytes(b"line one\n" + payload + b"\n")
        report = scan_public_tree(tmp_path, [name])
        assert report.ok is False, name
        findings = [f for f in report.findings if f.code.startswith("secret_pattern")]
        assert findings, name
        assert all(f.line == 2 for f in findings), name


def test_base64_encoded_pem_is_detected_without_entropy_rule(tmp_path: Path) -> None:
    pem = (
        "-----BEGIN RSA " + "PRIVATE KEY-----\n"
        "MIIEotherfakekeymaterialAAAA\n"
        "-----END RSA " + "PRIVATE KEY-----\n"
    )
    encoded = base64.b64encode(pem.encode("ascii")).decode("ascii")
    (tmp_path / "single-line.txt").write_text(f"blob: {encoded}\n", encoding="utf-8")
    report = scan_public_tree(tmp_path, ["single-line.txt"])
    assert report.ok is False
    assert any(f.code.startswith("secret_pattern") for f in report.findings)
    assert encoded not in report.to_json()

    wrapped = "\n".join(encoded[i : i + 40] for i in range(0, len(encoded), 40))
    (tmp_path / "wrapped.txt").write_text(wrapped + "\n", encoding="utf-8")
    wrapped_report = scan_public_tree(tmp_path, ["wrapped.txt"])
    assert wrapped_report.ok is False
    assert any(f.code.startswith("secret_pattern") for f in wrapped_report.findings)

    benign = base64.b64encode(b"just some ordinary text payload without keys" * 4).decode("ascii")
    (tmp_path / "benign.txt").write_text(f"data: {benign}\n", encoding="utf-8")
    assert scan_public_tree(tmp_path, ["benign.txt"]).ok is True


def test_high_entropy_alone_is_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "hashes.txt").write_text(
        "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08\n",
        encoding="utf-8",
    )
    assert scan_public_tree(tmp_path, ["hashes.txt"]).ok is True
