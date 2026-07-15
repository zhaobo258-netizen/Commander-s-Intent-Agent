# 5 分钟上手

## 1. 安装与自检

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m factory.cli verify-repo .
```

普通压缩包不要求包含 Git 仓库。`--public` 只用于维护者发布公开 Git 仓库前扫描 Git 跟踪文件。

## 2. CREATE：从目标到 Agent

先创建任务目录，再把你的答案填写到意图 YAML。可以复制 `examples/create-regional-manager/intent.yaml` 和 `design.yaml` 作为起点。

```bash
python -m factory.cli job-init --workshop workshop --mode CREATE --name my-agent --job-id create-001
python -m factory.cli next-question examples/create-regional-manager/intent.yaml
python -m factory.cli validate-intent examples/create-regional-manager/intent.yaml
python -m factory.cli generate --job-dir workshop/jobs/create-001-my-agent --intent examples/create-regional-manager/intent.yaml --design examples/create-regional-manager/design.yaml --template-root templates/agent
python -m factory.cli job-status workshop/jobs/create-001-my-agent
```

如果意图不完整，继续修改 YAML 并再次运行 `next-question`。生成可安全重跑；已有一致结果不会被悄悄替换。

## 3. REVIEW：只读审查现有 Agent

目标 Agent 与车间目录不能互相包含。报告写入车间，不写进目标目录。

```bash
python -m factory.cli review path/to/agent --workshop workshop --job-id review-001 --name existing-agent
```

重点看报告里的使命、能力、资源、约束、测试和可追溯性缺口。

## 4. OPTIMIZE：只生成候选

先根据审查报告准备优化计划。没有 `--approve` 时门禁会阻止创建候选；批准后也只得到副本。

```bash
python -m factory.cli job-init --workshop workshop --mode OPTIMIZE --name existing-agent --job-id optimize-001
python -m factory.cli optimize-prepare workshop/reviews/optimize-001-existing-agent path/to/plan.yaml workshop/candidate --approve
python -m factory.cli optimize-diff path/to/agent workshop/candidate
python -m factory.cli optimize-finalize workshop/reviews/optimize-001-existing-agent
```

`optimize-finalize` 只有在候选、差异和验证凭据仍匹配时才返回可交付候选。是否替换、安装、部署或发布仍由人决定。

## 5. Codex 自然语言入口

在源码仓库中可直接引用 `skills/commander-agent-factory`。如需放入个人 Codex 技能目录：

```bash
python -m factory.cli skill-install --source skills/commander-agent-factory --codex-home "$HOME/.codex" --mode copy
python -m factory.cli skill-check --source skills/commander-agent-factory --codex-home "$HOME/.codex"
```

卸载只删除由本工厂安装且身份匹配的目标：

```bash
python -m factory.cli skill-uninstall --source skills/commander-agent-factory --codex-home "$HOME/.codex"
```

wheel 不包含仓库顶层 Skill；任何安装命令都要显式指定可信的 `--source`。

## 6. 发布前门禁

```bash
python -m pytest -q
python -m factory.cli verify-repo . --public
python scripts/verify_public.py
```

通过表示本地验证成功，不表示已经推送、合并、发布或进入真实使用。
