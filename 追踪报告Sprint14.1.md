# Sprint14.1 Tracking Report

日期：2026-07-15  
任务：补全核心页面现有只读接口数据  
结论：**PASS（仅代表本 Sprint 的只读数据闭环通过，不代表回测、选股或交易能力已发布）**

## 1. 目标与范围

本轮只补全运行总览、Research Readiness、回测验证、交易运行控制、AI 审计和研究候选所需的现有数据。所有新增能力均为 GET 只读查询；没有新增交易动作、策略、AI Agent、数据库表或迁移。

成功标准：

- 页面字段来自现有配置、服务或数据库。
- 历史没有记录的字段明确返回 `not_recorded` 或 `blocked`。
- 不用 Mock、Synthetic、原型值或当前版本冒充历史血缘。
- 六个发布与交易开关保持关闭。
- 查询和验收不创建订单，不改变订单总数。

## 2. 新增或增强的只读接口

| 接口 | 真实来源 | 结果 |
|---|---|---|
| `GET /api/v1/stock/market/status` | `market.quotes`、股票主数据、认证交易日历 | 可返回行情覆盖、时效、日历覆盖和 Provider 元数据状态 |
| `GET /api/v1/portfolio/equity-curve` | `trade.account_records` | 返回每日最后一条账户资产快照，当前 2 个点 |
| `GET /api/v1/research/readiness` | `market.research_readiness_reviews` | 返回 43 条审核记录及字段、Profile、阻断维度 |
| `GET /api/v1/research/candidate-status` | Readiness 审核记录、Screener 发布锁 | 当前候选 0，状态 `release_locked`，不运行 Screener |
| `GET /api/v1/strategy/runtime-status` | 现有策略目录和字段声明 | 4 个策略配置，返回目录版本和稳定 Hash |
| `GET /api/v1/backtest/validation-summary` | `backtest.tasks`、`backtest.results`、Readiness | 历史结果血缘不足，明确返回 `blocked` |
| `GET /api/v1/trade/execution-status` | 当前安全配置、`trade.orders`、`risk.risk_rules` | 返回六个锁、订单来源审计和风险规则 Hash |
| `GET /api/v1/ai/audit-summary` | `ai.signals`、`ai.agent_logs`、`trade.orders` | AI 信号、数据资格、模型使用和订单关联审计 |

同时修复运行总览风险事件字段映射：后端真实字段 `ts`、`type` 现在分别显示为北京时间和 `risk_alert`，不再错误显示“待接入”。

## 3. 修改文件

后端：

- `backend/app/api/ai.py`
- `backend/app/api/backtest.py`
- `backend/app/api/portfolio.py`
- `backend/app/api/research.py`
- `backend/app/api/stock.py`
- `backend/app/api/strategy.py`
- `backend/app/api/trade.py`
- `backend/app/backtest/service.py`
- `backend/app/risk/monitor.py`
- `backend/app/schemas/ai.py`
- `backend/app/services/ai_service.py`
- `backend/app/services/portfolio_service.py`
- `backend/app/strategy/config_store.py`

前端：

- `frontend/src/pages/core/OverviewPage.tsx`
- `frontend/src/pages/core/ReadinessPage.tsx`
- `frontend/src/pages/core/BacktestValidationPage.tsx`
- `frontend/src/pages/core/TradeControlPage.tsx`
- `frontend/src/pages/core/AiAuditPage.tsx`
- `frontend/src/pages/research/ResearchCandidatesPage.tsx`
- `frontend/src/presentation/coreModels.ts`
- `frontend/src/styles/global.css`

验证与文档：

- `backend/tests/test_core_readonly_data_contracts.py`
- `scripts/verify_core_readonly_data.ps1`
- `docs/superpowers/specs/2026-07-15-core-readonly-data-completion.md`
- `追踪报告Sprint14.1.md`

## 4. 数据真实性与安全结果

- 行情状态：`empty`。当前没有行情记录；Provider 和自动 fallback 元数据没有被当前表记录，接口明确标记 `not_recorded`。
- 交易日历：当前日期不在认证日历覆盖内，返回 `calendar_not_covered`；没有 weekday fallback。
- Research Readiness：43 条；`ready=6`、`review_required=22`、`rejected=15`。
- 研究候选：`candidate_count=0`、`candidate_status=release_locked`、`tradable=false`、`order_created=false`。
- 回测：最新历史任务因未来函数检查、dataset Hash、版本、费用 Hash、Reference 对账和完整授权键未记录而 `blocked`，没有冒充可信回测。
- 订单：查询前后均为 7 条；AI 来源 0，定时任务来源 0。
- 历史订单审计：7 条旧订单缺少 caller/approval 的可靠记录，保持 `unknown/unapproved`，未被补写或美化。
- AI：当前信号 0，AI 来源订单 0，`AI_ORDER_ENABLED=false`。
- 六个发布锁：全部为 false。

## 5. 测试与验收

统一命令：

`powershell -ExecutionPolicy Bypass -File scripts/verify_core_readonly_data.ps1`

实际结果：

- 标准启动脚本：PASS。
- Backend 只读契约测试：6 passed，0 failed，0 skipped。
- Frontend 只读契约测试：3 passed，0 failed，0 skipped。
- TypeScript：PASS。
- Frontend production build：PASS。
- 六个新增/增强核心页面及研究候选页面浏览器实测：PASS。
- 浏览器控制台 error：0。
- 风险事件真实时间与类型复验：PASS。
- 核心只读数据统一验收：PASS。

浏览器检查页面：

- `/`
- `/readiness`
- `/backtest-validation`
- `/trade/control`
- `/ai-audit`
- `/research/candidates`

## 6. 未补写的历史字段

以下字段没有可靠历史来源，因此本轮没有伪造：

- 历史回测运行时 `dataset_hash`、策略版本、引擎版本、费用 Hash、Engine/Reference 对账。
- 行情记录的精确 Provider、端点和 fallback 轨迹。
- AI 越权尝试的独立事件计数器。
- 7 条既有订单缺失的 caller 和审批信息。

## 7. 剩余问题

### P0

无本轮新增 P0。

### P1

1. 当前 `market.quotes` 为空，且缺少 Provider/fallback 血缘字段；实时市场监控仍不能视为真实可用。
2. 当前认证交易日历没有覆盖 2026-07-15；需要在后续真实数据阶段更新并认证，禁止 weekday 推测。
3. 历史回测任务缺少完整运行时血缘和 Reference 对账，继续阻止可信发布。
4. 既有 7 条订单缺少可靠 caller/approval 审计，不能反向补造。

### P2

1. AI 越权尝试尚无独立持久化事件计数，当前正确显示 `not_recorded`。
2. 资产曲线只有 2 个真实快照点，展示正确但样本不足。
3. 浏览器存在 React Router v7 future flag 提示；不影响本轮功能。
4. Vite 主包超过 500 kB，构建仅告警；后续可在不改变页面语义时做按路由拆包。

## 8. 变更边界与回滚

- 未新增或修改数据库迁移。
- 未修改 Data Certification、Research Readiness 判定、回测口径、策略逻辑、Risk Engine 或 Execution Gate 语义。
- 未改变环境变量和发布锁。
- 未创建订单、候选或投资结论。
- 未引入第三方依赖。
- 回滚仅需撤销本轮 GET 查询、前端映射、验收脚本和文档；不涉及数据恢复。

## 9. 下一步准入结论

可以进入下一项“真实行情与多维研究数据接入设计”，但不得直接开放自动选股、公共回测或模拟自动交易。下一阶段应优先补齐行情 Provider 血缘、认证交易日历覆盖、新闻/公告/财务数据时点语义和统一研究事件模型。
