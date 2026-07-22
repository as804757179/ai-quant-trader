# P2-2 状态账本

更新日期：2026-07-22

| 项目 | 状态 | 依据 |
| --- | --- | --- |
| 行业当前快照 | `accepted_current_snapshot_only` | 后端契约测试、前端契约测试、真实 HTTP GET 验收 |
| 概念板块 | `accepted_unavailable` | 后端契约测试、前端契约测试、真实 HTTP GET 验收 |
| 交易所板块当前快照 | `accepted_current_snapshot_only` | 后端契约测试、前端契约测试、真实 HTTP GET 验收 |
| 市场情绪 | `accepted_unavailable` | 后端契约测试、前端契约测试、真实 HTTP GET 验收 |

## 不变量

- `P2-2-PIT-INDUSTRY-DATA-SOURCE`：`blocked`
- `P2-2-OBSERVED-SENTIMENT-EVIDENCE-SOURCE`：`blocked`
- `research_readiness=not_granted`
- `tradable=false`
- `order_created=false`
- 六个发布和交易锁全部为 `false`

## 禁止推导

- `current_snapshot` 不得回填为 PIT 历史事实。
- `unavailable` 不得回退为 AI 补全、推测分数或虚假 observed 证据。
- P2-2 不解除正式 P3 replay、P4-1D 或 P5 的 blocked 状态。
