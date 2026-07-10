# M2 Create Pipeline and Codex Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a confirmed intent into a resumable one-question interview, a traceable platform-neutral blueprint, a deterministic candidate package, and a valid optionally installed Codex factory skill.

**Architecture:** The Codex meta-agent makes semantic choices and writes explicit interview answers/design input. Python selects one missing question, verifies readiness, validates explicit design data, generates through an atomic staging directory, and manages the global skill without making the global copy a truth source.

**Tech Stack:** Python 3.11+, YAML, JSON Schema, pathlib, shutil, hashlib, pytest, Codex Skill metadata.

---

## File responsibility map

| File | Responsibility |
|---|---|
| `factory/interview/questions.yaml` | Plain-language question catalog and priority |
| `factory/interview/protocol.py` | Select one question and record one answer |
| `factory/production/blueprint.py` | Merge confirmed intent with explicit AI design input |
| `factory/production/generator.py` | Atomic candidate package rendering |
| `factory/production/codex.py` | Validate/install/check/uninstall Codex skill |
| `templates/agent/` | Required Agent document templates |
| `skills/commander-agent-factory/` | Project-local meta-agent truth source |
| `scripts/manage_codex_skill.py` | Human-facing installer wrapper |

### Task 1: One-question interview protocol

**Files:**
- Create: `factory/interview/__init__.py`
- Create: `factory/interview/questions.yaml`
- Create: `factory/interview/protocol.py`
- Create: `tests/interview/test_protocol.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing interview tests**

```python
from factory.governance.gates import GateDecision
from factory.interview.protocol import next_question, record_answer


def test_selects_exactly_one_highest_risk_question(incomplete_intent):
    decision = GateDecision(30, ("missing_confirmed_source:/user",), ("/user", "/authority"), False)
    question = next_question(incomplete_intent, decision)
    assert question.path == "/user"
    assert question.reason
    assert question.recommended_answer
    assert "暂时不知道" in question.options


def test_unknown_answer_does_not_create_confirmed_provenance(incomplete_intent):
    question = next_question(
        incomplete_intent,
        GateDecision(30, ("missing_confirmed_source:/user",), ("/user",), False),
    )
    updated = record_answer(incomplete_intent, question, "暂时不知道", answer_ref="input:2")
    assert not any(p["path"] == "/user" and p["source_type"] == "user_confirmed" for p in updated["provenance"])
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/interview/test_protocol.py -q`
Expected: import fails because the interview package does not exist.

- [ ] **Step 3: Implement catalog and protocol**

```python
from dataclasses import dataclass
from copy import deepcopy
from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class InterviewQuestion:
    id: str
    path: str
    prompt: str
    reason: str
    recommended_answer: str
    options: tuple[str, ...]


def next_question(intent: Mapping, decision: GateDecision) -> InterviewQuestion | None:
    if decision.ready:
        return None
    catalog = load_questions()
    for item in sorted(catalog, key=lambda item: item["priority"]):
        if item["path"] in decision.missing_sources or not pointer_present(intent, item["path"]):
            return InterviewQuestion(
                item["id"], item["path"], item["prompt"], item["reason"],
                item["recommended_answer"], tuple(item["options"]),
            )
    return None
```

The catalog must cover `/user`, `/mission`, `/desired_end_state`, `/key_tasks`, `/resources`, `/authority`, and `/acceptance` in that risk order. Every option list ends with `暂时不知道`. `record_answer` updates only the selected path; answers other than `暂时不知道` append `user_confirmed` provenance with the supplied answer reference.

Add `incomplete_intent` to `tests/conftest.py` by deep-copying `valid_intent`, clearing user/authority provenance, setting those sections to empty values, and setting `confirmed=false`.

- [ ] **Step 4: Run interview and M1 regression tests**

Run: `python -m pytest tests/interview/test_protocol.py tests/governance/test_gates.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/interview tests/interview/test_protocol.py
git commit -m "feat: add one-question commander interview"
```

### Task 2: Traceable platform-neutral blueprint builder

**Files:**
- Create: `factory/production/blueprint.py`
- Create: `tests/production/test_blueprint.py`
- Create: `tests/fixtures/contracts/valid-design.yaml`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing blueprint tests**

```python
import pytest

from factory.errors import GateBlockedError
from factory.production.blueprint import build_blueprint


def test_blocked_intent_cannot_build_blueprint(valid_intent, valid_design, blocked_decision):
    with pytest.raises(GateBlockedError):
        build_blueprint(valid_intent, valid_design, blocked_decision)


def test_blueprint_preserves_traceability(valid_intent, valid_design, ready_decision):
    blueprint = build_blueprint(valid_intent, valid_design, ready_decision)
    assert blueprint["commander_intent_ref"]["name"] == valid_intent["metadata"]["name"]
    assert blueprint["capabilities"][0]["intent_paths"] == ["/key_tasks/0"]
    assert blueprint["evaluation"]["cases"][0]["intent_paths"] == ["/acceptance/criteria/0"]
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/production/test_blueprint.py -q`
Expected: import fails because `blueprint.py` does not exist.

- [ ] **Step 3: Implement fail-closed blueprint construction**

Expose:

```python
def build_blueprint(intent: Mapping, design: Mapping, decision: GateDecision) -> dict:
    if not decision.ready:
        raise GateBlockedError("commander intent is not production-ready")
    blueprint = {
        "schema_version": "1.0",
        "metadata": dict(design["metadata"]),
        "commander_intent_ref": {
            "name": intent["metadata"]["name"],
            "version": intent["metadata"]["version"],
        },
        "capabilities": deepcopy(design["capabilities"]),
        "skills": deepcopy(design["skills"]),
        "workflow": deepcopy(design["workflow"]),
        "resources": deepcopy(design["resources"]),
        "harness": deepcopy(design["harness"]),
        "evaluation": deepcopy(design["evaluation"]),
        "adapters": deepcopy(design["adapters"]),
    }
    issues = validate_document("agent-blueprint", blueprint)
    if issues:
        raise ContractValidationError(issues)
    return blueprint
```

Do not invent capabilities or tools. The design fixture supplies every capability, skill, workflow step, permission, evaluation case, and Codex adapter declaration explicitly. Validate that every `intent_paths` entry resolves in the confirmed intent.

Add `valid_design`, `ready_decision`, and `blocked_decision` fixtures to `tests/conftest.py`. The ready decision is `GateDecision(100, (), (), True)`; the blocked decision includes `intent_not_confirmed` and is not ready.

- [ ] **Step 4: Run blueprint tests**

Run: `python -m pytest tests/production/test_blueprint.py tests/contracts/test_schemas.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/production/blueprint.py tests/production/test_blueprint.py tests/fixtures/contracts/valid-design.yaml
git commit -m "feat: build traceable agent blueprints"
```

### Task 3: Atomic candidate generator and manifest

**Files:**
- Create: `factory/production/generator.py`
- Create: `templates/agent/README.md.tmpl`
- Create: `templates/agent/COMMANDER_INTENT.md.tmpl`
- Create: `templates/agent/ARCHITECTURE.md.tmpl`
- Create: `templates/agent/WORKFLOW.md.tmpl`
- Create: `tests/production/test_generator.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing generator tests**

```python
import json
import pytest

from factory.production.generator import generate_candidate


def test_generator_creates_only_declared_components(tmp_path, valid_intent, valid_blueprint):
    result = generate_candidate(tmp_path, valid_intent, valid_blueprint, template_root="templates/agent")
    manifest = json.loads(result.manifest_path.read_text())
    assert (result.output_path / "README.md").exists()
    assert (result.output_path / "adapters/codex/SKILL.md").exists()
    assert not (result.output_path / "tools").exists()
    assert manifest["omitted_components"]["tools"] == "not_declared"


def test_failed_generation_leaves_no_partial_candidate(tmp_path, valid_intent, invalid_blueprint):
    with pytest.raises(Exception):
        generate_candidate(tmp_path, valid_intent, invalid_blueprint, template_root="templates/agent")
    assert not list(tmp_path.glob("*.staging-*"))
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/production/test_generator.py -q`
Expected: import fails because the generator does not exist.

- [ ] **Step 3: Implement staging, rendering, and manifest hashing**

```python
@dataclass(frozen=True, slots=True)
class GenerationResult:
    output_path: Path
    manifest_path: Path
    created_paths: tuple[str, ...]


def generate_candidate(job_dir, intent, blueprint, template_root) -> GenerationResult:
    validate_or_raise("commander-intent", intent)
    validate_or_raise("agent-blueprint", blueprint)
    output = safe_child(Path(job_dir) / "output", slugify(blueprint["metadata"]["name"]))
    staging = output.with_name(f"{output.name}.staging-{uuid4().hex}")
    try:
        render_required_documents(staging, intent, blueprint, Path(template_root))
        render_declared_components(staging, blueprint)
        manifest = build_manifest(staging, intent, blueprint)
        write_json(staging / "factory-manifest.json", manifest)
        staging.replace(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return GenerationResult(output, output / "factory-manifest.json", tuple(manifest["created_paths"]))
```

The manifest includes generator version, source intent/blueprint hashes, created paths, omitted components with reasons, and all truth layers false except `local_generated=true`. Render `AGENT_SPEC.yaml` from the validated blueprint. Generate `skills`, `tools`, `knowledge`, `evaluation`, and `deployment` only when their blueprint sections declare content.

Add `invalid_blueprint` as a deep copy of `valid_blueprint` with its workflow removed. Ensure the shared `valid_blueprint` fixture declares a Codex adapter and no external tools, matching the generator assertions.

- [ ] **Step 4: Run Golden, Failure, Boundary, and Unknown generator tests**

Run: `python -m pytest tests/production/test_generator.py -q`
Expected: all four case classes pass and no staging directories remain.

- [ ] **Step 5: Commit**

```bash
git add factory/production/generator.py templates/agent tests/production/test_generator.py
git commit -m "feat: generate atomic agent candidates"
```

### Task 4: Project-local Codex meta-skill

**Files:**
- Create: `skills/commander-agent-factory/SKILL.md`
- Create: `skills/commander-agent-factory/agents/openai.yaml`
- Create: `skills/commander-agent-factory/references/create-workflow.md`
- Create: `skills/commander-agent-factory/references/review-workflow.md`
- Create: `skills/commander-agent-factory/references/optimize-workflow.md`
- Create: `skills/commander-agent-factory/references/status-and-evidence.md`
- Create: `tests/codex/test_skill_structure.py`

- [ ] **Step 1: Write the failing structure test**

```python
from pathlib import Path
import yaml


SKILL = Path("skills/commander-agent-factory")


def test_skill_has_valid_minimal_frontmatter_and_references():
    text = (SKILL / "SKILL.md").read_text()
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert set(frontmatter) == {"name", "description"}
    assert frontmatter["name"] == "commander-agent-factory"
    assert "create" in frontmatter["description"].lower()
    assert "review" in frontmatter["description"].lower()
    assert "optimize" in frontmatter["description"].lower()
    assert all((SKILL / "references" / name).exists() for name in (
        "create-workflow.md", "review-workflow.md", "optimize-workflow.md", "status-and-evidence.md"
    ))
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/codex/test_skill_structure.py -q`
Expected: fails because the skill folder does not exist.

- [ ] **Step 3: Initialize and author the skill using the official creator**

Read `/Users/zhaobo/.codex/skills/.system/skill-creator/references/openai_yaml.md`, then run:

```bash
python /Users/zhaobo/.codex/skills/.system/skill-creator/scripts/init_skill.py commander-agent-factory --path skills --resources references --interface display_name="Commander Agent Factory" --interface short_description="Create, review, and optimize agents from commander's intent" --interface default_prompt="Use the Commander Agent Factory to create, review, or optimize an Agent through evidence-backed gates."
```

Replace the generated body with concise imperative instructions that:

1. route CREATE/REVIEW/OPTIMIZE using the approved deterministic rules;
2. create or resume a private job before multi-step work;
3. load only the matching workflow reference;
4. ask one plain-language question at a time in CREATE;
5. refuse production until the gate passes and intent is confirmed;
6. keep REVIEW read-only;
7. require explicit approval and a candidate copy for OPTIMIZE;
8. report truth layers separately.

Keep detailed contracts in `factory/contracts` and workflow explanations in references. Do not add a README inside the skill.

- [ ] **Step 4: Run official and repository skill validation**

Run: `python /Users/zhaobo/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/commander-agent-factory`
Expected: validation succeeds.

Run: `python -m pytest tests/codex/test_skill_structure.py -q`
Expected: all skill structure tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/commander-agent-factory tests/codex/test_skill_structure.py
git commit -m "feat: add Codex commander factory skill"
```

### Task 5: Safe optional Codex installation and drift check

**Files:**
- Create: `factory/production/codex.py`
- Create: `scripts/manage_codex_skill.py`
- Create: `tests/production/test_codex_install.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing install tests**

```python
from pathlib import Path
import pytest

from factory.production.codex import check_codex_skill, install_codex_skill, uninstall_codex_skill


def test_copy_install_detects_drift_and_safe_uninstall(tmp_path, skill_fixture):
    codex_home = tmp_path / ".codex"
    installed = install_codex_skill(skill_fixture, codex_home, mode="copy")
    assert check_codex_skill(skill_fixture, codex_home).status == "current"
    (installed / "SKILL.md").write_text("changed")
    assert check_codex_skill(skill_fixture, codex_home).status == "drifted"
    uninstall_codex_skill(skill_fixture, codex_home)
    assert not installed.exists()


def test_install_refuses_unmanaged_existing_target(tmp_path, skill_fixture):
    target = tmp_path / ".codex/skills/commander-agent-factory"
    target.mkdir(parents=True)
    (target / "foreign.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        install_codex_skill(skill_fixture, tmp_path / ".codex", mode="copy")
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/production/test_codex_install.py -q`
Expected: import fails because `factory.production.codex` does not exist.

- [ ] **Step 3: Implement managed copy/symlink lifecycle**

Expose `InstallCheck(status, source_hash, installed_hash, target)` plus these exact functions: `validate_codex_skill(path: Path) -> tuple[str, ...]`; `install_codex_skill(source: Path, codex_home: Path, mode: str) -> Path`; `check_codex_skill(source: Path, codex_home: Path) -> InstallCheck`; and `uninstall_codex_skill(source: Path, codex_home: Path) -> None`.

Write `.commander-factory-install.json` with source path, mode, and source hash. Uninstall only a target with a valid matching marker. Tests inject `codex_home`; never read or write the real `~/.codex`. The wrapper script parses `install`, `check`, and `uninstall` and defaults to `${CODEX_HOME:-~/.codex}` only outside tests.

Add `skill_fixture` to `tests/conftest.py` by copying the project-local `skills/commander-agent-factory` into `tmp_path`; no installation test may reference the user's actual home directory.

- [ ] **Step 4: Run lifecycle and skill validation tests**

Run: `python -m pytest tests/production/test_codex_install.py tests/codex/test_skill_structure.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/production/codex.py scripts/manage_codex_skill.py tests/production/test_codex_install.py
git commit -m "feat: manage optional Codex skill installation"
```

### Task 6: Create-pipeline CLI wiring

**Files:**
- Modify: `factory/cli/main.py`
- Create: `factory/cli/create.py`
- Create: `tests/cli/test_create.py`

- [ ] **Step 1: Write failing CLI tests**

Test these commands with temporary inputs: `next-question`, `validate-intent`, `generate`, `skill-install`, `skill-check`, and `skill-uninstall`. Assert JSON output is machine-readable, blocked generation returns `2`, validation failure returns `1`, and successful commands return `0`.

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/cli/test_create.py -q`
Expected: argparse rejects the new commands.

- [ ] **Step 3: Wire thin command handlers**

Handlers load YAML/JSON, call the M1/M2 APIs, print JSON with `ensure_ascii=False`, and return documented exit codes. They must not reproduce gate, generator, or installer logic.

- [ ] **Step 4: Run CLI and full M2 regressions**

Run: `python -m pytest tests/cli/test_create.py tests/interview tests/production tests/codex -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/cli tests/cli/test_create.py
git commit -m "feat: expose create pipeline commands"
```

### Task 7: End-to-end create pipeline and M2 runlog

**Files:**
- Create: `tests/integration/test_create_pipeline.py`
- Create: `docs/runlogs/M2_CREATE_CODEX.md`

- [ ] **Step 1: Write end-to-end cases**

Cover:

- incomplete intent returns one question and cannot generate;
- `暂时不知道` persists without satisfying the gate;
- complete confirmed intent plus explicit design builds a schema-valid blueprint;
- generated candidate has manifest/path parity and a valid Codex adapter;
- interrupted job resumes from the last answer and rechecks external state;
- global installation test uses only `tmp_path`.

- [ ] **Step 2: Run and observe the first integration failure**

Run: `python -m pytest tests/integration/test_create_pipeline.py -q`
Expected: fails at an unconnected seam; record the exact failure.

- [ ] **Step 3: Add the minimum orchestration adapter**

Create `factory/production/create_pipeline.py` with one `run_create(job_dir, intent, design, template_root) -> GenerationResult` function. It validates intent, evaluates the gate, builds the blueprint, transitions through READY/BLUEPRINTING/PRODUCING/VALIDATING/CANDIDATE_READY, and records evidence after every state.

- [ ] **Step 4: Run full M1+M2 gates and write the runlog**

Run: `python -m pytest -q`
Expected: all tests pass.

Run: `python /Users/zhaobo/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/commander-agent-factory`
Expected: validation succeeds.

Run: `python -m factory.cli verify-repo .`
Expected: exit `0`, including M2 skill/template checks.

Write `docs/runlogs/M2_CREATE_CODEX.md` with exact commands, counts, commit, and status: `local_generated=true`, `local_validated=true`, `installed=false` pending post-merge installation from the canonical project folder, `published=false`, `real_usage_verified=false`.

- [ ] **Step 5: Commit**

```bash
git add factory/production/create_pipeline.py tests/integration/test_create_pipeline.py docs/runlogs/M2_CREATE_CODEX.md
git commit -m "test: verify M2 create and Codex pipeline"
```
