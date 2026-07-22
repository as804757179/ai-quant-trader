# P4-0 Paper 订单与组合账务预检

状态：`draft_not_authorized`

日期：2026-07-22

## 1. 阶段边界

本文件仅冻结 P4-0 的设计与契约审查边界，不授权创建订单、模拟成交、资金写入、持仓写入、对账任务、外部 Broker 调用或任何发布和交易锁修改。

P4 不是 P3 的替代准入路径。正式 P3 replay 仍为 `blocked/deferred`；synthetic/test-only 仅用于工程验证，不能成为 Paper 订单、执行参考或组合账务的输入。

## 2. 已确认的可复用能力

| 能力 | 当前证据 | P4-0 结论 |
| --- | --- | --- |
| 执行门禁 | `backend/app/trade/execution_gate.py` | 已存在，必须继续 fail-closed；`synthetic`、`uncertified` 和 `unknown` 数据拒绝执行。 |
| 非写入预检 | `backend/app/trade/preflight.py` | 已存在；输入、执行门禁、熔断和风控检查可复用。 |
| 订单幂等 | `backend/app/trade/execution_authorization.py`、迁移 `025_execution_approval_intent_safety.py` | 已存在基础契约；P4 不得绕过。 |
| 模拟订单与账务 | `backend/app/trade/simulation_trader.py`、`backend/app/trade/account_ledger.py` | 仅为既有实现，不等于 P4 验收通过；需按 P4 契约重新验证。 |
| 组合只读查询 | `backend/app/services/portfolio_service.py`、`backend/app/api/portfolio.py` | 可复用为 P4 页面读取层，不增加写权限。 |
| 订单与持仓表 | `backend/alembic/versions/001_initial_schema.py`、`003_align_missing_columns.py`、`006_execution_audit.py` | 已存在，P4-0 不新增迁移或回填历史事实。 |

## 3. P4 实施前必须冻结的业务决定

以下任一项未确认时，P4 实现必须 blocked，不得使用默认值代替：

1. 阶段 D 的明确范围：仅人工 Paper 订单、是否允许模拟成交、目标账户和允许模式。
2. 可执行数据引用：必须是独立审计的 `Execution Reference`；不得使用 P3 synthetic、unknown、uncertified 或未许可数据。
3. Paper 账户契约：初始资金、币种、账户所有者、隔离边界和重置规则。
4. 订单契约：允许订单类型、有效期、撤单、拒绝、部分成交、状态机和幂等键。
5. 成交与费用契约：价格来源、滑点、佣金、印花税、过户费、涨跌停、停牌、最小交易单位和 T+1。
6. 责任与审批：人工下单主体、审批主体、职责分离例外是否允许、审批有效期和撤销规则。
7. 账务与对账：不可变账本事实、资产快照口径、盈亏归因、日终清算、差异处理和独立对账来源。
8. 验收周期：Paper 稳定运行窗口、故障恢复、对账频率和退出条件。

## 4. 强制安全契约

1. `AI_ORDER_ENABLED=false` 时，AI 来源永远返回 `AI_ORDER_DISABLED`。
2. 未通过 `ExecutionGate`、人工审批、熔断和风控时，订单、成交、资金和持仓必须保持零写入。
3. P3 synthetic/test-only、`unknown`、`uncertified`、无许可或无 Execution Reference 的数据必须返回 `UNCERTIFIED_DATASET` 或相应 blocked 原因。
4. `TRADING_EXECUTION_ENABLED`、`LIVE_TRADING_ENABLED`、`ALLOW_SCHEDULED_ORDER` 和其余发布锁在 P4-0 前后必须保持 `false`。
5. P4 Paper 与 simulation、live 必须显式隔离；不得以 simulation 或 Mock 状态伪装 Paper 验收。
6. 所有写入必须绑定 `actor_principal_id`、请求 Hash、幂等键、审批引用、数据引用和可审计时间；P4-0 不产生这些写入。

## 5. P4-0 验收标准

本轮仅以文档和只读代码证据验收：

1. 没有新增数据库迁移、模型、写接口、任务或外部 Provider 调用。
2. 已列明可复用组件及其证据路径。
3. 已列明 P4 实现前的全部业务冻结项与 fail-closed 规则。
4. 明确 P3 数据 blocked 不被降级或绕过。
5. 六个发布和交易锁保持 `false`。

## 6. 后续批次准入

只有用户单独确认阶段 D 范围及第 3 节全部业务决定后，才可进入 P4-1。

P4-1 的首批工作只能是：订单/成交/账务契约差距审查、最小追加式迁移草案、状态机测试和零执行集成测试；在任何真实 Paper 写入前仍需单独授权。

在此之前，正式 P3 replay、P3 realtime、P4 Paper 订单、资金与持仓写入均保持 blocked。
