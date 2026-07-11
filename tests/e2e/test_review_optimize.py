from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from factory.cli.main import main
from factory.errors import FactoryError
from factory.production import create_job, load_job
from factory.review import pipeline as review_pipeline
from factory.review.snapshot import snapshot_tree


ROOT = Path(__file__).resolve().parents[2]


def test_golden_and_malformed_reviews_are_read_only(tmp_path: Path, capsys) -> None:
    for fixture, expected_minimum in (("standard-agent", 0), ("minimal-agent", 2)):
        target = tmp_path / fixture
        shutil.copytree(ROOT / "tests/fixtures/review" / fixture, target)
        before = snapshot_tree(target)
        assert main(["review", str(target), "--workshop", str(tmp_path / f"workshop-{fixture}"), "--job-id", f"job-{fixture}", "--name", fixture]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["finding_count"] >= expected_minimum
        assert snapshot_tree(target).tree_hash == before.tree_hash


def test_review_detects_target_mutation_during_evaluation(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    shutil.copytree(ROOT / "tests/fixtures/review/standard-agent", target)
    job_dir = create_job(tmp_path / "workshop", "REVIEW", "mutating", datetime.now(timezone.utc), job_id="review-mutate")
    original = review_pipeline.review_agent

    def mutating_review(path, policy):
        report = original(path, policy)
        (Path(path) / "README.md").write_text("mutated during review\n", encoding="utf-8")
        return report

    monkeypatch.setattr(review_pipeline, "review_agent", mutating_review)
    with pytest.raises(FactoryError, match="changed"):
        review_pipeline.run_review(job_dir, target)
    assert load_job(job_dir)["status"] == "REVIEWING"


def _optimization_setup(tmp_path: Path):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "tests/fixtures/review/standard-agent", source)
    baseline = snapshot_tree(source).tree_hash
    plan = {
        "schema_version": "1.0", "target": str(source), "baseline_hash": baseline,
        "intent_change": False, "approved_by_user": True,
        "approved_at": "2026-07-11T12:00:00+00:00",
        "changes": ["Improve README"], "acceptance": ["Structural validation passes"],
        "rollback": "Delete candidate",
    }
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    job_dir = create_job(tmp_path / "opt-workshop", "OPTIMIZE", "optimize", datetime.now(timezone.utc), job_id="opt-e2e")
    return source, baseline, plan_path, job_dir


def test_unapproved_optimization_stops_without_candidate(tmp_path: Path, capsys) -> None:
    source, baseline, plan, job_dir = _optimization_setup(tmp_path)
    output = tmp_path / "candidates"
    assert main(["optimize-prepare", str(job_dir), str(plan), str(output)]) == 2
    capsys.readouterr()
    assert not output.exists()
    assert snapshot_tree(source).tree_hash == baseline


def test_approved_optimization_changes_candidate_only(tmp_path: Path, capsys) -> None:
    source, baseline, plan, job_dir = _optimization_setup(tmp_path)
    output = tmp_path / "candidates"
    assert main(["optimize-prepare", str(job_dir), str(plan), str(output), "--approve"]) == 0
    candidate = Path(json.loads(capsys.readouterr().out)["candidate_path"])
    (candidate / "README.md").write_text("# Approved candidate improvement\n", encoding="utf-8")
    assert main(["optimize-finalize", str(job_dir)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ready"] is True
    assert result["status_layers"]["local_generated"] is True
    assert result["status_layers"]["local_validated"] is True
    assert result["status_layers"]["published"] is False
    assert result["status_layers"]["real_usage_verified"] is False
    assert snapshot_tree(source).tree_hash == baseline
