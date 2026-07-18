# Sprint14.6：新闻证据人工复核工作流设计

状态：已确认实施并验收通过  
日期：2026-07-15

## 目标与成功标准

- 为已观察新闻提供人工结论、理由、复核人标识和服务器记录时间的追加式审计工作流。
- 原始 RSS 证据、Hash、来源、Provider 时间、可得时间和 `review_required` 保持不可变。
- 页面只展示标题、链接和既有证据元数据；打开外链由用户主动执行，系统不抓取正文。
- 所有读写响应持续返回 `observed_only=true`、`research_readiness=not_granted`、`tradable=false`、`order_created=false`。

## 数据模型

新增 `market.research_news_evidence_reviews`：

| 字段 | 规则 |
| --- | --- |
| `review_id` | API 生成 UUID；每次提交新建记录。 |
| `evidence_id` | 仅关联已观察、`review_required` 的新闻证据。 |
| `reviewer_label` | 1–128 字符的自填标识，未认证。 |
| `conclusion` | `title_link_relevant`、`title_link_irrelevant`、`needs_more_evidence` 三选一。 |
| `reason` | 必填，最多 2000 字符。 |
| `reviewed_at` | 数据库生成的追加时刻。 |

查询按 `reviewed_at DESC, review_id DESC` 返回历史；新闻证据列表仅嵌入最新一条 `manual_review`。

## API 与界面

1. `GET /research/evidence?evidence_type=news&quality_status=observed` 返回新闻详情和最新人工复核。
2. `GET /research/evidence/{evidence_id}/reviews` 返回目标证据的完整人工复核历史。
3. `POST /research/evidence/{evidence_id}/reviews` 只接受 `reviewer_label`、`conclusion`、`reason`，并追加记录。
4. 新增 `/research/news-review` 页面，展示观察新闻、外链按钮、最新复核状态、复核表单和历史记录。

## Fail-closed 规则

- 目标不是 observed 新闻、没有新闻详情、使用状态不为 `review_required`，或字段为空/超长时拒绝写入。
- 不提供更新、删除、批量写入、自动复核、AI 复核、定时复核或正文抓取接口。
- `title_link_relevant` 不改变 `usage_status`，不生成事件、情绪、因子、候选、回测输入或订单。

## 验收

- 后端契约测试验证迁移链、追加式约束、写入路由和不可交易边界。
- 前端类型检查与构建验证新闻复核页面和 API 合约。
- 真实验收对现有 observed 新闻追加一条 `needs_more_evidence` 记录，确认历史可读、原始 Hash/时间/状态不变、非法目标被拒绝、六个交易锁关闭且 AI/定时订单为 0。
