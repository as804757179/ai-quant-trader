# Sprint14.0 Tracking Report

日期：2026-07-15  
任务：恢复长期设计文档，并完成五个核心页面的第一阶段只读接口对接。

## 总体结论

本轮明确范围验收：**PASS**。

长期设计文档已精确恢复；五个核心页面已优先展示后端真实数据、真实发布锁和真实审计状态。没有修改数据库、迁移、Data Certification、Research Readiness 判定、Execution Gate、Risk Engine、策略逻辑或订单写入路径。

该结论不表示全部页面和全部业务接口已完成。当前仓库此前已清理旧的 backend/worker 全量测试，因此本轮只能确认新增精简契约测试、构建、标准启动、真实接口和浏览器验收通过，不能声称历史全量业务回归已执行。

## 文档恢复

- 恢复文件：`docs/superpowers/specs/2026-07-13-continuous-full-market-paper-trading-design.md`
- 来源提交：`436c4c0`
- 来源与工作区 Git blob hash：`583023d7d0df33af392dd06026c3d66f082b4f5a`
- 结论：内容完全一致，不是重新概括或重写。
- 新增接口说明：`docs/superpowers/specs/2026-07-15-core-page-readonly-api-integration.md`

## 接口改造

新增三个只读 GET：

1. `/api/v1/research/readiness`
   - 返回股票、周期、日期区间、复权口径、用途、Requirement Profile、字段证据、审核状态和阻断原因。
   - 实测 43 条审核记录，其中 ready 6、review_required 22、rejected 15。
2. `/api/v1/trade/execution-status`
   - 返回六个发布锁、交易模式、Paper 状态、人工审批要求和 AI 订单边界。
   - 六个发布锁实测全部为 false。
3. `/api/v1/ai/audit-summary`
   - 统计 AI 调用、信号、失败、AI 来源订单和模型配置状态。
   - AI 来源订单实测为 0；AI 直接下单权限为 false。
   - “越权尝试”没有独立事件计数器，真实显示 `not_recorded`，没有伪造为 0。

继续复用：`/health`、`/risk/dashboard`、`/risk/alerts`、`/portfolio/summary`、`/trade/mode`、`/trade/broker-status`、`/risk/exposure`、`/backtest/tasks`、`/ai/signals`。

## 五个页面结果

1. 运行总览：资产、盈亏、回撤、仓位、风险告警、数据库健康和执行门禁已接入；行情延迟、研究候选、资产曲线和策略版本仍明确显示待接入。
2. Research Readiness：用途级审核记录、状态分布、完整授权维度和阻断原因已接入。
3. 回测验证：修正了前端与真实 `task_id`、区间、universe、状态字段的契约漂移；不存在的 Hash、策略版本和 Engine/Reference 证据继续显示待接入。
4. 交易运行控制：模式、资金、仓位、券商探测和六个发布锁均读取真实接口；页面没有调用订单、撤单、同步或对账写接口。
5. AI 审计：实际调用数、信号数、AI 来源订单数和模型配置数已接入；AI 订单和定时任务边界继续关闭。

## 数据血缘与错误状态

- API `timestamp` 映射为数据截止时间。
- 响应头 `X-Request-ID` 映射为关联 ID。
- 后端 `source_version` 优先作为页面来源版本。
- 标准 API 响应与原生 `/health` 响应均可读取。
- 空数据、无权限、接口失败和待接入保持不同状态。
- 所有时间继续按 Asia/Shanghai 显示为 `yyyy-MM-dd HH:mm:ss`。

## 修改文件

后端：

- `backend/app/api/research.py`
- `backend/app/api/trade.py`
- `backend/app/api/ai.py`
- `backend/app/main.py`
- `backend/app/services/portfolio_service.py`
- `backend/tests/test_core_readonly_contracts.py`

前端：

- `frontend/package.json`
- `frontend/src/api/client.ts`
- `frontend/src/layout/AppShell.tsx`
- 五个 `frontend/src/pages/core/*` 核心页面
- `frontend/src/presentation/contracts.ts`
- `frontend/src/presentation/coreModels.ts`
- `frontend/src/presentation/readOnlyApi.ts`
- `frontend/src/presentation/readOnlyApiCore.mjs`
- `frontend/src/presentation/readOnlyApiCore.d.mts`
- `frontend/tests/readOnlyApiCore.test.mjs`

文档：恢复长期设计文档、新增只读接口说明和本报告。

## 验收结果

- `scripts/doctor.ps1`：PASS；仅提示当前 Python 无 chromadb，RAG 按既有设计为空检索。
- `scripts/verify_local_env.ps1`：PASS。
- 标准 `scripts/start-local.ps1 -SkipInstall`：PASS。
- 前端 TypeScript：PASS。
- 前端只读契约测试：3/3 PASS，skip/xfail/xpass=0。
- 前端生产构建：PASS；存在单个大于 500 kB 的 chunk 警告。
- 后端只读契约测试：3/3 PASS，skip/xfail/xpass=0。
- 后端 compileall：PASS。
- 新增三个路由 OpenAPI 方法：全部仅 GET。
- 五个核心页面浏览器检查：PASS。
- 浏览器控制台 error：0。
- 五页主内容横向溢出：0。
- SIMULATION 近 90 日订单数：验收前 7、验收后 7，无新增订单。
- AI 来源订单数：0。

## 安全状态

- `CERTIFIED_BACKTEST_EXECUTION_ENABLED=false`
- `CERTIFIED_SCREENER_OUTPUT_ENABLED=false`
- `TRADING_EXECUTION_ENABLED=false`
- `LIVE_TRADING_ENABLED=false`
- `AI_ORDER_ENABLED=false`
- `ALLOW_SCHEDULED_ORDER=false`

没有开放公共回测、真实选股、Paper 自动交易、Live Trading、AI Order 或 Celery 自动订单。

## 剩余问题

P0：无。

P1：

- 回测验证尚无可查询的 dataset/result hash、Engine/Reference 对账、规则和费用版本血缘。
- 运行总览尚无行情延迟、研究候选、资产曲线和策略版本接口。
- AI 越权拒绝尚无独立结构化事件计数器。
- 历史 backend/worker 全量测试套件已被清理，后续业务改造前应按当前契约重建必要测试，而不是恢复过时测试堆。

P2：

- 前端构建存在大 chunk 警告，当前不影响功能。
- chromadb 不可用，RAG 为空检索；本轮未修改该既有降级行为。

## 下一步准入

允许继续按 `2026-07-13-continuous-full-market-paper-trading-design.md` 推进“现有接口盘点与缺口补齐”的下一批只读页面；暂不允许据此开放回测、选股或交易权限。下一阶段优先补齐运行总览的行情时效/资产曲线和回测验证血缘，不应先扩展写操作。
