# M3 Review and Optimize Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-first read-only Agent review and explicitly approved candidate-copy optimization without modifying the source Agent.

**Architecture:** Snapshot the target without following links, evaluate only observable evidence, double-check the target tree remains unchanged, and write reports exclusively to the private workshop. Optimization begins only from an approved state, copies to an isolated candidate, hashes the baseline, validates the candidate, and emits a deterministic diff.

**Tech Stack:** Python 3.11+, pathlib, hashlib, dataclasses, difflib, shutil, JSON Schema, pytest.

---

## File responsibility map

| File | Responsibility |
|---|---|
| `factory/review/models.py` | Immutable evidence, finding, snapshot, and report types |
| `factory/review/snapshot.py` | Safe no-follow tree evidence and unchanged check |
| `factory/review/evaluator.py` | Structural checks and evidence-aware quality assessment |
| `factory/review/report.py` | JSON/Markdown report rendering outside target |
| `factory/review/pipeline.py` | Read-only review orchestration and state transitions |
| `factory/optimization/workspace.py` | Approved baseline-to-candidate copying |
| `factory/optimization/diff.py` | Candidate/baseline change report |
| `factory/optimization/pipeline.py` | Validation and finalize transitions |

### Task 1: Immutable review evidence and safe snapshots

**Files:**
- Create: `factory/review/__init__.py`
- Create: `factory/review/models.py`
- Create: `factory/review/snapshot.py`
- Create: `tests/review/test_snapshot.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing snapshot tests**

```python
from pathlib import Path

from factory.review.snapshot import snapshot_tree, verify_unchanged


def test_snapshot_records_relative_text_evidence_without_following_links(tmp_path):
    target = tmp_path / "agent"
    target.mkdir()
    (target / "COMMANDER_INTENT.md").write_text("# Mission\nHelp managers.\n")
    outside = tmp_path / "secret.txt"
    outside.write_text("outside")
    (target / "external-link").symlink_to(outside)
    snapshot = snapshot_tree(target)
    assert snapshot.files[0].path == "COMMANDER_INTENT.md"
    assert snapshot.files[0].line_count == 2
    assert "external-link" in snapshot.skipped_links


def test_verify_unchanged_detects_target_mutation(tmp_path):
    target = tmp_path / "agent"
    target.mkdir()
    file = target / "README.md"
    file.write_text("before")
    before = snapshot_tree(target)
    file.write_text("after")
    after = snapshot_tree(target)
    assert verify_unchanged(before, after) is False
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/review/test_snapshot.py -q`
Expected: import fails because `factory.review` does not exist.

- [ ] **Step 3: Implement immutable evidence models and no-follow scan**

```python
@dataclass(frozen=True, slots=True)
class EvidenceRef:
    path: str
    line_start: int | None
    line_end: int | None
    sha256: str
    status: str


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: str
    size: int
    line_count: int | None
    sha256: str


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    root: str
    files: tuple[FileSnapshot, ...]
    skipped_links: tuple[str, ...]
    skipped_unreadable: tuple[str, ...]
    tree_hash: str
```

`snapshot_tree(root: Path, max_file_bytes: int = 1_000_000) -> TreeSnapshot` must reject a non-directory, sort paths, use `lstat`, never follow links, record unreadable/oversize files without opening them, hash bytes for regular files, and compute `tree_hash` from normalized relative path plus file hash. `verify_unchanged(before, after)` compares root and tree hash.

Add `target_agent` to `tests/conftest.py` as a fresh temporary copy of `tests/fixtures/review/standard-agent` after Task 2 creates that fixture tree.

- [ ] **Step 4: Run snapshot tests**

Run: `python -m pytest tests/review/test_snapshot.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/review tests/review/test_snapshot.py
git commit -m "feat: capture immutable Agent review evidence"
```

### Task 2: Evidence-backed evaluator and provisional quality policy

**Files:**
- Create: `factory/governance/evaluation-policy.yaml`
- Create: `factory/review/evaluator.py`
- Create: `tests/review/test_evaluator.py`
- Create: `tests/fixtures/review/minimal-agent/README.md`
- Create: `tests/fixtures/review/standard-agent/COMMANDER_INTENT.md`
- Create: `tests/fixtures/review/standard-agent/AGENT_SPEC.yaml`
- Create: `tests/fixtures/review/standard-agent/evaluation/cases.yaml`

- [ ] **Step 1: Write failing evaluator tests**

```python
from pathlib import Path

from factory.review.evaluator import review_agent
from factory.governance.policy import load_policy


def test_minimal_agent_has_located_findings_and_no_confirmed_grade():
    report = review_agent(Path("tests/fixtures/review/minimal-agent"), load_policy("evaluation-policy"))
    assert {finding.severity for finding in report.findings} >= {"P1", "P2"}
    assert all(finding.evidence for finding in report.findings)
    assert report.quality["outcome"]["status"] == "not_evidenced"
    assert report.quality["evolution"]["status"] == "not_evidenced"
    assert report.quality["grade"] == "provisional"


def test_standard_agent_passes_structural_checks_without_claiming_real_use():
    report = review_agent(Path("tests/fixtures/review/standard-agent"), load_policy("evaluation-policy"))
    assert not any(f.severity in {"P0", "P1"} for f in report.findings)
    assert report.status_layers["real_usage_verified"] is False
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/review/test_evaluator.py -q`
Expected: import fails because `review_agent` does not exist.

- [ ] **Step 3: Implement ten structural dimensions and five quality layers**

Define:

```python
@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    severity: str
    title: str
    impact: str
    recommendation: str
    evidence: tuple[EvidenceRef, ...]
    evidence_status: str


@dataclass(frozen=True, slots=True)
class ReviewReport:
    target: str
    baseline_hash: str
    scope: tuple[str, ...]
    findings: tuple[Finding, ...]
    quality: dict
    status_layers: dict[str, bool]
    unverified: tuple[str, ...]
```

Implement checks for intent, traceability, skills, data/knowledge sources, tool permissions, state/error/recovery, human review, four case classes, novice-readable README, and privacy/license/platform coupling. Each finding must reference an observed path; missing files use a verified directory snapshot evidence reference with no line range.

Policy weights are Intent 20, Capability 20, Execution 20, Outcome 30, Evolution 10. If Outcome or Evolution lacks matching real evidence, set `status=not_evidenced`, omit a confirmed total, set `grade=provisional`, and add explicit unverified items. Structural completeness must not create `published` or `real_usage_verified`.

- [ ] **Step 4: Run evaluator and snapshot regressions**

Run: `python -m pytest tests/review/test_evaluator.py tests/review/test_snapshot.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/governance/evaluation-policy.yaml factory/review/evaluator.py tests/review tests/fixtures/review
git commit -m "feat: evaluate Agents from observable evidence"
```

### Task 3: Read-only review pipeline, reports, and CLI

**Files:**
- Create: `factory/review/report.py`
- Create: `factory/review/pipeline.py`
- Create: `factory/cli/review.py`
- Modify: `factory/cli/main.py`
- Create: `tests/integration/test_review_pipeline.py`
- Create: `tests/cli/test_review.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing read-only pipeline tests**

```python
from factory.review.pipeline import run_review
from factory.review.snapshot import snapshot_tree


def test_review_writes_only_to_workshop(review_job, target_agent):
    before = snapshot_tree(target_agent)
    result = run_review(review_job, target_agent)
    after = snapshot_tree(target_agent)
    assert before.tree_hash == after.tree_hash
    assert result.json_path.is_relative_to(review_job / "reports")
    assert result.markdown_path.is_relative_to(review_job / "reports")
    assert not (target_agent / "reports").exists()
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/integration/test_review_pipeline.py tests/cli/test_review.py -q`
Expected: imports or argparse fail because the pipeline and command do not exist.

- [ ] **Step 3: Implement report rendering and double-snapshot orchestration**

Define `WrittenReview` exactly as follows and implement `write_review_report(job_dir: Path, report: ReviewReport) -> WrittenReview` plus `run_review(job_dir: Path, target: Path) -> WrittenReview`.

```python
@dataclass(frozen=True, slots=True)
class WrittenReview:
    report: ReviewReport
    json_path: Path
    markdown_path: Path
```

`run_review` transitions REVIEW_INTAKE -> REVIEWING, snapshots the target, evaluates, writes JSON/Markdown only under `job_dir/reports`, snapshots again, raises if changed, then transitions to REVIEW_READY with both hashes as evidence. The Markdown starts with the verdict, then P0-P3 findings, provisional quality, unverified items, and separated truth layers.

Add `commander-factory review TARGET --workshop PATH --job-id ID --name NAME`. The command creates a REVIEW job, prints report paths, and returns `0` for completed review even when findings exist; IO or integrity failure returns `1`.

Add `review_job` to `tests/conftest.py` by calling the M1 `create_job` API under `tmp_path/reviews` with mode `REVIEW` and then transitioning it to `REVIEW_INTAKE`.

- [ ] **Step 4: Run pipeline, CLI, and contract tests**

Run: `python -m pytest tests/integration/test_review_pipeline.py tests/cli/test_review.py tests/contracts/test_schemas.py -q`
Expected: all tests pass and target hashes are unchanged.

- [ ] **Step 5: Commit**

```bash
git add factory/review factory/cli tests/integration/test_review_pipeline.py tests/cli/test_review.py
git commit -m "feat: add read-only Agent review pipeline"
```

### Task 4: Optimization plan contract and approval gate

**Files:**
- Create: `factory/contracts/optimization-plan.schema.json`
- Modify: `factory/contracts/validation.py`
- Create: `factory/optimization/__init__.py`
- Create: `factory/optimization/workspace.py`
- Create: `tests/optimization/test_workspace.py`
- Create: `tests/fixtures/contracts/valid-optimization-plan.yaml`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing approval tests**

```python
import pytest

from factory.errors import GateBlockedError
from factory.optimization.workspace import prepare_candidate


def test_unapproved_job_cannot_create_candidate(optimize_job, optimization_plan, tmp_path):
    with pytest.raises(GateBlockedError, match="OPTIMIZATION_APPROVED"):
        prepare_candidate(optimize_job, optimization_plan, tmp_path)
    assert not list(tmp_path.iterdir())


def test_approved_job_copies_candidate_without_git_or_source_mutation(approved_job, optimization_plan, target_agent, tmp_path):
    manifest = prepare_candidate(approved_job, optimization_plan, tmp_path)
    assert manifest.source_hash
    assert (manifest.candidate_path / "README.md").exists()
    assert not (manifest.candidate_path / ".git").exists()
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/optimization/test_workspace.py -q`
Expected: import fails because optimization support does not exist.

- [ ] **Step 3: Add the contract and candidate workspace**

The optimization plan requires `schema_version`, `target`, `baseline_hash`, `intent_change`, `approved_by_user`, `approved_at`, `changes`, `acceptance`, and `rollback`. Add `optimization-plan` to validation `KINDS`.

```python
@dataclass(frozen=True, slots=True)
class CandidateManifest:
    source_path: Path
    source_hash: str
    candidate_path: Path
    plan_hash: str


def prepare_candidate(job: Mapping, plan: Mapping, output: Path) -> CandidateManifest:
    if job["mode"] != "OPTIMIZE" or job["status"] != "OPTIMIZATION_APPROVED":
        raise GateBlockedError("job must be OPTIMIZATION_APPROVED")
    if not plan["approved_by_user"]:
        raise GateBlockedError("optimization plan lacks user approval")
    if plan["intent_change"] and not job["approvals"].get("new_intent_confirmed"):
        raise GateBlockedError("mission change requires confirmed new intent")
    # Verify baseline hash, copy to staging without .git, then atomically rename.
```

Reject output paths inside the source tree and source paths inside the output tree. Never follow source symlinks.

Add `optimization_plan`, `optimize_job`, and `approved_job` fixtures. `optimize_job` stops at `REVIEW_READY`; `approved_job` includes user approval evidence and is transitioned to `OPTIMIZATION_APPROVED`.

- [ ] **Step 4: Run contract and workspace tests**

Run: `python -m pytest tests/optimization/test_workspace.py tests/contracts/test_schemas.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/contracts factory/optimization tests/optimization tests/fixtures/contracts/valid-optimization-plan.yaml
git commit -m "feat: gate optimization candidate creation"
```

### Task 5: Candidate diff, validation, finalize, and CLI

**Files:**
- Create: `factory/optimization/diff.py`
- Create: `factory/optimization/pipeline.py`
- Create: `factory/cli/optimize.py`
- Modify: `factory/cli/main.py`
- Create: `tests/optimization/test_diff.py`
- Create: `tests/integration/test_optimization_pipeline.py`
- Create: `tests/cli/test_optimize.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing candidate finalization tests**

```python
from factory.optimization.diff import compare_trees
from factory.optimization.pipeline import finalize_optimization


def test_diff_reports_added_modified_deleted_without_secret_contents(baseline, candidate):
    diff = compare_trees(baseline, candidate)
    assert diff.modified == ("README.md",)
    assert diff.added == ("evaluation/new-case.yaml",)
    assert diff.deleted == ()
    assert "token" not in diff.summary.lower()


def test_failed_regression_does_not_reach_candidate_ready(approved_job, candidate_manifest):
    result = finalize_optimization(approved_job, candidate_manifest, validator=lambda _: ["schema failure"])
    assert result.ready is False
    assert result.job["status"] == "BLOCKED"
```

- [ ] **Step 2: Run and observe RED**

Run: `python -m pytest tests/optimization/test_diff.py tests/integration/test_optimization_pipeline.py -q`
Expected: imports fail because diff/finalize do not exist.

- [ ] **Step 3: Implement deterministic diff and fail-closed finalize**

Define `DiffReport(added, modified, deleted, summary)` and `OptimizationResult(ready, job, diff, validation_errors)`. Compare normalized path/hash snapshots; summaries include paths and statuses, never raw secret-like values. Finalize transitions OPTIMIZING -> VALIDATING, runs the injected validator, enters BLOCKED on any error, or enters CANDIDATE_READY with diff and validation evidence.

Add CLI commands:

- `optimize-prepare JOB_DIR PLAN OUTPUT`
- `optimize-diff BASELINE CANDIDATE`
- `optimize-finalize JOB_DIR CANDIDATE`

CLI does not edit the candidate; the Codex skill performs approved edits inside it.

Add `baseline`, `candidate`, and `candidate_manifest` fixtures under `tmp_path`; the candidate differs only by a README edit and one new evaluation file, and the manifest points to their real snapshot hashes.

- [ ] **Step 4: Run optimization, CLI, and review regressions**

Run: `python -m pytest tests/optimization tests/integration/test_optimization_pipeline.py tests/cli/test_optimize.py tests/integration/test_review_pipeline.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add factory/optimization factory/cli tests/optimization tests/integration/test_optimization_pipeline.py tests/cli/test_optimize.py
git commit -m "feat: validate and diff optimized Agent candidates"
```

### Task 6: M3 end-to-end gate and runlog

**Files:**
- Create: `tests/e2e/test_review_optimize.py`
- Create: `docs/runlogs/M3_REVIEW_OPTIMIZE.md`

- [ ] **Step 1: Write four end-to-end cases**

Cover Golden review, malformed Agent, attempted source-tree mutation during review, and unapproved optimization. Add an approved optimization case that edits only a candidate, validates it, and leaves source hash unchanged.

- [ ] **Step 2: Run and observe first failure**

Run: `python -m pytest tests/e2e/test_review_optimize.py -q`
Expected: fails at the first missing orchestration seam; record the exact failure.

- [ ] **Step 3: Wire only the missing seam and update repository verification**

Extend `verify_repository` to require evaluation policy, optimization schema, review fixture validity, and read-only/candidate-copy integration tests. Do not add public docs/privacy gates before M4.

- [ ] **Step 4: Run full M1-M3 verification and write runlog**

Run: `python -m pytest -q`
Expected: all tests pass.

Run: `python -m factory.cli verify-repo .`
Expected: exit `0`, including M3 checks.

Write `docs/runlogs/M3_REVIEW_OPTIMIZE.md` with exact commands, counts, source/candidate hash evidence, and truthful layers. A synthetic fixture does not set `real_usage_verified=true`.

- [ ] **Step 5: Commit**

```bash
git add factory/cli/verify.py tests/e2e/test_review_optimize.py docs/runlogs/M3_REVIEW_OPTIMIZE.md
git commit -m "test: verify M3 review and optimization"
```
