from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from factory.cli.main import main
from factory.cli.verify import VerificationReport, verify_repository


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_FILES = (
    "pyproject.toml",
    "factory/__init__.py",
    "factory/errors.py",
    "factory/serialization.py",
    "factory/cli/__init__.py",
    "factory/cli/__main__.py",
    "factory/cli/main.py",
    "factory/cli/verify.py",
    "factory/contracts/__init__.py",
    "factory/contracts/validation.py",
    "factory/governance/__init__.py",
    "factory/governance/gates.py",
    "factory/governance/policy.py",
    "factory/governance/state_machine.py",
    "factory/interview/__init__.py",
    "factory/interview/protocol.py",
    "factory/production/__init__.py",
    "factory/production/blueprint.py",
    "factory/production/generator.py",
    "factory/production/jobs.py",
    "factory/contracts/commander-intent.schema.json",
    "factory/contracts/agent-blueprint.schema.json",
    "factory/contracts/factory-job.schema.json",
    "factory/contracts/factory-manifest.schema.json",
    "factory/contracts/review-report.schema.json",
    "factory/governance/production-gates.yaml",
    "factory/governance/state-machine.yaml",
    "factory/interview/questions.yaml",
    "templates/job/JOB.md.tmpl",
    "templates/job/COMMANDER_INTENT.md.tmpl",
    "templates/agent/README.md.tmpl",
    "templates/agent/COMMANDER_INTENT.md.tmpl",
    "templates/agent/ARCHITECTURE.md.tmpl",
    "templates/agent/WORKFLOW.md.tmpl",
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


def test_repository_cannot_borrow_required_files_through_escaping_symlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "borrowed-repository"
    for relative in REPOSITORY_FILES:
        link = root / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(ROOT / relative)

    report = verify_repository(root)

    assert report.ok is False
    assert report.failures[0] == (
        "unsafe:factory/contracts/commander-intent.schema.json:outside-root"
    )
    assert all(not failure.startswith("unreadable:") for failure in report.failures)


def test_repository_allows_required_symlink_that_resolves_inside_root(
    tmp_path: Path,
) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/commander-intent.schema.json"
    internal = root / "internal/commander-intent.schema.json"
    internal.parent.mkdir()
    schema_path.replace(internal)
    schema_path.symlink_to(internal)

    report = verify_repository(root)

    assert report.ok is True, report.failures


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


@pytest.mark.parametrize(
    ("relative", "needle", "replacement"),
    [
        (
            "factory/governance/production-gates.yaml",
            'schema_version: "1.0"',
            'schema_version: "1.0"\nschema_version: "1.0"',
        ),
        (
            "factory/governance/production-gates.yaml",
            "    points: 15",
            "    points: 15\n    points: 15",
        ),
        (
            "factory/governance/state-machine.yaml",
            "      NEW: [DISCOVERY]",
            "      NEW: [DISCOVERY]\n      NEW: [DISCOVERY]",
        ),
    ],
)
def test_governance_yaml_duplicate_keys_fail_repository_verification(
    tmp_path: Path,
    relative: str,
    needle: str,
    replacement: str,
) -> None:
    root = _copy_repository_contract(tmp_path)
    policy_path = root / relative
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8").replace(
            needle,
            replacement,
            1,
        ),
        encoding="utf-8",
    )

    report = verify_repository(root)

    assert report.ok is False
    assert f"malformed:{relative}:invalid-yaml" in report.failures


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


def test_state_policy_rejects_unused_injected_factory_state(
    tmp_path: Path,
) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/factory-job.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["$defs"]["factory_state"]["enum"].append("ARCHIVED")
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is False
    assert any(
        item.startswith(
            "malformed:factory/governance/state-machine.yaml:invalid-policy"
        )
        and "not represented" in item
        and "ARCHIVED" in item
        for item in report.failures
    )


@pytest.mark.parametrize("nested", [False, True])
def test_production_policy_uses_injected_commander_intent_schema(
    tmp_path: Path,
    nested: bool,
) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/commander-intent.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if nested:
        mission = schema["$defs"]["mission"]
        mission["required"][0] = "purpose"
        mission["properties"]["purpose"] = mission["properties"].pop("statement")
    else:
        schema["required"][schema["required"].index("mission")] = "purpose"
        schema["properties"]["purpose"] = schema["properties"].pop("mission")
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is False
    assert any(
        item.startswith(
            "malformed:factory/governance/production-gates.yaml:invalid-policy"
        )
        and "schema does not define policy path" in item
        for item in report.failures
    )


@pytest.mark.parametrize(
    ("reference", "failure_kind"),
    [
        ("#/$defs/does-not-exist", "dangling-ref"),
        ("https://unregistered.example/schema.json", "external-ref"),
    ],
)
def test_schema_reference_integrity_fails_closed_without_network(
    tmp_path: Path,
    reference: str,
    failure_kind: str,
) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/commander-intent.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["mission"]["$ref"] = reference
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is False
    assert (
        f"malformed:factory/contracts/commander-intent.schema.json:{failure_kind}"
        in report.failures
    )


def test_schema_reference_integrity_allows_recursive_local_refs(
    tmp_path: Path,
) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/commander-intent.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["$defs"]["recursive_local"] = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/recursive_local"}},
    }
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is True, report.failures


@pytest.mark.parametrize(
    ("target_name", "target_value"),
    [("title", None), ("x-schema-list", [])],
)
def test_schema_reference_target_must_itself_be_a_schema(
    tmp_path: Path,
    target_name: str,
    target_value: object,
) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/commander-intent.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if target_value is not None:
        schema[target_name] = target_value
    schema["properties"]["mission"]["$ref"] = f"#/{target_name}"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is False
    assert (
        "malformed:factory/contracts/commander-intent.schema.json:"
        "invalid-ref-target"
        in report.failures
    )


def test_schema_reference_target_allows_boolean_schema(tmp_path: Path) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/commander-intent.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["$defs"]["allow_anything"] = True
    schema["$defs"]["boolean_reference"] = {
        "$ref": "#/$defs/allow_anything"
    }
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is True, report.failures


@pytest.mark.parametrize("array_token", ["-1", "01"])
def test_schema_reference_integrity_uses_rfc_array_indices(
    tmp_path: Path,
    array_token: str,
) -> None:
    root = _copy_repository_contract(tmp_path)
    schema_path = root / "factory/contracts/commander-intent.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["x-reference-array"] = [
        {"type": "string"},
        {"type": "string"},
    ]
    schema["$defs"]["array_reference"] = {
        "$ref": f"#/x-reference-array/{array_token}"
    }
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is False
    assert (
        "malformed:factory/contracts/commander-intent.schema.json:dangling-ref"
        in report.failures
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
                'requires-python = ">=3.11"',
                'requires-python = ">=3.0,!=3.10.*"',
            ),
            "invalid:pyproject.toml:project.requires-python",
        ),
        (
            lambda text: text.replace(
                'requires-python = ">=3.11"',
                'requires-python = ">3.10"',
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
            lambda text: text.replace(
                '"PyYAML>=6.0"',
                '"PyYAML>=6.0; python_version < \'3.0\'"',
            ),
            "invalid:pyproject.toml:project.dependencies:PyYAML",
        ),
        (
            lambda text: text.replace(
                '"PyYAML>=6.0"',
                '"PyYAML>=6.0garbage"',
            ),
            "invalid:pyproject.toml:project.dependencies:PyYAML",
        ),
        (
            lambda text: text.replace(
                '"PyYAML>=6.0"',
                '"PyYAML>=6.0,<5"',
            ),
            "invalid:pyproject.toml:project.dependencies:PyYAML",
        ),
        (
            lambda text: text.replace(
                ', "packaging>=24.0"',
                "",
            ),
            "invalid:pyproject.toml:project.dependencies:packaging",
        ),
        (
            lambda text: text.replace(
                'include = ["factory*"]',
                'include = ["factory"]',
            ),
            "invalid:pyproject.toml:package-discovery:factory.cli",
        ),
        (
            lambda text: text.replace(
                'include = ["factory*"]',
                'include = ["factory*"]\nexclude = ["factory.cli"]',
            ),
            "invalid:pyproject.toml:package-excluded:factory.cli",
        ),
        (
            lambda text: text.replace(
                'include = ["factory*"]',
                'include = ["factory*"]\nexclude = "factory.cli"',
            ),
            "invalid:pyproject.toml:package-discovery.exclude",
        ),
        (
            lambda text: text.replace(
                'include = ["factory*"]',
                'include = ["factory*"]\nwhere = ["missing"]',
            ),
            "invalid:pyproject.toml:package-discovery.where",
        ),
        (
            lambda text: (
                text
                + '\n[tool.setuptools.package-dir]\n'
                + '"" = "src"\n'
            ),
            "invalid:pyproject.toml:package-dir",
        ),
        (
            lambda text: (
                text
                + '\n[tool.setuptools.exclude-package-data]\n'
                + '"factory.contracts" = ["*.schema.json"]\n'
            ),
            (
                "invalid:pyproject.toml:exclude-package-data:"
                "factory/contracts/commander-intent.schema.json"
            ),
        ),
        (
            lambda text: (
                text
                + '\n[tool.setuptools.exclude-package-data]\n'
                + '"factory.contracts" = "*.schema.json"\n'
            ),
            "invalid:pyproject.toml:exclude-package-data:factory.contracts",
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
    ).replace('"PyYAML>=6.0"', '"pyyaml >= 6.0.0"').replace(
        '"jsonschema[format]>=4.21"',
        '"jsonschema[FORMAT] >= 4.21.0"',
    ).replace('"packaging>=24.0"', '"PACKAGING >= 24.0.0"')
    pyproject.write_text(contents, encoding="utf-8")

    report = verify_repository(root)

    assert report.ok is True, report.failures


def test_missing_declared_job_template_fails_verification(tmp_path: Path) -> None:
    root = _copy_repository_contract(tmp_path)
    (root / "templates/job/JOB.md.tmpl").unlink()

    report = verify_repository(root)

    assert report.ok is False
    assert "missing:templates/job/JOB.md.tmpl" in report.failures


def test_missing_representative_package_source_fails_verification(
    tmp_path: Path,
) -> None:
    root = _copy_repository_contract(tmp_path)
    (root / "factory/cli/__init__.py").unlink()

    report = verify_repository(root)

    assert report.ok is False
    assert "missing:factory/cli/__init__.py" in report.failures


def test_missing_m1_runtime_module_fails_verification(tmp_path: Path) -> None:
    root = _copy_repository_contract(tmp_path)
    (root / "factory/cli/main.py").unlink()

    report = verify_repository(root)

    assert report.ok is False
    assert "missing:factory/cli/main.py" in report.failures


def test_nonroot_package_discovery_is_rejected_before_empty_wheel_can_pass(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            "__pycache__",
            "*.egg-info",
            "build",
        ),
    )
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'include = ["factory*"]',
            'include = ["factory*"]\nwhere = ["empty"]',
        ),
        encoding="utf-8",
    )
    (root / "empty").mkdir()
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(root),
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(wheel_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    wheel = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert "factory/__init__.py" not in archive.namelist()
    report = verify_repository(root)
    assert report.ok is False
    assert "invalid:pyproject.toml:package-discovery.where" in report.failures


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
        (
            "jobs/*\nreviews/*\n!jobs/.gitkeep\n!reviews/.gitkeep\n"
            "!jobs/private-job/\n"
        ),
        (
            "jobs/*\nreviews/*\n!jobs/.gitkeep\n!reviews/.gitkeep\n"
            "!jobs/private-job/**\n"
        ),
        (
            "jobs/*\nreviews/*\n!jobs/.gitkeep\n!reviews/.gitkeep\n"
            "!jobs/leak\n!jobs/leak/**\n"
        ),
        (
            "jobs/*\nreviews/*\n!jobs/.gitkeep\n!reviews/.gitkeep\n"
            "jobs/extra-private/*\n"
        ),
        (
            " jobs/*\n reviews/*\n !jobs/.gitkeep\n !reviews/.gitkeep\n"
        ),
        (
            "jobs/* \nreviews/* \n!jobs/.gitkeep \n!reviews/.gitkeep \n"
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


def test_approved_workshop_rules_match_real_git_privacy_behavior(
    tmp_path: Path,
) -> None:
    root = _copy_repository_contract(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    private_job = root / "workshop/jobs/private-job/status.json"
    private_review = root / "workshop/reviews/private-review/status.json"
    private_job.parent.mkdir(parents=True)
    private_review.parent.mkdir(parents=True)
    private_job.write_text("{}", encoding="utf-8")
    private_review.write_text("{}", encoding="utf-8")

    def ignored(relative: str) -> bool:
        return subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", relative],
            cwd=root,
            check=False,
        ).returncode == 0

    assert ignored("workshop/jobs/private-job/status.json") is True
    assert ignored("workshop/reviews/private-review/status.json") is True
    assert ignored("workshop/jobs/.gitkeep") is False
    assert ignored("workshop/reviews/.gitkeep") is False
    assert verify_repository(root).ok is True

    spaced_rules = "".join(
        f" {rule}\n"
        for rule in ("jobs/*", "reviews/*", "!jobs/.gitkeep", "!reviews/.gitkeep")
    )
    (root / "workshop/.gitignore").write_text(spaced_rules, encoding="utf-8")
    assert ignored("workshop/jobs/private-job/status.json") is False
    assert ignored("workshop/reviews/private-review/status.json") is False
    assert verify_repository(root).ok is False


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


def test_job_status_escapes_lone_surrogate_for_utf8_stdout(
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
        encoding = "utf-8"

        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, value: str) -> int:
            value.encode("utf-8")
            self.parts.append(value)
            return len(value)

        def flush(self) -> None:
            return None

    stream = StrictUtf8Stream()
    monkeypatch.setattr(sys, "stdout", stream)

    assert main(["job-status", str(job_dir)]) == 0
    rendered = "".join(stream.parts)
    assert "\\ud800" in rendered
    assert json.loads(rendered)["name"] == "\ud800"


def test_job_status_escapes_unicode_for_ascii_stdout(
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
            "演示",
            "--job-id",
            "job-demo",
        ]
    ) == 0
    capsys.readouterr()

    class AsciiStream:
        encoding = "ascii"

        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, value: str) -> int:
            value.encode("ascii")
            self.parts.append(value)
            return len(value)

        def flush(self) -> None:
            return None

    stream = AsciiStream()
    monkeypatch.setattr(sys, "stdout", stream)
    job_dir = tmp_path / "jobs/job-demo-演示"

    assert main(["job-status", str(job_dir)]) == 0
    rendered = "".join(stream.parts)
    assert "\\u6f14\\u793a" in rendered
    assert json.loads(rendered)["name"] == "演示"


def test_verify_repo_escapes_unicode_failure_for_ascii_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _copy_repository_contract(tmp_path)
    policy_path = root / "factory/governance/production-gates.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8") + "雪: true\n",
        encoding="utf-8",
    )

    class AsciiStream:
        encoding = "ascii"

        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, value: str) -> int:
            value.encode("ascii")
            self.parts.append(value)
            return len(value)

        def flush(self) -> None:
            return None

    stream = AsciiStream()
    monkeypatch.setattr(sys, "stdout", stream)

    assert main(["verify-repo", str(root)]) == 1
    rendered = "".join(stream.parts)
    assert "\\u96ea" in rendered
    assert "invalid-policy" in rendered


def test_cli_error_is_ascii_safe_and_verify_execution_is_guarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AsciiStream:
        encoding = "ascii"

        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, value: str) -> int:
            value.encode("ascii")
            self.parts.append(value)
            return len(value)

        def flush(self) -> None:
            return None

    stream = AsciiStream()
    monkeypatch.setattr(sys, "stderr", stream)

    assert main(["job-status", str(tmp_path / "雪任务")]) == 1
    assert "error:" in "".join(stream.parts)
    assert "\\u96ea" in "".join(stream.parts)

    import factory.cli.main as main_module

    monkeypatch.setattr(
        main_module,
        "verify_repository",
        lambda _root: (_ for _ in ()).throw(RuntimeError("雪故障")),
    )
    assert main(["verify-repo", str(tmp_path)]) == 1
    assert "\\u96ea" in "".join(stream.parts)


def test_argparse_usage_error_remains_exit_two() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["job-init"])

    assert raised.value.code == 2


@pytest.mark.parametrize(
    "corruption",
    ["missing", "malformed", "duplicate", "impossible"],
)
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
    elif corruption == "duplicate":
        status_path = job_dir / "status.json"
        payload = status_path.read_text(encoding="utf-8").replace(
            '"status": "NEW"',
            '"status": "DELIVERED",\n  "status": "NEW"',
            1,
        )
        status_path.write_text(payload, encoding="utf-8")
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
