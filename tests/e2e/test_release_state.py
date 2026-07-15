import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_release_runlog_keeps_truth_layers_separate() -> None:
    text = (ROOT / "docs/runlogs/V0_1_0_RELEASE.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, flags=re.DOTALL)
    assert len(blocks) == 1
    status = yaml.safe_load(blocks[0])
    assert status == {
        "local_generated": True,
        "local_validated": True,
        "installed": False,
        "published": False,
        "real_usage_verified": False,
        "github_pushed": True,
        "customer_deliverable": False,
    }
    assert "GitHub 主分支" in text
    assert "真实业务" in text
