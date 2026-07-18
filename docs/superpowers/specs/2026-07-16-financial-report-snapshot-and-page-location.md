# Sprint14.9：财报原文快照与页级事实定位试点

状态：完成，真实验收通过  
日期：2026-07-16

## 1. 决策摘要

下一阶段建议优先建设固定两份年报的原文快照保管、页级文本提取审计和最小元数据定位，不进入财务指标、因子、候选、回测或交易。

该任务直接延续原始目标中的以下主线：

`真实多维数据 → Provider/原文/Hash/可得时间 → 原文事实定位 → 多维 Research Readiness → 后续研究候选`

Sprint14.8 已补齐来源条款证据和使用预审，但不能由代码产生许可批准。Sprint14.9 继续保持 CNINFO 的 `local_storage`、`derived_research` 为 `review_required`，所有输出只表示观察和定位，不授予研究使用权。

## 2. 当前真实基线

数据库当前有 14 条财报证据，其中 2 条 `observed`、12 条 `rejected`。两条 observed 年报已有 URL、字节数、SHA-256、首次观察时间和财报详情 sidecar：

| 股票 | Evidence ID | CNINFO 文档 ID | 原文 URL | 已记录字节数 | 已记录 SHA-256 |
| --- | --- | --- | --- | ---: | --- |
| `000001.SZ` | `cef779d8-96d7-4a01-8ae3-2b9a023447e0` | `1225022887` | `https://static.cninfo.com.cn/finalpage/2026-03-21/1225022887.PDF` | 1975076 | `2273565ecbe1b32536631fd4a019a4f4a990f4c793cfd5b70eae90d44d3ff16c` |
| `600000.SH` | `522d97a3-ff33-4001-81da-6575cd4ad8e3` | `1225062336` | `https://static.cninfo.com.cn/finalpage/2026-03-31/1225062336.PDF` | 36054699 | `e4d1cff0461c0ef24d26551ca68e31ad323a1b3eadd8a3c03f00feada364de22` |

重要事实：现有采集实现只在内存中读取 PDF 以计算 Hash 和字节数，未把这两份 PDF 原始字节保存到本地证据库；仓库及受管运行目录当前没有这两份财报快照。因此不能直接宣称“离线解析已归档 PDF”。

当前仍为 `unresolved` 的财报字段：

- `report_period_end`
- `consolidation_scope`
- `currency_code`
- `currency_unit`
- `audit_opinion`
- `financial_fact_provenance`
- 可验证的修订关系

## 3. 目标与成功标准

### 目标

1. 为上述两个固定 Evidence ID 建立原始 PDF 本地快照保管记录，证明本地字节与既有证据 Hash 完全一致。
2. 使用项目已安装的 `pypdf==3.17.4` 做确定性页级文本提取，不新增第三方依赖或 OCR。
3. 记录每页提取状态、字符数和规范化文本 Hash，使后续事实定位可复现。
4. 只定位财报期间、财务报表币种/单位、审计意见章节和报表范围候选，不提取或发布财务数值。
5. 所有定位结果保持 `located`、`ambiguous`、`unresolved` 或 `rejected`，不自动写成 validated。
6. 保持 27 条原始证据、来源许可预审、Research Readiness 和六个安全锁不变。

### 成功标准

- 只允许两个固定 Evidence ID；其他证据、URL、Provider、`unknown`、`synthetic` 被拒绝。
- 每次快照取得都必须重新计算 SHA-256 和字节数；与既有证据任一不一致时记录 `hash_mismatch`，不得进入解析。
- 原始 PDF 使用逻辑 `storage_key` 保存在 `%LOCALAPPDATA%\AIQuantTrader\evidence\financial_reports\cninfo\`，数据库不保存机器相关绝对路径，仓库不提交大型 PDF。
- 快照采用临时文件 + 原子重命名；失败不得留下可被误认成完整快照的目标文件。
- 页码固定为 PDF 的 1-based 物理页号；页级 Hash 的规范化规则和解析器版本必须固定。
- 无文本层、乱码、加密、页提取异常或多个冲突候选都必须 fail closed；本 Sprint 不用 OCR、AI 或人工猜测补齐。
- 不更新 `market.research_financial_report_details` 中现有 `unresolved` 值，不写入 `fundamental.financial_reports`。
- 多维资格预审仍为 2 条 `review_required`、12 条 `rejected`、0 条 ready，并继续包含 `PROVIDER_USAGE_PERMISSION_UNAPPROVED`、`FINANCIAL_FACTS_UNPARSED` 和 `READINESS_GRANT_NOT_IMPLEMENTED`。

## 4. 输入取得与许可边界

### 推荐输入方式

使用显式、一次性命令重新读取上述两个已固定 CNINFO PDF URL，并把响应与数据库既有 `raw_hash`、`document_bytes` 做完全匹配后才写入本地快照。

该方式具有以下限制：

- 只允许人工显式运行，不接入 Celery、Beat、启动脚本或定时任务。
- 不查询新财报、不扩大股票、不修改 CNINFO 分类、不使用 fallback。
- Hash 不一致时只记录失败；不得把新字节自动绑定到旧 Evidence ID，也不得覆盖旧 Hash。
- 用户确认该技术试点只表示允许按当前固定范围实施，不代表 CNINFO 已授予 `local_storage` 或 `derived_research` 许可。

### 备选输入方式

若不确认一次性重新读取，则必须由用户提供两份本地 PDF；导入时仍须与上述 Hash 和字节数完全一致。未取得匹配字节前，Sprint14.9 只能完成 ADR、迁移和拒绝路径，不能宣称真实解析验收通过。

## 5. 数据模型

建议新增迁移 `023`，只创建追加式 sidecar，不修改迁移 019 的原始详情记录。

### 5.1 `market.research_financial_report_snapshots`

| 字段 | 规则 |
| --- | --- |
| `snapshot_id` | UUID，追加式主键。 |
| `evidence_id` | 仅引用两个固定 observed 财报证据，`ON DELETE RESTRICT`。 |
| `source_usage_review_id` | 必须引用 CNINFO 当前 `local_storage` 预审；缺失或状态不是 `review_required` 时拒绝执行。该引用只记录治理状态，不构成批准。 |
| `expected_raw_hash`、`observed_raw_hash` | 均为 SHA-256；成功时必须相同。 |
| `expected_bytes`、`observed_bytes` | 成功时必须相同且大于 0。 |
| `content_type` | 成功时固定为可接受 PDF 类型。 |
| `acquisition_method` | `explicit_refetch` 或 `user_supplied_file`；首期只实现用户确认的一种。 |
| `storage_key` | 成功时使用相对逻辑键；失败时为空。 |
| `status` | `observed`、`hash_mismatch`、`fetch_failed`、`validation_failed`、`write_failed`。 |
| `failure_reason` | 非 observed 时必填。 |
| `fetched_at`、`received_at`、`stored_at` | 分离 Provider 获取、系统接收和本地持久化时点。 |
| `collector_version`、`created_at` | 固定版本并由数据库记录时间。 |

同一 Evidence ID 与相同 Hash 的重复显式操作可返回既有 observed 快照；新 Hash 不能覆盖旧记录。表级触发器拒绝 UPDATE 和 DELETE。

### 5.2 `market.research_financial_report_parse_runs`

| 字段 | 规则 |
| --- | --- |
| `parse_run_id` | UUID，追加式主键。 |
| `snapshot_id` | 只允许引用 `status=observed` 的快照。 |
| `source_usage_review_id` | 必须引用 CNINFO 当前 `derived_research` 预审；缺失或状态不是 `review_required` 时拒绝解析。 |
| `parser_name`、`parser_version` | 固定 `pypdf/3.17.4` 与项目解析策略版本。 |
| `normalization_version` | 固定页文本规范化规则。 |
| `status` | `success`、`partial`、`text_unavailable`、`parse_failed`、`validation_failed`、`write_failed`。 |
| `page_count`、`text_page_count` | 来自真实 PDF；不得推测。 |
| `failure_reason`、`started_at`、`completed_at` | 失败和时点可审计。 |

同一 `snapshot_id + parser_version + normalization_version` 不重复制造相同成功运行。表级触发器拒绝 UPDATE 和 DELETE。

### 5.3 `market.research_financial_report_page_evidence`

| 字段 | 规则 |
| --- | --- |
| `page_evidence_id` | UUID，追加式主键。 |
| `parse_run_id`、`page_number` | 页号从 1 开始，运行内唯一。 |
| `extraction_status` | `text_observed`、`empty`、`failed`。 |
| `text_hash`、`character_count` | `text_observed` 时必填；不在数据库保存整页文本。 |
| `failure_reason` | 非 `text_observed` 时说明原因。 |

### 5.4 `market.research_financial_metadata_locations`

| 字段 | 规则 |
| --- | --- |
| `location_id` | UUID，追加式主键。 |
| `parse_run_id`、`page_evidence_id` | 绑定具体解析运行和物理页。 |
| `field_name` | 首期只允许 `report_period_end`、`statement_currency_unit`、`audit_opinion_section`、`statement_scope_heading`。 |
| `raw_value`、`normalized_value` | 只保存最小匹配值；不能保存整页或长段正文。 |
| `match_start`、`match_end`、`anchor_hash` | 形成可复核页内定位；范围必须合法。 |
| `statement_scope` | `unresolved`、`consolidated`、`parent_company`；只绑定当前定位，不传播为整份年报口径。 |
| `status` | `located`、`ambiguous`、`unresolved`、`rejected`。 |
| `locator_version`、`created_at` | 固定版本，追加式。 |

## 6. 关键语义取舍

1. 年报通常同时包含合并报表和母公司报表，因此不得把任一章节标题直接升级成整份文档唯一的 `consolidation_scope`。
2. `statement_currency_unit` 只描述定位到的报表或章节，不能自动传播到全文或所有财务事实。
3. “标准无保留意见”等文本只能作为审计意见候选定位；没有完整审计报告上下文和后续复核时，不更新现有 `audit_opinion`。
4. 页级文本提取正确不等于财务事实正确；本 Sprint 不建立财务数值、因子或 Research Readiness 许可。
5. 现有一对一详情表保持原始观察状态，避免把后续解析结果覆盖成单一当前真相；后续人工复核应另建追加式记录。

## 7. 开发顺序

### Sprint14.9-A：输入方式与语义确认

- 确认采用 `explicit_refetch` 还是 `user_supplied_file`。
- 冻结两个 Evidence ID、Hash、字节数、URL 和运行目录。
- 新增 ADR-019，明确快照、页号、文本 Hash、定位状态和不传播边界。
- 未确认输入方式前不开始真实快照。

### Sprint14.9-B：原文快照保管

- 新增迁移 023 的快照表和数据库拒绝约束。
- 实现显式快照脚本、来源使用预审引用、原子写入、Hash/字节数匹配和失败审计。
- 对两个固定 Evidence ID 取得真实 observed 快照；任一不匹配则停止后续解析。

### Sprint14.9-C：页级提取与元数据定位

- 使用现有 `pypdf==3.17.4` 提取页文本。
- 写入解析运行、页级 Hash 和四类最小定位结果。
- 不引入 OCR、表格识别、LLM、RAG 或财务数字解析。

### Sprint14.9-D：只读 API 与真实验收

- 在现有财报证据响应中增加 snapshot、parse run 和 location sidecar；不改变原字段。
- 新增显式验收脚本，验证固定范围、Hash、版本追加、失败路径和数据库不可变性。
- 复核 27 条原证据快照、10 条来源预审、三类资格预审、六锁和订单审计均不变。
- 生成 `追踪报告Sprint14.9.md`。

## 8. 预计产出文件

- `docs/adr/ADR-019-financial-report-snapshot-and-page-location.md`
- `backend/alembic/versions/023_financial_report_snapshot_location.py`
- `worker/services/financial_report_snapshot_store.py`
- `worker/services/financial_report_page_locator.py`
- `scripts/snapshot_financial_report_evidence.py`
- `scripts/locate_financial_report_metadata.py`
- `backend/app/api/research.py` 的只读 sidecar 扩展
- 对应 backend/worker 定向测试
- `scripts/verify_financial_report_snapshot_location.ps1`
- `追踪报告Sprint14.9.md`

默认不新增前端文件。

## 9. 验收矩阵

| 验收项 | 必须结果 |
| --- | --- |
| 输入范围 | 仅两个固定 Evidence ID 和 CNINFO PDF URL |
| 原文一致性 | Hash、字节数与既有证据完全一致；不一致 fail closed |
| 使用治理引用 | 快照绑定 `local_storage` 预审；解析绑定 `derived_research` 预审，均不得解释为批准 |
| 本地保管 | 逻辑 storage key、原子写入、仓库不提交大型 PDF |
| 解析器 | 复用 `pypdf==3.17.4`，版本可追踪，无新增依赖 |
| 页级证据 | 1-based 页号、文本 Hash、字符数、失败原因可审计 |
| 定位范围 | 仅四类元数据定位，不解析财务数值 |
| 歧义处理 | 多候选、乱码、无文本层均不推断、不补齐 |
| 不可变性 | 新表拒绝 UPDATE/DELETE；旧详情不改写 |
| 原有证据 | 27 条证据的 ID、Hash、可得时间和 usage_status 不变 |
| 来源许可 | 10 条预审不变；CNINFO 仍为 review_required |
| Research Readiness | 0 ready，现有阻塞继续存在 |
| 安全边界 | 六锁关闭，AI 与定时任务订单为 0 |

## 10. 明确不做

- 不扩大到半年报、季报、摘要、其他股票或历史批量采集。
- 不更新 `fundamental.financial_reports`，不生成财务指标、同比环比、因子、评分或候选。
- 不把定位结果写回迁移 019 的 `unresolved` 字段。
- 不新增 OCR、表格解析器、LLM、RAG、第二 Provider 或第三方依赖。
- 不建立定时任务、全市场扫描、前端页面或公共写 API。
- 不把用户对技术试点的确认解释为 Provider 许可批准。
- 不打开回测、Screener、Paper、Live、AI 下单或定时下单。

## 11. 回滚

功能回滚停止快照和定位脚本及只读 sidecar；数据库追加记录和已经形成的本地证据文件继续保留，不通过删除伪造未发生。测试环境无真实记录时才允许 migration downgrade。存在真实快照时，删除本地文件必须单独制定保留、导出和审计方案。

## 12. 开始实施前确认点

1. 确认 Sprint14.9 只处理上述两个固定 Evidence ID，不扩大样本。
2. 确认输入方式：推荐 `explicit_refetch`；若选择 `user_supplied_file`，需先提供两份 Hash 完全匹配的 PDF。
3. 确认本阶段只做本地快照、页级 Hash 和元数据候选定位，不解析财务数值。
4. 确认 CNINFO 的 `local_storage`、`derived_research` 继续保持 `review_required`，所有输出仍为 observed-only。

## 13. 后续顺序

Sprint14.9 验收后，再根据真实页级提取质量制定 Sprint14.10“财务事实值与人工复核语义”。只有明确事实 Profile、期间、报表范围、币种单位、定位证据、修订链和认证复核主体后，才评估是否改变 `financial_fact_provenance`；不得从页面定位直接跳到财务因子、候选或交易。
