from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from factory.cli.main import main
from factory.governance import load_policy
from factory.production import create_job, load_job
from factory.review.evaluator import review_agent
from factory.review.pipeline import run_review
from factory.review.snapshot import snapshot_tree, verify_unchanged


ROOT = Path(__file__).resolve().parents[2]


def test_snapshot_skips_links_and_detects_mutation(tmp_path: Path) -> None:
    target = tmp_path / "agent"
    target.mkdir()
    (target / "README.md").write_text("before\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    (target / "link").symlink_to(outside)
    before = snapshot_tree(target)
    assert before.files[0].path == "README.md"
    assert before.skipped_links == ("link",)
    (target / "README.md").write_text("after\n", encoding="utf-8")
    assert verify_unchanged(before, snapshot_tree(target)) is False


def test_evaluator_is_evidence_backed_and_provisional() -> None:
    minimal = review_agent(ROOT / "tests/fixtures/review/minimal-agent", load_policy("evaluation-policy"))
    assert {finding.severity for finding in minimal.findings} >= {"P1", "P2"}
    assert minimal.quality["outcome"]["status"] == "not_evidenced"
    assert minimal.quality["grade"] == "provisional"
    standard = review_agent(ROOT / "tests/fixtures/review/standard-agent", load_policy("evaluation-policy"))
    assert not any(f.severity in {"P0", "P1"} for f in standard.findings)
    assert standard.status_layers["real_usage_verified"] is False


def test_review_pipeline_and_cli_never_modify_target(tmp_path: Path, capsys) -> None:
    target = tmp_path / "target"
    shutil.copytree(ROOT / "tests/fixtures/review/standard-agent", target)
    before = snapshot_tree(target)
    job_dir = create_job(tmp_path / "workshop", "REVIEW", "review-agent", datetime.now(timezone.utc), job_id="review-1")
    written = run_review(job_dir, target)
    assert verify_unchanged(before, snapshot_tree(target))
    assert written.json_path.is_relative_to(job_dir / "reports")
    assert load_job(job_dir)["status"] == "REVIEW_READY"
    assert json.loads(written.json_path.read_text(encoding="utf-8"))["verdict"] == "provisional"

    cli_target = tmp_path / "cli-target"
    shutil.copytree(target, cli_target)
    assert main(["review", str(cli_target), "--workshop", str(tmp_path / "cli-workshop"), "--job-id", "cli-review", "--name", "cli-agent"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["json_report"]).is_file()
    assert verify_unchanged(snapshot_tree(cli_target), snapshot_tree(cli_target))
