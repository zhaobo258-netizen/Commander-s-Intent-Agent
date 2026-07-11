# 5-minute quickstart

## Install and verify

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m factory.cli verify-repo . --public
```

## CREATE

Copy the example intent and design, then answer the interview fields. The factory asks one highest-priority question at a time and blocks incomplete production.

```bash
python -m factory.cli job-init --workshop workshop --mode CREATE --name my-agent --job-id create-001
python -m factory.cli next-question examples/create-regional-manager/intent.yaml
python -m factory.cli validate-intent examples/create-regional-manager/intent.yaml
python -m factory.cli generate --job-dir workshop/jobs/create-001-my-agent --intent examples/create-regional-manager/intent.yaml --design examples/create-regional-manager/design.yaml --template-root templates/agent
python -m factory.cli job-status workshop/jobs/create-001-my-agent
```

## REVIEW

The target and workshop must not contain each other. The report is written outside the target.

```bash
python -m factory.cli review path/to/agent --workshop workshop --job-id review-001 --name existing-agent
```

## OPTIMIZE

An optimization plan must be explicitly approved. The result is a candidate copy, not a replacement or deployment.

```bash
python -m factory.cli job-init --workshop workshop --mode OPTIMIZE --name existing-agent --job-id optimize-001
python -m factory.cli optimize-prepare workshop/reviews/optimize-001-existing-agent path/to/plan.yaml workshop/candidate --approve
python -m factory.cli optimize-diff path/to/agent workshop/candidate
python -m factory.cli optimize-finalize workshop/reviews/optimize-001-existing-agent
```

## Optional Codex installation

```bash
python -m factory.cli skill-install --source skills/commander-agent-factory --codex-home "$HOME/.codex" --mode copy
python -m factory.cli skill-check --source skills/commander-agent-factory --codex-home "$HOME/.codex"
python -m factory.cli skill-uninstall --source skills/commander-agent-factory --codex-home "$HOME/.codex"
```

The wheel does not embed the repository-level Skill. Always provide a trusted explicit `--source`.

## Release checks

```bash
python -m pytest -q
python -m factory.cli verify-repo . --public
python scripts/verify_public.py
```

Passing locally does not imply pushed, merged, published, installed, or verified in real use.
