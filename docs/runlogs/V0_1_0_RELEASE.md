# v0.1.0 本地发布候选验证

日期：2026-07-11（Asia/Shanghai）

验证实现提交：`16dad5f687f91c09f94b16f886557e4531a2b6d1`

## 可运行能力

- CREATE：逐题访谈、意图门禁、可追溯 Agent 工程包生成。
- REVIEW：对现有 Agent 做只读快照和证据化审查，报告写入独立车间。
- OPTIMIZE：显式批准后创建候选副本，校验候选哈希、差异与状态证据，不覆盖原件。
- Codex：仓库内自然语言 Skill，以及显式、可核验、可卸载的可选安装。
- Open source：中英文入口、脱敏可复现示例、公共隐私扫描和只读 CI。

## 验证

- 集中审核整改后的完整测试：`417 passed in 10.86s`。
- 公共仓库验证：`python -m factory.cli verify-repo . --public` 返回 `46` 项 `verified`，无失败。
- 隐私门禁：`python scripts/verify_public.py` 返回 `ok: true` 且 findings 为空。
- 完整测试后只进行一次未参与实现的 AI 集中审核；发现的问题一次性整改。

## 集中审核整改

- 修正文档中的 CREATE 与 OPTIMIZE 任务目录，并为 OPTIMIZE 使用独立的正确模式任务。
- NUL/二进制混合内容不再跳过密钥特征扫描。
- Git 索引与工作树不一致时公共门禁失败，避免扫描内容与待提交内容不一致。

非阻断技术债：GitHub Actions 当前使用官方主版本标签而不是不可变提交 SHA，后续发布加固时再固定。

## 当前真实状态

```yaml
local_generated: true
local_validated: true
installed: false
published: false
real_usage_verified: false
github_pushed: false
customer_deliverable: false
```

`local_validated=true` 只表示本地合成示例和测试通过。当前没有声明已全局安装；没有把分支合并到 GitHub 主分支或发布正式版本；没有客户交付证据，也没有真实业务使用证据。
