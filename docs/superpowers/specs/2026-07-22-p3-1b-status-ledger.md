# P3-1B 状态账本

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| 内部准入生命周期治理 | final_accepted | 迁移 043、`ee3bffe`、最终验收记录 |
| Certified K 线 lineage sidecar | final_accepted | 迁移 044、row Hash 定向与隔离数据库验证 |
| P3 replay Profile | draft_registered | 迁移 044/045；`enabled=false`，不可用于 runner |
| 只读治理状态接口 | final_accepted | `/api/v1/strategy/*` 与 `/api/v1/data/certified-lineage`；Legacy L0 PASS |
| P3 replay/realtime | blocked | 未冻结样本、策略版本、运行时间或时效；未授权数据源 |
| `P3_STRATEGY_VERSION_UNCONFIRMED` | blocked | dual_ma 主体 inactive，head 仍为 NULL，未写生命周期事实 |
| `P3_REALTIME_DATA_NOT_APPROVED` | blocked | `realtime_data_approved=false` |
| 六个发布和交易锁 | false | 最终验收读取配置验证 |

P3-1B 通过不改变上述 blocked 状态，也不授权订单、资金、持仓、P3 runner 或外部 Provider 调用。
