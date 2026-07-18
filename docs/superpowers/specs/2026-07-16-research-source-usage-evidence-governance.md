# Sprint14.8：研究来源条款证据与许可预审登记

状态：已完成并验收通过
日期：2026-07-16

完成结果：迁移 `022` 已应用；4 条固定官方页面均形成原始响应 Hash 证据，两个固定来源各有五类 `review_required` 预审；只读 API 与多维资格预审引用已接入。现有 27 条研究证据、Research Readiness 和六个发布与交易锁均未改变。详见根目录 `追踪报告Sprint14.8.md`。

## 1. 决策摘要

Sprint14.8 优先建设研究数据来源的条款证据与许可预审登记，不直接进入财报解析、公告事件解析或新闻正文抓取。

Sprint14.7 的 27 条真实证据全部存在 `PROVIDER_USAGE_PERMISSION_UNAPPROVED` 阻塞。即使先解决财报、公告或新闻的内容语义，来源许可仍会阻断 Research Readiness，因此先建立统一、可审计的来源使用证据链收益最高。

本 Sprint 只记录官方条款证据、拟使用范围和追加式预审结论。代码不能作出法律判断，也不能自行认定许可成立；首期没有 `approved` 路径，不修改任何现有证据的 `usage_status`，不消除 Sprint14.7 的来源许可阻塞。

## 2. 当前真实基线

2026-07-16 只读复核结果与 Sprint14.7 报告一致：

| 证据类型 | Provider | Source | observed | rejected | 当前使用状态 |
| --- | --- | --- | ---: | ---: | --- |
| 公告 | `cninfo` | `cninfo_listed_company_disclosure` | 1 | 0 | `review_required` |
| 财报 | `cninfo` | `cninfo_listed_company_disclosure` | 2 | 12 | `review_required` |
| 新闻 | `gdelt` | `gdelt_article_list_rss` | 2 | 10 | `review_required` |
| 合计 | — | — | 5 | 22 | `ready=0` |

当前不存在统一的来源条款证据表、使用范围登记或可审计的许可预审记录。现有 `usage_status` 只是证据行上的保守状态，不是许可决定或授权事实。

## 3. 目标与成功标准

### 目标

1. 为当前两个固定来源建立版本化、可追溯的官方条款/许可/数据政策证据记录。
2. 明确区分“官方文档已观察”“人工预审意见”和“已获授权”三种语义。
3. 按具体使用范围记录预审：人工查看、自动抓取、本地存储、衍生研究和再分发不得相互传播。
4. 对条款缺失、页面变化、Hash 变化、身份未认证或使用范围未覆盖的情况 fail closed。
5. 保持现有 Research Readiness、候选、回测和交易边界完全不变。

### 成功标准

- `cninfo/cninfo_listed_company_disclosure` 与 `gdelt/gdelt_article_list_rss` 均有条款发现审计；成功取得官方文档时记录 URL、获取时间、字节数和 SHA-256，无法取得时记录明确失败或 `discovery_unresolved`，不得用非官方页面替代。
- 每条预审记录必须引用一条条款证据和一个明确的 `usage_scope`。
- 首期预审状态只允许 `review_required` 或 `rejected`；任何输入均不能产生 `approved`。
- 未认证的 `reviewer_label` 只能表示记录者标签，不能表示法律、合规或审批主体。
- 27 条现有证据的 ID、Hash、可得时间和 `usage_status` 均保持不变，Sprint14.7 仍为 `ready=0`。
- 六个发布与交易锁保持关闭，AI 与定时任务订单保持为 0。

## 4. 语义与安全边界

### 4.1 来源使用键

每条许可预审必须显式绑定：

`provider + source + source_scope + usage_scope + terms_evidence_id + terms_hash + policy_version`

其中：

- `source_scope` 指固定端点、域名或数据产品范围，不能只写 Provider 名称后传播到其全部产品。
- `usage_scope` 首期只允许 `manual_observation`、`automated_fetch`、`local_storage`、`derived_research`、`redistribution`。
- 同一来源对一个使用范围的结论不得自动传播到其他使用范围。
- 条款 Hash、来源范围或策略版本变化后，旧预审不能继续作为当前依据。

### 4.2 三层事实必须分开

1. **条款证据事实**：系统在某一时刻观察到某个官方文档及其 Hash。
2. **预审意见**：未认证记录者基于条款证据写入 `review_required` 或 `rejected` 及理由。
3. **许可授权事实**：必须来自可验证的外部授权与有权主体；本 Sprint 不实现、不推断。

公开可访问、法定披露平台、免费、无需 Token、`robots.txt` 允许访问或人工认为可以使用，都不能单独等同于许可授权。

## 5. 最小数据模型

### 5.1 `market.research_source_terms_evidence`

追加式保存官方条款证据或发现失败：

| 字段 | 规则 |
| --- | --- |
| `terms_evidence_id` | UUID，不可更新覆盖。 |
| `provider`、`source`、`source_scope` | 必须使用固定已知值，禁止 `unknown`、`synthetic`。 |
| `document_kind` | `terms_of_use`、`license`、`data_policy`、`robots` 或 `other_official`；`robots` 不得被解释为许可。 |
| `terms_url` | 仅接受经 Sprint14.8-A 确认的官方 URL，不使用搜索结果页或第三方转载。 |
| `retrieved_at` | 系统实际取得响应的时间。 |
| `source_effective_at`、`source_time_precision` | 只有原文明确提供时填写；否则 unresolved。 |
| `raw_hash`、`document_bytes`、`content_type` | 成功取得文档时必填；Hash 为原始响应字节 SHA-256。 |
| `status` | `observed`、`discovery_unresolved`、`fetch_failed`、`validation_failed`。 |
| `failure_reason` | 非 observed 状态必填，不得静默跳过。 |
| `collector_version`、`created_at` | 固定版本并由服务器记录时间。 |

首期不默认在数据库复制完整条款正文；只保存来源 URL、响应 Hash、字节数和时间。若后续需要保存正文或归档文件，必须先单独确认存储授权与保留策略。

### 5.2 `market.research_source_usage_reviews`

追加式保存许可预审意见：

| 字段 | 规则 |
| --- | --- |
| `review_id` | UUID，每次提交新增记录，不更新或删除历史。 |
| `terms_evidence_id` | 必须引用条款证据。 |
| `usage_scope` | 单一明确范围，不接受数组或“全部用途”。 |
| `decision_status` | 首期只允许 `review_required`、`rejected`。 |
| `reason` | 必填，说明尚缺证据或明确拒绝依据。 |
| `reviewer_label` | 未认证自填标签，不代表审批身份。 |
| `identity_assurance` | 首期固定为 `unverified`。 |
| `policy_version`、`reviewed_at` | 固定策略版本和数据库时间。 |

## 6. 最小实施方案与取舍

### 推荐方案

1. 新增 ADR-018，冻结来源键、使用范围、证据状态、预审状态和身份边界。
2. 新增迁移 022，仅创建两张追加式审计表；不修改 `market.research_evidence` 或现有 K 线/多维 Readiness 表。
3. 新增显式条款证据采集脚本，只处理 Sprint14.8-A 确认的官方 URL；不定时运行、不 fallback、不自动扩大来源。
4. 新增显式本地预审追加脚本，只允许 `review_required`/`rejected`；不提供公共批准 API。
5. 新增只读 `GET /api/v1/research/source-usage-evidence`，返回条款证据、最新预审和完整历史引用。
6. Sprint14.7 资格预审最多增加只读的来源证据引用，不将 `provider_usage_permission` 标记为 validated，也不移除 `PROVIDER_USAGE_PERMISSION_UNAPPROVED`。

### 取舍

- 使用数据库追加式记录而非静态配置，保留条款版本和历史意见，避免修改配置后丢失旧语义。
- 不建立前端页面：首期先稳定数据模型、官方来源和拒绝路径。
- 不实现 `approved`：当前没有认证身份、可验证审批主体或外部授权文件链，开放批准入口会制造虚假授权。
- 不把条款发现失败视为系统错误通过；`discovery_unresolved` 是有效的 fail-closed 审计结果，但不会解除任何阻塞。

## 7. 开发顺序

### Sprint14.8-A：官方来源与使用范围确认

- 对 `cninfo` 和 `gdelt` 仅检索官方条款、许可或数据政策页面。
- 记录候选 URL、文档类型、有效时间语义和拟使用范围。
- 明确 `robots.txt`、公开访问、免费或无 Token 均不是许可结论。
- 用户确认固定 URL 与范围后，才能进入迁移和采集实现。

#### Sprint14.8-A 核验结果（2026-07-16）

核验时间：`2026-07-16T14:04:15+08:00`。本节只记录官方页面及其明示范围，不构成法律意见或许可批准。

| Provider / Source | 固定官方 URL | 文档类型 | 明示范围与边界 | Sprint14.8 处理 |
| --- | --- | --- | --- | --- |
| `cninfo/cninfo_listed_company_disclosure` | `https://www.cninfo.com.cn/new/index.htm` | `other_official` | 全站免责声明说明平台身份、信息可靠性免责和外链风险；未明示自动抓取、本地存储、衍生研究或再分发授权。 | 采集页面原始响应与 Hash，但五个 `usage_scope` 均保持 `review_required`，理由为官方页面未覆盖拟使用范围。 |
| `cninfo/cninfo_listed_company_disclosure` | `https://www.cninfo.com.cn/new/commonUrl?url=disclosure%2Flist%2Fnotice` | `other_official` | 官方公告栏目页，说明栏目内容由上市公司提供并提供公告阅览入口；未明示批量查询、PDF 下载存储或再利用授权。 | 用于限定 `source_scope`，不能作为许可授权；五个 `usage_scope` 均保持 `review_required`。 |
| `gdelt/gdelt_article_list_rss` | `https://www.gdeltproject.org/about.html` | `terms_of_use` | Terms of Use 明示 GDELT 发布的数据集可用于学术、商业或政府用途，并允许带 GDELT 引用及官网链接的再分发。 | 记录为官方条款证据；首期仍只生成 `review_required` 预审，不产生 `approved`。 |
| `gdelt/gdelt_article_list_rss` | `https://blog.gdeltproject.org/announcing-the-gdelt-article-list-rss-feed/` | `other_official` | 官方产品说明将 GAL 定义为数据集，并说明 RSS 每分钟更新、包含文章 URL 和标题，面向自动摄取/镜像发现流。 | 用于证明 Terms of Use 与固定 RSS 产品的范围关联；不扩展到新闻正文、图片或目标站点内容。 |

固定 `source_scope`：

- CNINFO：仅 `https://www.cninfo.com.cn/new/hisAnnouncement/query` 返回的公告元数据，以及其返回的 `static.cninfo.com.cn/finalpage/...` 公告 PDF；不传播到行情、数据商城、互动易或其他 CNINFO 产品。
- GDELT：仅 `https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss` 响应中的 GDELT GAL RSS 元数据（当前采集字段为标题和原文链接）；不包含链接目标的第三方新闻正文、图片、附件或目标站点抓取权利。

固定预审范围：

| Provider | `manual_observation` | `automated_fetch` | `local_storage` | `derived_research` | `redistribution` |
| --- | --- | --- | --- | --- | --- |
| CNINFO | `review_required` | `review_required` | `review_required` | `review_required` | `review_required` |
| GDELT GAL RSS 元数据 | `review_required` | `review_required` | `review_required` | `review_required` | `review_required`，并记录条款要求的 GDELT 引用与官网链接条件 |

不纳入固定清单：`https://irm.cninfo.com.cn/wechat/register` 仅适用于互动易注册服务，`https://list.cninfo.com.cn/ssi/privacy` 仅处理个人信息隐私语义，二者均不能覆盖本 Sprint 的公告查询与 PDF 范围。`robots.txt` 也不作为许可证据。

进入 Sprint14.8-B 前必须由用户确认上述四个固定 URL、两个 `source_scope` 和五类预审范围。确认只授权实现该审计模型，不代表确认 Provider 已授予使用许可。

### Sprint14.8-B：追加式证据与预审存储

- 新增 ADR-018 和迁移 022。
- 实现条款证据写入、失败审计和 Hash 版本追加。
- 实现本地显式预审追加，禁止更新、删除和 `approved`。

### Sprint14.8-C：只读 API 与资格预审引用

- 实现来源条款证据及预审历史查询。
- 在多维资格预审响应中只增加来源证据引用和当前预审状态。
- 继续返回 `research_readiness=not_granted`，不改变任何字段验证结果。

### Sprint14.8-D：真实验收与报告

- 对两个固定 source key 运行显式条款证据采集或记录 `discovery_unresolved`。
- 验证相同 URL 新 Hash 追加新版本，旧版本不可变。
- 验证非官方 URL、未知来源、空理由、`approved` 和更新/删除请求均被拒绝。
- 验证 27 条现有证据快照不变、`ready=0`、六锁关闭、AI/定时订单为 0。
- 完成定向测试、后端完整回归、核心只读回归和 `追踪报告Sprint14.8.md`。

## 8. 预计产出文件

- `docs/adr/ADR-018-research-source-usage-evidence-governance.md`
- `backend/alembic/versions/022_research_source_usage_evidence.py`
- 独立的来源条款证据与预审存储模块
- `backend/app/api/research.py` 的只读来源使用证据路由
- `backend/tests/test_research_source_usage_evidence.py`
- `scripts/collect_research_source_terms_evidence.py`
- `scripts/append_research_source_usage_review.py`
- `scripts/verify_research_source_usage_evidence.ps1`
- `追踪报告Sprint14.8.md`

默认不包含前端文件。

## 9. 验收矩阵

| 验收项 | 必须结果 |
| --- | --- |
| 官方来源范围 | 仅两个固定 source key；非官方 URL、unknown、synthetic 被拒绝 |
| 条款证据成功路径 | URL、获取时间、原始字节 Hash、字节数、类型和版本可审计 |
| 条款发现失败 | 明确 `discovery_unresolved` 或失败原因，不 fallback、不伪造文档 |
| 使用范围 | 每条预审只覆盖一个显式 `usage_scope`，权限不传播 |
| 预审状态 | 只允许 `review_required`、`rejected`；`approved` 必须被拒绝 |
| 复核身份 | 固定 `identity_assurance=unverified`，不构成审批主体 |
| 版本追加 | 新 Hash 追加新记录，旧 Hash 和旧预审不可变 |
| 现有证据 | 27 条证据的 ID、Hash、可得时间和 `usage_status` 不变 |
| Research Readiness | `ready=0`，来源许可阻塞继续存在 |
| 安全边界 | 六锁关闭，AI 与定时任务订单为 0 |

## 10. 明确不做

- 不提供法律意见，不判断任何 Provider 已授予自动抓取、存储、研究或再分发权利。
- 不新增 `approved` 写入路径，不修改现有证据的 `usage_status`。
- 不打开 Research Readiness、候选、回测、策略、风险、Paper、Live 或订单路径。
- 不抓取新闻正文、不解析财报指标、不解析公告事件、不扩大样本或定时采集。
- 不新增第三方依赖、运行时 fallback、第二 Provider、全市场扫描或前端审批页面。
- 不把 `robots.txt`、公开页面、法定披露、免费或无 Token 解释为许可批准。

## 11. 回滚

功能回滚停止条款采集、预审追加和只读路由；已记录的条款证据和预审历史继续保留，不通过删除数据伪造未发生。迁移 downgrade 只允许用于无生产审计数据的测试环境；有真实记录时必须先单独制定保留与导出方案。

## 12. 当前实施前置条件

2026-07-16 首次运行 `scripts\doctor.ps1` 时发现 Celery Beat 运行登记已过期，Watchdog 同步告警。现已通过标准 `scripts\stop-local.ps1` / `scripts\start-local.ps1` 完成受管恢复，并重新取得 doctor PASS 与 Watchdog `ok=true`；Chromadb 不可用仍为既有非阻断提示。不得按端口或进程名直接终止。

## 13. Sprint14.8 后续分流

- 若用户能提供可验证的外部授权和有权审批主体：另立 Sprint 设计 `approved`、身份验证及与资格预审的集成，不能在 Sprint14.8 内顺带开放。
- 若许可继续 unresolved：不得扩大自动采集；可在独立 Sprint 中仅对已经归档的财报 PDF 做离线、只读元数据和事实定位，仍保持 observed-only。
