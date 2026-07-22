# P3-0 状态账本

更新日期：2026-07-22。

| 状态项 | 当前状态 | 证据 |
| --- | --- | --- |
| P3-0 通用基础设施 | `final_acceptance_passed` | `docs/superpowers/specs/2026-07-22-p3-0-final-acceptance.md` |
| 迁移 042 | `verified_on_isolated_timescaledb` | `28c2544`；最终验收记录的升级、回滚和重升证据 |
| P3-0 新增回归 | `none_confirmed` | 当前完整回归与基线 `f600ced` 对照 |
| strategy runtime 既存 error | `PRE_EXISTING_NOT_INTRODUCED_BY_P3_0` | `test_strategy_runtime_hash_is_stable_and_declares_data_profile`；`build_strategy_runtime_status() missing 1 required positional argument: 'items'` |
| realtime 数据准入 | `blocked` | `realtime_data_approved=false`；`P3_REALTIME_DATA_NOT_APPROVED` |
| P3 策略版本准入 | `blocked` | `P3_STRATEGY_VERSION_UNCONFIRMED` |
| 正式样本 / Profile / 运行参数 | `unconfirmed` | 不存在已批准的 P3 正式值 |
| 订单、执行、资金、持仓写入 | `zero_for_test_only_run` | `TestOnlyShadowRunner` 定向验收 |
| 六个发布和交易锁 | `all_false` | 最终验收记录的执行前后断言 |
| 外部 Provider 调用 | `not_called_by_p3_test_only_chain` | `network_request_count=0` 与 P3 定向测试 |

## 不变约束

1. P3-0 只记录影子决策，不创建订单，不产生可交易状态。
2. 本账本不批准 P3 业务、阶段 C 实时验收或任何交易开关。
3. 既存 strategy runtime error 必须保持可见，除非未来由独立范围处理。
