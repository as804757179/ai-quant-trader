# Sprint14.6 追踪报告

生成日期：2026-07-15（Asia/Shanghai）

## 任务

完成已观察新闻证据的人工复核工作流：以追加式审计记录人工结论、理由、复核人标识和服务器时间；不抓取正文，不修改原始新闻证据，也不改变 Research Readiness、候选、回测、策略、风险或订单边界。

## 当前结论

**PASS（真实端到端验收）**。标准 `scripts\stop-local.ps1` / `scripts\start-local.ps1` 重启后已应用迁移 021；`scripts\verify_news_evidence_manual_review.ps1`、后端/前端回归和实际浏览器交互均通过。

## 已实现

- 新增 `market.research_news_evidence_reviews`，仅允许追加；没有更新、删除、批量写入、自动复核、AI 复核、定时复核或正文抓取入口。
- 仅 `news`、`quality_status=observed`、`usage_status=review_required` 且存在新闻详情 sidecar 的证据可写入复核；其他目标 fail-closed。
- 每条复核保存 UUID、未认证的自填 `reviewer_label`、三选一结论、必填理由和数据库生成的 `reviewed_at`；纠正只能继续追加。
- 增加 `GET/POST /api/v1/research/evidence/{evidence_id}/reviews`，证据列表仅嵌入最新 `manual_review`，历史按 `reviewed_at DESC, review_id DESC` 返回。
- 新增前端路由 `/research/news-review` 与“新闻人工复核”导航：仅显示标题、用户可主动打开的外链、证据元数据、复核表单和完整历史。
- 所有读写响应持续标记 `observed_only=true`、`research_readiness=not_granted`、`tradable=false`、`order_created=false`。

## 已验证证据

| 验证项 | 实际结果 |
| --- | --- |
| 标准启动与迁移 | PASS：标准启停流程完成，迁移 021 生效，前端 `http://127.0.0.1:3000` 与 API `http://127.0.0.1:8000` 可用 |
| 真实复核接口 | PASS：对 observed 新闻 `01bb225e-2e64-4157-b4be-6d226051ef76` 成功追加 `needs_more_evidence` 记录，并可读回历史 |
| 原始证据不可变 | PASS：原始 Hash、可得时间和 `review_required` 使用状态在复核后保持不变 |
| 非法目标 | PASS：rejected 新闻写入复核被 404 fail-closed 拒绝 |
| 发布与交易边界 | PASS：六个发布与交易锁关闭，AI 与定时任务订单均为 0 |
| 后端契约与核心只读回归 | PASS：后端测试 16 passed，覆盖追加式约束、路由、锁和只读边界 |
| 前端契约、类型与构建 | PASS：只读契约测试 3 passed，`tsc --noEmit` 和 Vite 生产构建通过 |
| 实际页面交互 | PASS：页面显示 observed 新闻和“由用户打开原文链接”；选择 `300750.SZ` 后表单解锁，浏览器提交的复核 `d2c91e6f-6d5a-4632-b3d7-5d209de0d887` 立即出现在历史中 |

## 审计记录说明

本次真实验收目标当前保留 3 条追加记录，均为 `needs_more_evidence`：两条脚本验收记录和一条浏览器 UI 验收记录。首次脚本执行时，PowerShell 对中文理由的字面比对发生编码误判，但接口实际已成功写入 `a1be7452-25e1-49d3-94a7-9a937d437139`；随后用稳定的 ASCII 验收理由重新执行，新增 `ff8cd4b1-f60f-4a6e-b728-e71c3ef9483c` 并全量 PASS。前端随后新增 `ui-acceptance` 记录 `d2c91e6f-6d5a-4632-b3d7-5d209de0d887`。三条记录均保留，没有删除、覆盖或修复旧审计数据。

## 边界与后续注意事项

- `reviewer_label` 是未认证的自填标识，不构成身份、审批权或授权事实。
- `title_link_relevant` 仅能表达人工认为标题/链接相关，不验证正文事实、事件、情绪或投资价值。
- 系统不访问新闻外链正文；打开外链必须由用户主动完成。
- 若未来需要登录身份、审批权限、正文级证据、来源授权或让复核影响任何研究/交易流程，必须先单独完成 ADR 与安全评审。
- 当前环境仍有既有 Chromadb 不可用提示，RAG 按既有设计降级为空检索；与本 Sprint 的人工复核 API、页面和安全边界无关。
