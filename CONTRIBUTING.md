# Contributing

1. Create a feature branch and install with `python -m pip install -e ".[dev]"`.
2. Add a failing test for changed behavior, implement the smallest compatible change, and keep public contracts backward-compatible or document the version change.
3. Never commit private workshop jobs, generated customer artifacts, credentials, endpoints, or real customer data.
4. Keep REVIEW read-only and OPTIMIZE approval-gated.
5. Before a pull request, run:

```bash
python -m pytest -q
python -m factory.cli verify-repo . --public
python scripts/verify_public.py
```

Use focused commits and explain contract, privacy, permission, and migration impact in the pull request.
