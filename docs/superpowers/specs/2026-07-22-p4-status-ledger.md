# P4 状态账本

状态：`archived_not_frozen`

日期：2026-07-22

| 项目 | 当前状态 | 证据 | 解除条件 |
| --- | --- | --- |
| P4-1A 账务事实链路差距审计 | `completed` | `2026-07-22-p4-1a-ledger-gap-audit.md` | 仅为后续设计输入，不代表 Paper 准入。 |
| P4-1B synthetic/test-only 工程验证 | `completed_test_only` | `2026-07-22-p4-1b-synthetic-paper-decision.md`、提交 `44e0435` | 仅限 local synthetic/test-only；不得升级为正式 Paper。 |
| P4-1C Phase D 准入决策 | `archived_not_frozen` | `2026-07-22-p4-1c-phase-d-admission-decision-draft.md` | 用户已确认继续保持安全边界，不冻结业务参数。 |
| P4-1D 正式 Paper 实施 | `P4-1D_NOT_ADMITTED` | P4-1C 第 6 节 | 同时满足合规 Execution Reference、独立对账来源，以及 Paper 范围、账户、订单规则、审批和验收周期的明确冻结。 |
| 免费观测模拟轨道 | `not_phase_d` | `ADR-024-free-observation-simulation-mode.md` | 不构成 Execution Reference、正式 Paper 或 P5 准入。 |
| 正式 P3 replay | `blocked/deferred` | `2026-07-22-p3-1d-replay-data-source-due-diligence.md` | 合格许可、逐行 PIT/lineage/Hash、交易日历和公司行动证据。 |
| 正式 P4 写入与 P5 | `blocked` | P4-1C 第 5 至 7 节 | P4-1D 获准、实施并完成稳定 Paper 账务闭环。 |

## 不变安全边界

- `CERTIFIED_BACKTEST_EXECUTION_ENABLED=false`
- `CERTIFIED_SCREENER_OUTPUT_ENABLED=false`
- `TRADING_EXECUTION_ENABLED=false`
- `LIVE_TRADING_ENABLED=false`
- `AI_ORDER_ENABLED=false`
- `ALLOW_SCHEDULED_ORDER=false`
- `P3_REPLAY_DUAL_MA_RAW_OHLCV_V1` 保持 `draft/disabled`。
- `P3_REALTIME_DATA_NOT_APPROVED` 与 `realtime_data_approved=false` 保持不变。

本账本不授予 Paper、replay、realtime、P5 或任何资金、订单、成交、持仓与对账写入权限。
