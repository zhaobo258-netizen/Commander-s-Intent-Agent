# Commander's Intent Agent Factory

An open-source workshop that turns an incomplete goal into a reviewable agent package. It confirms mission, success criteria, resources, and constraints before production. The same CLI can review an existing agent without modifying it and can create an optimization candidate after explicit human approval.

[中文](README.md) · [5-minute quickstart](docs/QUICKSTART_EN.md) · [status model](docs/STATUS_MODEL.md) · [contributing](CONTRIBUTING.md)

## Three entry points

- **CREATE** interviews the user one question at a time and generates an agent package.
- **REVIEW** inspects an existing agent read-only and writes its report to a separate workshop.
- **OPTIMIZE** prepares a plan first and creates a candidate copy only after explicit approval. It never overwrites the source agent.

## Quick start

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m factory.cli --version
python -m factory.cli verify-repo . --public
python scripts/build_examples.py
```

The generated CREATE package is under `examples/create-regional-manager/output/`; the read-only review report is under `examples/review-minimal-agent/report/`.

## Create

```bash
python -m factory.cli job-init --workshop workshop --mode CREATE --name my-agent --job-id create-001
python -m factory.cli next-question examples/create-regional-manager/intent.yaml
python -m factory.cli validate-intent examples/create-regional-manager/intent.yaml
python -m factory.cli generate --job-dir workshop/create-001 --intent examples/create-regional-manager/intent.yaml --design examples/create-regional-manager/design.yaml --template-root templates/agent
python -m factory.cli job-status workshop/create-001
```

Missing information blocks production instead of being guessed. See the [English quickstart](docs/QUICKSTART_EN.md) for REVIEW and OPTIMIZE.

## Codex skill

The natural-language adapter lives at [`skills/commander-agent-factory/SKILL.md`](skills/commander-agent-factory/SKILL.md). Optional installation:

```bash
python -m factory.cli skill-install --source skills/commander-agent-factory --codex-home "$HOME/.codex" --mode copy
python -m factory.cli skill-check --source skills/commander-agent-factory --codex-home "$HOME/.codex"
python -m factory.cli skill-uninstall --source skills/commander-agent-factory --codex-home "$HOME/.codex"
```

The source path is explicit by design. The current wheel does not embed the repository-level Skill, so installing the Python package does not install the Codex Skill.

## Safety and status

Keep private requirements and customer data in ignored workshop paths. Run `python scripts/verify_public.py` before publication. `0.1.0` is a local release candidate: generated and locally validated do not imply installed, published, or verified in real use. See the [status model](docs/STATUS_MODEL.md).

Licensed under [MIT](LICENSE). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
