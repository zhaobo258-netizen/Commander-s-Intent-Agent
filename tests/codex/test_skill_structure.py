from __future__ import annotations

import re
from pathlib import Path

from factory.serialization import strict_yaml_load


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "commander-agent-factory"


def test_skill_has_minimal_frontmatter_and_owned_routes() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = strict_yaml_load(text.split("---", 2)[1])

    assert set(frontmatter) == {"name", "description"}
    assert frontmatter["name"] == "commander-agent-factory"
    description = frontmatter["description"]
    assert description.startswith("Use when")
    assert all(word in description.lower() for word in ("build", "audit", "improve"))
    assert all(word in description.lower() for word in ("ordinary coding", "standalone skill"))
    assert len(text.splitlines()) < 500
    assert "TODO" not in text
    assert not re.search(r"/Users/|~/.codex", text)


def test_skill_references_are_complete_and_non_speculative() -> None:
    names = (
        "create-workflow.md",
        "review-workflow.md",
        "optimize-workflow.md",
        "status-and-evidence.md",
    )
    for name in names:
        path = SKILL / "references" / name
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "TODO" not in text
        assert not re.search(r"/Users/|~/.codex", text)
    assert "one highest-risk question" in (SKILL / "references/create-workflow.md").read_text(encoding="utf-8")
    assert "REVIEW is read-only" in (SKILL / "references/review-workflow.md").read_text(encoding="utf-8")
    assert "Without approval" in (SKILL / "references/optimize-workflow.md").read_text(encoding="utf-8")


def test_openai_metadata_names_skill_explicitly() -> None:
    metadata = strict_yaml_load((SKILL / "agents/openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]
    assert interface["display_name"] == "Commander Agent Factory"
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$commander-agent-factory" in interface["default_prompt"]
