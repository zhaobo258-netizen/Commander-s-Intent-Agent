# REVIEW workflow

## Inputs

- The Agent source path or artifact reference.
- A private REVIEW job.
- Available immutable evidence and validation commands.

## Steps

1. Create or resume the REVIEW job and verify the target still matches the recorded source.
2. Snapshot evidence without modifying the target.
3. Evaluate intent, capability, execution, outcome, evolution, permissions, provenance, tests, and usability only where evidence exists.
4. Record findings with severity, location, impact, remediation, and evidence status.
5. Keep unsupported business outcome and evolution scores provisional.

## Boundary

REVIEW is read-only. A request to fix findings must become a separate OPTIMIZE job. Use the deterministic `python -m factory.cli review` command and report a completed factory review only when its report and evidence snapshot are present and valid. If that command is unavailable or fails, return only a structural review draft marked unverified.

## Output

Return a review report and evidence snapshot references. Never convert a clean-looking artifact into installed, published, production-ready, or real-use evidence.
