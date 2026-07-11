from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml


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
def valid_blueprint() -> dict:
    return copy.deepcopy(_load_fixture("valid-blueprint.yaml"))


@pytest.fixture
def valid_job() -> dict:
    return copy.deepcopy(_load_fixture("valid-job.json"))


@pytest.fixture
def valid_review() -> dict:
    return copy.deepcopy(_load_fixture("valid-review.json"))
