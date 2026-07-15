# Changelog

## Unreleased

- Expand the public privacy gate with named rules for known credential shapes (GitHub, GitLab, Slack, OpenAI, Stripe, Google, AWS, authorization headers, JWT, PEM), sensitive paths, control-character normalization, and deterministic base64-PEM decoding. Reports stay redacted.
- Block unapproved OPTIMIZE requests before any state transition, checkpoint, or candidate directory is created.
- Support Codex skill install/check/uninstall when Codex home lives under a symlinked ancestor (for example macOS `/tmp`), while still rejecting symlinks at or below Codex home.
- Include large files (>1MB) in review snapshots via streamed sha256 so their path, size, and hash are part of the tree hash; regenerate the deterministic public examples accordingly.
- Clarify in the READMEs that the privacy scan detects known secret signatures, sensitive paths, and unsafe files, and that example timestamps are synthetic.

## 0.1.0 - Local release candidate (2026-07-11)

- Add commander's-intent interview, completeness gates, and traceable Agent generation.
- Add a project-local Codex Skill with optional managed installation.
- Add read-only Agent review and approval-gated optimization candidates.
- Add sanitized public examples, privacy scanning, bilingual onboarding, and repository verification.
