from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from factory.errors import ContractValidationError
from factory.governance.gates import GateDecision
from factory.interview import protocol as protocol_module
from factory.interview.protocol import (
    UNKNOWN_ANSWER,
    InterviewQuestion,
    load_questions,
    next_question,
    record_answer,
)


RISK_PATHS = (
    "/user",
    "/mission",
    "/desired_end_state",
    "/key_tasks",
    "/resources",
    "/authority",
    "/acceptance",
)


def _decision(*missing_sources: str, ready: bool = False) -> GateDecision:
    return GateDecision(
        score=100 if ready else 30,
        blockers=() if ready else ("interview_incomplete",),
        missing_sources=missing_sources,
        ready=ready,
    )


def _user_question(incomplete_intent: dict) -> InterviewQuestion:
    question = next_question(
        incomplete_intent,
        _decision("/user"),
    )
    assert question is not None
    return question


def test_catalog_has_exact_risk_order_and_plain_language_questions() -> None:
    questions = load_questions()

    assert tuple(question.path for question in questions) == RISK_PATHS
    assert len({question.id for question in questions}) == len(RISK_PATHS)
    for question in questions:
        assert question.prompt.endswith("？")
        assert question.prompt.count("？") == 1
        assert question.reason.strip()
        assert question.recommended_answer in question.options[:-1]
        assert question.options[-1] == UNKNOWN_ANSWER
        assert len(question.options) == len(set(question.options))
        assert not any(
            jargon in question.prompt.lower()
            for jargon in ("json", "yaml", "api", "schema", "pointer")
        )


def test_selects_exactly_one_highest_risk_question(
    incomplete_intent: dict,
) -> None:
    decision = GateDecision(
        30,
        ("missing_confirmed_source:/user",),
        ("/authority", "/user"),
        False,
    )

    question = next_question(incomplete_intent, decision)

    assert isinstance(question, InterviewQuestion)
    assert question.path == "/user"
    assert question.reason
    assert question.recommended_answer
    assert question.options[-1] == UNKNOWN_ANSWER


def test_catalog_order_wins_over_missing_source_order(valid_intent: dict) -> None:
    question = next_question(
        valid_intent,
        _decision("/acceptance", "/resources", "/mission"),
    )

    assert question is not None
    assert question.path == "/mission"


def test_empty_noncritical_key_tasks_are_selected(valid_intent: dict) -> None:
    valid_intent["key_tasks"] = []

    question = next_question(valid_intent, _decision())

    assert question is not None
    assert question.path == "/key_tasks"


def test_ready_decision_returns_none_without_loading_catalog(
    valid_intent: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_files(_package: str) -> object:
        raise AssertionError("ready decisions must not load interview resources")

    monkeypatch.setattr(protocol_module, "files", unexpected_files)

    assert next_question(valid_intent, _decision(ready=True)) is None


def test_unknown_answer_persists_without_confirmed_provenance(
    incomplete_intent: dict,
) -> None:
    question = _user_question(incomplete_intent)
    incomplete_intent["provenance"].extend(
        [
            {
                "path": "/user",
                "source_type": "user_confirmed",
                "reference": "stale-user-answer",
            },
            {
                "path": "/user",
                "source_type": "user_confirmed",
                "reference": "duplicate-stale-user-answer",
            },
        ]
    )
    before = copy.deepcopy(incomplete_intent)

    updated = record_answer(
        incomplete_intent,
        question,
        UNKNOWN_ANSWER,
        answer_ref="input:2",
    )

    assert updated["user"] == UNKNOWN_ANSWER
    assert not any(
        record["source_type"] == "user_confirmed"
        and record["path"] == "/user"
        for record in updated["provenance"]
    )
    assert incomplete_intent == before


def test_structural_answer_updates_only_selected_path_and_fresh_provenance(
    incomplete_intent: dict,
) -> None:
    question = _user_question(incomplete_intent)
    answer = {
        "role": "社区活动负责人",
        "scenario": "活动发布前检查筹备资料",
    }
    incomplete_intent["provenance"].extend(
        [
            {
                "path": "/user",
                "source_type": "inference",
                "reference": "stale-inference",
            },
            {
                "path": "/user",
                "source_type": "user_confirmed",
                "reference": "stale-confirmation",
            },
            {
                "path": "/mission",
                "source_type": "user_confirmed",
                "reference": "keep-mission",
            },
        ]
    )
    before = copy.deepcopy(incomplete_intent)
    answer_before = copy.deepcopy(answer)

    updated = record_answer(
        incomplete_intent,
        question,
        answer,
        answer_ref="input:3",
    )

    assert updated["user"] == answer
    assert updated["user"] is not answer
    assert incomplete_intent == before
    assert answer == answer_before
    assert {
        key: value
        for key, value in updated.items()
        if key not in {"user", "provenance"}
    } == {
        key: value
        for key, value in before.items()
        if key not in {"user", "provenance"}
    }
    user_records = [
        record for record in updated["provenance"] if record["path"] == "/user"
    ]
    assert user_records == [
        {
            "path": "/user",
            "source_type": "user_confirmed",
            "reference": "input:3",
        }
    ]
    assert {
        "path": "/mission",
        "source_type": "user_confirmed",
        "reference": "keep-mission",
    } in updated["provenance"]

    answer["role"] = "修改后的外部值"
    assert updated["user"]["role"] == "社区活动负责人"


@pytest.mark.parametrize("answer_ref", ["", "   ", None, 42, "\ud800"])
def test_known_answer_requires_nonempty_utf8_answer_reference(
    incomplete_intent: dict,
    answer_ref: object,
) -> None:
    question = _user_question(incomplete_intent)
    before = copy.deepcopy(incomplete_intent)

    with pytest.raises(ContractValidationError, match="answer reference"):
        record_answer(
            incomplete_intent,
            question,
            {"role": "负责人", "scenario": "检查资料"},
            answer_ref=answer_ref,
        )

    assert incomplete_intent == before


@pytest.mark.parametrize(
    "unsafe_path",
    ["", "user", "/user/role", "/user~2role", "/__class__", "/user/../authority"],
)
def test_record_answer_rejects_non_catalog_or_unsafe_pointer(
    incomplete_intent: dict,
    unsafe_path: str,
) -> None:
    question = replace(_user_question(incomplete_intent), path=unsafe_path)
    before = copy.deepcopy(incomplete_intent)

    with pytest.raises(ContractValidationError, match="question path"):
        record_answer(
            incomplete_intent,
            question,
            {"role": "负责人", "scenario": "检查资料"},
            answer_ref="input:safe",
        )

    assert incomplete_intent == before


def test_record_answer_rejects_non_list_provenance_without_mutation(
    incomplete_intent: dict,
) -> None:
    question = _user_question(incomplete_intent)
    incomplete_intent["provenance"] = "not-a-list"
    before = copy.deepcopy(incomplete_intent)

    with pytest.raises(ContractValidationError, match="provenance"):
        record_answer(
            incomplete_intent,
            question,
            {"role": "负责人", "scenario": "检查资料"},
            answer_ref="input:4",
        )

    assert incomplete_intent == before


class _CatalogResource:
    def __init__(self, text: str) -> None:
        self._text = text

    def joinpath(self, filename: str) -> "_CatalogResource":
        assert filename == "questions.yaml"
        return self

    def read_text(self, *, encoding: str) -> str:
        assert encoding == "utf-8"
        return self._text


def _inject_catalog(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(
        protocol_module,
        "files",
        lambda package: _CatalogResource(text)
        if package == "factory.interview"
        else pytest.fail(f"unexpected package: {package}"),
    )


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        (
            'schema_version: "1.0"\nschema_version: "1.0"\nquestions: []\n',
            "could not load",
        ),
        (
            'schema_version: "1.0"\nquestions: []\n',
            "exactly",
        ),
        (
            """schema_version: "1.0"
questions:
  - id: user
    priority: 1
    path: /mission
    prompt: 你想解决什么问题？
    reason: 需要明确目标。
    recommended_answer: 说明具体问题
    options: [说明具体问题, 暂时不知道]
""",
            "exactly",
        ),
    ],
)
def test_malformed_or_duplicate_key_catalog_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    catalog: str,
    message: str,
) -> None:
    _inject_catalog(monkeypatch, catalog)

    with pytest.raises(ValueError, match=message):
        load_questions()


def test_clean_wheel_install_can_load_question_catalog(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    checkout = tmp_path / "checkout"
    wheelhouse = tmp_path / "wheelhouse"
    target = tmp_path / "target"
    checkout.mkdir()
    wheelhouse.mkdir()
    shutil.copy2(root / "pyproject.toml", checkout / "pyproject.toml")
    shutil.copytree(root / "factory", checkout / "factory")
    shutil.copytree(root / "templates", checkout / "templates")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(checkout),
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheelhouse),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheelhouse.glob("*.whl"))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            str(wheel),
            "--no-deps",
            "--target",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(target)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from factory.interview.protocol import load_questions; "
                "questions = load_questions(); "
                "print(questions[0].path, questions[-1].options[-1])"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == f"/user {UNKNOWN_ANSWER}"
