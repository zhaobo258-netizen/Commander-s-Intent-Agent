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


def _validate_transition_history(
    job: Mapping,
    current: str,
    checkpoint_state: str,
) -> None:
    history = job["transitions"]
    if current == "NEW":
        if not history:
            return
        latest = history[-1]
        if latest["from"] == "BLOCKED" and latest["to"] == "NEW":
            return
        raise TransitionError(
            "NEW job transition history must be empty or end BLOCKED -> NEW"
        )

    if not history:
        raise TransitionError(
            f"{current} job requires non-empty transition history"
        )

    latest = history[-1]
    if current == "BLOCKED":
        if latest["to"] != "BLOCKED":
            raise TransitionError(
                "factory job latest transition must end at BLOCKED"
            )
        if latest["from"] != checkpoint_state:
            raise TransitionError(
                "factory job latest transition source is inconsistent with "
                "checkpoint state"
            )
        return

    if latest["to"] != current:
        raise TransitionError(
            "factory job latest transition is inconsistent with status: "
            f"{latest['to']} != {current}"
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
    if current != "BLOCKED" and current != checkpoint_state:
        raise TransitionError(
            "factory job status is inconsistent with checkpoint state: "
            f"{current} != {checkpoint_state}"
        )
    _validate_transition_history(job, current, checkpoint_state)

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
    transitioned = deepcopy(job)
    transitioned["status"] = target
    transitioned["updated_at"] = at
    transitioned["checkpoint"].update(
        {
            "sequence": transitioned["checkpoint"]["sequence"] + 1,
            "state": current if target == "BLOCKED" else target,
            "next_action": f"continue:{target}",
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
