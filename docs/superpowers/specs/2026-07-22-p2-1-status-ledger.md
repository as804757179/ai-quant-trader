# P2-1 状态账本

更新日期：2026-07-22

| 项目 | 状态 | 依据 |
| --- | --- | --- |
| 深度分析证据聚合 | `final_accepted` | 后端契约测试、前端契约测试、真实 HTTP GET 验收 |
| 排除与阻断资格事实 | `final_accepted` | 后端契约测试、前端契约测试、真实 HTTP GET 验收 |
| 持仓与资格审核只读关联 | `final_accepted` | 后端契约测试、前端契约测试、真实 HTTP GET 验收 |

## 不变量

- `research_readiness=not_granted`
- `tradable=false`
- `order_created=false`
- `CERTIFIED_BACKTEST_EXECUTION_ENABLED=false`
- `CERTIFIED_SCREENER_OUTPUT_ENABLED=false`
- `TRADING_EXECUTION_ENABLED=false`
- `LIVE_TRADING_ENABLED=false`
- `AI_ORDER_ENABLED=false`
- `ALLOW_SCHEDULED_ORDER=false`

## 未解除事项

- P2-1 不改变正式 P3 replay、P4-1D 或 P5 的 blocked 状态。
- P2-2 的 `P2-2-PIT-INDUSTRY-DATA-SOURCE` 与 `P2-2-OBSERVED-SENTIMENT-EVIDENCE-SOURCE` 技术债继续保持；不得用 current snapshot 或派生结果伪装为正式 PIT/observed 数据。
