from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from factory.cli.main import main
from factory.production import create_job, load_job


ROOT = Path(__file__).resolve().parents[2]


def _write_yaml(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_next_question_and_validate_intent_are_machine_readable(
    tmp_path: Path,
    incomplete_intent: dict,
    capsys,
) -> None:
    intent_path = tmp_path / "intent.yaml"
    _write_yaml(intent_path, incomplete_intent)
    assert main(["next-question", str(intent_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["question"]["path"] == "/user"

    assert main(["validate-intent", str(intent_path)]) == 2
    decision = json.loads(capsys.readouterr().out)
    assert decision["ready"] is False


def test_generate_runs_create_job_to_candidate_ready(
    tmp_path: Path,
    production_ready_intent: dict,
    valid_design: dict,
    capsys,
) -> None:
    job_dir = create_job(
        tmp_path / "workshop",
        "CREATE",
        "cli-agent",
        datetime(2026, 7, 11, tzinfo=timezone.utc),
        job_id="job-cli",
    )
    intent_path = tmp_path / "intent.yaml"
    design_path = tmp_path / "design.yaml"
    _write_yaml(intent_path, production_ready_intent)
    _write_yaml(design_path, valid_design)

    assert main([
        "generate",
        "--job-dir", str(job_dir),
        "--intent", str(intent_path),
        "--design", str(design_path),
        "--template-root", str(ROOT / "templates" / "agent"),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["job_state"] == "CANDIDATE_READY"
    assert Path(payload["manifest_path"]).is_file()
    assert payload["status_layers"] == {
        "local_generated": True,
        "local_validated": True,
        "installed": False,
        "published": False,
        "real_usage_verified": False,
    }
    assert load_job(job_dir)["status"] == "CANDIDATE_READY"


def test_blocked_generate_returns_two_without_output(
    tmp_path: Path,
    valid_intent: dict,
    valid_design: dict,
    capsys,
) -> None:
    job_dir = create_job(
        tmp_path / "workshop", "CREATE", "blocked", datetime.now(timezone.utc), job_id="job-blocked"
    )
    intent_path = tmp_path / "intent.yaml"
    design_path = tmp_path / "design.yaml"
    _write_yaml(intent_path, valid_intent)
    _write_yaml(design_path, valid_design)

    assert main([
        "generate", "--job-dir", str(job_dir), "--intent", str(intent_path),
        "--design", str(design_path), "--template-root", str(ROOT / "templates" / "agent"),
    ]) == 2
    assert not any((job_dir / "output").iterdir())
    assert "not production-ready" in capsys.readouterr().err


def test_skill_cli_lifecycle_uses_injected_home(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source" / "commander-agent-factory"
    shutil.copytree(ROOT / "skills" / "commander-agent-factory", source)
    home = tmp_path / ".codex"
    common = ["--source", str(source), "--codex-home", str(home)]

    assert main(["skill-install", *common]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "installed"
    assert main(["skill-check", *common]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "current"
    assert main(["skill-uninstall", *common]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_installed"
