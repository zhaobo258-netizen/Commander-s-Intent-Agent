from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from factory.governance import evaluate_production_gate, load_policy


CONTRACT_FIXTURES = Path(__file__).parent / "fixtures" / "contracts"


def _load_fixture(filename: str) -> Any:
    path = CONTRACT_FIXTURES / filename
    with path.open(encoding="utf-8") as fixture_file:
        if path.suffix == ".json":
            return json.load(fixture_file)
        return yaml.safe_load(fixture_file)


@pytest.fixture
def valid_intent() -> dict:
    return copy.deepcopy(_load_fixture("valid-intent.yaml"))


@pytest.fixture
def production_ready_intent(valid_intent: dict) -> dict:
    intent = copy.deepcopy(valid_intent)
    policy = load_policy("production-gates")
    intent["provenance"] = [
        {
            "path": path,
            "source_type": "user_confirmed",
            "reference": f"fixture-confirmed:{path}",
        }
        for path in policy["critical_paths"]
    ]
    intent["confirmed"] = True
    assert evaluate_production_gate(intent, policy).ready is True
    return intent


@pytest.fixture
def ready_decision(production_ready_intent: dict):
    return evaluate_production_gate(
        production_ready_intent,
        load_policy("production-gates"),
    )


@pytest.fixture
def blocked_decision(valid_intent: dict):
    return evaluate_production_gate(valid_intent, load_policy("production-gates"))


@pytest.fixture
def incomplete_intent(valid_intent: dict) -> dict:
    intent = copy.deepcopy(valid_intent)
    intent["user"] = {}
    intent["authority"] = {}
    intent["provenance"] = [
        record
        for record in intent["provenance"]
        if record["path"] not in {"/user", "/authority"}
    ]
    intent["confirmed"] = False
    return intent


@pytest.fixture
def valid_blueprint() -> dict:
    return copy.deepcopy(_load_fixture("valid-blueprint.yaml"))


@pytest.fixture
def valid_design() -> dict:
    return copy.deepcopy(_load_fixture("valid-design.yaml"))


@pytest.fixture
def valid_job() -> dict:
    return copy.deepcopy(_load_fixture("valid-job.json"))


@pytest.fixture
def valid_review() -> dict:
    return copy.deepcopy(_load_fixture("valid-review.json"))


@pytest.fixture
def valid_optimization_plan() -> dict:
    return copy.deepcopy(_load_fixture("valid-optimization-plan.yaml"))
