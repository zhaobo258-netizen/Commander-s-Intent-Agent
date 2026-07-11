from __future__ import annotations

import copy
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from factory.contracts import validate_document
from factory.errors import ContractValidationError, FactoryError, UnsafePathError
from factory.production import jobs as jobs_module
from factory.production.jobs import create_job, load_job, resume_job, save_checkpoint


NOW = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("mode", "container", "suffix"),
    [
        ("CREATE", "jobs", "create-agent"),
        ("REVIEW", "reviews", "review-agent"),
        ("OPTIMIZE", "reviews", "optimize-agent"),
    ],
)
def test_create_job_builds_private_layout_and_valid_initial_contract(
    tmp_path: Path,
    mode: str,
    container: str,
    suffix: str,
) -> None:
    job_dir = create_job(tmp_path, mode, suffix, NOW, job_id=f"job-{suffix}")

    assert job_dir == tmp_path / container / f"job-{suffix}-{suffix}"
    assert {path.name for path in job_dir.iterdir()} == {
        "COMMANDER_INTENT.md",
        "JOB.md",
        "evidence",
        "intake",
        "output",
        "reports",
        "status.json",
    }
    assert all(
        (job_dir / directory).is_dir()
        for directory in ("intake", "evidence", "reports", "output")
    )
    assert f"# Factory Job: {suffix}" in (job_dir / "JOB.md").read_text(
        encoding="utf-8"
    )
    assert f"Job ID: `job-{suffix}`" in (job_dir / "JOB.md").read_text(
        encoding="utf-8"
    )
    commander_intent = (job_dir / "COMMANDER_INTENT.md").read_text(
        encoding="utf-8"
    )
    assert f"Agent: {suffix}" in commander_intent
    assert "Status: Not confirmed" in commander_intent

    job = load_job(job_dir)
    assert validate_document("factory-job", job) == ()
    assert job == {
        "schema_version": "1.0",
        "job_id": f"job-{suffix}",
        "mode": mode,
        "name": suffix,
        "status": "NEW",
        "scope": {
            "summary": f"Private {mode.lower()} factory job for {suffix}",
            "target_refs": [],
        },
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "checkpoint": {
            "sequence": 0,
            "state": "NEW",
            "next_action": (
                "begin_discovery" if mode == "CREATE" else "begin_review_intake"
            ),
            "updated_at": NOW.isoformat(),
            "evidence_ref": None,
        },
        "missing_items": [],
        "approvals": [],
        "status_layers": {
            "local_generated": False,
            "local_validated": False,
            "installed": False,
            "published": False,
            "real_usage_verified": False,
        },
        "evidence": [],
        "transitions": [],
    }


@pytest.mark.parametrize(
    "unsafe",
    ["", "   ", "..", "sales..agent", "../escape", "nested/agent", r"nested\agent", "/absolute"],
)
@pytest.mark.parametrize("field", ["name", "job_id"])
def test_create_job_rejects_unsafe_path_components_before_mutation(
    tmp_path: Path,
    field: str,
    unsafe: str,
) -> None:
    arguments = {"name": "safe-agent", "job_id": "job-safe"}
    arguments[field] = unsafe

    with pytest.raises(UnsafePathError):
        create_job(
            tmp_path,
            "CREATE",
            arguments["name"],
            NOW,
            job_id=arguments["job_id"],
        )

    assert list(tmp_path.iterdir()) == []


def test_create_job_rejects_symlinked_container_escape(tmp_path: Path) -> None:
    workshop_root = tmp_path / "workshop"
    outside = tmp_path / "outside"
    workshop_root.mkdir()
    outside.mkdir()
    (workshop_root / "jobs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError, match="outside workshop root"):
        create_job(
            workshop_root,
            "CREATE",
            "safe-agent",
            NOW,
            job_id="job-safe",
        )

    assert list(outside.iterdir()) == []


def test_create_job_refuses_to_overwrite_existing_job(tmp_path: Path) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "safe-agent",
        NOW,
        job_id="job-safe",
    )
    sentinel = job_dir / "keep.txt"
    sentinel.write_text("do not replace", encoding="utf-8")
    original_status = (job_dir / "status.json").read_bytes()

    with pytest.raises(FactoryError, match="already exists"):
        create_job(
            tmp_path,
            "CREATE",
            "safe-agent",
            NOW,
            job_id="job-safe",
        )

    assert sentinel.read_text(encoding="utf-8") == "do not replace"
    assert (job_dir / "status.json").read_bytes() == original_status


@pytest.mark.parametrize(
    ("mode", "now"),
    [
        ("DEPLOY", NOW),
        ("CREATE", datetime(2026, 7, 11, 9, 0)),
    ],
)
def test_create_job_validates_mode_and_timezone_before_mutation(
    tmp_path: Path,
    mode: str,
    now: datetime,
) -> None:
    with pytest.raises(FactoryError):
        create_job(tmp_path, mode, "safe-agent", now, job_id="job-safe")

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (None, "missing status"),
        ("{not-json", "malformed status"),
        ("[]", "must be a mapping"),
        ("{}", "invalid factory-job contract"),
    ],
)
def test_load_job_wraps_missing_malformed_and_invalid_status_errors(
    tmp_path: Path,
    contents: str | None,
    message: str,
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    if contents is not None:
        (job_dir / "status.json").write_text(contents, encoding="utf-8")

    with pytest.raises(ContractValidationError, match=message):
        load_job(job_dir)


def test_load_job_returns_independent_data(tmp_path: Path) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "safe-agent",
        NOW,
        job_id="job-safe",
    )

    loaded = load_job(job_dir)
    loaded["status_layers"]["published"] = True

    assert load_job(job_dir)["status_layers"]["published"] is False


def test_job_checkpoint_is_atomic_and_resumable(tmp_path: Path) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-001",
    )
    job = load_job(job_dir)
    job["checkpoint"] = {"sequence": 1, "next_action": "ask_user"}

    save_checkpoint(job_dir, job, {"kind": "answer", "ref": "input:1"})
    resumed = resume_job(job_dir, external_probe=lambda _: {"checked": True})

    assert resumed["checkpoint"]["sequence"] == 1
    assert resumed["checkpoint"]["state"] == "NEW"
    assert resumed["checkpoint"]["evidence_ref"] == "input:1"
    assert resumed["external_state"] == {"checked": True}
    assert not list(job_dir.glob("*.tmp"))


def test_save_checkpoint_normalizes_evidence_without_mutating_callers(
    tmp_path: Path,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-001",
    )
    job = load_job(job_dir)
    job_before = copy.deepcopy(job)
    evidence = {"kind": "answer", "ref": "intake/answer-1.md"}
    evidence_before = copy.deepcopy(evidence)

    save_checkpoint(job_dir, job, evidence)

    assert job == job_before
    assert evidence == evidence_before
    persisted = load_job(job_dir)
    assert persisted["evidence"][-1] == {
        "kind": "answer",
        "ref": "intake/answer-1.md",
        "status": "unverified",
        "at": NOW.isoformat(),
    }
    assert persisted["checkpoint"]["evidence_ref"] == "intake/answer-1.md"


def test_partial_checkpoint_hydrates_only_audit_fields_from_persisted_snapshot(
    tmp_path: Path,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-001",
    )
    job = load_job(job_dir)
    job["updated_at"] = "2026-07-11T09:30:00+00:00"
    job["checkpoint"] = {"sequence": 1, "next_action": "ask_user"}

    save_checkpoint(job_dir, job, {"kind": "answer", "ref": "input:1"})

    persisted = load_job(job_dir)
    assert persisted["checkpoint"] == {
        "sequence": 1,
        "state": "NEW",
        "next_action": "ask_user",
        "updated_at": NOW.isoformat(),
        "evidence_ref": "input:1",
    }
    assert persisted["evidence"][-1]["at"] == NOW.isoformat()


def test_save_checkpoint_preserves_explicit_valid_evidence_status_and_time(
    tmp_path: Path,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-001",
    )
    job = load_job(job_dir)
    evidence = {
        "kind": "schema_validation",
        "ref": "evidence/schema.txt",
        "status": "verified",
        "at": "2026-07-11T09:05:00+00:00",
    }

    save_checkpoint(job_dir, job, evidence)

    assert load_job(job_dir)["evidence"][-1] == evidence


@pytest.mark.parametrize(
    "evidence",
    [
        {"kind": "", "ref": "input:1"},
        {"kind": "answer", "ref": ""},
        {"kind": "answer", "ref": "input:1", "status": "trusted"},
        {
            "kind": "answer",
            "ref": "input:1",
            "at": "2026-07-11T09:00:00",
        },
        {"kind": "answer", "ref": "input:1", "unknown": True},
    ],
)
def test_save_checkpoint_rejects_invalid_evidence_without_changing_status(
    tmp_path: Path,
    evidence: dict,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-001",
    )
    before = (job_dir / "status.json").read_bytes()

    with pytest.raises(ContractValidationError, match="evidence"):
        save_checkpoint(job_dir, load_job(job_dir), evidence)

    assert (job_dir / "status.json").read_bytes() == before


def test_truth_layers_do_not_cascade(tmp_path: Path) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-002",
    )
    job = load_job(job_dir)
    job["status_layers"]["local_generated"] = True

    save_checkpoint(job_dir, job, {"kind": "generation", "ref": "output"})

    assert load_job(job_dir)["status_layers"] == {
        "local_generated": True,
        "local_validated": False,
        "installed": False,
        "published": False,
        "real_usage_verified": False,
    }


@pytest.mark.parametrize("mutation", ["remove", "rewrite"])
def test_save_checkpoint_rejects_persisted_evidence_prefix_tampering(
    tmp_path: Path,
    mutation: str,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-history",
    )
    save_checkpoint(
        job_dir,
        load_job(job_dir),
        {"kind": "answer", "ref": "input:1"},
    )
    before = (job_dir / "status.json").read_bytes()
    tampered = load_job(job_dir)
    if mutation == "remove":
        tampered["evidence"].clear()
    else:
        tampered["evidence"][0]["ref"] = "rewritten"

    with pytest.raises(ContractValidationError, match="persisted evidence prefix"):
        save_checkpoint(
            job_dir,
            tampered,
            {"kind": "answer", "ref": "input:2"},
        )

    assert (job_dir / "status.json").read_bytes() == before


@pytest.mark.parametrize("mutation", ["remove", "rewrite"])
def test_save_checkpoint_rejects_persisted_transition_prefix_tampering(
    tmp_path: Path,
    mutation: str,
) -> None:
    from factory.governance.state_machine import transition

    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-history",
    )
    discovery_time = datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc)
    transitioned = transition(
        load_job(job_dir),
        "DISCOVERY",
        "scope_received",
        ["evidence/scope.md"],
        discovery_time,
    )
    save_checkpoint(
        job_dir,
        transitioned,
        {"kind": "transition", "ref": "evidence/scope.md"},
    )
    before = (job_dir / "status.json").read_bytes()
    tampered = load_job(job_dir)
    if mutation == "remove":
        tampered["transitions"].clear()
    else:
        tampered["transitions"][0]["trigger"] = "rewritten"

    with pytest.raises(ContractValidationError, match="persisted transition prefix"):
        save_checkpoint(
            job_dir,
            tampered,
            {"kind": "answer", "ref": "input:2"},
        )

    assert (job_dir / "status.json").read_bytes() == before


def test_atomic_save_flushes_fsyncs_replaces_and_leaves_no_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-atomic",
    )
    real_fsync = os.fsync
    real_replace = os.replace
    events: list[str] = []

    def recording_fsync(fd: int) -> None:
        descriptor_kind = "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        events.append(f"fsync:{descriptor_kind}")
        real_fsync(fd)

    def recording_replace(source: Path | str, target: Path | str) -> None:
        events.append("replace")
        real_replace(source, target)

    monkeypatch.setattr(jobs_module.os, "fsync", recording_fsync)
    monkeypatch.setattr(jobs_module.os, "replace", recording_replace)

    save_checkpoint(
        job_dir,
        load_job(job_dir),
        {"kind": "answer", "ref": "input:1"},
    )

    assert events == ["fsync:file", "replace", "fsync:directory"]
    assert not list(job_dir.glob("*.tmp"))
    assert (job_dir / "status.json").read_text(encoding="utf-8").endswith("\n")


def test_atomic_replace_failure_preserves_old_status_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-atomic",
    )
    before = (job_dir / "status.json").read_bytes()

    def fail_replace(_source: Path | str, _target: Path | str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(jobs_module.os, "replace", fail_replace)

    with pytest.raises(FactoryError, match="atomic status write failed"):
        save_checkpoint(
            job_dir,
            load_job(job_dir),
            {"kind": "answer", "ref": "input:1"},
        )

    assert (job_dir / "status.json").read_bytes() == before
    assert not list(job_dir.glob("*.tmp"))


def test_resume_replace_failure_preserves_previous_external_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-resume-atomic",
    )
    resume_job(job_dir, lambda _: {"previous": True})
    before = (job_dir / "status.json").read_bytes()

    def fail_replace(_source: Path | str, _target: Path | str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(jobs_module.os, "replace", fail_replace)

    with pytest.raises(FactoryError, match="atomic status write failed"):
        resume_job(job_dir, lambda _: {"new": True})

    assert (job_dir / "status.json").read_bytes() == before
    assert load_job(job_dir)["external_state"] == {"previous": True}
    assert not list(job_dir.glob("*.tmp"))


def test_template_loader_supports_installed_resources_outside_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_templates = tmp_path / "installed-share" / "templates" / "job"
    installed_templates.mkdir(parents=True)
    source_templates = Path(__file__).parents[2] / "templates" / "job"
    for filename in ("JOB.md.tmpl", "COMMANDER_INTENT.md.tmpl"):
        (installed_templates / filename).write_bytes(
            (source_templates / filename).read_bytes()
        )
    monkeypatch.setattr(jobs_module, "_TEMPLATE_ROOT", tmp_path / "missing-checkout")
    monkeypatch.setattr(
        jobs_module,
        "_INSTALLED_TEMPLATE_ROOT",
        installed_templates,
    )
    outside_cwd = tmp_path / "outside-cwd"
    outside_cwd.mkdir()
    monkeypatch.chdir(outside_cwd)

    job_dir = create_job(
        tmp_path / "workshop",
        "CREATE",
        "portable-agent",
        NOW,
        job_id="job-portable",
    )

    assert (job_dir / "JOB.md").is_file()
    assert load_job(job_dir)["name"] == "portable-agent"


def test_resume_reprobes_and_replaces_stale_external_state(tmp_path: Path) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-resume",
    )
    calls: list[dict] = []

    def probe(job_view: dict) -> dict:
        calls.append(job_view)
        job_view["name"] = "mutated-probe-copy"
        return {"probe_sequence": len(calls)}

    first = resume_job(job_dir, probe)
    second = resume_job(job_dir, probe)

    assert first["external_state"] == {"probe_sequence": 1}
    assert second["external_state"] == {"probe_sequence": 2}
    assert len(calls) == 2
    assert calls[0] is not calls[1]
    assert load_job(job_dir)["name"] == "sales-agent"


def test_resumed_job_remains_valid_for_transition_and_checkpoint_save(
    tmp_path: Path,
) -> None:
    from factory.governance.state_machine import transition

    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-resume-transition",
    )
    resumed = resume_job(job_dir, lambda _: {"repository_head": "abc123"})
    transitioned = transition(
        resumed,
        "DISCOVERY",
        "scope_received",
        ["evidence/scope.md"],
        datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
    )

    save_checkpoint(
        job_dir,
        transitioned,
        {"kind": "transition", "ref": "evidence/scope.md"},
    )

    persisted = load_job(job_dir)
    assert validate_document("factory-job", persisted) == ()
    assert persisted["status"] == "DISCOVERY"
    assert persisted["external_state"] == {"repository_head": "abc123"}


@pytest.mark.parametrize(
    "probe_result",
    [
        ["not", "a", "mapping"],
        {"not_json": {1, 2, 3}},
        {"not_finite": float("nan")},
    ],
)
def test_invalid_probe_result_leaves_prior_status_intact(
    tmp_path: Path,
    probe_result: object,
) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-resume",
    )
    resume_job(job_dir, lambda _: {"previous": True})
    before = (job_dir / "status.json").read_bytes()

    with pytest.raises(FactoryError, match="external probe result"):
        resume_job(job_dir, lambda _: probe_result)  # type: ignore[arg-type]

    assert (job_dir / "status.json").read_bytes() == before
    assert load_job(job_dir)["external_state"] == {"previous": True}


def test_probe_failure_leaves_prior_status_intact(tmp_path: Path) -> None:
    job_dir = create_job(
        tmp_path,
        "CREATE",
        "sales-agent",
        NOW,
        job_id="job-resume",
    )
    before = (job_dir / "status.json").read_bytes()

    def failed_probe(_job: dict) -> dict:
        raise RuntimeError("probe unavailable")

    with pytest.raises(FactoryError, match="external probe failed"):
        resume_job(job_dir, failed_probe)

    assert (job_dir / "status.json").read_bytes() == before
