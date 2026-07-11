"""Select and record one highest-risk commander-intent question at a time."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml

from factory.errors import ContractValidationError
from factory.governance.gates import GateDecision
from factory.governance.policy import load_policy
from factory.serialization import strict_json_loads, strict_yaml_load


UNKNOWN_ANSWER = "暂时不知道"
_RISK_PATHS = (
    "/user",
    "/mission",
    "/desired_end_state",
    "/key_tasks",
    "/resources",
    "/authority",
    "/acceptance",
)
_CATALOG_KEYS = {"schema_version", "questions"}
_QUESTION_KEYS = {
    "id",
    "priority",
    "path",
    "prompt",
    "reason",
    "recommended_answer",
    "options",
}
_MISSING = object()


@dataclass(frozen=True, slots=True)
class InterviewQuestion:
    id: str
    path: str
    prompt: str
    reason: str
    recommended_answer: str
    options: tuple[str, ...]


def _catalog_error(message: str) -> ValueError:
    return ValueError(f"malformed interview question catalog: {message}")


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    location: str,
) -> None:
    missing = sorted(expected - set(value))
    if missing:
        raise _catalog_error(f"{location} missing keys: {', '.join(missing)}")
    unknown = sorted(set(value) - expected, key=str)
    if unknown:
        rendered = ", ".join(str(key) for key in unknown)
        raise _catalog_error(f"{location} has unknown keys: {rendered}")


def _require_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _catalog_error(f"{location} must be a non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _catalog_error(f"{location} must be valid UTF-8") from exc
    return value


def load_questions() -> tuple[InterviewQuestion, ...]:
    """Load a fresh, strictly validated copy of the canonical catalog."""
    try:
        resource = files("factory.interview").joinpath("questions.yaml")
        document = strict_yaml_load(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise _catalog_error(f"could not load questions.yaml: {exc}") from exc

    if not isinstance(document, Mapping):
        raise _catalog_error("document must be a mapping")
    _require_exact_keys(document, _CATALOG_KEYS, "document")
    if document["schema_version"] != "1.0":
        raise _catalog_error("schema_version must be '1.0'")

    raw_questions = document["questions"]
    if not isinstance(raw_questions, list) or len(raw_questions) != len(_RISK_PATHS):
        raise _catalog_error(
            f"questions must contain exactly {len(_RISK_PATHS)} entries"
        )

    questions: list[InterviewQuestion] = []
    seen_ids: set[str] = set()
    for index, (raw, expected_path) in enumerate(
        zip(raw_questions, _RISK_PATHS, strict=True),
        start=1,
    ):
        location = f"questions[{index - 1}]"
        if not isinstance(raw, Mapping):
            raise _catalog_error(f"{location} must be a mapping")
        _require_exact_keys(raw, _QUESTION_KEYS, location)

        question_id = _require_text(raw["id"], f"{location}.id")
        if question_id in seen_ids:
            raise _catalog_error(f"{location}.id must be unique")
        seen_ids.add(question_id)

        priority = raw["priority"]
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise _catalog_error(f"{location}.priority must be an integer")
        if priority != index:
            raise _catalog_error(
                f"{location}.priority must preserve exact risk order {index}"
            )

        path = _require_text(raw["path"], f"{location}.path")
        if path != expected_path:
            raise _catalog_error(
                f"questions must preserve exact risk order: expected {expected_path}"
            )
        prompt = _require_text(raw["prompt"], f"{location}.prompt")
        if not prompt.endswith("？") or prompt.count("？") != 1:
            raise _catalog_error(f"{location}.prompt must contain one plain question")
        reason = _require_text(raw["reason"], f"{location}.reason")
        recommended = _require_text(
            raw["recommended_answer"],
            f"{location}.recommended_answer",
        )

        raw_options = raw["options"]
        if not isinstance(raw_options, list) or len(raw_options) < 2:
            raise _catalog_error(f"{location}.options must contain at least two choices")
        options = tuple(
            _require_text(option, f"{location}.options[{option_index}]")
            for option_index, option in enumerate(raw_options)
        )
        if len(options) != len(set(options)):
            raise _catalog_error(f"{location}.options must not contain duplicates")
        if options[-1] != UNKNOWN_ANSWER:
            raise _catalog_error(
                f"{location}.options must end with {UNKNOWN_ANSWER}"
            )
        if recommended not in options[:-1]:
            raise _catalog_error(
                f"{location}.recommended_answer must be a known option"
            )

        questions.append(
            InterviewQuestion(
                id=question_id,
                path=path,
                prompt=prompt,
                reason=reason,
                recommended_answer=recommended,
                options=options,
            )
        )
    return tuple(questions)


def _pointer_tokens(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        raise ContractValidationError("invalid interview question path")
    try:
        path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError("invalid interview question path") from exc

    tokens: list[str] = []
    for raw_token in path[1:].split("/"):
        index = 0
        while index < len(raw_token):
            if raw_token[index] != "~":
                index += 1
                continue
            if index + 1 >= len(raw_token) or raw_token[index + 1] not in "01":
                raise ContractValidationError("invalid interview question path")
            index += 2
        tokens.append(raw_token.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _resolve_pointer(document: object, path: str) -> object:
    current = document
    for token in _pointer_tokens(path):
        if isinstance(current, Mapping):
            if token not in current:
                return _MISSING
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return _MISSING
            index = int(token)
            if index >= len(current):
                return _MISSING
            current = current[index]
            continue
        return _MISSING
    return current


def _is_material(value: object) -> bool:
    if value is _MISSING or value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value != UNKNOWN_ANSWER
    if isinstance(value, (Mapping, Sequence, bytes, bytearray)):
        return len(value) > 0
    return True


def _required_paths_by_section() -> dict[str, tuple[str, ...]]:
    policy = load_policy("production-gates")
    required: dict[str, tuple[str, ...]] = {}
    for section in policy["sections"]:
        section_path = f"/{section['id']}"
        required[section_path] = tuple(section["required_paths"])
    return required


def _contract_blocker_affects(path: str, blocker: str) -> bool:
    prefix = "contract_invalid:"
    if not blocker.startswith(prefix):
        return False
    issue_path = blocker[len(prefix) :].split(":", 1)[0]
    return issue_path == path or issue_path.startswith(f"{path}/")


def next_question(
    intent: Mapping,
    decision: GateDecision,
) -> InterviewQuestion | None:
    """Return only the highest-risk unanswered question, or ``None``."""
    if decision.ready:
        return None
    if not isinstance(intent, Mapping):
        raise ContractValidationError("commander intent must be a mapping")

    required_by_section = _required_paths_by_section()
    missing_sources = frozenset(
        path for path in decision.missing_sources if isinstance(path, str)
    )
    for question in load_questions():
        required_paths = required_by_section.get(question.path, (question.path,))
        section_incomplete = any(
            not _is_material(_resolve_pointer(intent, path))
            for path in required_paths
        )
        contract_invalid = any(
            _contract_blocker_affects(question.path, blocker)
            for blocker in decision.blockers
            if isinstance(blocker, str)
        )
        if question.path in missing_sources or section_incomplete or contract_invalid:
            return question
    return None


def _validate_question_path(question: object) -> str:
    if not isinstance(question, InterviewQuestion):
        raise ContractValidationError("invalid interview question path")
    path = question.path
    tokens = _pointer_tokens(path)
    if path not in _RISK_PATHS or tokens != (path[1:],):
        raise ContractValidationError("invalid interview question path")
    return path


def _normalize_structural_answer(path: str, answer: object) -> object:
    expected_list = path == "/key_tasks"
    if expected_list:
        if not isinstance(answer, list):
            raise ContractValidationError(
                "known interview answer for /key_tasks must be a list"
            )
    elif not isinstance(answer, Mapping):
        raise ContractValidationError(
            f"known interview answer for {path} must be a mapping"
        )

    try:
        serialized = json.dumps(answer, ensure_ascii=False, allow_nan=False)
        serialized.encode("utf-8")
        normalized = strict_json_loads(serialized)
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ContractValidationError(
            "known interview answer must be JSON-compatible UTF-8"
        ) from exc
    if expected_list and not isinstance(normalized, list):
        raise ContractValidationError(
            "known interview answer for /key_tasks must be a list"
        )
    if not expected_list and not isinstance(normalized, dict):
        raise ContractValidationError(
            f"known interview answer for {path} must be a mapping"
        )
    return normalized


def _validate_answer_ref(answer_ref: object) -> str:
    if not isinstance(answer_ref, str) or not answer_ref.strip():
        raise ContractValidationError(
            "known interview answer reference must be a non-empty UTF-8 string"
        )
    try:
        answer_ref.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(
            "known interview answer reference must be a non-empty UTF-8 string"
        ) from exc
    return answer_ref


def _replace_pointer(document: dict, path: str, value: object) -> None:
    tokens = _pointer_tokens(path)
    current: object = document
    for token in tokens[:-1]:
        if not isinstance(current, dict) or token not in current:
            raise ContractValidationError("interview question path cannot be resolved")
        current = current[token]
    if not isinstance(current, dict):
        raise ContractValidationError("interview question path cannot be resolved")
    current[tokens[-1]] = deepcopy(value)


def _paths_related(left: str, right: str) -> bool:
    try:
        left_tokens = _pointer_tokens(left)
        right_tokens = _pointer_tokens(right)
    except ContractValidationError:
        return False
    shared = min(len(left_tokens), len(right_tokens))
    return left_tokens[:shared] == right_tokens[:shared]


def record_answer(
    intent: Mapping,
    question: InterviewQuestion,
    answer: object,
    *,
    answer_ref: object,
) -> dict:
    """Return an immutable intent update for one selected interview path."""
    if not isinstance(intent, Mapping):
        raise ContractValidationError("commander intent must be a mapping")
    path = _validate_question_path(question)

    provenance = intent.get("provenance")
    if not isinstance(provenance, list) or any(
        not isinstance(record, Mapping) for record in provenance
    ):
        raise ContractValidationError("commander intent provenance must be a list")

    is_unknown = answer == UNKNOWN_ANSWER
    if is_unknown:
        normalized_answer: object = UNKNOWN_ANSWER
        normalized_ref: str | None = None
    else:
        normalized_answer = _normalize_structural_answer(path, answer)
        normalized_ref = _validate_answer_ref(answer_ref)

    updated = deepcopy(dict(intent))
    _replace_pointer(updated, path, normalized_answer)
    updated["provenance"] = [
        record
        for record in updated["provenance"]
        if not (
            isinstance(record.get("path"), str)
            and _paths_related(record["path"], path)
        )
    ]
    if not is_unknown:
        updated["provenance"].append(
            {
                "path": path,
                "source_type": "user_confirmed",
                "reference": normalized_ref,
            }
        )
    return updated


__all__ = [
    "UNKNOWN_ANSWER",
    "InterviewQuestion",
    "load_questions",
    "next_question",
    "record_answer",
]
