# ADR-017：多维研究证据资格预审与拒绝路径

日期：2026-07-15
状态：Accepted

## 背景

Sprint14.3 至 Sprint14.6 已为公告、财报和新闻建立只读观察证据：固定来源、原文或 RSS 条目 Hash、可得时间、失败审计，以及新闻标题/链接的追加式人工复核。它们均保持 `usage_status=review_required`，没有获得 Research Readiness、候选、回测或交易资格。

现有 `ResearchDataRequirementProfile` 和 `ResearchReadinessService` 专用于 K 线数据，其授权键包含股票、日期区间、复权、用途和字段 Profile。将该模型直接套用于文档证据会错误传播 K 线 `ready` 语义，或把已观察文档误解为可研究输入。

## 决策

1. 新增独立的多维证据资格预审 Profile 和只读预审服务；不修改 K 线 `ResearchDataRequirementProfile`、`ResearchReadinessService` 或 `market.research_readiness_reviews`。
2. 每次预审必须显式声明 `research_use_scope`、`requirement_profile` 和完整 `required_fields`。授权键固定为：

   `stock_code + evidence_type + evidence_id + raw_hash + available_at + research_use_scope + requirement_profile + policy_version`

   任一字段缺失、改变、Profile 与用途不匹配或字段集合不匹配时 fail closed。
3. 首期仅定义以下 Profile：

   - `ANNOUNCEMENT_EVENT_RESEARCH_V1` / `announcement_event_research`
   - `FINANCIAL_REPORT_FUNDAMENTAL_RESEARCH_V1` / `financial_report_research`
   - `NEWS_EVENT_RESEARCH_V1` / `news_event_research`

4. 首期预审只能返回 `review_required` 或 `rejected`，没有 `ready` 分支。所有结果无论其他字段状态如何，都追加 `READINESS_GRANT_NOT_IMPLEMENTED`；这表示预审不是 Research Readiness 授权。
5. 预审直接读取现有证据、财报详情、新闻详情和最新新闻人工复核，不新增表、不写入审批快照、不修改原始证据或人工复核。结果以 `policy_version` 与规范化输入 SHA-256 指纹复现。
6. 新闻的 RSS 条目 Hash 不得表示正文 Hash；标题/链接人工复核也不验证正文事实或身份。`title_link_irrelevant` 必须产生 `NEWS_ASSOCIATION_REJECTED` 并返回 `rejected`，而非被后续字段或人工记录升级。
7. 所有预审 API 响应继续携带 `observed_only=true`、`research_readiness=not_granted`、`tradable=false` 和 `order_created=false`。预审不得调用候选、回测、策略、风险、Execution Gate、AI 或订单路径，也不得改变六个发布与交易安全锁。

## 后果

- 当前真实公告、财报和新闻会得到可解释的阻塞项，但不会得到研究或交易授权。
- API 调用方必须明确说明所需用途和字段，不能利用默认值扩大适用范围。
- 不建立持久化预审快照可避免第二套授权状态源；若未来需要签署、身份、审批或历史授权，必须单独设计追加式存储和新的 ADR。
- Profile、字段或阻塞规则发生实质变化时必须升级 `policy_version`，不能改写旧结果的语义。

## 回滚

本决策首期没有迁移和数据写入。回滚仅移除独立预审模块、只读路由、测试和验收脚本；既有证据、人工复核、K 线 Research Readiness 与交易安全锁均不受影响。
