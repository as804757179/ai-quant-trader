# P1 状态账本

更新日期：2026-07-22

## 任务状态

| 任务 | 状态 | 依据 |
| --- | --- | --- |
| P1-1 组合、风险与订单只读页面复用 | `final_accepted` | 后端定向测试、前端契约测试、受鉴权 HTTP 验收 |
| P1-2 公告、新闻与 AI 证据页面复用 | `final_accepted` | 研究证据定向测试、受鉴权 HTTP 验收；P0-1 复核闭环已验收 |
| P1-3 观察行情与流动性 | `final_accepted` | `66cca02`、迁移 `046`、行情 provenance 定向测试、受鉴权 HTTP 验收 |
| P1-4 系统运行可观测性 | `final_accepted` | 系统健康定向测试、前端系统契约测试、受鉴权 HTTP 验收 |

## 不变量

- `CERTIFIED_BACKTEST_EXECUTION_ENABLED=false`
- `CERTIFIED_SCREENER_OUTPUT_ENABLED=false`
- `TRADING_EXECUTION_ENABLED=false`
- `LIVE_TRADING_ENABLED=false`
- `AI_ORDER_ENABLED=false`
- `ALLOW_SCHEDULED_ORDER=false`
- P1 不授予 Research Readiness，不解除 P3 正式 replay、P4-1D 正式 Paper 或 P5 的数据、运行和交易准入阻塞。
- 观察行情保持 `observed_only`；不得由 P1 页面或接口推导交易资格、订单创建或执行授权。

## 下一准入

P2-1 研究聚合与持仓复评是当前开发优先级总表中唯一的下一实施候选。开始前须只读核查现有实现、接口消费方和 P0/P1 验收依赖；P2-2 的正式 PIT 行业/板块与 observed 情绪数据源技术债继续独立 blocked，不得作为 P2-1 的静默输入或 fallback。
