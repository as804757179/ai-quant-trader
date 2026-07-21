# P2-3 AI 摘要与证据展示契约

日期：2026-07-22  
状态：冻结（V1 页面复用）

## 目标

将“AI 摘要”页面接入既有只读接口，展示已记录 AI 信号与调用审计。页面不生成新的分析、不写入 AI 私有证据副本，也不改变 Research Readiness、风险、订单或任何发布锁。

## 接口复用

1. `GET /ai/signals?page=1&page_size=50`：展示已记录的信号标签、风险等级、信号时间、有效性、历史数据状态与 `recommendation_only` 边界。
2. `GET /ai/audit-summary?days=30`：展示已记录调用数、失败数、模型使用记录、最新调用/信号时间、数据状态计数和 AI 来源订单审计。
3. “AI 证据复核”继续复用 `GET /research/evidence`、证据详情和页级复核接口；不得创建 AI 私有证据副本。

## V1 字段与禁止推断

- `agent_usage[].model_used` 是已记录模型标识；调用版本未持久化时页面显示“未记录”。
- 当前 `ai.signals` 与 `market.research_evidence` 没有可追溯关联；证据引用、证据截止时间和逐信号证据资格必须显示“未记录”，不得用 `signal_time`、`latest_signal_at` 或任意当前证据替代。
- `action` 是 AI 分析标签，不是订单意图；所有摘要保持 `recommendation_only=true`、`tradable=false`、`research_eligible=false`。
- 证据缺失、历史数据为 `unknown`、`uncertified`、`synthetic`、信号过期或调用失败时，不输出可操作 BUY/SELL，不授予 Research Readiness、回测或交易资格。
- `ai_order_count` 仅为历史审计计数；页面不创建或修改订单。`AI_ORDER_ENABLED`、`ALLOW_SCHEDULED_ORDER` 与全部执行锁不因本任务改变。

## 页面状态

- 成功或空列表：展示真实计数；空列表不显示为零条可用建议。
- 接口失败或无权限：保留未知/失败状态，不显示为已接入。
- 证据关联：固定显示“未记录”，直到未来存在持久化 AI-证据血缘表和逐记录证据引用。

## 验收与回滚

- 前端契约测试验证只复用登记接口、无 `pendingState`、无证据关联推断、无订单/研究授权措辞。
- 既有 AI 只读路由契约、前端测试、类型检查和生产构建必须通过。
- 回滚仅移除 AI 摘要页的 hooks 和展示，恢复真实“待接入”状态；不删除 AI、证据或订单审计事实。
