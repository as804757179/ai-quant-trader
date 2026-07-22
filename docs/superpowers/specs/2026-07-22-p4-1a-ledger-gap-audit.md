# P4-1A Paper 订单与账务事实链路差距审计

状态：`draft_not_authorized`

日期：2026-07-22

## 1. 审计边界

本文件只记录 P4-1A 的只读代码审计、最小追加式迁移草案和后续测试清单。它不授权创建 Paper 订单、模拟成交、资金写入、持仓写入、对账任务、外部 Broker 调用或任何发布与交易锁变更。

P3 正式 replay 仍为 `blocked/deferred`。synthetic/test-only 输入不得作为 P4 订单、成交、账务或 Execution Reference 的输入。

## 2. 已确认事实

| 范围 | 证据 | 已确认事实 |
| --- | --- | --- |
| 订单汇总 | `backend/alembic/versions/001_initial_schema.py` | `trade.orders` 保存状态、累计成交数量、均价和佣金；`(mode, idempotency_key)` 已唯一。 |
| 订单历史 | `backend/alembic/versions/001_initial_schema.py`、`backend/app/trade/simulation_trader.py`、`backend/app/trade/order_sync.py` | `trade.order_history` 记录状态转换，但当前契约未将其定义为 P4 的不可变业务事实账本。 |
| 持仓与账户 | `backend/alembic/versions/001_initial_schema.py`、`backend/app/trade/account_ledger.py`、`backend/app/trade/simulation_trader.py` | `trade.positions` 和 `trade.account_records` 是可更新的持仓/资产快照；代码存在更新和删除路径。 |
| 审批与意图 | `backend/alembic/versions/025_execution_approval_intent_safety.py`、`backend/app/trade/execution_authorization.py` | 已有审批、审批事件、订单意图与 outbox 基础；审批事件具有数据库 append-only 限制，订单意图具有请求主体与幂等键。 |
| 执行门禁 | `backend/app/trade/execution_gate.py`、`backend/app/trade/preflight.py` | 现有门禁 fail-closed；`unknown`、`uncertified` 和 `synthetic` 数据不得通过执行门禁。 |

## 3. P4 差距结论

1. `trade.orders` 的累计成交字段是可变汇总，不能单独作为可追放、可重算的逐笔成交事实。
2. `trade.positions` 与 `trade.account_records` 是可变快照，不能单独作为账务事实来源或重放依据。
3. `trade.order_history` 有状态记录，但当前没有 P4 所需的统一事件类型、严格顺序、因果引用、责任主体和不可变性契约。
4. 现有 `trade.execution_approval_events` 可以复用为审批审计证据；它不替代订单、成交、资金和持仓的业务事实链。
5. `trade.broker_outbox` 可复用为已发送请求审计，但尚未形成 P4 所需的外部回执、成交事实与独立对账结果的完整契约。
6. 任何未来 P4 写入仍必须经过现有 `ExecutionGate`、`OrderPreflight`、人工审批和独立 Execution Reference；本审计不放宽该边界。

## 4. 后续最小追加式迁移草案（未授权实施）

仅在阶段 D 业务参数冻结并单独授权后，评估以下新增对象；不得修改或回填历史事实：

| 候选对象 | 最小职责 | 关键契约 |
| --- | --- | --- |
| `trade.order_events` | 记录一次订单状态转换的事实 | 追加式；唯一事件键；`order_id`、前后状态、actor、发生时间、原因、请求 Hash、幂等键、审批与数据引用均可审计。 |
| `trade.fill_facts` | 记录不可变逐笔成交事实 | 追加式；`order_id`、外部成交引用、成交时间、数量、价格、费用规则版本、Execution Reference、来源与 Hash；重复外部成交引用必须拒绝。 |
| `trade.ledger_entries` | 记录资金、持仓和费用的双向账务分录 | 追加式；关联订单/成交事实；借贷平衡、币种、账户边界、时间和规则版本可验证。 |
| `trade.reconciliation_runs`、`trade.reconciliation_items` | 记录独立对账过程与差异 | 追加式；对账范围、输入来源、规则版本、结果 Hash、差异和人工处置引用可审计。 |

兼容原则：现有订单、持仓、账户和历史记录保留原值并标记为 legacy/unverified（如无法证明）；不得通过推测、当前时间或批量回填把它们升级为 P4 账务事实。

## 5. 实施前必须由用户冻结的决策

以下任一项未确认，P4 写入实现继续 blocked：

1. Phase D 的明确范围及允许模式（仅人工 Paper 订单、是否允许模拟成交）。
2. Paper 账户、币种、所有者、初始资金、隔离和重置规则。
3. 可执行数据的独立 Execution Reference、许可和时效口径。
4. 订单类型、状态机、有效期、撤单、部分成交及幂等语义。
5. 成交价格、滑点、佣金、税费、交易日历、涨跌停、停牌、最小单位和 T+1 规则版本。
6. 人工提交与审批主体、审批有效期、撤销规则和职责分离（含 local-development 例外是否可用于 Paper）。
7. 对账来源、频率、差异阈值、处置流程和稳定运行验收周期。

## 6. 后续验收清单（未执行）

1. 订单状态机、订单事件、成交事实和账务分录均追加式，非法更新或删除被拒绝。
2. 相同请求重试不重复创建订单、成交、分录或对账事实；同一幂等键不同请求 Hash fail-closed。
3. 每笔成交均可由不可变输入、费用规则和 Execution Reference 重算订单累计值、持仓和账户快照。
4. 对账差异不能静默修正；必须保留差异事实和人工处置审计。
5. 缺失审批、Execution Reference、许可、时效、交易规则或责任主体时，订单、成交、资金和持仓均零写入。
6. 六个发布和交易锁在所有失败与成功测试前后均保持 `false`；不创建 AI、调度或外部 Broker 自动入口。

## 7. 当前状态

P4-1A 仅完成差距审计材料，尚未开始 P4 业务实现。正式 P3 replay、P3 realtime、P4 Paper 订单、成交、资金、持仓和对账写入均保持 blocked。
