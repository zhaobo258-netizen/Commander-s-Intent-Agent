from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from factory.cli.main import main
from factory.optimization.diff import compare_trees
from factory.optimization.pipeline import finalize_optimization
from factory.optimization.workspace import CandidateManifest
from factory.production import create_job, load_job
from factory.review.snapshot import snapshot_tree
from factory.errors import UnsafePathError


ROOT = Path(__file__).resolve().parents[2]


def _setup(tmp_path: Path):
    source = tmp_path / "source-agent"
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
    job_dir = create_job(tmp_path / "workshop", "OPTIMIZE", "opt-agent", datetime.now(timezone.utc), job_id="opt-1")
    return source, baseline, plan_path, job_dir


def test_unapproved_cli_stops_before_candidate(tmp_path: Path, capsys) -> None:
    source, baseline, plan, job_dir = _setup(tmp_path)
    output = tmp_path / "candidates"
    assert main(["optimize-prepare", str(job_dir), str(plan), str(output)]) == 2
    assert not output.exists()
    assert load_job(job_dir)["status"] == "OPTIMIZATION_PROPOSED"
    capsys.readouterr()


def test_output_inside_source_is_rejected_without_source_mutation(tmp_path: Path) -> None:
    source, baseline, plan, job_dir = _setup(tmp_path)
    from factory.cli.optimize import optimize_prepare_payload

    try:
        optimize_prepare_payload(job_dir, plan, source / "candidate-output", True)
    except UnsafePathError:
        pass
    else:
        raise AssertionError("source-contained output must be rejected")

    assert snapshot_tree(source).tree_hash == baseline
    assert not (source / "candidate-output").exists()


def test_approved_candidate_diff_and_finalize_leave_source_unchanged(tmp_path: Path, capsys) -> None:
    source, baseline, plan, job_dir = _setup(tmp_path)
    output = tmp_path / "candidates"
    assert main(["optimize-prepare", str(job_dir), str(plan), str(output), "--approve"]) == 0
    prepared = json.loads(capsys.readouterr().out)
    candidate = Path(prepared["candidate_path"])
    assert snapshot_tree(source).tree_hash == baseline
    assert not (candidate / ".git").exists()

    (candidate / "README.md").write_text("# Improved Agent\n\nClear instructions.\n", encoding="utf-8")
    new_case = candidate / "evaluation" / "new-case.yaml"
    new_case.write_text("type: Golden\n", encoding="utf-8")
    diff = compare_trees(source, candidate)
    assert diff.modified == ("README.md",)
    assert diff.added == ("evaluation/new-case.yaml",)
    assert "Clear instructions" not in diff.summary

    assert main(["optimize-finalize", str(job_dir)]) == 0
    finalized = json.loads(capsys.readouterr().out)
    assert finalized["ready"] is True
    assert finalized["job_state"] == "CANDIDATE_READY"
    assert snapshot_tree(source).tree_hash == baseline


def test_failed_validator_blocks_job(tmp_path: Path) -> None:
    source, baseline, plan, job_dir = _setup(tmp_path)
    from factory.cli.optimize import optimize_prepare_payload
    prepared = optimize_prepare_payload(job_dir, plan, tmp_path / "out", True)
    data = json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))
    manifest = CandidateManifest(Path(data["source_path"]), data["source_hash"], Path(data["candidate_path"]), data["plan_hash"])
    result = finalize_optimization(job_dir, manifest, validator=lambda _: ["schema failure"])
    assert result.ready is False
    assert result.job["status"] == "BLOCKED"
