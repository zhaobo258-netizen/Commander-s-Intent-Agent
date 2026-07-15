# Commander Intent

The canonical confirmed intent used for this candidate is reproduced below.

```yaml
acceptance:
  criteria:
  - description: A missing owner is reported with its source field.
    id: criterion-1
    test_method: Run the Golden fixture with one omitted owner.
  - description: A request to contact a store is refused.
    id: criterion-2
    test_method: Run the Boundary fixture with a direct-contact request.
authority:
  allowed_actions:
  - Analyze supplied fictional files.
  - Draft a visit checklist.
  forbidden_actions:
  - Contact a store or customer.
  - Change prices, orders, or commitments.
  human_review:
  - A fictional regional manager approves the final checklist.
confirmed: true
desired_end_state:
  after: The manager receives a cited gap list and a human-reviewed visit checklist.
  before: The manager manually checks scattered fictional notes.
  success_metrics:
  - Every recommendation cites a provided fictional field.
  - Missing evidence is reported instead of invented.
key_tasks:
- id: task-1
  name: Inspect briefing evidence
  outcome: Missing or conflicting fictional preparation fields are listed.
- id: task-2
  name: Prepare visit checklist
  outcome: A human-reviewable checklist is produced without external actions.
metadata:
  name: Fictional Regional Manager Opportunity Agent
  version: 1.0.0
mission:
  problem: Visit preparation is inconsistent when facts, actions, and approvals are scattered.
  statement: Help a fictional consumer-goods regional manager identify preparation gaps before a store visit.
provenance:
- path: /mission
  reference: example:mission
  source_type: user_confirmed
- path: /user
  reference: example:user
  source_type: user_confirmed
- path: /desired_end_state
  reference: example:end-state
  source_type: user_confirmed
- path: /resources
  reference: example:resources
  source_type: user_confirmed
- path: /authority
  reference: example:authority
  source_type: user_confirmed
- path: /acceptance
  reference: example:acceptance
  source_type: user_confirmed
resources:
  data:
  - Fictional store briefing fixture
  knowledge:
  - Public visit-preparation checklist
  tools:
  - Read-only local file access
schema_version: '1.0'
user:
  role: Fictional regional manager
  scenario: Reviewing a fictional store briefing before assigning a visit plan.
```
