# Status and evidence

Report these five layers independently:

| Layer | Minimum evidence |
|---|---|
| `local_generated` | Candidate tree and valid manifest exist locally. |
| `local_validated` | Relevant deterministic checks passed against that candidate. |
| `installed` | A managed installation exists and matches its canonical source. |
| `published` | The intended remote or release contains the verified version. |
| `real_usage_verified` | A real downstream run produced verified evidence. |

Also state Git branch/push, customer delivery, and runtime activation separately when relevant. File creation, a green local test, installation, publication, and real usage never prove one another.

Use `verified`, `inferred`, or `unverified` for evidence. Re-check changeable external state instead of trusting an old checkpoint. Never place secrets, customer data, credentials, or private workshop contents in committed evidence.
