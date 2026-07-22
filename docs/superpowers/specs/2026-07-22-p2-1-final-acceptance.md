# P2-1 研究聚合与持仓复评最终验收

状态：`final_accepted`

验收日期：2026-07-22

## 范围

本验收覆盖既有的三个只读聚合接口及其前端页面：

| 接口 | 页面 | 结论 |
| --- | --- | --- |
| `GET /api/v1/research/deep-analysis` | 深度分析 | 通过 |
| `GET /api/v1/research/exclusions` | 排除与阻断 | 通过 |
| `GET /api/v1/research/holdings-review` | 持仓再评估 | 通过 |

本轮未新增接口、迁移、数据源、策略或调度；仅对已有实现完成实际契约、前端和运行时验收。

## 已验证证据

- 后端定向测试命令：
  `backend\\.venv\\Scripts\\python.exe -m unittest tests.test_p2_research_aggregation_contracts tests.test_research_evidence_contracts tests.test_research_evidence_pagination tests.test_research_evidence_readiness_audit -v`；`28 passed`，退出码 0。
- 前端 P2-1 契约测试：`node --test tests/researchDeepContract.test.mjs tests/researchExclusionsContract.test.mjs tests/researchHoldingsContract.test.mjs`；`3 passed`，退出码 0。
- `npm run typecheck` 和 `npm run build` 均通过；构建仅报告既有 bundle 体积警告。
- 通过项目标准启动脚本进行本地真实 HTTP 验收：
  - `/research/deep-analysis?page=1&page_size=1`：200，当前总数 27；
  - `/research/exclusions?page=1&page_size=1`：200，当前总数 37；
  - `/research/holdings-review?mode=simulation&page=1&page_size=1`：200，当前总数 2。
- 三个响应均验证为 `observed_only=true`、`research_readiness=not_granted`、`tradable=false`、`order_created=false`。

## 语义与安全边界

- 深度分析仅展示已有证据的 `available_at`、来源、批次、质量和用途状态，不生成技术、情绪、行业、流动性或 Alpha 结论。
- 排除与阻断仅展示 `review_required`、`rejected` 的字段级资格审核事实；不将其混为风险事件或交易拒绝结论。
- 持仓再评估仅关联既有持仓和同证券最新资格审核记录；证券级风险关联不可证明时保持 `not_recorded`，不生成持有、减仓、加仓、换股或卖出动作。
- 运行时验收只发送 GET；P2-1 接口未创建任务、订单、执行、资金或持仓写入，也未调用外部 Provider。
- 六个发布和交易锁均保持 `false`。本验收不授予 Research Readiness，不解除 P3 正式 replay、P4-1D 或 P5 blocker。

## 后续

P2-1 已最终验收。下一优先级候选为 P2-2 行业、板块与情绪观察的当前实现与降级语义复核；正式 PIT 行业/板块和 observed 情绪证据数据源技术债仍需保持独立 blocked。
