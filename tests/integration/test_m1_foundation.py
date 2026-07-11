from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from factory import production as production_module
from factory.cli.main import main
from factory.cli.verify import verify_repository
from factory.contracts import validate_document
from factory.governance import (
    evaluate_production_gate,
    load_policy,
    transition,
    validate_lifecycle_snapshot,
)
from factory.production import (
    load_job,
    resume_job,
    save_checkpoint,
)


ROOT = Path(__file__).resolve().parents[2]
VALID_INTENT = ROOT / "tests" / "fixtures" / "contracts" / "valid-intent.yaml"


def test_m1_foundation_runs_local_job_through_ready_and_validation(
    tmp_path: Path,
    capsys,
) -> None:
    workshop = tmp_path / "workshop"
    job_dir = workshop / "jobs" / "job-m1-foundation-m1-foundation"

    return_code = main(
        [
            "job-init",
            "--workshop",
            str(workshop),
            "--mode",
            "CREATE",
            "--name",
            "m1-foundation",
            "--job-id",
            "job-m1-foundation",
        ]
    )

    assert return_code == 0
    assert capsys.readouterr().out.splitlines() == [
        f"created:{job_dir}",
        "state:NEW",
    ]
    assert job_dir.is_dir()

    fixture_before = VALID_INTENT.read_bytes()
    with VALID_INTENT.open(encoding="utf-8") as stream:
        intent = yaml.safe_load(stream)
    policy = load_policy("production-gates")
    intent["provenance"] = [
        {
            "path": path,
            "source_type": "user_confirmed",
            "reference": f"integration-confirmed:{path}",
        }
        for path in policy["critical_paths"]
    ]

    assert VALID_INTENT.read_bytes() == fixture_before
    assert validate_document("commander-intent", intent) == ()
    gate = evaluate_production_gate(intent, policy)
    assert gate.score == 100
    assert gate.ready is True
    assert gate.blockers == ()
    assert gate.missing_sources == ()

    job = load_job(job_dir)
    created_at = datetime.fromisoformat(job["created_at"])
    for offset, target in enumerate(
        (
            "DISCOVERY",
            "INTERVIEWING",
            "INTENT_CONFIRMATION",
            "READY",
        ),
        start=1,
    ):
        transition_ref = f"evidence/transition-{offset}-{target.lower()}.md"
        job = transition(
            job,
            target,
            trigger=f"integration_{target.lower()}",
            evidence=[transition_ref],
            now=created_at + timedelta(seconds=offset),
        )
        save_checkpoint(
            job_dir,
            job,
            {
                "kind": "state_transition",
                "ref": transition_ref,
                "status": "verified",
                "at": job["updated_at"],
            },
        )
        job = load_job(job_dir)
        assert job["status"] == target
        assert validate_document("factory-job", job) == ()
        validate_lifecycle_snapshot(job)

    assert gate.ready is True
    probe_calls: list[dict] = []

    def injected_probe(snapshot: dict) -> dict:
        probe_calls.append(snapshot)
        return {
            "source": "injected-test-probe",
            "repository_head": "fresh-local-head",
        }

    resumed = resume_job(job_dir, injected_probe)

    assert len(probe_calls) == 1
    assert probe_calls[0]["status"] == "READY"
    assert resumed["external_state"] == {
        "source": "injected-test-probe",
        "repository_head": "fresh-local-head",
    }
    assert load_job(job_dir)["external_state"] == resumed["external_state"]

    validation_ref = "evidence/m1-local-validation.txt"
    checkpoint_ref = "evidence/m1-status-checkpoint.json"
    marked = production_module.mark_status_layer(
        resumed, "local_validated", validation_ref
    )
    save_checkpoint(
        job_dir,
        marked,
        {
            "kind": "checkpoint",
            "ref": checkpoint_ref,
            "status": "verified",
            "at": marked["updated_at"],
        },
    )
    persisted = load_job(job_dir)

    assert persisted["status_layers"] == {
        "local_generated": False,
        "local_validated": True,
        "installed": False,
        "published": False,
        "real_usage_verified": False,
    }
    assert {
        "kind": "status_layer:local_validated",
        "ref": validation_ref,
        "status": "verified",
        "at": marked["updated_at"],
    } in persisted["evidence"]
    assert persisted["evidence"][-1]["ref"] == checkpoint_ref
    assert persisted["external_state"] == resumed["external_state"]
    assert validate_document("factory-job", persisted) == ()
    validate_lifecycle_snapshot(persisted)

    repository_report = verify_repository(ROOT)
    assert repository_report.ok is True
    assert repository_report.failures == ()
