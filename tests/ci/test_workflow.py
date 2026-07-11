from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_ci_is_read_only_and_runs_public_gate() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))

    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in workflow["on"]
    matrix = workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert set(matrix) == {"3.11", "3.13"}
    commands = "\n".join(
        step.get("run", "") for step in workflow["jobs"]["test"]["steps"]
    )
    assert "python -m pytest" in commands
    assert "python -m factory.cli verify-repo . --public" in commands
