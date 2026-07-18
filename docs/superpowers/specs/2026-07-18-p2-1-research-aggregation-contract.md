# P2-1 研究聚合与持仓复评接口契约

## 范围与边界

P2-1 仅增加三个只读聚合接口：`GET /research/deep-analysis`、`GET /research/exclusions` 和 `GET /research/holdings-review`。所有接口都采用服务端稳定分页，保持 `research_readiness=not_granted`、`tradable=false`、`order_created=false`，不生成研究结论、候选、交易动作或授权。

## 接口

### 深度分析

`GET /research/deep-analysis` 读取 `market.research_evidence` 与对应批次。每条记录保留 `provider`、`source`、`available_at`、`received_at`、`quality_status`、`usage_status`、版本与 Hash；`available_at` 是唯一用于展示的可得时间。可按 `stock_code`、`evidence_type` 筛选。接口不生成技术、情绪、行业、流动性或 Alpha 结论；未有来源的维度必须保持未记录。

### 排除与阻断

`GET /research/exclusions` 读取 `market.research_readiness_reviews` 中 `review_required` 或 `rejected` 的记录。每条记录保留用途范围、Requirement Profile、字段级未解决/拒绝项、Provider 验证、公司行动、缺失状态与审核时间。它是资格审核事实，不将其扩展为风险事件或交易拒绝结论。

### 持仓再评估

`GET /research/holdings-review` 读取 `trade.positions`，并仅左连接同一证券最新记录的 `market.research_readiness_reviews`。返回持仓数量、可用数量、记录更新时间及该审核记录的完整用途/Profile/时间维度；没有审核记录则标为 `not_recorded`。现有 `risk.risk_events` 没有证券级关联字段，因此风险关联状态固定为 `not_recorded`，不得按全局风险事件推断单个持仓风险。接口不推荐持有、减仓、加仓、换股或卖出。

## 验证

每项接口必须覆盖：筛选与稳定分页、来源字段、只读 SQL、权限、未授予研究/交易状态和前端契约。完成每项后执行相关后端测试、接口台账测试、前端契约测试、类型检查和生产构建，再提交中文 Git 说明。
