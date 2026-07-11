import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from factory import __version__
from factory.cli.create import (
    generate_payload,
    json_text,
    next_question_payload,
    skill_check_payload,
    skill_install_payload,
    skill_uninstall_payload,
    validate_intent_payload,
)
from factory.cli.verify import verify_repository
from factory.cli.review import review_payload
from factory.cli.optimize import optimize_diff_payload, optimize_finalize_payload, optimize_prepare_payload
from factory.errors import GateBlockedError
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
    verify_parser.add_argument("--public", action="store_true")

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

    question_parser = subparsers.add_parser("next-question")
    question_parser.add_argument("intent", type=Path)

    intent_parser = subparsers.add_parser("validate-intent")
    intent_parser.add_argument("intent", type=Path)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--job-dir", required=True, type=Path)
    generate_parser.add_argument("--intent", required=True, type=Path)
    generate_parser.add_argument("--design", required=True, type=Path)
    generate_parser.add_argument("--template-root", required=True, type=Path)

    for command in ("skill-install", "skill-check", "skill-uninstall"):
        skill_parser = subparsers.add_parser(command)
        skill_parser.add_argument("--source", required=True, type=Path)
        skill_parser.add_argument("--codex-home", required=True, type=Path)
        if command == "skill-install":
            skill_parser.add_argument("--mode", choices=("copy", "symlink"), default="copy")
    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("target", type=Path)
    review_parser.add_argument("--workshop", required=True, type=Path)
    review_parser.add_argument("--job-id", required=True)
    review_parser.add_argument("--name", required=True)
    optimize_prepare = subparsers.add_parser("optimize-prepare")
    optimize_prepare.add_argument("job_dir", type=Path)
    optimize_prepare.add_argument("plan", type=Path)
    optimize_prepare.add_argument("output", type=Path)
    optimize_prepare.add_argument("--approve", action="store_true")
    optimize_diff = subparsers.add_parser("optimize-diff")
    optimize_diff.add_argument("baseline", type=Path)
    optimize_diff.add_argument("candidate", type=Path)
    optimize_finalize = subparsers.add_parser("optimize-finalize")
    optimize_finalize.add_argument("job_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.version:
            _emit(f"commander-factory {__version__}", sys.stdout)
            return 0
        if args.command == "verify-repo":
            report = verify_repository(args.root, public=args.public)
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
        if args.command == "next-question":
            _emit(json_text(next_question_payload(args.intent)), sys.stdout)
            return 0
        if args.command == "validate-intent":
            payload, return_code = validate_intent_payload(args.intent)
            _emit(json_text(payload), sys.stdout)
            return return_code
        if args.command == "generate":
            _emit(
                json_text(
                    generate_payload(
                        args.job_dir,
                        args.intent,
                        args.design,
                        args.template_root,
                    )
                ),
                sys.stdout,
            )
            return 0
        if args.command == "skill-install":
            _emit(json_text(skill_install_payload(args.source, args.codex_home, args.mode)), sys.stdout)
            return 0
        if args.command == "skill-check":
            _emit(json_text(skill_check_payload(args.source, args.codex_home)), sys.stdout)
            return 0
        if args.command == "skill-uninstall":
            _emit(json_text(skill_uninstall_payload(args.source, args.codex_home)), sys.stdout)
            return 0
        if args.command == "review":
            _emit(json_text(review_payload(args.target, args.workshop, args.job_id, args.name)), sys.stdout)
            return 0
        if args.command == "optimize-prepare":
            _emit(json_text(optimize_prepare_payload(args.job_dir, args.plan, args.output, args.approve)), sys.stdout)
            return 0
        if args.command == "optimize-diff":
            _emit(json_text(optimize_diff_payload(args.baseline, args.candidate)), sys.stdout)
            return 0
        if args.command == "optimize-finalize":
            payload = optimize_finalize_payload(args.job_dir)
            _emit(json_text(payload), sys.stdout)
            return 0 if payload["ready"] else 2
    except GateBlockedError as exc:
        _emit_error(exc)
        return 2
    except Exception as exc:
        _emit_error(exc)
        return 1
    return 0
