# P1 新接口与页面集成最终验收

状态：`final_accepted`

验收日期：2026-07-22

## 范围

本记录覆盖开发优先级总表中的 P1-1 至 P1-4。验收范围仅限既有组合、风险、研究证据、观察行情和系统可观测性接口及其前端接入；不新增交易、调度、数据源或发布能力。

| 任务 | 验收对象 | 结论 |
| --- | --- | --- |
| P1-1 | 账户、持仓、资产曲线、风险总览/暴露/规则/熔断、风险事件和订单查询页面 | 通过 |
| P1-2 | 官方公告、新闻与 AI 证据复核页面对既有研究证据接口的复用 | 通过 |
| P1-3 | `GET /api/v1/stock/quotes`、`GET /api/v1/stock/liquidity` 及行情/流动性页面 | 通过 |
| P1-4 | `GET /api/v1/system/health`、`alerts`、`jobs`、`audit-events` 及系统可观测性页面 | 通过 |

## 已验证证据

- 后端 P1 定向测试命令：
  `backend\\.venv\\Scripts\\python.exe -m unittest tests.test_l5_portfolio_read_only tests.test_l5_durable_risk_alerts tests.test_l2_risk_rule_snapshot tests.test_research_evidence_contracts tests.test_research_evidence_pagination tests.test_research_source_usage_evidence tests.test_research_evidence_readiness_audit tests.test_realtime_quote_provenance_contracts tests.test_system_health_contracts -q`；`65 passed`，退出码 0。
- 前端 P1 契约测试命令：
  `node --test tests/apiClientContract.test.mjs tests/systemHealthContract.test.mjs tests/systemAlertsContract.test.mjs tests/systemJobsContract.test.mjs tests/systemAuditContract.test.mjs`；`25 passed`，退出码 0。
- P1-3 使用迁移 `046` 增加观察行情最新记录索引，并保持返回语义为 `observed_only`、`tradable=false`、`order_created=false`。本地真实 HTTP 验收中，`/stock/quotes?page=1&page_size=1` 为 200（约 1.05 秒），`/stock/liquidity?page=1&page_size=1` 为 200（约 1.00 秒）。
- 使用项目标准启动脚本和一个 24 小时有效、固定 auditor 只读 scope 的本地临时 service principal 完成受鉴权 HTTP 验收。18 个 P1 GET 接口均返回 HTTP 200：组合 3 个、风险 6 个、订单 1 个、研究证据 2 个、观察行情 2 个、系统可观测性 4 个。
- 临时凭据仅在当前验收进程内使用，验收后已撤销，并写入 `AUTH_CREDENTIAL_PROVISIONED` 与 `AUTH_CREDENTIAL_REVOKED` 追加式审计记录；原始 Token 未写入文件或验收记录。
- 验收前后对 `trade.orders`、`trade.order_history`、`trade.positions`、`trade.account_records`、`trade.execution_approvals`、`trade.execution_approval_events`、`trade.order_intents`、`trade.broker_outbox` 的行数和内容指纹完全一致。

## 安全边界

- 本次运行时验收只发送 GET；P1 GET 链路未调用外部 Provider、未创建任务、未调用订单或执行服务。
- 六个发布和交易锁在验收前后均为 `false`：`CERTIFIED_BACKTEST_EXECUTION_ENABLED`、`CERTIFIED_SCREENER_OUTPUT_ENABLED`、`TRADING_EXECUTION_ENABLED`、`LIVE_TRADING_ENABLED`、`AI_ORDER_ENABLED`、`ALLOW_SCHEDULED_ORDER`。
- 本验收不授予 Research Readiness，不解除正式 P3 replay、P4-1D 或 P5 的任何 blocker。

## 后续

P0 与 P1 已完成最终验收。下一实施任务按开发优先级进入 P2-1；实施前仍需以当前代码、接口、页面和状态账本复核其依赖与缺口，不得因本验收自动解除 P2-2 数据许可、P3 或 P4 的阻塞状态。
