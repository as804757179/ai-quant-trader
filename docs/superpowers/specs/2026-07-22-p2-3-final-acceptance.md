# P2-3 AI 摘要与证据展示最终验收

状态：`final_accepted`

验收日期：2026-07-22

## 范围

本验收覆盖 AI 摘要页面对既有只读接口的复用：

| 接口 | 页面用途 | 结论 |
| --- | --- | --- |
| `GET /api/v1/ai/signals` | 已记录 AI 信号标签与有效性审计 | 通过 |
| `GET /api/v1/ai/audit-summary` | 调用、模型使用与 AI 来源订单历史审计 | 通过 |
| 既有研究证据与页级复核接口 | AI 证据复核页面复用 | P0-1 已验收，未创建 AI 私有证据副本 |

本轮未生成新的 AI 分析、信号、证据、任务、订单或交易授权。

## 已验证证据

- 后端定向测试命令：`backend\\.venv\\Scripts\\python.exe -m unittest tests.test_l5_ai_signal_semantics tests.test_core_readonly_contracts -v`；`6 passed`，退出码 0。
- 前端契约测试命令：`node --test tests/aiSummaryContract.test.mjs tests/appShellSafety.test.mjs`；`5 passed`，退出码 0。
- `npm run typecheck` 与 `npm run build` 均通过；构建仅报告既有 bundle 体积警告。
- 项目标准启动后的匿名只读 HTTP 验收中，`/api/v1/ai/signals?page=1&page_size=1` 与 `/api/v1/ai/audit-summary?days=30` 均返回 200；审计响应确认 `ai_order_enabled=false`、`ai_direct_order_allowed=false`。

## 固定语义与边界

- AI 信号的 `action` 是分析标签，不是订单意图；信号列表逐项保持 `recommendation_only=true`、`tradable=false`、`research_eligible=false`、`data_authorization_status=not_granted`。
- 当前 AI 信号与研究证据未持久化逐信号关联；页面固定展示“未记录”，不以信号时间、最新调用时间或任意当前证据替代证据引用或证据截止时间。
- `ai_order_count` 仅为历史审计计数，不代表本页创建订单；本页面没有写接口。
- unknown、uncertified、synthetic、过期或调用失败的记录不被包装为 BUY/SELL 交易事实，也不授予 Research Readiness、回测或交易资格。
- 本次仅发送 GET；不调用外部 Provider，不创建任务、订单、执行、资金或持仓写入。
- 六个发布和交易锁保持 `false`；正式 P3 replay、P4-1D 和 P5 blocker 不变。

## 后续

P0、P1、P2-1、P2-2 和 P2-3 的页面/API 验收已完成。后续不应重复开发已有接口；应回到开发优先级总表，对 P3/P4 已冻结的 blocked 状态和尚未完成的正式数据、Execution Reference 准入条件进行审计，而不是将 AI 摘要视为策略或交易准入。
