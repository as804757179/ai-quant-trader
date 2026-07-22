# P3-1C 状态账本

更新日期：2026-07-22

| 状态项 | 当前状态 | 证据或解除条件 |
| --- | --- | --- |
| P3-1C 决策材料 | `archived_not_frozen` | `2026-07-22-p3-1c-replay-data-admission-decision.md` |
| P3-1D 数据源尽调 | `NO_COMPLIANT_REPLAY_DATA_SOURCE_FOUND` | `2026-07-22-p3-1d-replay-data-source-due-diligence.md`；无新官方许可或逐行 PIT/血缘证据时不重复搜索 |
| Sprint13 十股名单 | `candidate_only` | 不继承 Sprint13 数据许可或工程验证语义；尚未冻结 |
| `p3-replay-sprint13-10-candidate-v1` | `candidate_only` | `sample_hash=f5c702b8c04ecc9346cbc0786a5e87ebe962a5162c4f0c21238ff979fa274845` |
| P3 replay Profile | `draft_disabled` | `P3_REPLAY_DUAL_MA_RAW_OHLCV_V1`；`enabled=false`；runner 不可用 |
| P3 replay 数据集 | `blocked` | 无合格许可、逐行 lineage、`available_at`、`row_hash`、公司行动 PIT 证据和完整覆盖 |
| `P3_PROVIDER_LICENSE_UNCONFIRMED` | `blocked` | 提供覆盖自动化、存储、二次处理及 replay 的 Provider 许可 |
| `P3_INPUT_LINEAGE_UNVERIFIED` | `blocked` | 提供逐行 verified lineage 与原始 evidence |
| `P3_INPUT_AVAILABLE_AT_MISSING` | `blocked` | 提供逐行可审计、非推测的 `available_at` |
| `P3_INPUT_HASH_MISSING` | `blocked` | 提供 dataset、batch、row、input snapshot 的可复算 Hash |
| `P3_INPUT_CORPORATE_ACTION_UNVERIFIED` | `blocked` | 提供公司行动或无事件的 PIT 证据 |
| 正式 P3 replay | `blocked_deferred` | 无合规数据源；Sprint13 不得用于正式 replay |
| P3 replay/realtime | `not_started` | 不得因候选参数或策略状态改变而启动 |
| `P3_REALTIME_DATA_NOT_APPROVED` | `blocked` | `realtime_data_approved=false`；需独立实时许可与准入 |
| 六个发布和交易锁 | `all_false` | 保持安全默认值，不在本轮变更范围内 |

## 不变约束

1. `dual_ma v5` 保持现状；本账本不构成策略、样本、Profile 或数据集的新增授权。
2. Profile 必须保持 `draft/disabled`，不得被 runner 使用。
3. 不得使用 Sprint13 数据进行正式 P3 replay。
4. synthetic/test-only 仅用于工程验证，不得描述为真实历史 replay、模拟实盘或阶段 C 通过。
5. 本轮不产生订单、执行、资金或持仓写入，不调用外部 Provider。
