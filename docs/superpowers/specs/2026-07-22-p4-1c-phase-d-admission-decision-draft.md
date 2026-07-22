# P4-1C Phase D 准入与参数冻结决策草案

状态：`archived_not_frozen`

日期：2026-07-22

## 1. 审计范围与当前结论

本文件仅记录 P4-1C 的只读审计、准入判断和参数冻结建议。它不授权代码、迁移、数据库写入、Paper 订单、成交、资金、持仓、对账任务、外部 Provider 或 Git 提交。

归档结论：用户已确认在没有合规 Execution Reference 和独立对账来源前不启动正式 Paper；`P4-1D_NOT_ADMITTED` 保持不变。Paper 范围、账户、订单规则和审批规则均未冻结。

已审计的直接证据包括：

- `docs/superpowers/specs/2026-07-22-p4-1a-ledger-gap-audit.md`
- `docs/superpowers/specs/2026-07-22-p4-1b-synthetic-paper-decision.md`
- `docs/superpowers/specs/2026-07-22-p3-1d-replay-data-source-due-diligence.md`
- `backend/app/trade/execution_gate.py`
- `backend/app/trade/preflight.py`
- `backend/app/trade/execution_authorization.py`
- `backend/app/trade/ashare_rules.py`
- `backend/app/trade/base_trader.py`
- `backend/app/services/trade_service.py`
- `backend/alembic/versions/001_initial_schema.py`
- `backend/alembic/versions/025_execution_approval_intent_safety.py`
- `.env.host` 的非敏感运行开关。

当前 `.env.host` 显示 `APP_ENV=development`、`TRADE_MODE=simulation`、`TRADING_EXECUTION_ENABLED=false`、`PAPER_TRADING_ENABLED=true`、`REQUIRE_HUMAN_APPROVAL=true`；六个发布与交易锁均为 `false`。`PAPER_TRADING_ENABLED=true` 不构成 Phase D 授权：`ExecutionGate` 仍要求总执行开关、人工审批和非 `unknown`/`uncertified`/`synthetic` 的数据状态。

## 2. 六个决策域

| 决策域 | 现有依据 | 推荐方案 | 理由 | 风险与回滚 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1. Paper 运行范围 | `ExecutionGate` 区分 simulation/paper/live；`.env.host` 当前为 simulation 且总执行关闭；P4-1B 只允许 local synthetic/test-only。 | Phase D 的首个正式范围应限制为“人工发起、显式审批、单一隔离 Paper 账户、无 AI、无调度、无 live”的 Paper 运行；不得把 P4-1B 自动升级。 | 最小化攻击面，复用现有执行门禁和审批路径。 | 未冻结范围前不启用执行；若未来撤回授权，保持总执行开关和六锁为 false。 | `requires_user_confirmation` |
| 2. 账户标识、币种、初始资金、重置 | `trade.account_records` 仅按 mode 保存资产快照，`trade.positions` 也没有正式账户身份契约；P4-1B 的 `test:p4-synthetic-paper-account-v1`、CNY、100000.00 明确仅用于内存测试。 | 先冻结独立 Paper 账户 ID、所有者、币种、初始资金、隔离边界和重置审批规则；不得复用 synthetic 账户或金额。 | 正式账务需要可归属、可对账的账户边界。 | 当前不创建账户；未来错误账户可通过新账户和追加式更正事实处理，不覆盖历史事实。 | `requires_user_confirmation` |
| 3. Execution Reference | P3-1D 状态为 `NO_COMPLIANT_REPLAY_DATA_SOURCE_FOUND`；P3 许可、lineage、`available_at`、Hash、公司行动与 realtime 仍 blocked；`ExecutionGate` 拒绝 synthetic、uncertified 和 unknown。 | 不冻结来源，不允许正式 Paper 写入。只有取得覆盖自动化、本地存储、二次处理、执行用途、PIT、逐行 Hash、时效、交易日历和公司行动的合格证据后，才评估首选来源。 | Execution Reference 是订单、成交、费用和对账可审计的共同前提。 | 保持 `blocked`；不得以现有缓存、Sprint13、mock QMT 或 synthetic 替代。 | `blocked` |
| 4. 订单、成交、费用与交易规则 | `OrderRequest` 支持 MARKET/LIMIT；`ashare_rules.py` 和 `SimulationTrader` 含本地模拟费率、滑点、涨跌停和 T+1 实现；P4-1A 已确认它们不是不可变 P4 事实契约。 | 建立独立、版本化的 Phase D 规则清单后再冻结：订单类型、有效期、撤单、部分成交、成交价、费用、滑点、日历、涨跌停、停牌、最小单位与 T+1。当前不采用任何模拟默认值。 | 模拟常量不等于经确认的正式 Paper 规则，也缺少可执行数据来源。 | 未冻结时拒绝订单；未来规则更改以新规则版本和追加式事实生效，不改写既有成交。 | `requires_user_confirmation` |
| 5. 提交、审批与职责分离 | `ExecutionAuthorizationService` 要求 human principal，正式审批 SQL 明确拒绝请求人与审批人为同一主体；P4-1B 单人例外只存在于 test-only 内存账本。 | 正式 Paper 默认严格职责分离：提交人与审批人必须是不同的 active human principal；local_development 单人例外不得自动传播到 Paper。 | 复用现有 fail-closed 服务，避免 synthetic 工程例外降低正式治理标准。 | 缺少独立审批人时保持订单 blocked；如未来需要例外，必须先单独批准、建立追加式审计与环境拒绝规则。 | `requires_user_confirmation` |
| 6. 对账来源、独立性、频率与差异处置 | `TradeService.reconcile_with_broker` 可调用适配器比对持仓；P4-1A 已确认没有不可变成交/账务/对账事实模型，且当前 mock QMT 不构成独立正式对账来源。 | 至少冻结两条独立来源：追加式内部事实账本与经许可的外部执行/账户参考；冻结频率、差异阈值、阻断、人工处置、恢复和稳定验收周期。 | 没有独立对账，无法证明资金、持仓与成交正确。 | 当前不运行正式对账；差异或来源缺失必须阻断后续订单，不得静默修正。 | `blocked` |

## 3. 可冻结的安全项

以下为已有代码、配置或验收材料支持的安全边界，可继续保持，但不等于 Phase D 业务参数已冻结：

1. 六个发布和交易锁均保持 `false`。
2. `AI_ORDER_ENABLED=false`，不创建 AI、自动或调度订单。
3. 正式 P3 replay 保持 `blocked/deferred`；`P3_REPLAY_DUAL_MA_RAW_OHLCV_V1` 保持 `draft/disabled`。
4. P4-1B 仅为 `local_development` 的 synthetic/test-only 内存工程验证；不得成为 Paper Execution Reference、正式费率、正式账户或验收证据。
5. 正式 Paper 订单、成交、资金、持仓和对账写入继续未授权。

## 4. 需要用户确认的事项

在 Execution Reference 仍 blocked 的前提下，以下确认只能形成候选契约，不能启动正式 Paper：

1. 是否批准第 2 节第 1 行的最小范围，或提供不同的 Paper 范围。
2. Paper 账户的 ID、所有者、币种、初始资金、隔离与重置审批规则。
3. Phase D 订单、成交、费用、滑点、交易日历和 T+1 的权威规则来源及版本；不得仅引用当前模拟实现。
4. 是否坚持正式职责分离；若拟议 local-development 单人例外，必须单独确认其环境边界、审计字段、过期条件与禁止传播规则。
5. 对账的独立来源、频率、差异阈值、人工处置人与稳定运行验收周期。

## 5. blocked 项及解除条件

| blocked 项 | 解除条件 |
| --- | --- |
| `P3_PROVIDER_LICENSE_UNCONFIRMED` | 合格 Provider 的项目用途许可，覆盖自动化、本地存储、二次处理和执行/研究用途。 |
| `P3_INPUT_LINEAGE_UNVERIFIED`、`P3_INPUT_AVAILABLE_AT_MISSING`、`P3_INPUT_HASH_MISSING`、`P3_INPUT_CORPORATE_ACTION_UNVERIFIED` | 完整 dataset/batch/row 证据，逐行 `available_at`、可复算 Hash、交易日历和公司行动 PIT 证据。 |
| `P3_REALTIME_DATA_NOT_APPROVED` / `realtime_data_approved=false` | 独立的真实实时 Provider 许可、时效和执行准入验证。 |
| Phase D Execution Reference | 上述许可和证据形成可审计、独立于 P4-1B 的 Execution Reference 后，由用户单独确认。 |
| 正式对账 | 独立外部来源、追加式账务事实模型和差异处置契约均冻结。 |

## 6. P4-1D 准入结论

`P4-1D_NOT_ADMITTED`。

理由：第 3 与第 6 决策域为 `blocked`，且第 1、2、4、5 域尚未得到用户确认。不得创建正式 Paper 订单、成交、资金、持仓、对账迁移或运行入口。

## 7. 一次确认的最小决策清单

1. 明确 Phase D Paper 范围是否采用“人工、显式审批、单账户、无 AI、无调度、无 live”。
2. 提供并确认 Paper 账户契约。
3. 提供合格 Execution Reference 的许可与逐行证据；在此之前确认继续不启动正式 Paper。
4. 确认权威的订单、成交、费用和交易规则版本，或明确暂不冻结。
5. 确认职责分离与审批有效期/撤销规则。
6. 确认对账来源、频率、差异处置与稳定验收周期。

在所有项目确认且 Execution Reference 合格前，P4-1D 继续不准入，P5 也保持 blocked。
