from pathlib import Path


def test_public_root_and_private_boundary() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("AGENTS.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", ".gitignore"):
        assert (root / name).is_file()
    assert "MIT License" in (root / "LICENSE").read_text(encoding="utf-8")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "skills/commander-agent-factory/SKILL.md" in agents
    assert "factory/contracts/" in agents
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "workshop/jobs/*" in ignore and "workshop/reviews/*" in ignore
