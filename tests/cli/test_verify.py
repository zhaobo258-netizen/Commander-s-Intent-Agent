from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from factory.cli.main import main
from factory.cli.verify import VerificationReport, verify_repository


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_FILES = (
    "pyproject.toml",
    "factory/__init__.py",
    "factory/contracts/commander-intent.schema.json",
    "factory/contracts/agent-blueprint.schema.json",
    "factory/contracts/factory-job.schema.json",
    "factory/contracts/review-report.schema.json",
    "factory/governance/production-gates.yaml",
    "factory/governance/state-machine.yaml",
    "templates/job/JOB.md.tmpl",
    "templates/job/COMMANDER_INTENT.md.tmpl",
    "workshop/README.md",
    "workshop/.gitignore",
    "workshop/jobs/.gitkeep",
    "workshop/reviews/.gitkeep",
)


def _copy_repository_contract(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    for relative in REPOSITORY_FILES:
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def test_verification_report_is_immutable() -> None:
    report = VerificationReport(ok=True, checks=("verified:x",), failures=())

    with pytest.raises(FrozenInstanceError):
        report.ok = False  # type: ignore[misc]


def test_verify_repo_reports_commander_intent_as_first_missing_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = verify_repository(tmp_path)

    assert report.ok is False
    assert report.failures[0] == (
        "missing:factory/contracts/commander-intent.schema.json"
    )
    assert main(["verify-repo", str(tmp_path)]) == 1
    output = capsys.readouterr().out.splitlines()
    assert output[0] == "missing:factory/contracts/commander-intent.schema.json"


def test_complete_repository_verifies_without_writing() -> None:
    before_files = _snapshot(ROOT)
    before_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    report = verify_repository(ROOT)

    after_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert report.ok is True, report.failures
    assert report.failures == ()
    assert "verified:factory/contracts/commander-intent.schema.json" in report.checks
    assert "verified:factory/governance/state-machine.yaml" in report.checks
    assert "verified:pyproject.toml" in report.checks
    assert "verified:workshop-ignore-semantics" in report.checks
    assert _snapshot(ROOT) == before_files
    assert after_status == before_status


@pytest.mark.parametrize(
    ("relative", "contents", "failure_prefix"),
    [
        (
            "factory/contracts/commander-intent.schema.json",
            "{not json",
            "malformed:factory/contracts/commander-intent.schema.json:invalid-json",
        ),
        (
            "factory/contracts/agent-blueprint.schema.json",
            '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":7}',
            "malformed:factory/contracts/agent-blueprint.schema.json:invalid-schema",
        ),
        (
            "factory/governance/production-gates.yaml",
            "sections: [",
            "malformed:factory/governance/production-gates.yaml:invalid-yaml",
        ),
        (
            "factory/governance/state-machine.yaml",
            "schema_version: '1.0'\nmodes: {}\n",
            "malformed:factory/governance/state-machine.yaml:invalid-policy",
        ),
        (
            "pyproject.toml",
            "[project\nname = 'broken'\n",
            "malformed:pyproject.toml:invalid-toml",
        ),
    ],
)
def test_malformed_repository_inputs_become_failures_not_exceptions(
    tmp_path: Path,
    relative: str,
    contents: str,
    failure_prefix: str,
) -> None:
    root = _copy_repository_contract(tmp_path)
    (root / relative).write_text(contents, encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is False
    assert any(item.startswith(failure_prefix) for item in report.failures)


def test_verifier_uses_injected_factory_job_schema_for_state_policy(
    tmp_path: Path,
) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/factory-job.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["mode"]["enum"] = ["CREATE"]
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is False
    assert any(
        item.startswith(
            "malformed:factory/governance/state-machine.yaml:invalid-policy"
        )
        and "unknown schema modes" in item
        for item in report.failures
    )


def test_schema_json_rejects_duplicate_object_keys(tmp_path: Path) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/commander-intent.schema.json"
    original = schema_path.read_text(encoding="utf-8")
    schema_path.write_text(
        original.replace(
            '"$schema": "https://json-schema.org/draft/2020-12/schema",',
            (
                '"$schema": "https://json-schema.org/draft/2020-12/schema",\n'
                '  "$schema": "https://json-schema.org/draft/2020-12/schema",'
            ),
            1,
        ),
        encoding="utf-8",
    )

    report = verify_repository(root)

    assert report.ok is False
    assert (
        "malformed:factory/contracts/commander-intent.schema.json:invalid-json"
        in report.failures
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda text: text.replace(
                'name = "commander-intent-agent-factory"',
                'name = "wrong-package"',
            ),
            "invalid:pyproject.toml:project.name",
        ),
        (
            lambda text: text.replace(
                'commander-factory = "factory.cli.main:main"',
                'commander-factory = "factory.cli.main:wrong"',
            ),
            "invalid:pyproject.toml:project.scripts.commander-factory",
        ),
        (
            lambda text: text.replace(
                'requires-python = ">=3.11"',
                'requires-python = ">=3.110"',
            ),
            "invalid:pyproject.toml:project.requires-python",
        ),
        (
            lambda text: text.replace(
                '"PyYAML>=6.0"',
                '"fake-PyYAML>=6.0"',
            ),
            "invalid:pyproject.toml:project.dependencies:PyYAML",
        ),
        (
            lambda text: text.replace('"factory.governance" = ["*.yaml"]', ""),
            "invalid:pyproject.toml:package-data:factory/governance/production-gates.yaml",
        ),
    ],
)
def test_package_metadata_mismatches_are_reported(
    tmp_path: Path,
    mutation,
    expected: str,
) -> None:
    root = _copy_repository_contract(tmp_path)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        mutation(pyproject.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    report = verify_repository(root)

    assert report.ok is False
    assert expected in report.failures


def test_package_version_mismatch_is_reported(tmp_path: Path) -> None:
    root = _copy_repository_contract(tmp_path)
    (root / "factory/__init__.py").write_text(
        '__version__ = "9.9.9"\n',
        encoding="utf-8",
    )

    report = verify_repository(root)

    assert report.ok is False
    assert "mismatch:factory/__init__.py:version" in report.failures


def test_semantically_equivalent_metadata_format_verifies(tmp_path: Path) -> None:
    root = _copy_repository_contract(tmp_path)
    pyproject = root / "pyproject.toml"
    contents = pyproject.read_text(encoding="utf-8")
    contents = contents.replace(
        'requires-python = ">=3.11"',
        'requires-python = ">= 3.11.0, < 4"',
    ).replace(
        'dependencies = ["PyYAML>=6.0", "jsonschema[format]>=4.21"]',
        'dependencies = ["pyyaml >= 6.0.0", "jsonschema[FORMAT] >= 4.21.0"]',
    )
    pyproject.write_text(contents, encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is True, report.failures


def test_missing_declared_job_template_fails_verification(tmp_path: Path) -> None:
    root = _copy_repository_contract(tmp_path)
    (root / "templates/job/JOB.md.tmpl").unlink()

    report = verify_repository(root)

    assert report.ok is False
    assert "missing:templates/job/JOB.md.tmpl" in report.failures


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("workshop/README.md", "missing:workshop/README.md"),
        ("workshop/jobs/.gitkeep", "missing:workshop/jobs/.gitkeep"),
        ("workshop/reviews/.gitkeep", "missing:workshop/reviews/.gitkeep"),
    ],
)
def test_missing_workshop_files_fail_verification(
    tmp_path: Path,
    relative: str,
    expected: str,
) -> None:
    root = _copy_repository_contract(tmp_path)
    (root / relative).unlink()

    report = verify_repository(root)

    assert report.ok is False
    assert expected in report.failures


@pytest.mark.parametrize(
    "contents",
    [
        "jobs/*\nreviews/*\n!jobs/.gitkeep\n",
        "!jobs/.gitkeep\njobs/*\nreviews/*\n!reviews/.gitkeep\n",
        (
            "jobs/*\nreviews/*\n!jobs/.gitkeep\n!reviews/.gitkeep\n"
            "!jobs/private-job/status.json\n"
        ),
    ],
)
def test_incorrect_workshop_ignore_rules_fail_semantic_check(
    tmp_path: Path,
    contents: str,
) -> None:
    root = _copy_repository_contract(tmp_path)
    (root / "workshop/.gitignore").write_text(contents, encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is False
    assert any(
        failure.startswith("invalid:workshop/.gitignore")
        for failure in report.failures
    )
    assert "verified:workshop-ignore-semantics" not in report.checks


@pytest.mark.parametrize(
    ("mode", "container"),
    [("CREATE", "jobs"), ("REVIEW", "reviews"), ("OPTIMIZE", "reviews")],
)
def test_job_init_routes_each_mode_to_injected_workshop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    container: str,
) -> None:
    result = main(
        [
            "job-init",
            "--workshop",
            str(tmp_path),
            "--mode",
            mode,
            "--name",
            "demo",
            "--job-id",
            f"job-{mode.lower()}",
        ]
    )

    expected = tmp_path / container / f"job-{mode.lower()}-demo"
    assert result == 0
    assert expected.is_dir()
    assert f"created:{expected}" in capsys.readouterr().out
    assert json.loads((expected / "status.json").read_text(encoding="utf-8"))[
        "status"
    ] == "NEW"


def test_job_init_refuses_invalid_name_and_existing_job_without_overwrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = [
        "job-init",
        "--workshop",
        str(tmp_path),
        "--mode",
        "CREATE",
        "--job-id",
        "job-demo",
    ]
    assert main([*base, "--name", "../escape"]) == 1
    assert not (tmp_path / "jobs").exists()

    assert main([*base, "--name", "demo"]) == 0
    status_path = tmp_path / "jobs/job-demo-demo/status.json"
    original = status_path.read_bytes()
    assert main([*base, "--name", "demo"]) == 1

    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert status_path.read_bytes() == original


def test_job_status_prints_deterministic_utf8_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(
        [
            "job-init",
            "--workshop",
            str(tmp_path),
            "--mode",
            "CREATE",
            "--name",
            "演示",
            "--job-id",
            "job-demo",
        ]
    ) == 0
    capsys.readouterr()
    job_dir = tmp_path / "jobs/job-demo-演示"

    assert main(["job-status", str(job_dir)]) == 0
    first = capsys.readouterr().out
    assert '"mode": "CREATE"' in first
    assert '"name": "演示"' in first
    assert main(["job-status", str(job_dir)]) == 0
    assert capsys.readouterr().out == first


def test_job_status_returns_one_when_stdout_cannot_encode_document(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert main(
        [
            "job-init",
            "--workshop",
            str(tmp_path),
            "--mode",
            "CREATE",
            "--name",
            "demo",
            "--job-id",
            "job-demo",
        ]
    ) == 0
    capsys.readouterr()
    job_dir = tmp_path / "jobs/job-demo-demo"
    status_path = job_dir / "status.json"
    document = json.loads(status_path.read_text(encoding="utf-8"))
    document["name"] = "\ud800"
    status_path.write_text(json.dumps(document), encoding="utf-8")

    class StrictUtf8Stream:
        def write(self, value: str) -> int:
            value.encode("utf-8")
            return len(value)

        def flush(self) -> None:
            return None

    monkeypatch.setattr(sys, "stdout", StrictUtf8Stream())

    assert main(["job-status", str(job_dir)]) == 1
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("corruption", ["missing", "malformed", "impossible"])
def test_job_status_turns_domain_failures_into_exit_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    corruption: str,
) -> None:
    job_dir = tmp_path / "jobs/job-demo-demo"
    if corruption != "missing":
        assert main(
            [
                "job-init",
                "--workshop",
                str(tmp_path),
                "--mode",
                "CREATE",
                "--name",
                "demo",
                "--job-id",
                "job-demo",
            ]
        ) == 0
        capsys.readouterr()
    if corruption == "malformed":
        (job_dir / "status.json").write_text("{broken", encoding="utf-8")
    elif corruption == "impossible":
        status_path = job_dir / "status.json"
        document = json.loads(status_path.read_text(encoding="utf-8"))
        document["status"] = "DELIVERED"
        document["checkpoint"].update(
            {"state": "DELIVERED", "next_action": "completed:DELIVERED"}
        )
        status_path.write_text(json.dumps(document), encoding="utf-8")

    assert main(["job-status", str(job_dir)]) == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "Traceback" not in captured.err


def test_module_cli_verifies_injected_repository_root() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "factory.cli", "verify-repo", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "verified:pyproject.toml" in completed.stdout
    assert completed.stderr == ""
