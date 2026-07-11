"""Evidence-backed lifecycle transitions for factory jobs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime

from factory.contracts import validate_document
from factory.errors import TransitionError
from factory.governance.policy import load_policy


def _mode_policy(mode: str) -> Mapping:
    policy = load_policy("state-machine")
    modes = policy["modes"]
    if not isinstance(mode, str) or mode not in modes:
        raise TransitionError(f"unknown factory mode: {mode}")
    return modes[mode]


def _mode_states(mode_policy: Mapping) -> frozenset[str]:
    transitions = mode_policy["transitions"]
    states = set(transitions)
    states.update(mode_policy["terminal_states"])
    states.update({"BLOCKED", "CANCELLED"})
    for targets in transitions.values():
        states.update(targets)
    return frozenset(states)


def allowed_next(mode: str, state: str) -> tuple[str, ...]:
    """Return policy-ordered targets allowed after ``state`` for ``mode``."""
    mode_policy = _mode_policy(mode)
    if not isinstance(state, str) or state not in _mode_states(mode_policy):
        raise TransitionError(f"unknown factory state for {mode}: {state}")

    if state in mode_policy["terminal_states"]:
        return ()
    if state == "BLOCKED":
        return ("CANCELLED",)

    return tuple(mode_policy["transitions"][state]) + ("BLOCKED", "CANCELLED")


def _validate_factory_job(job: object, stage: str) -> None:
    if not isinstance(job, Mapping):
        raise TransitionError(
            f"invalid {stage} factory-job contract: document must be a mapping"
        )
    issues = validate_document("factory-job", job)
    if issues:
        details = ", ".join(
            f"{issue.path}:{issue.code}" for issue in issues
        )
        raise TransitionError(f"invalid {stage} factory-job contract: {details}")


def _validated_evidence(evidence: object) -> list[str]:
    if (
        not isinstance(evidence, Sequence)
        or isinstance(evidence, (str, bytes, bytearray))
        or not evidence
        or any(
            not isinstance(reference, str) or not reference.strip()
            for reference in evidence
        )
    ):
        raise TransitionError(
            "transition evidence must be a non-empty ordered list of non-empty refs"
        )
    return list(evidence)


def _audit_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_now(job: Mapping, now: datetime) -> None:
    audit_times = [
        ("created_at", job["created_at"]),
        ("updated_at", job["updated_at"]),
        ("checkpoint.updated_at", job["checkpoint"]["updated_at"]),
    ]
    if job["transitions"]:
        audit_times.append(
            ("latest transition.at", job["transitions"][-1]["at"])
        )

    for label, value in audit_times:
        if now < _audit_datetime(value):
            raise TransitionError(f"transition now precedes {label}")


def _checkpoint_next_action(mode: str, current: str, target: str) -> str:
    if target == "BLOCKED":
        return f"resume:{current}"
    if target == "CANCELLED":
        return "cancelled"
    if not allowed_next(mode, target):
        return f"completed:{target}"
    return f"continue:{target}"


def _validate_transition_history(
    job: Mapping,
    mode: str,
    current: str,
    checkpoint_state: str,
) -> None:
    history = job["transitions"]
    if not history:
        if current != "NEW":
            raise TransitionError(
                f"{current} job requires non-empty transition history"
            )
        if checkpoint_state != "NEW":
            raise TransitionError(
                "factory job status is inconsistent with checkpoint state: "
                f"NEW != {checkpoint_state}"
            )
        return

    latest = history[-1]
    if latest["to"] != current:
        raise TransitionError(
            "factory job latest transition is inconsistent with status: "
            f"{latest['to']} != {current}"
        )
    if current == "BLOCKED" and latest["from"] != checkpoint_state:
        raise TransitionError(
            "factory job latest transition source is inconsistent with "
            "checkpoint state"
        )

    if history[0]["from"] == "BLOCKED":
        raise TransitionError("transition history cannot start from BLOCKED")

    resume_state: str | None = None
    previous_target: str | None = None
    previous_at: datetime | None = None
    for record in history:
        source = record["from"]
        target = record["to"]
        record_at = _audit_datetime(record["at"])
        if previous_at is not None and record_at < previous_at:
            raise TransitionError(
                "transition history timestamps must be nondecreasing"
            )
        if previous_target is not None and source != previous_target:
            raise TransitionError(
                "transition history must be continuous: "
                f"expected {previous_target}, found {source}"
            )

        if source == "BLOCKED":
            if resume_state is None or target not in (resume_state, "CANCELLED"):
                raise TransitionError(
                    f"{current} job transition history contains illegal edge: "
                    f"{source} -> {target}"
                )
            resume_state = None
        else:
            try:
                next_states = allowed_next(mode, source)
            except TransitionError as exc:
                raise TransitionError(
                    f"{current} job transition history contains illegal edge: "
                    f"{source} -> {target}"
                ) from exc
            if target not in next_states:
                raise TransitionError(
                    f"{current} job transition history contains illegal edge: "
                    f"{source} -> {target}"
                )
            if target == "BLOCKED":
                resume_state = source

        previous_target = target
        previous_at = record_at

    if current == "BLOCKED":
        if checkpoint_state != resume_state:
            raise TransitionError(
                "factory job latest transition source is inconsistent with "
                "checkpoint state"
            )
    elif checkpoint_state != current:
        raise TransitionError(
            "factory job status is inconsistent with checkpoint state: "
            f"{current} != {checkpoint_state}"
        )


def transition(
    job: Mapping,
    target: str,
    trigger: str,
    evidence: object,
    now: datetime,
) -> dict:
    """Return a copied factory job advanced to an allowed target state."""
    _validate_factory_job(job, "input")
    if not isinstance(trigger, str) or not trigger.strip():
        raise TransitionError("transition trigger must be a non-empty string")
    evidence_refs = _validated_evidence(evidence)
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise TransitionError("transition now must be a timezone-aware datetime")

    current = job["status"]
    checkpoint_state = job["checkpoint"]["state"]
    _validate_transition_history(
        job,
        job["mode"],
        current,
        checkpoint_state,
    )
    _validate_now(job, now)

    if current == "BLOCKED":
        try:
            resume_state_targets = allowed_next(job["mode"], checkpoint_state)
        except TransitionError as exc:
            raise TransitionError(
                f"blocked checkpoint has invalid resume state: {checkpoint_state}"
            ) from exc
        if "BLOCKED" not in resume_state_targets:
            raise TransitionError(
                f"blocked checkpoint has terminal resume state: {checkpoint_state}"
            )
        resume_targets = (checkpoint_state, "CANCELLED")
        if target not in resume_targets:
            raise TransitionError(f"illegal transition: {current} -> {target}")

    if current != "BLOCKED" and target not in allowed_next(job["mode"], current):
        raise TransitionError(f"illegal transition: {current} -> {target}")

    at = now.isoformat()
    next_action = _checkpoint_next_action(job["mode"], current, target)
    transitioned = deepcopy(job)
    transitioned["status"] = target
    transitioned["updated_at"] = at
    transitioned["checkpoint"].update(
        {
            "sequence": transitioned["checkpoint"]["sequence"] + 1,
            "state": current if target == "BLOCKED" else target,
            "next_action": next_action,
            "updated_at": at,
            "evidence_ref": evidence_refs[-1],
        }
    )
    transitioned["transitions"].append(
        {
            "from": current,
            "to": target,
            "trigger": trigger,
            "evidence": evidence_refs,
            "at": at,
        }
    )
    _validate_factory_job(transitioned, "output")
    return transitioned
