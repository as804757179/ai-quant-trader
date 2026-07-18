# Sprint14.5 追踪报告

生成日期：2026-07-15（Asia/Shanghai）

## 任务

完成新闻证据的最小只读观察试点：在没有付费 Token 的前提下，固定使用 GDELT Article List RSS，对 `002594.SZ`、`300750.SZ` 进行显式标题别名匹配采集，保留来源、RSS 条目 Hash、Provider 时间、系统可得时间、拒绝审计和新闻详情 sidecar。

## 当前结论

**PASS（真实端到端验收）**。标准 `start-local` 流程已应用迁移 020 并通过环境验收；随后 `scripts\verify_news_evidence.ps1` 完成真实 RSS 读取、数据库写入、只读 API、安全锁和核心回归检查。

## 已实现

- 固定 Provider=`gdelt`、来源=`gdelt_article_list_rss`、RSS 端点为 `https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss`，没有 GDELT DOC API、第二 Provider、缓存替代或 fallback。
- 仅固定样本 `002594.SZ`（`BYD`、`比亚迪`）和 `300750.SZ`（`CATL`、`宁德时代`）可被显式采集；每样本每次最多接受 1 条标题别名匹配记录。
- 新增一对一 `market.research_news_details` sidecar，记录 RSS URL、原始标题、发布域名、GDELT Provider 时间、标题别名匹配、15 分钟窗口、内容范围和 Hash 表示语义。
- 不读取外链正文。`raw_hash` 和 `document_bytes` 严格表示重新序列化 RSS `item`，不是外链文章正文 Hash；外链 URL 仅作为待人工复核的原文定位。
- 固定时间语义：`source_published_date=NULL`、`source_published_at=NULL`、`publication_time_precision=unresolved`；RSS `pubDate` 以 `publication_or_first_seen` 记录到详情，`available_at=first_observed_at`、`availability_basis=system_first_observed`。
- 采集入口仅为显式脚本 `scripts\collect_news_evidence.py`；未接入 Celery Beat、RAG、Data Certification、Research Readiness、候选、回测、策略、风控或订单链路。

## 已验证证据

| 验证项 | 实际结果 |
| --- | --- |
| 标准重启与迁移 | PASS：`scripts\stop-local.ps1` 后由 `scripts\start-local.ps1` 安全启动，迁移 020 生效 |
| 真实固定样本采集 | PASS：`002594.SZ` 批次 `fc813dfc-e110-4153-9995-2bec9d40f226` 为 `partial`（接受 1、拒绝 10）；`300750.SZ` 批次 `399a81d5-c2c8-4102-b845-79206a32e5fb` 为 `success`（接受 1、拒绝 0） |
| 来源、Hash 与可得时间 | PASS：两条 observed 新闻均记录 `gdelt`/固定来源、64 位 RSS 条目 SHA-256、Provider 时间、首次系统观察的可得时间；未推断原始发布时间 |
| 新闻详情 sidecar | PASS：两样本均返回 `publication_or_first_seen`、`title_alias_match`、`review_required`、`title_link_only`、15 分钟窗口和 `metadata_observed` |
| Provider 单元测试 | PASS：6 passed |
| Worker 单元测试 | PASS：6 passed |
| 后端契约测试 | PASS：5 passed |
| 核心只读回归 | PASS：后端 15 passed、前端契约测试 3 passed、TypeScript 检查与前端构建通过 |
| 发布与交易边界 | PASS：六个发布/交易锁关闭，AI 与定时任务来源订单均为 0；结果保持 `observed_only=true`、`research_readiness=not_granted`、不可交易、不可创建订单 |

## 已处理的审计事件

GDELT RSS 是 15 分钟滚动窗口，首次实时读取时两个固定样本均未命中，采集逻辑正确返回 `validation_failed` 而不伪造历史结果。随后的真实验收窗口中两个样本均命中；`002594.SZ` 另外有 10 条已匹配记录超过本次上限，均以 rejected 审计保留，没有静默丢弃。

## 边界与后续工作

- P1：标题别名匹配仅是待人工核验的弱关联；不证明公司相关性、事件事实、情绪或投资结论。
- P1：当前不抓取正文，Hash 仅覆盖 RSS 条目而非外链原文。若后续需要正文级证据、许可、保留策略或语义解析，须单独完成来源授权和 ADR 评审。
- P1：RSS 滚动窗口的未命中不表示无新闻；如需稳定、可回放的历史覆盖，应独立评审归档来源、时间口径和存储边界。
- P2：当前环境仍提示 Chromadb 不可用，RAG 按既有设计降级为空检索；这不影响本次新闻证据采集、API 或安全边界。
