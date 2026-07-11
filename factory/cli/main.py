import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from factory import __version__
from factory.cli.verify import verify_repository
from factory.errors import FactoryError
from factory.production.jobs import create_job, load_job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commander-factory")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    verify_parser = subparsers.add_parser("verify-repo")
    verify_parser.add_argument("root", type=Path)

    init_parser = subparsers.add_parser("job-init")
    init_parser.add_argument("--workshop", required=True, type=Path)
    init_parser.add_argument(
        "--mode",
        required=True,
        choices=("CREATE", "REVIEW", "OPTIMIZE"),
    )
    init_parser.add_argument("--name", required=True)
    init_parser.add_argument("--job-id", required=True)

    status_parser = subparsers.add_parser("job-status")
    status_parser.add_argument("job_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"commander-factory {__version__}")
        return 0
    if args.command == "verify-repo":
        report = verify_repository(args.root)
        for item in (*report.checks, *report.failures):
            print(item)
        return 0 if report.ok else 1
    try:
        if args.command == "job-init":
            job_dir = create_job(
                args.workshop,
                args.mode,
                args.name,
                datetime.now(timezone.utc),
                job_id=args.job_id,
            )
            job = load_job(job_dir)
            print(f"created:{job_dir}")
            print(f"state:{job['status']}")
            return 0
        if args.command == "job-status":
            job = load_job(args.job_dir)
            print(
                json.dumps(
                    job,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
            )
            return 0
    except (FactoryError, OSError, TypeError, ValueError) as exc:
        print(f"error:{exc}", file=sys.stderr)
        return 1
    return 0
