#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from factory.production.codex import (
    check_codex_skill,
    install_codex_skill,
    uninstall_codex_skill,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "commander-agent-factory"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "check", "uninstall"))
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
    )
    parser.add_argument("--mode", choices=("copy", "symlink"), default="copy")
    args = parser.parse_args()

    if args.action == "install":
        target = install_codex_skill(args.source, args.codex_home, args.mode)
        print(json.dumps({"status": "installed", "target": str(target)}, ensure_ascii=False))
    elif args.action == "uninstall":
        uninstall_codex_skill(args.source, args.codex_home)
        print(json.dumps({"status": "not_installed"}, ensure_ascii=False))
    else:
        check = check_codex_skill(args.source, args.codex_home)
        print(json.dumps({
            "status": check.status,
            "source_hash": check.source_hash,
            "installed_hash": check.installed_hash,
            "target": str(check.target),
        }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
