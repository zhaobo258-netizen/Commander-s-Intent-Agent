from __future__ import annotations

import shutil
from pathlib import Path

from factory.contracts import validate_document
from factory.governance.privacy import scan_public_tree
from factory.serialization import strict_json_loads, strict_yaml_load
from scripts.build_examples import build_examples


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


def _tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_create_example_is_contract_valid_and_factory_generated() -> None:
    root = EXAMPLES / "create-regional-manager"
    intent = strict_yaml_load((root / "intent.yaml").read_text(encoding="utf-8"))
    assert validate_document("commander-intent", intent) == ()
    manifest = strict_json_loads((root / "output/factory-manifest.json").read_text(encoding="utf-8"))
    assert validate_document("factory-manifest", manifest) == ()
    blueprint = strict_yaml_load((root / "output/AGENT_SPEC.yaml").read_text(encoding="utf-8"))
    assert validate_document("agent-blueprint", blueprint) == ()
    assert {case["type"] for case in blueprint["evaluation"]["cases"]} == {"Golden", "Failure", "Boundary", "Unknown"}


def test_examples_are_public_safe_and_deterministic(tmp_path: Path) -> None:
    paths = [path.relative_to(EXAMPLES).as_posix() for path in EXAMPLES.rglob("*") if path.is_file()]
    assert scan_public_tree(EXAMPLES, paths).ok is True
    copied = tmp_path / "examples"
    shutil.copytree(EXAMPLES, copied)
    shutil.rmtree(copied / "create-regional-manager" / "output")
    shutil.rmtree(copied / "review-minimal-agent" / "report")
    build_examples(copied)
    assert _tree(copied / "create-regional-manager" / "output") == _tree(EXAMPLES / "create-regional-manager" / "output")
    assert _tree(copied / "review-minimal-agent" / "report") == _tree(EXAMPLES / "review-minimal-agent" / "report")
