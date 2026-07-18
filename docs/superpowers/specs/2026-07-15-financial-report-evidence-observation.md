# Sprint14.4-A：财报证据观察语义设计

状态：已确认实施并验收通过  
日期：2026-07-15

## 目标与成功标准

- 在不改变既有研究与交易边界的前提下，为财报全文建立可追溯的原文观察语义。
- 固定 Provider、请求分类、原文 URL、PDF Hash、发布时间精度、首次观察时间、可得时间和失败原因均可审计。
- 财报报告期、口径、币种、单位、审计意见与修订关系没有原文证据时明确显示为 `unresolved`，不产生推测值。
- 设计实现后仍只返回 `observed_only=true`、`research_readiness=not_granted`、`tradable=false`、`order_created=false`。

## 已验证的 Provider 分类

2026-07-15 对巨潮 `000001.SZ` 执行只读查询，确认以下分类可返回对应的定期报告标题：

| 分类 | 返回示例 | 本 Sprint 使用 |
| --- | --- | --- |
| `category_ndbg_szsh` | `2025年年度报告`、`2025年年度报告摘要` | 使用年报全文 |
| `category_bndbg_szsh` | `2025年半年度报告`、摘要 | 不实施 |
| `category_yjdbg_szsh` | `2026年一季度报告` | 不实施 |
| `category_sjdbg_szsh` | `2025年三季度报告` | 不实施 |

巨潮资讯仍仅作为固定的原文观察来源，自动化使用状态保持 `review_required`；不把“法定信息披露平台”解释为自动化使用已获批准。

## 最小实施范围（Sprint14.4-B）

1. 固定 Provider 为 `cninfo`，请求端点沿用 `https://www.cninfo.com.cn/new/hisAnnouncement/query`，分类固定为 `category_ndbg_szsh`，不使用 fallback。
2. 建议固定样本为 `000001.SZ` 与 `600000.SH`，每个交易所各 1 只；每次显式命令最多采集各 1 条最新年报全文 PDF。
3. 标题在去除空白后必须以 `YYYY年年度报告` 严格结尾，可带公司名称前缀。摘要或任何非全文文件写入 rejected 审计并带失败原因，不能作为年报全文接受。
4. 下载原文后验证 PDF 内容类型、非零字节数和 SHA-256；来源证券代码、机构标识和原文 URL 域名必须与请求一致。
5. 通用批次/证据表复用 ADR-013；新增一对一财报详情表，保存 Provider 分类、原始报告期标签、详情解析状态与未解析语义。
6. 新增显式采集脚本与只读 API 筛选，不接入 Celery Beat、RAG、`fundamental.financial_reports` 或任何研究/交易生产链路。

## 财报详情字段与 fail-closed 规则

| 字段 | Sprint14.4-B 写入规则 |
| --- | --- |
| `report_kind` | 固定为 `annual`。 |
| `report_period_label` | 保存标题中的原始年份标签。 |
| `report_period_end` | 无 PDF 原文定位证据时为 `NULL`。 |
| `period_precision` | `title_label`，不伪造精确报告截止日。 |
| `document_role` | 仅接受 `full_report`；其他为 rejected。 |
| `consolidation_scope`、`currency_code`、`currency_unit`、`audit_opinion` | 固定为 `unresolved`，直到后续原文解析与人工复核。 |
| `revision_status` | 正常全文为 `none`；检测到更正/修订但无法验证关联时为 `revision_relation_unresolved` 并拒绝。 |
| `supersedes_evidence_id` | 仅在可审计地确认原文关系后填写；首期始终为 `NULL`。 |
| `detail_parse_status` | `metadata_observed`，不表示财务数值已经解析或可用。 |

## 时间、版本与失败审计

- 巨潮列表不被视为可证明的精确公开时刻：`source_published_at=NULL`、`publication_time_precision=date`。
- `first_observed_at` 为系统首次成功取得并校验 PDF 的时刻；`available_at` 与其相同。
- 相同外部文档 ID 的新 Hash 追加一条证据；旧 Hash、旧批次和旧详情保留。
- 网络、分类、标题、来源证券、PDF、Hash、详情或数据库写入失败，必须写入 `fetch_failed`、`validation_failed`、`write_failed` 或 rejected 审计；不得静默跳过或用上一份年报替代。

## 实施验证

- Provider 单元测试：分类固定、标题过滤、PDF/Hash、无 fallback、失败审计。
- Worker 单元测试：财报详情的 `unresolved` 字段、追加版本、修订关系拒绝和 observed-only 边界。
- 后端契约测试：`/research/evidence?evidence_type=financial_report` 的来源、详情、时间和权限字段。
- 真实验收：标准 `start-local` 后，显式采集固定样本，验证两份 PDF、批次、Hash、日期精度、详情未解析状态和六个安全锁。
- 回归验收：核心只读数据契约、前端类型检查与构建通过。

## 明确不做

- 不采集半年报、一季报、三季报、摘要、业绩预告、快报或全市场历史财报。
- 不从 PDF 提取财务指标，不更新 `fundamental.financial_reports`，不形成因子、候选或回测输入。
- 不新增第三方依赖、定时采集、第二 Provider 或运行时 fallback。
- 不开启任何发布、回测、交易、AI 下单或定时下单开关。

## 实施前确认点

1. 接受 ADR-014 的年报全文最小范围与 `review_required` 使用状态。
2. 确认固定样本 `000001.SZ` 与 `600000.SH`；如需替换，只能在实施前更新本说明和测试固定输入。
3. 确认“详情未解析”可作为原文观察状态，不被误解为财报口径、财务因子或 Research Readiness。
