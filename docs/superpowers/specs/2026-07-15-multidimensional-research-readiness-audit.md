# Sprint14.7：多维研究证据 Readiness 资格预审与拒绝路径

状态：已确认实施并验收通过
日期：2026-07-15

## 1. 决策摘要

下一步进入 Sprint14.7，但本阶段只建设新闻、公告、财报证据的 **Research Readiness 资格预审**，不授予 Research Readiness。

预审必须独立于现有 K 线 Readiness 授权模型，只验证授权键、Requirement Profile、字段证据和拒绝路径。当前实际证据预期全部保持 `review_required` 或 `rejected`，实际验收中的 `ready` 数量必须为 0。

默认采用确定性只读计算，不新增数据库表、不新增前端页面、不修改原始证据或人工复核记录。若未来需要正式签署、身份审批或历史授权快照，再单独设计追加式审批存储。

## 2. 制定依据与当前基线

| 已完成阶段 | 当前能力 | 仍未解决的边界 |
| --- | --- | --- |
| Sprint14.3 公告证据 | 固定巨潮来源、原文 PDF Hash、日期精度、首次观察与可得时间 | 来源只提供日期精度；自动化使用权限仍待审；正文事件未解析、未复核 |
| Sprint14.4 财报证据 | 固定年报全文、原文 PDF Hash、详情 sidecar、失败审计 | 报告期截止日、合并口径、币种、单位、审计意见与财务事实仍未解析 |
| Sprint14.5 新闻证据 | 免费 GDELT RSS、标题/链接、RSS 条目 Hash、Provider 时间、首次观察时间 | 无正文、无正文 Hash、原始发布时间未确认、15 分钟滚动窗口不代表完整覆盖 |
| Sprint14.6 新闻人工复核 | 追加式标题/链接复核历史与只读展示 | `reviewer_label` 未认证；复核不验证正文事实，也不构成任何授权 |

共同基线保持不变：

- `usage_status=review_required`；
- `observed_only=true`；
- `research_readiness=not_granted`；
- `tradable=false`；
- `order_created=false`；
- 六个发布、回测与交易安全锁继续关闭；
- AI 订单与定时任务订单继续为 0。

## 3. 目标与成功标准

### 目标

1. 为公告、财报、新闻分别定义版本化 Requirement Profile 和允许的研究用途。
2. 为每条证据生成完整、不可隐式补全的预审授权键。
3. 将共同阻塞项和类型特有阻塞项转换为稳定的机器可读代码。
4. 对缺字段、未知 Profile、用途不匹配、证据已拒绝等情况 fail closed。
5. 用真实数据库证据证明当前没有任何多维证据获得 Research Readiness。

### 成功标准

- 三类实际证据均能得到确定、可解释、可复现的预审结果和阻塞项。
- 未显式声明用途、Profile 或必需字段时拒绝评估，不使用默认 Profile。
- Profile 与证据类型、研究用途或必需字段不匹配时拒绝评估。
- rejected 证据不能被任何人工复核或字段组合升级。
- 即使所有已定义语义阻塞项未来被解决，本阶段仍返回 `READINESS_GRANT_NOT_IMPLEMENTED`，不产生 `ready`。
- 预审前后原始证据、Hash、时间、`usage_status`、人工复核历史、候选、回测与订单数据均不改变。

## 4. 资格预审语义

### 4.1 授权键

每次预审必须显式包含：

`stock_code + evidence_type + evidence_id + raw_hash + available_at + research_use_scope + requirement_profile + policy_version`

其中：

- `raw_hash` 必须同时结合证据类型解释其 Hash 范围；新闻 RSS 条目 Hash 不能冒充正文 Hash。
- `available_at` 只表达系统可证明的最早可得时间，不反推来源公开时刻。
- `research_use_scope` 与 `requirement_profile` 必须由调用方显式声明。
- 任一授权键字段缺失、改变或不匹配时必须重新评估，旧结果不得传播。

### 4.2 首期 Requirement Profiles

| Profile | 允许用途 | 首期要求 |
| --- | --- | --- |
| `ANNOUNCEMENT_EVENT_RESEARCH_V1` | `announcement_event_research` | 原文级 Hash、可得时间、可接受的公开时点、证券关联、事件内容验证、修订关系与来源使用许可 |
| `FINANCIAL_REPORT_FUNDAMENTAL_RESEARCH_V1` | `financial_report_research` | 原文级 Hash、报告期、合并口径、币种、单位、审计意见、财务事实来源定位、修订关系与来源使用许可 |
| `NEWS_EVENT_RESEARCH_V1` | `news_event_research` | 正文来源与 Hash、来源公开时间、证券关联、正文事实验证、覆盖范围说明、复核身份与来源使用许可 |

只读人工查看现有证据不需要这些研究 Profile，也不能因此获得研究用途授权。

### 4.3 预审结果

首期只允许：

- `review_required`：至少一个必需语义未解决；
- `rejected`：原始证据或任一必需语义已明确拒绝。

禁止返回或写入 `ready`。当其他阻塞项为空时，仍必须增加 `READINESS_GRANT_NOT_IMPLEMENTED`。

### 4.4 最小阻塞代码

共同阻塞代码：

- `PROVIDER_USAGE_PERMISSION_UNAPPROVED`
- `EVIDENCE_QUALITY_NOT_OBSERVED`
- `AVAILABLE_AT_UNRESOLVED`
- `HASH_SCOPE_INSUFFICIENT`
- `RESEARCH_CONTENT_NOT_VALIDATED`
- `READINESS_GRANT_NOT_IMPLEMENTED`

公告特有阻塞代码：

- `ANNOUNCEMENT_PUBLICATION_TIME_DATE_ONLY`
- `ANNOUNCEMENT_EVENT_CONTENT_UNPARSED`
- `ANNOUNCEMENT_REVISION_LINEAGE_UNVERIFIED`

财报特有阻塞代码：

- `REPORT_PERIOD_END_UNRESOLVED`
- `CONSOLIDATION_SCOPE_UNRESOLVED`
- `CURRENCY_OR_UNIT_UNRESOLVED`
- `AUDIT_OPINION_UNRESOLVED`
- `FINANCIAL_FACTS_UNPARSED`
- `FINANCIAL_REPORT_REVISION_RELATION_UNRESOLVED`

新闻特有阻塞代码：

- `NEWS_CONTENT_SCOPE_TITLE_LINK_ONLY`
- `NEWS_ARTICLE_BODY_HASH_MISSING`
- `NEWS_SOURCE_PUBLICATION_TIME_UNRESOLVED`
- `NEWS_ASSOCIATION_REVIEW_REQUIRED`
- `NEWS_ASSOCIATION_REJECTED`
- `NEWS_REVIEWER_IDENTITY_UNVERIFIED`
- `NEWS_ROLLING_WINDOW_COVERAGE_LIMITED`

阻塞代码只能依据已存证据产生，禁止通过猜测、默认值或外部未归档信息消除。

## 5. 最小实施方案与取舍

### 推荐方案

1. 新增独立的多维证据 Profile 与预审服务，不修改 `research_profiles.py` 和既有 K 线 `research_readiness.py` 的授权语义。
2. 预审直接读取现有 `market.research_evidence`、财报详情、新闻详情和最新人工复核。
3. 新增只读 `GET /api/v1/research/evidence/readiness-audit`：调用方必须提供 `research_use_scope` 与 `requirement_profile`，可选按证据类型、证券或证据 ID 筛选。
4. 响应返回授权键、`policy_version`、预审状态、必需字段、已验证字段、未解决字段、拒绝字段、阻塞代码和输入指纹。
5. 所有响应继续返回 `observed_only=true`、`research_readiness=not_granted`、`tradable=false`、`order_created=false`。
6. 新增显式真实验收脚本；脚本只读数据库和 API，不修复、不回填、不批准。

### 取舍

- 不新增预审结果表：避免形成第二套状态源和无必要迁移；结果由不可变证据、最新追加式复核与版本化策略确定性生成。
- 通过规范化输入指纹和 `policy_version` 保证结果可复核；验收报告保留当次输入指纹与汇总。
- 不新增前端页面：本阶段目标是验证授权键与拒绝路径。统一阻塞视图可在规则稳定后作为独立 Sprint 实施。
- 不复用 K 线 Profile：避免将 K 线的区间、复权和字段级 ready 语义错误传播到文档证据。

## 6. 开发顺序

### Sprint14.7-A：设计确认

- 新增 ADR-017，冻结授权键、三类 Profile、阻塞代码、输入指纹和非传播规则。
- 确认本阶段没有 `ready` 路径、数据库写入或前端范围。
- 用户确认后才能进入实现。

### Sprint14.7-B：后端只读预审

- 新增独立 Profile/预审模块。
- 新增只读 API 与序列化契约。
- 对未知 Profile、用途不匹配、字段集合不匹配和 rejected 证据 fail closed。
- 不修改证据采集、人工复核、候选、回测、策略、风险或订单调用链。

### Sprint14.7-C：测试与真实验收

- 单元测试覆盖三类 Profile、共同/特有阻塞代码、输入指纹稳定性和授权键变化。
- 契约测试覆盖显式参数、错误请求、只读响应和安全标记。
- 使用当前真实公告、财报和新闻证据执行预审，确认全部至少有一个有效阻塞项且 `ready=0`。
- 对现有 rejected 证据执行负向验收，确认不能升级。
- 核对六个安全锁关闭、AI/定时订单为 0，且预审前后关键表行数与原始字段不变。

### Sprint14.7-D：报告与后续决策

- 生成 `追踪报告Sprint14.7.md`，列出各类型真实阻塞项、输入指纹、验收命令和结果。
- 只依据真实审计结果确定 Sprint14.8，不在本阶段自动扩大抓取或研究用途。

## 7. 预计产出文件

- `docs/adr/ADR-017-multidimensional-evidence-readiness-audit.md`
- 独立的后端多维证据 Profile/预审模块
- `backend/app/api/research.py` 的只读预审路由
- `backend/tests/test_research_evidence_readiness_audit.py`
- `scripts/verify_research_evidence_readiness_audit.ps1`
- `追踪报告Sprint14.7.md`

默认不包含数据库迁移和前端文件。

## 8. 验收矩阵

| 验收项 | 必须结果 |
| --- | --- |
| 当前 observed 公告 | `review_required`，至少包含来源许可、日期精度或内容未验证阻塞 |
| 当前 observed 财报 | `review_required`，明确列出未解析的报告语义与财务事实阻塞 |
| 当前 observed 新闻 | `review_required`，明确列出正文、发布时间、关联/身份或覆盖阻塞 |
| `title_link_relevant` 新闻 | 仍不得越过正文、时间、身份、来源许可与最终授权阻塞 |
| rejected 证据 | `rejected`，不得被人工复核或其他字段升级 |
| 缺少 Profile/用途/必需字段 | fail closed，不使用默认值 |
| Profile 与用途或证据类型不匹配 | fail closed |
| 数据副作用 | 证据、详情、复核、候选、回测、策略、风险和订单数据均不改变 |
| 安全边界 | 六个安全锁关闭；AI 与定时任务订单为 0 |
| 实际授权 | `ready=0`、`research_readiness=not_granted` |

## 9. 明确不做

- 不把 `usage_status` 改为 `approved`，不写入现有 `market.research_readiness_reviews`。
- 不授予候选、筛选、回测、策略、因子、风险、Paper、Live 或订单使用资格。
- 不新增新闻正文抓取、PDF 财务指标解析、第二 Provider、定时任务、全市场采集或第三方依赖。
- 不把免费、公开可访问或人工相关性结论解释为自动化使用授权。
- 不建立登录身份、审批角色、电子签名或正式授权工作流。
- 不打开任何发布、回测、交易、AI 下单或定时下单开关。

## 10. 回滚

首期没有迁移和数据写入。回滚只需移除只读路由、独立预审模块、测试和验收脚本；原始证据、人工复核与既有 Research Readiness 不受影响。

## 11. Sprint14.8 候选顺序

Sprint14.7 验收后按阻塞项优先级选择，不提前承诺实施：

1. 来源自动化使用许可与审批主体登记；没有明确授权时继续保持 `review_required`。
2. 财报原文元数据、修订关系和财务事实定位的只读解析/人工复核。
3. 公告精确公开时点、事件内容与修订链验证。
4. 新闻正文级合法来源、正文 Hash、来源发布时间和已认证复核身份。

任何一项若会改变研究用途或授权状态，必须重新进行 ADR、安全评审和用户确认。
