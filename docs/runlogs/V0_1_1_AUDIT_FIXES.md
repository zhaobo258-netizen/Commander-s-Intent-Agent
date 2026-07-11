# v0.1.0 发布候选审计整改（C1 / I1 / I2 / I4）

日期：2026-07-12（Asia/Shanghai）

针对未参与实现的 AI 集中审核结论（PR #1 `Ready: No`）进行的定点修复。每项先写失败测试，再改实现；只在 `codex/commander-agent-factory-v0.1` 分支工作，不合并 main。

## C1（阻塞）：公开隐私门禁漏报已知凭证

- `factory/governance/privacy.py` 的密钥规则从 4 条扩展为具名规则集，覆盖：
  GitHub fine-grained 与 classic token、GitLab PAT、Slack token 五种前缀、
  OpenAI（含 project key）、Stripe live key、Google API key、AWS AKIA/ASIA、
  `Authorization: Bearer/Basic/Token` 头、JWT 三段结构、PEM 私钥头。
- 新增敏感路径规则 `sensitive_path`：`secrets.json`、`credentials.json`、
  `*.key`、`*.pem`、`*.p12`、`workshop/private/`、`workshop/customer-data/`。
- 扫描用副本做控制字符归一化（保留换行以维持行号），NUL 或其他控制字符
  不能再切断 token 检测。
- base64 编码的 PEM 只做确定性解码后识别私钥头（单行与折行两种形态），
  不引入泛化高熵规则；纯高熵字符串（如 sha256 值）不误报。
- 报告继续只输出路径、规则代码、行号和 SHA-256 指纹，绝不输出密钥原文。

## I1（发布前）：未批准 OPTIMIZE 污染状态机

- `optimize_prepare_payload` 现在先验证 `--approve` 与 `plan.approved_by_user`，
  验证失败立即抛 `GateBlockedError`；`_to_proposed` 与一切状态推进、
  checkpoint、候选目录创建都发生在批准之后。
- 回归测试证明：未批准调用前后 job 的 `status`、`transitions`、`approvals`
  与任务目录文件树逐字节一致，候选输出目录不存在。

## I2（发布前）：symlink 路径下 Codex Skill 安装崩溃

- `factory/production/codex.py::_paths` 对 `codex_home` 一次性 canonical 化，
  target 与 sidecar 全部从规范化 home 派生，再做 `relative_to` 边界判断。
- Codex home 的祖先是 symlink（如 macOS `/tmp -> /private/tmp`）时，
  copy / check / uninstall 全生命周期可用；home 自身或 home 之下出现
  symlink 仍被拒绝，恶意祖先 sidecar symlink 逃逸测试保持通过。

## I4（发布前）：REVIEW 大文件完整性

- `snapshot_tree` 对超过 1MB 的普通文件改为流式 sha256（256KB 分块），
  不再整体读入内存，也不再只记录路径。
- 大文件的路径、大小、hash 全部纳入 `tree_hash`；`line_count` 为 null。
- 测试证明：只改一个 >1MB 文件的内容（含同尺寸改写）后
  `verify_unchanged` 必须失败。
- `tree_hash` 算法因此纳入文件大小字段，公开示例已用
  `scripts/build_examples.py` 重新生成并保持确定性。

## 文档

- README 中英文的公开隐私扫描描述改为“检测已知密钥特征、敏感路径和
  不安全文件”，明确不宣称能识别所有秘密。
- README 中英文标明示例报告时间戳为合成时间，仅用于可复现性。

## 技术债登记（本轮不扩展修复）

- 审计中的 N1–N7 非阻断项全部登记为技术债，留待后续迭代处理，
  本轮不做范围扩展。
- 既有债项继续有效：GitHub Actions 使用官方主版本标签而非不可变提交 SHA。
- 独立复审新登记的加固项（不在 C1 要求范围内）：
  - 控制字符归一化目前覆盖 ASCII 控制字节（含 NUL）；0x80–0x9F C1 字节
    与 UTF-8 零宽字符（如 U+200B）插入 token 的形态未覆盖。
  - base64 编码 PEM 的确定性解码只支持标准字母表，base64url 变体未覆盖。
  - `_paths` 在 check/uninstall 路径上也会创建 Codex home/skills 目录的副作用；
    check 与 rename 之间理论上存在 TOCTOU 窗口。

## 验证

- 每项修复先运行失败测试，再运行对应模块测试。
- 完整测试：`458 passed`。
- `python -m factory.cli verify-repo . --public` 返回 `46` 项 `verified`，无失败。
- `python scripts/verify_public.py` 返回 `ok: true` 且 findings 为空。
- 未参与实现的 AI（独立 Claude 进程，只读工具）对 C1/I1/I2/I4 做集中复审：
  四项判定 `CLOSED`，结论 `READY-FOR-REREVIEW: yes`；其提出的范围外
  加固建议已登记为上述技术债。
- 变更仅提交到 `codex/commander-agent-factory-v0.1` 功能分支；未合并 main，
  未 force-push，未触碰任何真实客户数据。
