# P2-3 状态账本

更新日期：2026-07-22

| 项目 | 状态 | 依据 |
| --- | --- | --- |
| AI 信号标签只读展示 | `final_accepted` | AI 信号语义测试、前端契约测试、真实 HTTP GET 验收 |
| AI 调用与订单历史审计摘要 | `final_accepted` | 只读路由测试、前端契约测试、真实 HTTP GET 验收 |
| AI 证据复核复用 | `final_accepted` | P0-1 已验收；P2-3 未创建私有证据副本 |

## 不变量

- `recommendation_only=true` 不等于 Research Readiness、回测资格、策略结论或订单意图。
- 逐信号证据引用、证据截止时间和调用版本未记录时必须保持“未记录”。
- `AI_ORDER_ENABLED=false`
- `ALLOW_SCHEDULED_ORDER=false`
- 其余四个发布和交易锁也保持 `false`。
- P2-3 不解除正式 P3 replay、P4-1D 或 P5 的 blocked 状态。
