# 交付状态模型

本项目禁止用上一层的证据代替下一层。每一层必须单独陈述：

| 状态 | 含义 | 典型证据 |
|---|---|---|
| `local_generated` | 文件已在本地生成 | 文件清单、提交哈希 |
| `local_validated` | 本地相关测试与门禁通过 | pytest、仓库验证、隐私扫描 |
| `installed` | 工具或 Skill 已装入目标环境 | 安装检查结果 |
| `published` | 指定发布渠道已生效 | 主分支/正式版本/发布页证据 |
| `real_usage_verified` | 真实用户在真实场景完成任务 | 脱敏的端到端验收记录 |

补充状态也应分开报告：

- `github_pushed`：某个分支已推送，不等于合并或发布。
- `customer_deliverable`：客户可获得并按说明使用，不等于已经真实使用。
- `candidate_ready`：优化候选完整且验证通过，不等于已替换原 Agent。

默认安全表述：本地验证通过后只声明 `local_generated=true` 和 `local_validated=true`；其余状态没有独立证据时保持 `false`。
