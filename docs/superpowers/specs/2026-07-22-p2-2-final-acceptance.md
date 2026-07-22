# P2-2 行业、板块与情绪观察 V1 最终验收

状态：`final_accepted_degraded_semantics`

验收日期：2026-07-22

## 范围

本验收只确认 P2-2 的接口契约与 V1 降级语义，不代表正式 PIT 行业/板块数据源或 observed 情绪证据数据源已接入。

| 接口 | V1 语义 | 结论 |
| --- | --- | --- |
| `GET /api/v1/market/industry-classifications` | `legacy_internal` 的 `current_snapshot`、非 PIT | 通过 |
| `GET /api/v1/market/concept-boards` | 无正式来源时明确 `unavailable` | 通过 |
| `GET /api/v1/market/exchange-boards` | `legacy_internal` 的 `current_snapshot`、非 PIT | 通过 |
| `GET /api/v1/market/sentiment` | 无合格原始证据时明确 `unavailable`，不生成分数 | 通过 |

## 已验证证据

- 后端定向测试命令：`backend\\.venv\\Scripts\\python.exe -m unittest tests.test_p2_2_market_observation_contracts -v`；`9 passed`，退出码 0。
- 前端契约测试命令：`node --test tests/marketSectorContract.test.mjs tests/marketSentimentContract.test.mjs`；`2 passed`，退出码 0。
- 通过项目标准启动脚本的真实 HTTP GET 验收：
  - 行业当前快照：200，1 类，`data_semantics=current_snapshot`、`pit_capable=false`；
  - 概念板块：200，0 条，`availability_status=unavailable`；
  - 交易所板块当前快照：200，4 类，`data_semantics=current_snapshot`、`pit_capable=false`；
  - 市场情绪：200，0 条，`availability_status=unavailable`、`score=null`、`derived=false`、`derived_from_observed=false`、`observed_only=false`。
- 四个响应均保持 `research_readiness=not_granted`、`tradable=false`、`order_created=false`。

## 固定降级边界

- 行业和交易所板块仅可用于当前页面展示、查询和非历史性辅助筛选；不得用于回测、Walk Forward、训练、历史因子或任何 PIT 研究结论。
- 概念板块不使用行业字段替代；未来正式模型保持独立。
- 情绪分数只能是 `derived` 或 `derived_from_observed`；当前无合格原始证据时必须为 `unavailable`，不能标为 `observed` 或 `observed_only`。
- 本次只发送 GET，不接入或调用外部 Provider，不写入订单、执行、资金、持仓、策略、Profile 或数据模型。
- 六个发布和交易锁保持 `false`；正式 P3 replay、P4-1D 和 P5 blocker 不变。

## 技术债与后续

- `P2-2-PIT-INDUSTRY-DATA-SOURCE`：获得正式许可与 PIT 证据后再处理。
- `P2-2-OBSERVED-SENTIMENT-EVIDENCE-SOURCE`：获得原始证据、许可和完整 lineage 后再处理。

上述技术债不阻塞 V1 其他功能，但不得被静默降级为可用于历史研究或交易的事实。下一优先级候选为 P2-3 AI 摘要与证据展示的当前实现和安全边界复核。
