# P0 新接口与页面集成最终验收

状态：`final_accepted`

验收日期：2026-07-22

## 范围

本记录覆盖开发优先级总表中的 P0-1 至 P0-6。验收只覆盖既有或本轮补齐的只读查询、财报页级人工复核闭环及其前端页面；不授予 Research Readiness、回测、选股发布或交易权限。

| 任务 | 验收对象 | 结论 |
| --- | --- | --- |
| P0-1 | 财报页级候选、复核历史、追加式人工复核及 AI 证据复核页面 | 通过 |
| P0-2 | `GET /api/v1/data/certified-klines` 与 Certified Store 页面 | 通过 |
| P0-3 | `GET /api/v1/data/certification-batches`、`quality-results` 与数据批次/质量页面 | 通过 |
| P0-4 | `GET /api/v1/data/blockers` 与阻塞归因页面 | 通过 |
| P0-5 | `GET /api/v1/data/provider-validations` 与 Provider 验证页面 | 通过 |
| P0-6 | 交易日历、交易规则、费用规则、证券状态只读接口与页面 | 通过 |

## 已验证证据

- 后端定向与 L1 权限测试：37 passed，退出码 0。
- 前端 P0 契约测试：24 passed，退出码 0；`npm run typecheck`、`npm run build` 均通过。构建仅报告既有 bundle 体积警告。
- 本地项目标准启动后，11 个 P0 相关 GET 请求均返回 HTTP 200；响应中的 `tradable=false`、`order_created=false` 保持不变。
- 浏览器运行时验证了 Certified Store、数据批次、数据质量、阻塞归因、Provider 验证、交易日历、交易规则、费用规则、证券状态和 AI 证据复核页面均可渲染，未出现路由错误。P0-1 的真实鉴权追加式复核和幂等重试已在提交 `3b7b6b3` 前的专门验收中完成。
- 六个发布和交易锁均为 `false`。

## 安全边界

- P0-1 的 POST 仅使用既有追加式人工复核契约，未产生候选发布、Research Readiness、回测、订单或交易授权。
- P0-2 至 P0-6 的本次运行时验收只发送 GET；不调用外部 Provider，不修改认证数据、规则、批次或数据库事实。
- 本验收不改变 P3 正式 replay、P4 正式 Paper 或 P5 的 blocked 状态。

## 后续

下一步进入 P1 全量集成验收与归档。P1 已有实现需在 P0 依赖满足后，以实际路由、权限、页面与运行时证据统一复核；未通过验收前不得将 P1 标记为最终完成。
