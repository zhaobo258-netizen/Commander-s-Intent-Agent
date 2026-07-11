from __future__ import annotations

import copy
import importlib
from datetime import datetime, timezone

import pytest

import factory.governance.policy as policy_module
from factory.contracts import validate_document
from factory.governance.policy import load_policy
from factory.errors import TransitionError


def _state_machine_policy() -> dict:
    return load_policy("state-machine")


def _state_machine_module():
    return importlib.import_module("factory.governance.state_machine")


@pytest.fixture
def new_job(valid_job: dict) -> dict:
    job = copy.deepcopy(valid_job)
    job["mode"] = "CREATE"
    job["status"] = "NEW"
    job["checkpoint"]["sequence"] = 0
    job["checkpoint"]["state"] = "NEW"
    job["checkpoint"]["next_action"] = "begin_discovery"
    job["checkpoint"]["evidence_ref"] = None
    job["transitions"] = []
    return job


def _job_at(
    new_job: dict,
    state: str,
    *,
    mode: str = "CREATE",
    previous: str = "NEW",
) -> dict:
    job = copy.deepcopy(new_job)
    job["mode"] = mode
    job["status"] = state
    job["checkpoint"].update(
        {
            "sequence": 1,
            "state": state,
            "next_action": f"continue:{state}",
            "evidence_ref": "evidence/prior.txt",
        }
    )
    job["transitions"] = [
        {
            "from": previous,
            "to": state,
            "trigger": "prior_step",
            "evidence": ["evidence/prior.txt"],
            "at": "2026-07-11T09:00:00+00:00",
        }
    ]
    return job


def test_loads_state_machine_policy_for_all_factory_job_modes() -> None:
    state_machine_policy = _state_machine_policy()

    assert state_machine_policy["schema_version"] == "1.0"
    assert tuple(state_machine_policy["modes"]) == (
        "CREATE",
        "REVIEW",
        "OPTIMIZE",
    )
    assert state_machine_policy["modes"]["CREATE"]["transitions"]["NEW"] == [
        "DISCOVERY"
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda policy: policy.pop("modes"),
        lambda policy: policy["modes"].pop("REVIEW"),
        lambda policy: policy["modes"].__setitem__(
            "DEPLOY",
            copy.deepcopy(policy["modes"]["CREATE"]),
        ),
    ],
)
def test_state_machine_policy_requires_exact_schema_modes(
    mutation,
) -> None:
    malformed = copy.deepcopy(_state_machine_policy())
    mutation(malformed)

    with pytest.raises(ValueError, match="modes"):
        policy_module.validate_state_machine_policy(malformed)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda policy: policy["modes"]["CREATE"]["transitions"].__setitem__(
            "NOT_A_STATE",
            ["DISCOVERY"],
        ),
        lambda policy: policy["modes"]["CREATE"]["transitions"]["NEW"].append(
            "NOT_A_STATE"
        ),
    ],
)
def test_state_machine_policy_rejects_unknown_states_and_targets(
    mutation,
) -> None:
    malformed = copy.deepcopy(_state_machine_policy())
    mutation(malformed)

    with pytest.raises(ValueError, match="unknown state"):
        policy_module.validate_state_machine_policy(malformed)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda policy: policy["modes"]["CREATE"]["transitions"]["NEW"].append(
            "DISCOVERY"
        ),
        lambda policy: policy["modes"]["CREATE"]["terminal_states"].append(
            "DELIVERED"
        ),
    ],
)
def test_state_machine_policy_rejects_duplicates(
    mutation,
) -> None:
    malformed = copy.deepcopy(_state_machine_policy())
    mutation(malformed)

    with pytest.raises(ValueError, match="duplicates"):
        policy_module.validate_state_machine_policy(malformed)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda policy: policy["modes"]["CREATE"].pop("transitions"),
        lambda policy: policy["modes"]["CREATE"]["transitions"].pop("DISCOVERY"),
    ],
)
def test_state_machine_policy_rejects_missing_transition_tables(
    mutation,
) -> None:
    malformed = copy.deepcopy(_state_machine_policy())
    mutation(malformed)

    with pytest.raises(ValueError, match="transition"):
        policy_module.validate_state_machine_policy(malformed)


def test_state_machine_policy_derives_modes_and_states_from_factory_job_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = policy_module.load_schema("factory-job")
    schema["properties"]["mode"]["enum"].append("REPAIR")
    schema["$defs"]["factory_state"]["enum"].append("REPAIRING")
    extended = copy.deepcopy(_state_machine_policy())
    extended["modes"]["REPAIR"] = {
        "terminal_states": ["REPAIRING", "CANCELLED"],
        "transitions": {"NEW": ["REPAIRING"]},
    }
    monkeypatch.setattr(policy_module, "load_schema", lambda _kind: schema)

    policy_module.validate_state_machine_policy(extended)


def test_create_new_allows_discovery_then_emergency_targets() -> None:
    state_machine = _state_machine_module()

    assert state_machine.allowed_next("CREATE", "NEW") == (
        "DISCOVERY",
        "BLOCKED",
        "CANCELLED",
    )


def test_modes_expose_only_their_canonical_primary_flows() -> None:
    state_machine = _state_machine_module()

    create_flow = (
        "NEW",
        "DISCOVERY",
        "INTERVIEWING",
        "INTENT_CONFIRMATION",
        "READY",
        "BLUEPRINTING",
        "PRODUCING",
        "VALIDATING",
        "CANDIDATE_READY",
        "DELIVERED",
    )
    review_flow = ("NEW", "REVIEW_INTAKE", "REVIEWING", "REVIEW_READY")
    optimize_flow = (
        "NEW",
        "REVIEW_INTAKE",
        "REVIEWING",
        "REVIEW_READY",
        "OPTIMIZATION_PROPOSED",
        "OPTIMIZATION_APPROVED",
        "OPTIMIZING",
        "VALIDATING",
        "CANDIDATE_READY",
    )

    for mode, flow in (
        ("CREATE", create_flow),
        ("REVIEW", review_flow),
        ("OPTIMIZE", optimize_flow),
    ):
        for current, target in zip(flow, flow[1:]):
            assert state_machine.allowed_next(mode, current)[0] == target

    assert "REVIEWING" not in state_machine.allowed_next("CREATE", "NEW")
    assert "BLUEPRINTING" not in state_machine.allowed_next("REVIEW", "NEW")


def test_intent_confirmation_can_return_to_interviewing() -> None:
    state_machine = _state_machine_module()

    assert state_machine.allowed_next("CREATE", "INTENT_CONFIRMATION")[:2] == (
        "READY",
        "INTERVIEWING",
    )


def test_all_nonterminal_tables_include_blocked_and_cancelled() -> None:
    state_machine = _state_machine_module()

    for mode, mode_policy in _state_machine_policy()["modes"].items():
        for state in mode_policy["transitions"]:
            assert state_machine.allowed_next(mode, state)[-2:] == (
                "BLOCKED",
                "CANCELLED",
            )


def test_terminal_states_do_not_allow_further_transitions() -> None:
    state_machine = _state_machine_module()

    policy = _state_machine_policy()
    for mode, mode_policy in policy["modes"].items():
        for terminal_state in mode_policy["terminal_states"]:
            assert state_machine.allowed_next(mode, terminal_state) == ()


@pytest.mark.parametrize(
    ("mode", "state"),
    [
        ("DEPLOY", "NEW"),
        ("CREATE", "NOT_A_STATE"),
        ("CREATE", "REVIEWING"),
        ("REVIEW", "BLUEPRINTING"),
    ],
)
def test_allowed_next_rejects_unknown_mode_or_mode_specific_state(
    mode: str,
    state: str,
) -> None:
    state_machine = _state_machine_module()

    with pytest.raises(TransitionError):
        state_machine.allowed_next(mode, state)


def test_legal_transition_returns_updated_copy_with_checkpoint_and_evidence(
    new_job: dict,
) -> None:
    state_machine = _state_machine_module()
    original = copy.deepcopy(new_job)
    now = datetime(2026, 7, 11, 9, 30, tzinfo=timezone.utc)
    evidence = ("evidence/interview.md", "evidence/intent.yaml")

    transitioned = state_machine.transition(
        new_job,
        "DISCOVERY",
        "scope_received",
        evidence,
        now,
    )

    assert transitioned is not new_job
    assert new_job == original
    assert transitioned["status"] == "DISCOVERY"
    assert transitioned["updated_at"] == now.isoformat()
    assert transitioned["checkpoint"] == {
        "sequence": 1,
        "state": "DISCOVERY",
        "next_action": "continue:DISCOVERY",
        "updated_at": now.isoformat(),
        "evidence_ref": "evidence/intent.yaml",
    }
    assert transitioned["transitions"] == [
        {
            "from": "NEW",
            "to": "DISCOVERY",
            "trigger": "scope_received",
            "evidence": ["evidence/interview.md", "evidence/intent.yaml"],
            "at": now.isoformat(),
        }
    ]
    assert validate_document("factory-job", transitioned) == ()


def test_illegal_transition_names_source_and_target(new_job: dict) -> None:
    state_machine = _state_machine_module()

    with pytest.raises(TransitionError, match="NEW -> PRODUCING"):
        state_machine.transition(
            new_job,
            "PRODUCING",
            "skip_ahead",
            ["evidence/skip.txt"],
            datetime(2026, 7, 11, 9, 30, tzinfo=timezone.utc),
        )


def test_transition_to_blocked_preserves_resume_state_in_checkpoint(
    new_job: dict,
) -> None:
    state_machine = _state_machine_module()
    discovery_job = _job_at(new_job, "DISCOVERY")
    now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)

    blocked = state_machine.transition(
        discovery_job,
        "BLOCKED",
        "needs_owner_input",
        ["evidence/blocker.md"],
        now,
    )

    assert blocked["status"] == "BLOCKED"
    assert blocked["checkpoint"]["state"] == "DISCOVERY"
    assert blocked["checkpoint"]["sequence"] == 2
    assert blocked["transitions"][-1] == {
        "from": "DISCOVERY",
        "to": "BLOCKED",
        "trigger": "needs_owner_input",
        "evidence": ["evidence/blocker.md"],
        "at": now.isoformat(),
    }


def test_blocked_job_can_resume_only_to_checkpoint_state(new_job: dict) -> None:
    state_machine = _state_machine_module()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)
    blocked = state_machine.transition(
        _job_at(new_job, "DISCOVERY"),
        "BLOCKED",
        "needs_owner_input",
        ["evidence/blocker.md"],
        now,
    )

    resumed = state_machine.transition(
        blocked,
        "DISCOVERY",
        "owner_answered",
        ["evidence/owner-answer.md"],
        now,
    )

    assert resumed["status"] == "DISCOVERY"
    assert resumed["checkpoint"]["state"] == "DISCOVERY"
    assert resumed["transitions"][-1]["from"] == "BLOCKED"

    with pytest.raises(TransitionError, match="BLOCKED -> INTERVIEWING"):
        state_machine.transition(
            blocked,
            "INTERVIEWING",
            "skip_resume_state",
            ["evidence/invalid-resume.md"],
            now,
        )


def test_blocked_job_can_be_cancelled(new_job: dict) -> None:
    state_machine = _state_machine_module()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)
    blocked = state_machine.transition(
        _job_at(new_job, "DISCOVERY"),
        "BLOCKED",
        "needs_owner_input",
        ["evidence/blocker.md"],
        now,
    )

    cancelled = state_machine.transition(
        blocked,
        "CANCELLED",
        "owner_cancelled",
        ["evidence/cancellation.md"],
        now,
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["checkpoint"]["state"] == "CANCELLED"


def test_nonblocked_job_rejects_checkpoint_state_inconsistent_with_status(
    new_job: dict,
) -> None:
    state_machine = _state_machine_module()
    inconsistent = _job_at(new_job, "DISCOVERY")
    inconsistent["checkpoint"]["state"] = "NEW"

    with pytest.raises(TransitionError, match="checkpoint"):
        state_machine.transition(
            inconsistent,
            "INTERVIEWING",
            "continue",
            ["evidence/continue.md"],
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


def test_nonblocked_job_rejects_latest_transition_inconsistent_with_status(
    new_job: dict,
) -> None:
    state_machine = _state_machine_module()
    inconsistent = _job_at(new_job, "DISCOVERY")
    inconsistent["transitions"][-1]["to"] = "INTERVIEWING"

    with pytest.raises(TransitionError, match="latest transition"):
        state_machine.transition(
            inconsistent,
            "INTERVIEWING",
            "continue",
            ["evidence/continue.md"],
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


def test_nonnew_nonblocked_job_requires_transition_history(new_job: dict) -> None:
    state_machine = _state_machine_module()
    inconsistent = _job_at(new_job, "DISCOVERY")
    inconsistent["transitions"] = []

    with pytest.raises(TransitionError, match="transition history"):
        state_machine.transition(
            inconsistent,
            "INTERVIEWING",
            "continue",
            ["evidence/continue.md"],
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


def test_new_job_rejects_nonempty_transition_history(new_job: dict) -> None:
    state_machine = _state_machine_module()
    new_job["transitions"] = [
        {
            "from": "DISCOVERY",
            "to": "NEW",
            "trigger": "invalid_rewind",
            "evidence": ["evidence/rewind.md"],
            "at": "2026-07-11T09:00:00+00:00",
        }
    ]

    with pytest.raises(TransitionError, match="NEW.*transition history"):
        state_machine.transition(
            new_job,
            "DISCOVERY",
            "scope_received",
            ["evidence/scope.md"],
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


def test_blocked_job_requires_transition_history(new_job: dict) -> None:
    state_machine = _state_machine_module()
    blocked = _job_at(new_job, "DISCOVERY")
    blocked["status"] = "BLOCKED"
    blocked["transitions"] = []

    with pytest.raises(TransitionError, match="BLOCKED.*transition history"):
        state_machine.transition(
            blocked,
            "DISCOVERY",
            "owner_answered",
            ["evidence/owner-answer.md"],
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


def test_blocked_job_requires_latest_transition_to_blocked(new_job: dict) -> None:
    state_machine = _state_machine_module()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)
    blocked = state_machine.transition(
        _job_at(new_job, "DISCOVERY"),
        "BLOCKED",
        "needs_owner_input",
        ["evidence/blocker.md"],
        now,
    )
    blocked["transitions"][-1]["to"] = "DISCOVERY"

    with pytest.raises(TransitionError, match="latest transition.*BLOCKED"):
        state_machine.transition(
            blocked,
            "DISCOVERY",
            "owner_answered",
            ["evidence/owner-answer.md"],
            now,
        )


def test_blocked_job_requires_latest_source_to_match_checkpoint(
    new_job: dict,
) -> None:
    state_machine = _state_machine_module()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)
    blocked = state_machine.transition(
        _job_at(new_job, "DISCOVERY"),
        "BLOCKED",
        "needs_owner_input",
        ["evidence/blocker.md"],
        now,
    )
    blocked["transitions"][-1]["from"] = "INTERVIEWING"

    with pytest.raises(TransitionError, match="latest transition.*checkpoint"):
        state_machine.transition(
            blocked,
            "DISCOVERY",
            "owner_answered",
            ["evidence/owner-answer.md"],
            now,
        )


def test_valid_blocked_history_resumes_and_appends_resume_transition(
    new_job: dict,
) -> None:
    state_machine = _state_machine_module()
    now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)
    blocked = state_machine.transition(
        _job_at(new_job, "DISCOVERY"),
        "BLOCKED",
        "needs_owner_input",
        ["evidence/blocker.md"],
        now,
    )

    resumed = state_machine.transition(
        blocked,
        "DISCOVERY",
        "owner_answered",
        ["evidence/owner-answer.md"],
        now,
    )

    assert resumed["checkpoint"]["state"] == "DISCOVERY"
    assert resumed["transitions"][-1] == {
        "from": "BLOCKED",
        "to": "DISCOVERY",
        "trigger": "owner_answered",
        "evidence": ["evidence/owner-answer.md"],
        "at": now.isoformat(),
    }


def test_transition_rejects_invalid_factory_job_contract(new_job: dict) -> None:
    state_machine = _state_machine_module()
    del new_job["job_id"]

    with pytest.raises(TransitionError, match="factory-job contract"):
        state_machine.transition(
            new_job,
            "DISCOVERY",
            "scope_received",
            ["evidence/scope.md"],
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("trigger", ["", "   ", None])
def test_transition_requires_nonempty_trigger(new_job: dict, trigger: object) -> None:
    state_machine = _state_machine_module()

    with pytest.raises(TransitionError, match="trigger"):
        state_machine.transition(
            new_job,
            "DISCOVERY",
            trigger,
            ["evidence/scope.md"],
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    "evidence",
    [
        [],
        [""],
        ["   "],
        "evidence/scope.md",
    ],
)
def test_transition_requires_nonempty_evidence_refs(
    new_job: dict,
    evidence: object,
) -> None:
    state_machine = _state_machine_module()

    with pytest.raises(TransitionError, match="evidence"):
        state_machine.transition(
            new_job,
            "DISCOVERY",
            "scope_received",
            evidence,
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


def test_transition_requires_timezone_aware_now(new_job: dict) -> None:
    state_machine = _state_machine_module()

    with pytest.raises(TransitionError, match="timezone-aware"):
        state_machine.transition(
            new_job,
            "DISCOVERY",
            "scope_received",
            ["evidence/scope.md"],
            datetime(2026, 7, 11, 10, 0),
        )


def test_transition_validates_input_and_output_factory_job_contracts(
    new_job: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_machine = _state_machine_module()
    actual_validate_document = validate_document
    validated: list[tuple[str, object]] = []

    def recording_validator(kind: str, document: object):
        validated.append((kind, document))
        return actual_validate_document(kind, document)

    monkeypatch.setattr(state_machine, "validate_document", recording_validator)

    transitioned = state_machine.transition(
        new_job,
        "DISCOVERY",
        "scope_received",
        ["evidence/scope.md"],
        datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
    )

    assert [kind for kind, _document in validated] == [
        "factory-job",
        "factory-job",
    ]
    assert validated[0][1] is new_job
    assert validated[1][1] is transitioned


@pytest.mark.parametrize(
    ("mode", "target"),
    [("CREATE", "REVIEWING"), ("REVIEW", "BLUEPRINTING")],
)
def test_transition_rejects_cross_mode_target(
    new_job: dict,
    mode: str,
    target: str,
) -> None:
    state_machine = _state_machine_module()
    new_job["mode"] = mode

    with pytest.raises(TransitionError, match=f"NEW -> {target}"):
        state_machine.transition(
            new_job,
            target,
            "wrong_mode",
            ["evidence/wrong-mode.md"],
            datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        )


def test_governance_package_exports_state_machine_api() -> None:
    governance = importlib.import_module("factory.governance")
    state_machine = _state_machine_module()

    assert governance.allowed_next is state_machine.allowed_next
    assert governance.transition is state_machine.transition
    assert (
        governance.validate_state_machine_policy
        is policy_module.validate_state_machine_policy
    )
