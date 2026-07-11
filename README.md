# 指挥官意图 Agent 工厂

一个把模糊目标转成可审查 Agent 工程包的开源车间。它先确认使命、成功标准、资源和边界，再进入生产；同一套命令也能只读审查现有 Agent，并在人工批准后生成优化候选。

[English](README_EN.md) · [5 分钟上手](docs/QUICKSTART.md) · [状态口径](docs/STATUS_MODEL.md) · [贡献指南](CONTRIBUTING.md)

## 三个入口

- **CREATE**：说“我要做一个 Agent”，工厂逐题补齐指挥官意图并生成工程包。
- **REVIEW**：说“审查这个 Agent”，工厂只读分析目标目录，把报告写入独立车间。
- **OPTIMIZE**：说“优化这个 Agent”，工厂先生成计划；只有显式批准后才创建候选副本，不覆盖原件。

## 快速开始

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m factory.cli --version
python -m factory.cli verify-repo .
```

直接体验完整 CREATE 流程：

```bash
python scripts/build_examples.py
```

生成结果在 `examples/create-regional-manager/output/`，只读审查报告在 `examples/review-minimal-agent/report/`。

## 创建一个 Agent

```bash
python -m factory.cli job-init --workshop workshop --mode CREATE --name my-agent --job-id create-001
python -m factory.cli next-question examples/create-regional-manager/intent.yaml
python -m factory.cli validate-intent examples/create-regional-manager/intent.yaml
python -m factory.cli generate --job-dir workshop/create-001 --intent examples/create-regional-manager/intent.yaml --design examples/create-regional-manager/design.yaml --template-root templates/agent
python -m factory.cli job-status workshop/create-001
```

`next-question` 每次只返回一个最重要的问题。信息不足时，`validate-intent` 和 `generate` 会阻止生产，而不是替用户猜答案。

## 审查与优化

```bash
python -m factory.cli review path/to/agent --workshop workshop --job-id review-001 --name existing-agent
python -m factory.cli optimize-prepare workshop/review-001 path/to/plan.yaml workshop/candidate --approve
python -m factory.cli optimize-diff path/to/agent workshop/candidate
python -m factory.cli optimize-finalize workshop/review-001
```

REVIEW 不修改目标。OPTIMIZE 的 `--approve` 只授权创建候选，不代表候选已部署或已发布；详细流程见[快速上手](docs/QUICKSTART.md)。

## 在 Codex 中使用

仓库内的 [`skills/commander-agent-factory/SKILL.md`](skills/commander-agent-factory/SKILL.md) 是自然语言入口。可选安装：

```bash
python -m factory.cli skill-install --source skills/commander-agent-factory --codex-home "$HOME/.codex" --mode copy
python -m factory.cli skill-check --source skills/commander-agent-factory --codex-home "$HOME/.codex"
python -m factory.cli skill-uninstall --source skills/commander-agent-factory --codex-home "$HOME/.codex"
```

从源码运行时必须明确传入 `--source`。当前 wheel 不内嵌仓库顶层 Skill，因此安装 Python 包不等于安装 Codex Skill。

## 安全边界

- 私有需求、客户资料和生成中的工作文件只放在被忽略的 `workshop/` 子目录，不提交到公共仓库。
- `scripts/verify_public.py` 扫描被 Git 跟踪的文件，发现密钥特征、私有路径、符号链接或不可读文件即失败。
- 任何金额、权限、外发、部署与不可逆动作都应保留人工确认。

## 当前状态

这是 `0.1.0` 本地发布候选。代码已生成和本地验证，不自动代表已经安装、GitHub 主分支已发布或真实业务使用已验证。准确口径见[状态模型](docs/STATUS_MODEL.md)。

许可证：[MIT](LICENSE)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。
