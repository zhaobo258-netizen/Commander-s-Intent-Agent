import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = (
    ROOT / "README.md",
    ROOT / "README_EN.md",
    ROOT / "docs" / "QUICKSTART.md",
    ROOT / "docs" / "QUICKSTART_EN.md",
    ROOT / "docs" / "STATUS_MODEL.md",
)


def test_relative_markdown_links_resolve() -> None:
    link_pattern = re.compile(r"\[[^]]+\]\(([^)]+)\)")
    for document in DOCS:
        for target in link_pattern.findall(document.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            assert (document.parent / target).resolve().exists(), f"broken link in {document}: {target}"


def test_documented_factory_commands_exist() -> None:
    supported = {
        "generate",
        "job-init",
        "job-status",
        "next-question",
        "optimize-diff",
        "optimize-finalize",
        "optimize-prepare",
        "review",
        "skill-check",
        "skill-install",
        "skill-uninstall",
        "validate-intent",
        "verify-repo",
    }
    command_pattern = re.compile(r"python -m factory\.cli ([a-z][a-z-]+)")
    documented = set()
    for document in DOCS:
        documented.update(command_pattern.findall(document.read_text(encoding="utf-8")))
    assert documented <= supported
    assert {"generate", "review", "optimize-prepare", "verify-repo"} <= documented
