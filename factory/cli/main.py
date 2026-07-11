import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from factory import __version__
from factory.cli.verify import verify_repository
from factory.production.jobs import create_job, load_job


def _encoding_safe_text(value: str, stream: TextIO) -> str:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        return value.encode(encoding, errors="backslashreplace").decode(encoding)
    except LookupError:
        return value.encode("ascii", errors="backslashreplace").decode("ascii")


def _emit(value: str, stream: TextIO) -> None:
    stream.write(_encoding_safe_text(value, stream) + "\n")


def _emit_error(error: Exception) -> None:
    try:
        _emit(f"error:{error}", sys.stderr)
    except Exception:
        try:
            sys.stderr.write("error:unprintable application error\n")
        except Exception:
            pass


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
    try:
        if args.version:
            _emit(f"commander-factory {__version__}", sys.stdout)
            return 0
        if args.command == "verify-repo":
            report = verify_repository(args.root)
            for item in (*report.checks, *report.failures):
                _emit(item, sys.stdout)
            return 0 if report.ok else 1
        if args.command == "job-init":
            job_dir = create_job(
                args.workshop,
                args.mode,
                args.name,
                datetime.now(timezone.utc),
                job_id=args.job_id,
            )
            job = load_job(job_dir)
            _emit(f"created:{job_dir}", sys.stdout)
            _emit(f"state:{job['status']}", sys.stdout)
            return 0
        if args.command == "job-status":
            job = load_job(args.job_dir)
            _emit(
                json.dumps(
                    job,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                ),
                sys.stdout,
            )
            return 0
    except Exception as exc:
        _emit_error(exc)
        return 1
    return 0
