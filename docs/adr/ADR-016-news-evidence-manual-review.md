# ADR-016：新闻证据人工复核审计语义

日期：2026-07-15  
状态：Accepted

## 背景

ADR-015 的新闻证据只包含固定 RSS 的标题、链接与 Provider 时间，`title_alias_match` 仅是弱关联且始终为 `review_required`。现有系统能够显示观察证据，但不能记录人工对标题/链接关联所作的结论、理由、复核人和时间。

本地环境没有已认证的用户身份系统，也没有外链正文抓取授权。人工复核记录不能被误解为身份认证、正文事实验证、Research Readiness 或交易授权。

## 决策

1. 新增独立、追加式的 `market.research_news_evidence_reviews`。每次提交创建一条新记录，禁止通过 API 更新或删除历史复核；更正通过追加新的复核记录完成。
2. 仅允许对 `quality_status=observed`、`evidence_type=news`、`usage_status=review_required` 的新闻证据提交复核。rejected 新闻、公告、财报或已改变使用状态的证据 fail closed。
3. 每条复核必须记录 `reviewer_label`、`conclusion`、非空 `reason` 和数据库生成的 `reviewed_at`。`reviewer_label` 是未认证环境中的自填标识，不等同于登录身份、审批身份或授权主体。
4. 结论只允许为 `title_link_relevant`、`title_link_irrelevant`、`needs_more_evidence`，其语义仅限于标题/链接关联复核；不表示正文事实、情绪、事件、证券实体唯一识别、投资结论或数据认证。
5. 研究证据查询只显示最新一条复核作为当前人工状态，并提供完整历史只读查询。原始证据、新闻详情、Hash、时间、`usage_status`、Data Certification、Research Readiness、候选、回测、策略、风险、执行和全部发布/交易锁均不得被复核写入改变。
6. 前端新增独立新闻复核页面。页面仅展示已有观察证据并允许用户手动打开外链；系统不请求、抓取、缓存、解析或摘要外链正文。

## 后果

- 人工判断变为可追踪、可纠正的审计事实，且不会覆盖 RSS 原始观察记录。
- 最新复核便于操作，完整追加历史保留分歧与纠正过程。
- 未认证的 `reviewer_label` 不能用作权限、责任归属或生产审批依据；接入身份系统需独立设计。
- 即使结论为 `title_link_relevant`，新闻仍只属于 observed-only，不能进入任何研究准备或交易路径。

## 回滚

回滚实现会停止新的复核写入和页面入口；已写入的人工复核、原始证据和新闻详情均为审计事实，不通过删除记录伪造未发生。任何数据清理必须单独留存原因、范围和可追踪迁移。
