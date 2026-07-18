# ADR-015：新闻证据观察试点语义

日期：2026-07-15  
状态：Accepted

## 背景

ADR-013 已建立公告、新闻和财报共享的研究证据主表，ADR-014 已为财报建立详情 sidecar；新闻仍缺少可审计的来源、标题关联、时间含义、Hash 表示和内容范围语义。现有新闻展示接口没有这些字段，不能作为研究或交易输入。

本阶段没有可用的付费新闻 Token。GDELT Article List 的滚动 RSS 提供免费、开放的全局文章索引，但 RSS 的 `pubDate` 可能是发布者时间，也可能是 GDELT 首次见到的时间，不能被解释为可验证的原始发布时刻。

## 决策

1. Sprint14.5 仅使用固定 Provider=`gdelt`、source=`gdelt_article_list_rss` 和 HTTPS RSS 端点 `https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss`，不使用 GDELT DOC API、第二 Provider、缓存替代或 fallback。
2. 只允许显式人工调用的固定样本：`002594.SZ`（标题别名 `BYD`、`比亚迪`）与 `300750.SZ`（标题别名 `CATL`、`宁德时代`）。每个样本每次最多接受 1 条当前 RSS 中的标题别名匹配记录；其余匹配记录和不完整记录写入 rejected 审计。全局 RSS 中不匹配固定别名的条目不属于本次候选集。
3. 试点只读取 RSS 条目的标题、链接和 Provider 时间；不下载、解析、缓存或 Hash 外链文章正文。通用证据的 `document_url` 指向外链原文，`raw_hash` 和 `document_bytes` 分别表示 RSS 条目重新序列化 XML 的 SHA-256 与字节数，绝不宣称为外链文章正文 Hash。
4. 新增一对一 `market.research_news_details`，仅为 observed 新闻写入：固定 RSS URL、原始标题、外链发布域名、Provider 报告时间、`publication_or_first_seen` 时间语义、标题别名关联、`review_required` 关联状态、`title_link_only` 内容范围、15 分钟滚动窗口、Hash 原始表示和解析状态。
5. 通用证据表的 `source_published_date` 与 `source_published_at` 始终为空，`publication_time_precision=unresolved`；RSS `pubDate` 原串写入 `source_timestamp_raw`，解析后的 Provider 时间只写入新闻详情。`first_observed_at` 与 `available_at` 均为系统接收 RSS 并校验条目的时刻，`availability_basis=system_first_observed`。
6. 新闻证据始终为 observed-only、`usage_status=review_required`。不得写入 Data Certification、Research Readiness、RAG、候选、回测、策略、风险、执行、AI 下单、定时采集或任一发布/交易锁。

## 后果

- 可审计地看到某个标题链接何时经固定 RSS 被系统观察、RSS 记录本身的 Hash 表示，以及标题与固定别名的弱关联方式。
- 任何标题别名匹配仅表示待人工核验，不能证明公司相关性、事件事实、情绪、可得发布时间或投资结论。
- 不读取正文降低外链使用边界和抓取成本，但也意味着不能在本阶段生成事件标签、财务/公告结论或研究特征。
- RSS 为 15 分钟滚动窗口，未命中不是“没有新闻”的证明；固定样本、别名映射和标题匹配均留待下一阶段独立评审。

## 回滚

回滚实现会停止显式新闻采集和只读详情展示；已写入的 RSS 批次、Hash、observed/rejected 证据及详情均为审计事实，不通过删除记录伪造未发生。任何删除或重建详情关系都必须保留可追踪迁移与原因。
