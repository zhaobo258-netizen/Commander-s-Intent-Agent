# M1 Factory Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic package, data contracts, production gate, state machine, private job persistence, and repository verification shell.

**Architecture:** JSON Schema owns document shape, YAML owns human-readable policies, and small Python modules load and enforce both. Jobs persist immutable evidence and transition history atomically under an injected workshop root, so tests never touch the real user workspace.

**Tech Stack:** Python 3.11+, argparse, dataclasses, pathlib, PyYAML, jsonschema, pytest.

---

## File responsibility map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package, dependencies, CLI entrypoint, pytest settings |
| `factory/errors.py` | Public exception types |
| `factory/contracts/validation.py` | Schema loading and normalized issues |
| `factory/contracts/*.schema.json` | Four approved machine contracts |
| `factory/governance/policy.py` | YAML policy loading only |
| `factory/governance/gates.py` | Readiness scoring and critical blockers |
| `factory/governance/state_machine.py` | Legal transitions and history |
| `factory/production/jobs.py` | Atomic create/load/checkpoint/resume |
| `factory/cli/main.py` | Thin argparse routing |
| `factory/cli/verify.py` | Repository structure verification |

### Task 1: Package and CLI shell

**Files:**
- Create: `pyproject.toml`
- Create: `factory/__init__.py`
- Create: `factory/errors.py`
- Create: `factory/cli/__init__.py`
- Create: `factory/cli/__main__.py`
- Create: `factory/cli/main.py`
- Create: `tests/cli/test_main.py`

- [ ] **Step 1: Write the failing package and CLI test**

```python
from factory import __version__
from factory.cli.main import build_parser, main


def test_package_version_and_help(capsys):
    assert __version__ == "0.1.0"
    parser = build_parser()
    assert parser.prog == "commander-factory"
    assert main(["--version"]) == 0
    assert "0.1.0" in capsys.readouterr().out
```

- [ ] **Step 2: Run the test and observe RED**

Run: `python -m pytest tests/cli/test_main.py -q`
Expected: collection fails with `ModuleNotFoundError: No module named 'factory'`.

- [ ] **Step 3: Implement the package shell**

Use this package metadata:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "commander-intent-agent-factory"
version = "0.1.0"
description = "A commander's-intent-driven factory for creating, reviewing, and optimizing AI agents."
requires-python = ">=3.11"
dependencies = ["PyYAML>=6.0", "jsonschema>=4.21"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
commander-factory = "factory.cli.main:main"

[tool.setuptools.packages.find]
include = ["factory*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

Implement `factory/__init__.py` with `__version__ = "0.1.0"`. Define `FactoryError`, `ContractValidationError`, `GateBlockedError`, `TransitionError`, and `UnsafePathError` in `factory/errors.py`. Implement `build_parser()` with `--version` and `main(argv: list[str] | None = None) -> int`; `factory/cli/__main__.py` must exit with `main()`.

- [ ] **Step 4: Run the target test and CLI smoke**

Run: `python -m pytest tests/cli/test_main.py -q`
Expected: `1 passed`.

Run: `python -m factory.cli --version`
Expected: output contains `commander-factory 0.1.0` and exit code `0`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml factory tests/cli/test_main.py
git commit -m "feat: initialize factory package and CLI"
```

### Task 2: Contract schemas and normalized validation

**Files:**
- Create: `factory/contracts/__init__.py`
- Create: `factory/contracts/validation.py`
- Create: `factory/contracts/commander-intent.schema.json`
- Create: `factory/contracts/agent-blueprint.schema.json`
- Create: `factory/contracts/factory-job.schema.json`
- Create: `factory/contracts/review-report.schema.json`
- Create: `tests/contracts/test_schemas.py`
- Create: `tests/fixtures/contracts/valid-intent.yaml`
- Create: `tests/fixtures/contracts/valid-blueprint.yaml`
- Create: `tests/fixtures/contracts/valid-job.json`
- Create: `tests/fixtures/contracts/valid-review.json`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write failing validation tests**

```python
from pathlib import Path
import json
import yaml

from factory.contracts.validation import load_schema, validate_document

FIXTURES = Path("tests/fixtures/contracts")


def load_fixture(name: str):
    path = FIXTURES / name
    return json.loads(path.read_text()) if path.suffix == ".json" else yaml.safe_load(path.read_text())


def test_all_valid_contract_examples_pass():
    pairs = {
        "commander-intent": "valid-intent.yaml",
        "agent-blueprint": "valid-blueprint.yaml",
        "factory-job": "valid-job.json",
        "review-report": "valid-review.json",
    }
    for kind, fixture in pairs.items():
        assert validate_document(kind, load_fixture(fixture)) == ()


def test_intent_rejects_unknown_key_and_invalid_source():
    intent = load_fixture("valid-intent.yaml")
    intent["unknown"] = True
    intent["provenance"][0]["source_type"] = "ai_guess"
    issues = validate_document("commander-intent", intent)
    assert {issue.code for issue in issues} == {"additionalProperties", "enum"}
```

- [ ] **Step 2: Run the test and observe RED**

Run: `python -m pytest tests/contracts/test_schemas.py -q`
Expected: import fails because `factory.contracts.validation` does not exist.

- [ ] **Step 3: Implement schema loading and issue normalization**

```python
from dataclasses import dataclass
from importlib.resources import files
import json
from collections.abc import Mapping

from jsonschema import Draft202012Validator


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str
    code: str
    message: str


KINDS = {"commander-intent", "agent-blueprint", "factory-job", "review-report"}


def load_schema(kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown contract kind: {kind}")
    resource = files("factory.contracts").joinpath(f"{kind}.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_document(kind: str, data: Mapping) -> tuple[ValidationIssue, ...]:
    validator = Draft202012Validator(load_schema(kind))
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
    return tuple(
        ValidationIssue(
            path="/" + "/".join(map(str, error.absolute_path)),
            code=error.validator,
            message=error.message,
        )
        for error in errors
    )
```

Each schema must declare Draft 2020-12, set `additionalProperties: false` at document and governed object boundaries, and enforce these exact top-level requirements:

| Contract | Required top-level keys |
|---|---|
| commander-intent | `schema_version`, `metadata`, `mission`, `user`, `desired_end_state`, `key_tasks`, `resources`, `authority`, `acceptance`, `provenance`, `confirmed` |
| agent-blueprint | `schema_version`, `metadata`, `commander_intent_ref`, `capabilities`, `skills`, `workflow`, `resources`, `harness`, `evaluation`, `adapters` |
| factory-job | `schema_version`, `job_id`, `mode`, `name`, `status`, `scope`, `created_at`, `updated_at`, `checkpoint`, `missing_items`, `approvals`, `status_layers`, `evidence`, `transitions` |
| review-report | `schema_version`, `target`, `scope`, `evidence`, `findings`, `quality`, `verdict`, `status_layers`, `unverified` |

Enums must match the approved spec: modes `CREATE/REVIEW/OPTIMIZE`; provenance `user_confirmed/observed_file/tool_result/inference/assumption`; evidence states `verified/inferred/unverified`; findings `P0/P1/P2/P3`; truth layers are five independent booleans and never conditionally imply each other.

In `tests/conftest.py`, provide `valid_intent`, `valid_blueprint`, `valid_job`, and `valid_review` fixtures by loading the four files from `tests/fixtures/contracts`; return a fresh deep copy for every test.

- [ ] **Step 4: Run contract tests**

Run: `python -m pytest tests/contracts/test_schemas.py -q`
Expected: all contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/contracts tests/contracts tests/fixtures/contracts tests/conftest.py
git commit -m "feat: add factory data contracts"
```

### Task 3: Production policy and fail-closed readiness gate

**Files:**
- Create: `factory/governance/__init__.py`
- Create: `factory/governance/production-gates.yaml`
- Create: `factory/governance/policy.py`
- Create: `factory/governance/gates.py`
- Create: `tests/governance/test_gates.py`

- [ ] **Step 1: Write failing gate tests**

```python
import yaml
from pathlib import Path

from factory.governance.gates import evaluate_production_gate
from factory.governance.policy import load_policy


def valid_intent():
    return yaml.safe_load(Path("tests/fixtures/contracts/valid-intent.yaml").read_text())


def test_complete_confirmed_intent_is_ready():
    decision = evaluate_production_gate(valid_intent(), load_policy("production-gates"))
    assert decision.score == 100
    assert decision.blockers == ()
    assert decision.ready is True


def test_score_cannot_override_missing_authority_source():
    intent = valid_intent()
    intent["provenance"] = [p for p in intent["provenance"] if p["path"] != "/authority"]
    decision = evaluate_production_gate(intent, load_policy("production-gates"))
    assert decision.score >= 80
    assert "missing_confirmed_source:/authority" in decision.blockers
    assert decision.ready is False
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/governance/test_gates.py -q`
Expected: import fails because the gate modules do not exist.

- [ ] **Step 3: Implement policy and decision types**

Use the exact weights `15/15/20/10/15/15/10`, threshold `80`, critical paths `/mission`, `/user`, `/desired_end_state`, `/resources`, `/authority`, `/acceptance`, and confirmed source types `user_confirmed`, `observed_file`, `tool_result`.

```python
from dataclasses import dataclass
from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class GateDecision:
    score: int
    blockers: tuple[str, ...]
    missing_sources: tuple[str, ...]
    ready: bool


def evaluate_production_gate(intent: Mapping, policy: Mapping) -> GateDecision:
    score = sum(
        section["points"]
        for section in policy["sections"]
        if all(_present(intent, path) for path in section["required_paths"])
    )
    confirmed = {
        item["path"]
        for item in intent.get("provenance", [])
        if item.get("source_type") in policy["confirmed_source_types"]
    }
    missing = tuple(path for path in policy["critical_paths"] if not _covered(path, confirmed))
    blockers = tuple(f"missing_confirmed_source:{path}" for path in missing)
    if not intent.get("confirmed", False):
        blockers += ("intent_not_confirmed",)
    ready = score >= policy["threshold"] and not blockers
    return GateDecision(score, blockers, missing, ready)
```

Implement `_present` for JSON-pointer-like paths and `_covered` so provenance for `/authority/allowed_actions` covers itself but does not cover sibling `/authority/forbidden_actions`; provenance recorded exactly at `/authority` covers its descendants.

- [ ] **Step 4: Run target and contract regression**

Run: `python -m pytest tests/governance/test_gates.py tests/contracts/test_schemas.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/governance tests/governance/test_gates.py
git commit -m "feat: enforce production readiness gate"
```

### Task 4: State machine and transition evidence

**Files:**
- Create: `factory/governance/state-machine.yaml`
- Create: `factory/governance/state_machine.py`
- Create: `tests/governance/test_state_machine.py`

- [ ] **Step 1: Write failing transition tests**

```python
from datetime import datetime, timezone
import pytest

from factory.errors import TransitionError
from factory.governance.state_machine import allowed_next, transition


NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


def test_create_flow_records_transition_evidence(valid_job):
    assert allowed_next("CREATE", "NEW") == ("DISCOVERY", "BLOCKED", "CANCELLED")
    updated = transition(valid_job, "DISCOVERY", "user_requested_create", ["input:1"], NOW)
    assert updated["status"] == "DISCOVERY"
    assert updated["transitions"][-1]["evidence"] == ["input:1"]


def test_illegal_jump_is_rejected(valid_job):
    with pytest.raises(TransitionError, match="NEW -> PRODUCING"):
        transition(valid_job, "PRODUCING", "skip", [], NOW)
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/governance/test_state_machine.py -q`
Expected: import fails because `state_machine.py` does not exist.

- [ ] **Step 3: Implement exact mode flows**

Encode the approved CREATE and REVIEW/OPTIMIZE flows in YAML. Add `BLOCKED` and `CANCELLED` as legal targets from every nonterminal state; a blocked job can return only to its recorded `resume_state` or become cancelled.

```python
def allowed_next(mode: str, state: str) -> tuple[str, ...]:
    transitions = load_policy("state-machine")["modes"][mode]["transitions"]
    return tuple(transitions.get(state, ()))


def transition(job, target, trigger, evidence, now):
    current = job["status"]
    if target not in allowed_next(job["mode"], current):
        raise TransitionError(f"illegal transition {current} -> {target}")
    updated = deepcopy(job)
    updated["status"] = target
    updated["updated_at"] = now.isoformat()
    updated["transitions"].append({
        "from": current,
        "to": target,
        "trigger": trigger,
        "evidence": list(evidence),
        "at": now.isoformat(),
    })
    return updated
```

- [ ] **Step 4: Run state tests**

Run: `python -m pytest tests/governance/test_state_machine.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/governance/state-machine.yaml factory/governance/state_machine.py tests/governance/test_state_machine.py
git commit -m "feat: add evidence-backed factory state machine"
```

### Task 5: Atomic private job persistence and resume

**Files:**
- Create: `factory/production/__init__.py`
- Create: `factory/production/jobs.py`
- Create: `templates/job/JOB.md.tmpl`
- Create: `templates/job/COMMANDER_INTENT.md.tmpl`
- Create: `tests/production/test_jobs.py`

- [ ] **Step 1: Write failing persistence tests**

```python
from datetime import datetime, timezone
import json

from factory.production.jobs import create_job, load_job, resume_job, save_checkpoint


NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


def test_job_checkpoint_is_atomic_and_resumable(tmp_path):
    job_dir = create_job(tmp_path, "CREATE", "sales-agent", NOW, job_id="job-001")
    job = load_job(job_dir)
    job["checkpoint"] = {"sequence": 1, "next_action": "ask_user"}
    save_checkpoint(job_dir, job, {"kind": "answer", "ref": "input:1"})
    resumed = resume_job(job_dir, external_probe=lambda _: {"checked": True})
    assert resumed["checkpoint"]["sequence"] == 1
    assert resumed["external_state"] == {"checked": True}
    assert not list(job_dir.glob("*.tmp"))


def test_truth_layers_do_not_cascade(tmp_path):
    job_dir = create_job(tmp_path, "CREATE", "sales-agent", NOW, job_id="job-002")
    job = load_job(job_dir)
    job["status_layers"]["local_generated"] = True
    save_checkpoint(job_dir, job, {"kind": "generation", "ref": "output"})
    assert load_job(job_dir)["status_layers"]["published"] is False
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/production/test_jobs.py -q`
Expected: import fails because `factory.production.jobs` does not exist.

- [ ] **Step 3: Implement safe paths and atomic writes**

`create_job` must reject names containing `/`, `\\`, `..`, or a resolved path outside the injected workshop root. Render `JOB.md` and the initial `COMMANDER_INTENT.md` from `templates/job`, create `intake/`, `evidence/`, `reports/`, `output/`, and a schema-valid `status.json`. Write JSON to a sibling temporary file, flush and `os.fsync`, then `os.replace`.

Expose exactly these signatures: `create_job(workshop_root: Path, mode: str, name: str, now: datetime, *, job_id: str) -> Path`; `load_job(job_dir: Path) -> dict`; `save_checkpoint(job_dir: Path, job: Mapping, evidence: Mapping) -> None`; and `resume_job(job_dir: Path, external_probe: Callable[[Mapping], Mapping]) -> dict`.

`resume_job` must call the injected probe and store its result as current external state; it must not reuse stale external state from a previous session.

- [ ] **Step 4: Run persistence and state regressions**

Run: `python -m pytest tests/production/test_jobs.py tests/governance/test_state_machine.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/production templates/job tests/production/test_jobs.py
git commit -m "feat: persist resumable private factory jobs"
```

### Task 6: Repository verification and M1 CLI commands

**Files:**
- Create: `factory/cli/verify.py`
- Modify: `factory/cli/main.py`
- Create: `tests/cli/test_verify.py`
- Create: `workshop/README.md`
- Create: `workshop/.gitignore`
- Create: `workshop/jobs/.gitkeep`
- Create: `workshop/reviews/.gitkeep`

- [ ] **Step 1: Write failing CLI tests**

```python
from factory.cli.main import main


def test_verify_repo_reports_missing_contracts(tmp_path, capsys):
    assert main(["verify-repo", str(tmp_path)]) == 1
    assert "missing:factory/contracts/commander-intent.schema.json" in capsys.readouterr().out


def test_job_init_and_status_use_injected_workshop(tmp_path, capsys):
    assert main(["job-init", "--workshop", str(tmp_path), "--mode", "CREATE", "--name", "demo", "--job-id", "job-demo"]) == 0
    assert main(["job-status", str(tmp_path / "jobs" / "job-demo-demo")]) == 0
    assert '"mode": "CREATE"' in capsys.readouterr().out
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/cli/test_verify.py -q`
Expected: argparse rejects the unknown commands.

- [ ] **Step 3: Implement thin CLI routing**

Create `VerificationReport(ok: bool, checks: tuple[str, ...], failures: tuple[str, ...])` and `verify_repository(root: Path)`. M1 verification checks the four schemas, both governance policies, package metadata, and private workshop ignore rules. Add `verify-repo`, `job-init`, and `job-status` subcommands; command functions return `0` for verified/success and `1` for verification failure.

`workshop/.gitignore` must contain:

```gitignore
jobs/*
reviews/*
!jobs/.gitkeep
!reviews/.gitkeep
```

- [ ] **Step 4: Run target and full M1 tests**

Run: `python -m pytest tests/cli/test_verify.py -q`
Expected: all CLI tests pass.

Run: `python -m pytest tests/contracts tests/governance tests/production tests/cli -q`
Expected: all M1 tests pass.

Run: `python -m factory.cli verify-repo .`
Expected: exit `0` and report M1 checks as verified.

- [ ] **Step 5: Commit**

```bash
git add factory/cli tests/cli/test_verify.py workshop
git commit -m "feat: add M1 repository and job commands"
```

### Task 7: M1 integration and status checkpoint

**Files:**
- Create: `tests/integration/test_m1_foundation.py`
- Create: `docs/runlogs/M1_FOUNDATION.md`

- [ ] **Step 1: Write the failing end-to-end test**

Create one test that runs `job-init`, loads the valid intent fixture, evaluates the gate, transitions `NEW -> DISCOVERY -> INTERVIEWING -> INTENT_CONFIRMATION -> READY`, saves after every transition, resumes through an injected external probe, and asserts only `local_validated` becomes true after validation evidence is recorded.

- [ ] **Step 2: Run and observe the first integration failure**

Run: `python -m pytest tests/integration/test_m1_foundation.py -q`
Expected: fails at the first unimplemented integration seam; record the exact assertion in the task notes.

- [ ] **Step 3: Add only the adapters needed by the test**

Do not add M2 interviewing or generation. Wire existing M1 APIs and add a `mark_status_layer(job, layer, evidence_ref)` helper that changes exactly one truth layer and appends matching evidence.

- [ ] **Step 4: Run all M1 gates and write the runlog**

Run: `python -m pytest tests/contracts tests/governance tests/production tests/cli tests/integration/test_m1_foundation.py -q`
Expected: all M1 tests pass.

Run: `python -m factory.cli verify-repo .`
Expected: exit `0`.

Write `docs/runlogs/M1_FOUNDATION.md` with the exact commit, commands, exit codes, test count, and the truthful status `local_validated`; set `published` and `real_usage_verified` to false.

- [ ] **Step 5: Commit**

```bash
git add factory tests/integration/test_m1_foundation.py docs/runlogs/M1_FOUNDATION.md
git commit -m "test: verify M1 factory foundation"
```
