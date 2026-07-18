# ADR-014：财报证据观察试点语义

日期：2026-07-15  
状态：Accepted

## 背景

ADR-013 已建立公告的独立研究证据 sidecar，`market.research_evidence` 已预留 `financial_report` 类型，但没有财报期别、报表口径、单位、审计意见和修订关系的语义。现有 `fundamental.financial_reports` 与其 API 读取路径不具备本 Sprint 所需的原文、Hash、可得时间和版本审计，不能作为本试点输入。

巨潮资讯为现有固定公告 Provider，可按定期报告分类返回年报、半年报、一季报和三季报。其自动化使用许可尚未被批准，必须继续保持 `review_required`。

## 决策

1. Sprint14.4-B 仅试点巨潮年报全文 PDF：固定 Provider=`cninfo`、source=`cninfo_listed_company_disclosure`、分类=`category_ndbg_szsh`，不使用 fallback。每次显式人工调用最多为每个固定样本读取 1 条最新年报全文。
2. 只接受规范化标题以 `YYYY年年度报告` 严格结尾、且可带公司名称前缀的全文文档；摘要、业绩预告、快报、问询回复、社会责任报告及无法判定角色的文档写入 rejected 审计，不伪装成财报全文。
3. 通用证据表继续只保存不可变的原文与来源；新增一对一 `market.research_financial_report_details` 作为财报观察详情。它仅关联 `quality_status=observed` 的 `financial_report` 证据，至少记录：
   - `provider_category`、分类版本和标题原文；
   - `report_kind=annual`、`report_period_label`、`report_period_end`、期间精度；
   - 文档角色、合并/母公司口径、币种、金额单位和审计意见；
   - 修订标识、被修订证据 ID、修订关系状态和详情解析状态。
4. 年报标题可提供原始期间标签；未由原文明确解析的报告截止日、口径、币种、单位、审计意见或修订关系必须记录为 `unresolved`，不得推导、补齐或映射为数值因子。Sprint14.4-B 不解析财务指标、三大报表或审计文本。
5. 相同 `source_document_id` 出现新 `raw_hash` 时追加通用证据，不覆盖历史证据。不同文档 ID 的更正或修订仅在具备可审计的原文关联证据时建立关系；否则保留 `revision_relation_unresolved` 的拒绝审计。
6. 巨潮列表的时间语义沿用 ADR-013：仅保存 `source_published_date` 和原始时间字段，`source_published_at` 为空、`publication_time_precision=date`；`available_at=first_observed_at`，`availability_basis=system_first_observed`。
7. 财报证据始终为 observed-only。不得写入 Data Certification、Research Readiness、`fundamental.financial_reports`、候选、回测、策略、风险、执行、AI 下单或任一发布/交易锁。

## 后果

- 可审计地证明某份年报全文来自固定 Provider、何时被系统观察，以及其来源与版本是否可校验。
- 详情表允许显式展示“尚未解析”，避免把原文观察误认为财务口径或可用因子。
- 更正链在缺少可验证关联时会 fail closed，降低错误覆盖原始版本的风险。
- 半年报、一季报、三季报、摘要、财务指标解析和常驻采集均留待后续独立评审。

## 回滚

回滚实现会停止显式年报采集和只读详情展示；已写入的批次、原文 Hash、observed/rejected 证据及详情均为审计事实，不通过删除记录伪造未发生。任何删除或重建详情关系都必须保留可追踪的迁移与原因。
