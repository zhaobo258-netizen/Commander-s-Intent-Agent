# OPTIMIZE workflow

## Inputs

- A completed evidence-backed review.
- Explicit scope and acceptance criteria.
- Approval evidence identifying the allowed changes.

## Steps

1. Create or resume the OPTIMIZE job and verify the source and review evidence have not drifted.
2. Produce an optimization plan tied to review findings.
3. Stop before mutation until explicit approval is recorded.
4. Copy the source into an isolated candidate area; never modify the original Agent in place.
5. Apply only approved changes, validate the candidate, and produce a source-to-candidate diff.
6. Finalize only after acceptance checks pass.

## Boundary

Without approval, produce a plan only. Until deterministic M3 optimize commands exist in the current checkout, return a structural proposal marked unverified; do not simulate approval, mutation, or validation in prose.

## Output

Return the candidate path, diff, validation evidence, remaining findings, and separated truth layers. Optimization does not imply installation, publication, or real usage.
