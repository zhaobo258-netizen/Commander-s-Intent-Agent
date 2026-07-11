#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from factory.cli.create import generate_payload, load_mapping
from factory.production import create_job
from factory.review.pipeline import run_review


def build_examples(examples_root: Path) -> None:
    examples = Path(examples_root)
    create_root = examples / "create-regional-manager"
    review_root = examples / "review-minimal-agent"
    with tempfile.TemporaryDirectory(prefix="commander-factory-examples-") as temporary:
        temp = Path(temporary)
        create_job_dir = create_job(
            temp / "create-workshop",
            "CREATE",
            "public-example",
            datetime(2026, 7, 11, tzinfo=timezone.utc),
            job_id="example-create",
        )
        payload = generate_payload(
            create_job_dir,
            create_root / "intent.yaml",
            create_root / "design.yaml",
            ROOT / "templates" / "agent",
        )
        output = create_root / "output"
        shutil.rmtree(output, ignore_errors=True)
        shutil.copytree(Path(payload["output_path"]), output)

        review_job = create_job(
            temp / "review-workshop",
            "REVIEW",
            "public-review-example",
            datetime(2026, 7, 11, tzinfo=timezone.utc),
            job_id="example-review",
        )
        written = run_review(review_job, review_root / "target")
        report_dir = review_root / "report"
        shutil.rmtree(report_dir, ignore_errors=True)
        report_dir.mkdir(parents=True)
        document = json.loads(written.json_path.read_text(encoding="utf-8"))
        document["target"]["ref"] = "examples/review-minimal-agent/target"
        for item in document["evidence"]:
            item["at"] = "2026-07-11T00:00:00+00:00"
        for finding in document["findings"]:
            for item in finding["evidence"]:
                item["at"] = "2026-07-11T00:00:00+00:00"
        (report_dir / "review.json").write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        shutil.copy2(written.markdown_path, report_dir / "review.md")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "examples")
    args = parser.parse_args()
    build_examples(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
