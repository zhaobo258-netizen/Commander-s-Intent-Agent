from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from factory.cli.main import main
from factory.cli.verify import verify_repository
from factory.production import load_job


ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, value: dict) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_m2_create_pipeline_generates_valid_candidate_and_manages_temp_skill(
    tmp_path: Path,
    incomplete_intent: dict,
    production_ready_intent: dict,
    valid_design: dict,
    capsys,
) -> None:
    workshop = tmp_path / "workshop"
    assert main([
        "job-init", "--workshop", str(workshop), "--mode", "CREATE",
        "--name", "m2-agent", "--job-id", "job-m2",
    ]) == 0
    capsys.readouterr()
    job_dir = workshop / "jobs" / "job-m2-m2-agent"

    draft = tmp_path / "draft-intent.yaml"
    _write(draft, incomplete_intent)
    assert main(["next-question", str(draft)]) == 0
    assert json.loads(capsys.readouterr().out)["question"]["path"] == "/user"

    intent = tmp_path / "confirmed-intent.yaml"
    design = tmp_path / "design.yaml"
    _write(intent, production_ready_intent)
    _write(design, valid_design)
    assert main(["validate-intent", str(intent)]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True

    generate_args = [
        "generate", "--job-dir", str(job_dir), "--intent", str(intent),
        "--design", str(design), "--template-root", str(ROOT / "templates" / "agent"),
    ]
    assert main(generate_args) == 0
    generated = json.loads(capsys.readouterr().out)
    assert generated["job_state"] == "CANDIDATE_READY"
    assert Path(generated["manifest_path"]).is_file()
    assert main(generate_args) == 0
    assert json.loads(capsys.readouterr().out)["manifest_path"] == generated["manifest_path"]

    job = load_job(job_dir)
    assert job["status_layers"] == {
        "local_generated": True,
        "local_validated": True,
        "installed": False,
        "published": False,
        "real_usage_verified": False,
    }

    source = tmp_path / "skill-source" / "commander-agent-factory"
    shutil.copytree(ROOT / "skills" / "commander-agent-factory", source)
    codex_home = tmp_path / ".codex"
    common = ["--source", str(source), "--codex-home", str(codex_home)]
    assert main(["skill-install", *common]) == 0
    capsys.readouterr()
    assert main(["skill-check", *common]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "current"
    assert main(["skill-uninstall", *common]) == 0
    capsys.readouterr()

    report = verify_repository(ROOT)
    assert report.ok is True
    assert report.failures == ()
