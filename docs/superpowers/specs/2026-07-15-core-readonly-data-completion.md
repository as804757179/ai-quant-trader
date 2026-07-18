# 核心页面只读数据闭环

日期：2026-07-15  
状态：已验收

## 目标

补齐运行总览、Research Readiness、回测验证、交易运行控制和 AI 审计的真实只读数据。任何字段只能来自现有配置、服务或数据库；历史未记录的血缘必须返回 `not_recorded`，不得用当前版本、Mock 或原型值补齐。

## 数据映射

| 页面 | 数据来源 | 新增/增强 GET 接口 |
|---|---|---|
| 运行总览 | `market.quotes`、认证交易日历、`trade.account_records`、Readiness、策略目录 | `/stock/market/status`、`/portfolio/equity-curve`、`/research/candidate-status`、`/strategy/runtime-status` |
| Research Readiness | `market.research_readiness_reviews` | `/research/readiness` 增加字段、Profile、Provider、缺失、企业行动和阻塞分布 |
| 回测验证 | `backtest.tasks`、`backtest.results`、Readiness | `/backtest/validation-summary` |
| 交易运行控制 | 当前安全配置、`trade.orders`、`risk.risk_rules` | `/trade/execution-status` 增加订单审计和规则 Hash |
| AI 审计 | `ai.signals`、`ai.agent_logs`、`trade.orders` | `/ai/audit-summary` 增加数据资格、模型使用和真实订单关联 |

## 真实性规则

1. `market.quotes` 没有 Provider 字段时返回 `provider_metadata_status=not_recorded`，不猜测底层 Provider。
2. 当前日期不在认证交易日历覆盖内时返回 `calendar_not_covered`，不使用 weekday fallback。
3. Screener 发布锁关闭时，候选数为 0；接口只展示 Readiness 排除和待复核记录，不输出投资候选。
4. 资产曲线只读取账户每日最后一条真实快照；没有记录时返回空列表。
5. 历史回测未保存 dataset、策略版本、引擎版本、费用 Hash 或 Reference 对账时明确标记 `not_recorded_at_run_time`。从持久化结果重建的 Hash 不冒充原始运行时 Hash。
6. AI 信号数据资格来自 `raw_agent_output.historical_data_status`；订单创建状态通过 `trade.orders.signal_id` 实际关联。

## 安全与回滚

本轮没有新增 POST/PUT/PATCH/DELETE，没有数据库迁移，没有修改交易、策略、风控或认证语义。六个发布锁保持关闭。回滚只需撤销新增 GET 字段、前端读取映射和展示，不涉及数据恢复。

## 验收

验收包括后端契约测试、前端契约测试、TypeScript、生产构建、标准启动、全部新增接口实调、核心页面浏览器检查、六个发布锁为 false、AI 来源订单为 0、验收前后订单数量不变。
