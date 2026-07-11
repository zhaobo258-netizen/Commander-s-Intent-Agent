#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from factory.cli.verify import verify_repository
from factory.governance.privacy import scan_public_tree


def main() -> int:
    repository = verify_repository(ROOT)
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    privacy = scan_public_tree(ROOT, (path for path in tracked if path))
    print(privacy.to_json())
    for failure in repository.failures:
        print(failure, file=sys.stderr)
    return 0 if repository.ok and privacy.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
