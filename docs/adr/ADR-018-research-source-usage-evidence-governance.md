# ADR-018：研究来源条款证据与许可预审登记

日期：2026-07-16
状态：Accepted

## 背景

Sprint14.3 至 Sprint14.7 已为公告、财报和新闻建立来源、原文 Hash、抓取时间、可得时间及多维资格预审。当前 27 条真实证据全部保持 `usage_status=review_required`，并被 `PROVIDER_USAGE_PERMISSION_UNAPPROVED` 阻塞。

公开可访问、法定披露平台、免费、无需 Token 或允许自动访问，都不能单独证明来源已授权自动抓取、本地存储、衍生研究或再分发。现有证据行上的 `usage_status` 也不是条款证据或有权主体的许可决定。

## 决策

1. 新增独立的追加式条款证据表 `market.research_source_terms_evidence` 和许可预审表 `market.research_source_usage_reviews`；不修改 `market.research_evidence`、K 线 Research Readiness 或多维资格预审的授权语义。
2. 首期只接受两个固定来源键：

   - `cninfo/cninfo_listed_company_disclosure`
   - `gdelt/gdelt_article_list_rss`

3. 来源范围必须精确绑定：

   - CNINFO 仅覆盖 `https://www.cninfo.com.cn/new/hisAnnouncement/query` 返回的公告元数据及其返回的 `static.cninfo.com.cn/finalpage/...` 公告 PDF。
   - GDELT 仅覆盖 `https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss` 中由 GDELT 发布的 GAL RSS 标题和原文链接元数据，不覆盖第三方新闻正文、图片、附件或目标站点抓取权利。

4. 首期条款证据 URL 固定为：

   - `https://www.cninfo.com.cn/new/index.htm`
   - `https://www.cninfo.com.cn/new/commonUrl?url=disclosure%2Flist%2Fnotice`
   - `https://www.gdeltproject.org/about.html`
   - `https://blog.gdeltproject.org/announcing-the-gdelt-article-list-rss-feed/`

   非官方 URL、其他 CNINFO 产品、其他 GDELT 产品、`unknown` 和 `synthetic` 必须被拒绝。`robots.txt` 不作为许可证据。
5. 条款证据记录保存官方 URL、原始响应 SHA-256、字节数、内容类型、实际获取时间、来源时间语义和采集器版本。发现失败必须追加 `discovery_unresolved`、`fetch_failed` 或 `validation_failed` 及明确原因，不得 fallback 或用第三方转载替代。
6. 使用范围固定为 `manual_observation`、`automated_fetch`、`local_storage`、`derived_research`、`redistribution`。每条预审只绑定一个范围、一个条款证据 Hash 和一个策略版本，结论不得跨范围传播。
7. 首期预审结论只允许 `review_required` 或 `rejected`，不实现 `approved`。`reviewer_label` 是未认证记录者标签，`identity_assurance` 固定为 `unverified`，均不构成法律、合规或审批主体。
8. 两张表均由数据库触发器拒绝更新和删除；条款 Hash、来源范围或策略版本变化时必须新增记录。条款证据被预审引用后使用 `ON DELETE RESTRICT` 保持历史链。
9. Sprint14.8 不修改现有 27 条证据的 ID、Hash、可得时间或 `usage_status`，不移除 `PROVIDER_USAGE_PERMISSION_UNAPPROVED`，不授予 Research Readiness，也不触达候选、回测、策略、风险、AI、Paper、Live 或订单路径。

## 后果

- 官方条款页面、抓取失败和人工预审都能按版本审计，但系统仍不会代替有权主体作出许可批准。
- GDELT Terms of Use 可作为其 GAL RSS 数据集范围的官方条款证据；再分发预审必须保留条款要求的 GDELT 引用与官网链接条件。该证据不传播到链接目标的第三方内容。
- CNINFO 当前官方页面未明示覆盖拟使用范围，因此相关预审继续保持 `review_required`。
- 后续只读 API 可以引用最新预审和完整历史，但不能据此把来源字段标为 validated。

## 回滚

功能回滚停止条款采集、预审追加和只读查询，已写入的审计历史继续保留。迁移 downgrade 只适用于没有真实审计数据的测试环境；存在真实记录时必须先制定导出和保留方案，不能通过删除记录伪造未发生。
