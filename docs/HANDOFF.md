# 交接文件（AI 全局上下文）

最后更新：2026-07-12（Asia/Shanghai）。任何新进入的 AI 先读本文件，再按需加载其他文档。

## 一句话说明

这是「指挥官意图 Agent 工厂」`v0.1.0` 本地发布候选：把模糊目标转成可审查 Agent 工程包（CREATE），只读审查现有 Agent（REVIEW），显式批准后生成不覆盖原件的优化候选（OPTIMIZE）。

## 仓库与分支结构

- 主仓库：`/Users/zhaobo/Desktop/Obsidian Vault/系统软件开发/指挥官Agent工厂`（`main` 分支，只有 `.gitignore`、`docs/superpowers` 计划文档和 worktree 挂载点）。
- 工作分支 worktree：`.worktrees/commander-agent-factory-v0.1`，分支 `codex/commander-agent-factory-v0.1`——**全部实现代码在这里，所有工作只在这个分支进行**。
- 远端：`https://github.com/zhaobo258-netizen/Commander-s-Intent-Agent.git`，草稿 PR #1 从功能分支指向 main。
- 纪律（来自用户/Codex 指令，持续有效）：**禁止合并 main、禁止 force-push、禁止触碰真实客户数据**。

## 时间线

1. M1–M3：工厂地基、CREATE+Codex Skill、REVIEW+OPTIMIZE，各里程碑 runlog 在 `docs/runlogs/`。
2. M4 开源发布候选：`docs/runlogs/V0_1_0_RELEASE.md`，417 测试通过，推送并创建草稿 PR #1。
3. 独立 AI 集中审核判定 PR #1 `Ready: No`：C1（隐私门禁漏报 12 类凭证，阻塞）、I1（未批准 OPTIMIZE 污染状态机）、I2（symlink 路径下 skill-install 崩溃）、I4（REVIEW >1MB 文件只记录路径不哈希）；N1–N7 非阻断。
4. 2026-07-12 审计整改（本轮，commit `afa89a8`）：C1/I1/I2/I4 全部修复，细节见 `docs/runlogs/V0_1_1_AUDIT_FIXES.md`。未参与实现的独立 AI 只读复审判定四项 CLOSED，`READY-FOR-REREVIEW: yes`。

## 当前真实状态

```yaml
local_generated: true
local_validated: true      # 458 测试通过 + 两个公开门禁通过
installed: false
published: false           # PR #1 仍是草稿，未合并 main
real_usage_verified: false
customer_deliverable: false
audit_c1_i1_i2_i4: closed  # 待人工/审核方重新评估 Ready
```

注意：远端功能分支历史曾被重写过一次；本地用 `-s ours` 合并（两树逐字节一致，`61f6030`）后普通推送调和，未 force-push。

## 本轮修复落点（改哪找哪）

- C1 隐私门禁：`factory/governance/privacy.py`（具名凭证规则集、`sensitive_path`、控制字符归一化、base64-PEM 确定性解码；报告永远只含路径/规则/行号/指纹）。测试 `tests/privacy/test_public_tree.py`。
- I1 批准门禁：`factory/cli/optimize.py::optimize_prepare_payload`（批准验证先于任何状态推进/checkpoint/候选目录）。测试 `tests/optimization/test_pipeline.py`。
- I2 symlink：`factory/production/codex.py::_paths`（codex_home 一次 canonical 化；macOS `/tmp` 祖先 symlink 可用，home 及以下 symlink 仍拒绝）。测试 `tests/production/test_codex_install.py`。
- I4 大文件：`factory/review/snapshot.py`（>1MB 流式 sha256，路径+大小+hash 纳入 tree_hash，`line_count` 可为 null）。tree_hash 算法变了，公开示例已用 `scripts/build_examples.py` 重新生成。测试 `tests/review/test_review_pipeline.py`。

## 环境与验证命令

- Python 3.11；虚拟环境在 `/tmp/commander-agent-factory-venv`（重启后可能消失，重建：`python3.11 -m venv /tmp/commander-agent-factory-venv && /tmp/commander-agent-factory-venv/bin/pip install -e '.[dev]'`）。
- 标准验证序列（全部应通过）：
  1. `pytest -q` → 458 passed
  2. `python -m factory.cli verify-repo . --public` → 46 项 verified
  3. `python scripts/verify_public.py` → `ok: true`
- 陷阱：公共门禁会因「Git 索引与工作树不一致」失败（设计如此）。改完文件先 `git add -A` 再跑门禁和 `tests/cli/test_public_verify.py`。

## 待办与技术债（不要顺手扩大范围）

- 下一步：请审核方对 PR #1 重新评估 Ready；合并 main 由人类决定。
- N1–N7 非阻断项：登记为技术债，后续迭代处理。
- GitHub Actions 用主版本标签而非不可变提交 SHA（发布加固时固定）。
- 复审登记的加固项（范围外）：C1 控制字节（0x80–0x9F）与零宽字符插入 token 未覆盖；base64url 变体 PEM 未覆盖；`_paths` 在 check/uninstall 时创建目录的副作用与 check→rename 的理论 TOCTOU 窗口。

## 工作纪律（AGENTS.md 的浓缩）

- REVIEW 只读；OPTIMIZE 必须显式批准且只改隔离候选，绝不覆盖原件。
- `factory/contracts/` 与 `factory/governance/` 是机器可读的真相；多步任务的私有工件放 `workshop/`（被忽略）。
- 交付方式：完成一个可运行里程碑 → 只用直接相关测试 → 登记非阻断债 → 一次完整验证 → 一次未参与实现的 AI 集中审核。
- 状态口径诚实分层（见 `docs/STATUS_MODEL.md`）：生成 ≠ 验证 ≠ 安装 ≠ 发布 ≠ 真实使用。
