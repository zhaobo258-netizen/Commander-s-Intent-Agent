# 私人 Agent 工作区

这个目录是 Agent 工厂的私人车间，不是公开示例库。

- `jobs/` 保存新建 Agent 的访谈、检查点、证据和候选产物。
- `reviews/` 保存对现有 Agent 的审查或优化生产单。

这两个目录中的任务默认被 Git 忽略。请不要把客户原始数据、明文密钥、Token、验证码或未脱敏的访谈记录提交到仓库。需要公开的内容应先脱敏，再由人明确确认。

工厂的完成状态必须分层记录：`local_generated`、`local_validated`、`installed`、`published`和 `real_usage_verified`。前一层成立不代表后一层已经完成；没有对应证据时必须保持未验证。
