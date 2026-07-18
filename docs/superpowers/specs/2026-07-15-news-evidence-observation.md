# Sprint14.5：新闻证据语义与 GDELT RSS 试点设计

状态：已确认实施并验收通过  
日期：2026-07-15

## 目标与成功标准

- 在不改变既有研究与交易边界的前提下，建立新闻标题/链接观察证据的来源、Hash、时间和关联语义。
- 固定 GDELT Article List RSS 来源、外链 URL、RSS 条目 Hash 表示、抓取时间、首次观察时间、可得时间和拒绝原因均可审计。
- 明确区分 GDELT Provider 时间和原始发布时刻：本 Sprint 不推导 `source_published_at`。
- 全程维持 `observed_only=true`、`research_readiness=not_granted`、`tradable=false`、`order_created=false`。

## 固定 Provider 与样本范围

| 项目 | 固定值 |
| --- | --- |
| Provider | `gdelt` |
| Source | `gdelt_article_list_rss` |
| RSS 端点 | `https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss` |
| 窗口 | GDELT 15 分钟滚动 RSS |
| `002594.SZ` 候选别名 | `BYD`、`比亚迪` |
| `300750.SZ` 候选别名 | `CATL`、`宁德时代` |
| 每样本每次接受上限 | 1 条标题别名匹配记录 |

固定样本和别名只用于生成待复核候选，不能表示企业实体已被唯一识别。全局 RSS 中不匹配固定别名的记录不收集；已匹配但超过上限、缺少链接或时间、链接无效的记录必须以 rejected 方式审计。

## 证据字段与 fail-closed 规则

| 字段 | Sprint14.5 写入规则 |
| --- | --- |
| `document_url` | RSS `link` 外链；只保存链接，不请求文章正文。 |
| `raw_hash` | RSS `item` 重新序列化 XML 的 SHA-256，不是外链正文 Hash。 |
| `document_bytes` | 上述 RSS 条目重新序列化 XML 的字节数。 |
| `source_published_date`、`source_published_at` | 始终为 `NULL`。 |
| `source_timestamp_raw` | 原始 RSS `pubDate` 字符串。 |
| `provider_reported_at` | 解析后的 RSS `pubDate`，只存新闻详情。 |
| `provider_time_semantics` | 固定为 `publication_or_first_seen`，不把它升级为原始发布时间。 |
| `association_method` | 固定为 `title_alias_match`。 |
| `association_status`、`usage_status` | 固定为 `review_required`。 |
| `content_scope` | 固定为 `title_link_only`。 |
| `available_at` | 等于首次系统观察时刻，`availability_basis=system_first_observed`。 |

RSS 响应、XML、固定来源、Hash、时间、链接、标题、别名、详情或数据库写入失败时，必须写入 `fetch_failed`、`validation_failed`、`write_failed` 或 rejected 审计；不得用缓存、上一条新闻、第二 Provider 或推断时间替代。

## 最小实施范围

1. 在 `a-stock-data` 新增独立 `/news-evidence/{code}` 路由，保留旧 `/news/{code}` 不变。
2. 新增新闻详情 sidecar 和迁移，仅关联 observed 新闻证据。
3. 新增 Worker 显式同步方法和 `scripts/collect_news_evidence.py`；不登记 Celery Beat 或任何常驻任务。
4. 只读研究证据 API 返回 `news_detail`，不接入前端候选、RAG 或交易路径。
5. 新增 Provider、Worker、后端契约、显式真实验收和安全锁检查。

## 明确不做

- 不抓取、存储、解析、摘要或向量化外链正文。
- 不接入 Eastmoney、新浪、Tushare、GDELT DOC API 或第二新闻 Provider。
- 不新增 Token、第三方依赖、定时采集、自动重试回填或全市场扫描。
- 不生成情绪、事件、财务、策略、候选、回测、订单或 AI 下单输入。
