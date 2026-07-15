---
name: commander-agent-factory
description: Use when someone wants to design or build an AI Agent from a vague goal, audit an existing Agent, improve an Agent through an approval-gated candidate, or work inside the Commander Intent Agent Factory; not for ordinary coding, running a business Agent, standalone Skill authoring, or installing unrelated Skills.
---

# Commander Agent Factory

Convert a human goal into an evidence-backed Agent while keeping generation, validation, installation, publication, and real usage as separate facts.

## Route the request

- CREATE: load [references/create-workflow.md](references/create-workflow.md).
- REVIEW: load [references/review-workflow.md](references/review-workflow.md).
- OPTIMIZE: load [references/optimize-workflow.md](references/optimize-workflow.md).
- Status or evidence questions: load [references/status-and-evidence.md](references/status-and-evidence.md).

Load only the matching reference. Treat `factory/contracts/` and `factory/governance/` as the machine-readable truth; never replace their decisions with prose.

## Operate the factory

1. Create or resume a private workshop job before multi-step work.
2. Re-read its status and re-probe changeable external state before continuing.
3. Ask one plain-language question at a time when CREATE information is incomplete.
4. Refuse production until the current gate passes and the revised intent is confirmed.
5. Keep REVIEW read-only.
6. Keep OPTIMIZE approval-gated and write only to a candidate copy before finalization.
7. Run the relevant deterministic validation before reporting completion.
8. Report every truth layer separately.

If a referenced deterministic command or API is unavailable, stop at a clearly labeled structural draft. Do not imitate a missing backend with an unsupported completion claim.

## Handoffs

- Hand standalone Codex Skill creation or editing to `skill-creator` and `skill-refresh`.
- Hand unrelated curated or GitHub Skill installation to `skill-installer`.
- Do not invoke this factory merely to run a generated business Agent or perform ordinary software development.
