# Commander Intent Agent Factory

New session? Read [docs/HANDOFF.md](docs/HANDOFF.md) first for the current state, branch discipline, and verification sequence.

Use [skills/commander-agent-factory/SKILL.md](skills/commander-agent-factory/SKILL.md) as the Agent-factory entry. Route work to CREATE, REVIEW, or OPTIMIZE and load only the matching reference.

Treat `factory/contracts/` and `factory/governance/` as machine-readable truth. Keep multi-step jobs private under `workshop/`. REVIEW is read-only. OPTIMIZE requires explicit approval and edits only an isolated candidate.

Default delivery mode is completion-first: finish one runnable milestone, use only directly relevant tests during implementation, record nonblocking debt without expanding scope, then run one full verification and one concentrated independent audit. Keep generated, validated, installed, published, and real-use states separate.
