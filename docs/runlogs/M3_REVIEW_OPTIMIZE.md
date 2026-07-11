# M3 REVIEW + OPTIMIZE Local Verification

Date: 2026-07-11 (Asia/Shanghai)

Verified implementation commit: `5b6f42b1d98dfd1e8bb30aa5702c6fe982e7b39c`

## Completed capability

- No-follow Agent tree snapshots with immutable path/hash evidence.
- Evidence-backed provisional quality evaluation; Outcome, Evolution, and real usage remain unverified without matching evidence.
- REVIEW reports written only to private workshop jobs, with before/after source hashes.
- Optimization plan contract and explicit approval gate.
- Atomic source-to-candidate copy excluding `.git` and rejecting source/output overlap.
- Path/hash-only diffs without raw file content.
- Candidate validation and fail-closed `BLOCKED` transition.
- CLI review, optimize-prepare, optimize-diff, and optimize-finalize flows.

## Verification

- Full suite after concentrated audit remediation: `401 passed in 10.36s`.
- Repository verification: `28` checks reported `verified`; no failures.
- Clean wheel installed outside the repository and completed:
  - read-only REVIEW with a provisional report;
  - approved candidate preparation;
  - candidate-only edit and finalization to `CANDIDATE_READY`;
  - source tree hash unchanged.

## Truth layers for the synthetic optimized candidate

```yaml
local_generated: true
local_validated: true
installed: false
published: false
real_usage_verified: false
github_pushed: false
customer_deliverable: false
```

The evidence uses synthetic repository fixtures, not customer or real business data. It proves local workflow behavior only. No global installation, publication, customer delivery, or real downstream use is claimed.

Concentrated audit remediation rejects target/workshop overlap before REVIEW writes and binds OPTIMIZE diff, validation, and state evidence to one candidate tree hash. Nonblocking debt retained for M4: optimization intake currently compresses review-state semantics, and the private candidate manifest is not yet cryptographically bound to the approved plan and job identity.
