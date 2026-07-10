# Commander’s Intent Agent Factory V0.1 Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the complete V0.1 local-first Agent factory, including deterministic contracts, create/review/optimize pipelines, a Codex adapter, public documentation, privacy gates, and verified GitHub publication.

**Architecture:** Keep `factory/contracts` and `factory/governance` as the machine-readable truth source. Use the Codex skill for semantic interviewing and orchestration, Python for deterministic state, validation, generation, review, optimization, and installation, and private ignored workshop jobs for resumable work.

**Tech Stack:** Python 3.11+, argparse, PyYAML, jsonschema, pytest, Markdown, JSON Schema, GitHub Actions.

---

## Source of truth

- Approved specification: `docs/superpowers/specs/2026-07-11-commander-agent-factory-design.md`
- Public repository: `https://github.com/zhaobo258-netizen/Commander-s-Intent-Agent`
- Local branch at planning time: `main`
- Local specification commit: `c105984`

## Why this is split into four plans

The approved design contains four independently testable subsystems. Execute them in order so each phase leaves a usable, verified increment:

1. [M1 Foundation](2026-07-11-m1-factory-foundation.md): contracts, gates, state machine, job persistence, and CLI shell.
2. [M2 Create and Codex](2026-07-11-m2-create-codex.md): one-question interview protocol, blueprint/generator, Codex meta-skill, and optional installation.
3. [M3 Review and Optimize](2026-07-11-m3-review-optimize.md): read-only evidence, findings, provisional evaluation, candidate-copy optimization, and diffs.
4. [M4 Open-source Release](2026-07-11-m4-open-source-release.md): privacy gates, bilingual docs, public examples, CI, and verified publication.

## Stable cross-phase API contracts

Later phases must reuse these names exactly:

| API | Owner phase | Contract |
|---|---|---|
| `ValidationIssue` | M1 | `path`, `code`, `message` |
| `validate_document(kind, data)` | M1 | Returns `tuple[ValidationIssue, ...]` |
| `GateDecision` | M1 | `score`, `blockers`, `missing_sources`, `ready` |
| `evaluate_production_gate(intent, policy)` | M1 | Never treats inference or assumption as confirmed evidence |
| `allowed_next(mode, state)` | M1 | Returns legal target states only |
| `transition(job, target, trigger, evidence, now)` | M1 | Returns a new job document and appends history |
| `create_job`, `load_job`, `save_checkpoint`, `resume_job` | M1 | Persist atomically inside `workshop` |
| `InterviewQuestion` | M2 | `id`, `path`, `prompt`, `reason`, `recommended_answer`, `options` |
| `next_question(intent, decision)` | M2 | Returns exactly one question or `None` |
| `GenerationResult` | M2 | `output_path`, `manifest_path`, `created_paths` |
| `EvidenceRef`, `Finding`, `TreeSnapshot`, `ReviewReport` | M3 | Evidence-first immutable review records |
| `CandidateManifest`, `DiffReport`, `OptimizationResult` | M3 | Candidate-copy optimization records |
| `VerificationReport`, `PrivacyReport` | M1/M4 | Never infer later truth layers from local success |

## Execution and branch strategy

- [ ] Commit the approved plans on local `main`, then publish this planning baseline once with `git push -u origin main`; verify `git ls-remote origin refs/heads/main` equals local `main`. This establishes the empty repository's PR base and does not claim V0.1 is released.
- [ ] Create an isolated worktree and feature branch `codex/commander-agent-factory-v0.1` before implementation.
- [ ] Execute M1, M2, M3, and M4 in order.
- [ ] For every task: RED test, observed failure, minimal implementation, target test, full phase regression, commit.
- [ ] After each phase: run its documented gate and record the exact command/output in the phase plan.
- [ ] After M4: run full local gates, inspect the complete diff, and perform independent specification and quality review.
- [ ] Publish only after local validation; verify remote SHA and GitHub Actions separately.
- [ ] Keep `real_usage_verified` false until a real external user or business task supplies matching evidence.

## Program-level acceptance command

Run from the repository root after all four plans are complete:

```bash
python -m pytest -q
python -m factory.cli verify-repo . --public
git diff --check origin/main...HEAD
```

Expected:

- `pytest` exits `0` with no failed, skipped-required, or errored tests.
- `verify-repo` exits `0` and reports contracts, examples, Codex skill, privacy, and public docs as verified.
- `git diff --check` exits `0` with no whitespace errors.
- These commands prove local validation only; publication and real usage remain separate states.
