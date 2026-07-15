# CREATE workflow

## Inputs

- A goal or task stated by the user.
- A private CREATE job directory.
- Structured Commander Intent answers and their evidence references.
- Explicit Agent design data; do not invent capabilities, tools, or permissions.

## Steps

1. Initialize or resume the CREATE job and verify its current state.
2. Evaluate the current intent with the production gate.
3. If blocked, select exactly one highest-risk question. Explain why it matters in ordinary language.
4. Treat catalog options as answer directions. Convert the user's answer into the selected section structure before recording it.
5. After every answer, keep `confirmed=false`; present the revised intent for explicit confirmation.
6. Re-evaluate the gate. Continue only when the actual decision is ready.
7. Build the blueprint from explicit design data and require every `intent_paths` entry to resolve.
8. Generate the candidate atomically in the job output directory.
9. Validate the candidate and then mark only the evidence-supported local layer.

## Output and completion

Return the candidate path, manifest path, unresolved items, and separated truth layers. CREATE is locally generated only when the manifest and complete candidate tree agree. It is not installed, published, or real-usage-verified unless separate evidence proves those states.

## Failure behavior

On missing information, ask one question. On stale gate evidence, re-evaluate. On path, contract, adapter, template, collision, or manifest failure, preserve the existing output and report the blocker.
