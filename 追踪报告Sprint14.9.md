# 追踪报告 Sprint14.9：财报原文快照与页级事实定位试点

日期：2026-07-16  
状态：完成，真实验收通过

## 1. 结论

Sprint14.9 已按 A → B → C → D 顺序完成：

1. 通过 ADR-019 与迁移 023 固定两份 CNINFO 年报、显式回抓方式、Hash/字节绑定和追加式数据边界。
2. 真实回抓两份 PDF，并保存到 `%LOCALAPPDATA%\AIQuantTrader\evidence\financial_reports\cninfo\`；数据库只保存逻辑 `storage_key`。
3. 使用项目已有 `pypdf==3.17.4` 提取 1-based 物理页文本，记录规范化文本 Hash、字符数和失败状态。
4. 保守定位报告期、币种/单位、审计意见章节和报表范围标题，并通过现有研究证据接口返回只读旁路。
5. 完成真实文件、PostgreSQL 不可变约束、接口、安全锁、来源许可与多维 Research Readiness 回归。

本 Sprint 没有解析财务数值，没有更新 `market.research_financial_report_details`，没有授予 Provider 使用许可或 Research Readiness，也没有打开候选、回测或交易能力。

## 2. 真实快照与解析结果

| 股票 | Evidence ID | 快照状态 | 字节数 | 解析状态 | PDF 页数 | 文本页数 | 定位记录 |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| `000001.SZ` | `cef779d8-96d7-4a01-8ae3-2b9a023447e0` | `observed` | 1975076 | `success` | 288 | 288 | 167 |
| `600000.SH` | `522d97a3-ff33-4001-81da-6575cd4ad8e3` | `observed` | 36054699 | `partial` | 454 | 452 | 195 |

两份本地 PDF 的 SHA-256 和字节数均与既有 observed 证据完全一致。`600000.SH` 有 2 页未提取到文本，已按页记录为不可提取，未伪装成全量成功。

## 3. 定位结果

两份年报的四类字段都存在多个文本候选，因此当前 362 条定位记录全部为 `ambiguous`：

| Evidence ID | 报告期候选 | 币种/单位候选 | 审计意见候选 | 报表范围标题候选 |
| --- | ---: | ---: | ---: | ---: |
| `cef779d8-96d7-4a01-8ae3-2b9a023447e0` | 100 | 46 | 11 | 10 |
| `522d97a3-ff33-4001-81da-6575cd4ad8e3` | 100 | 54 | 17 | 24 |

报告期候选按确定性规则最多保留 100 条并明确记录截断原因。系统没有从重复候选中猜测唯一值，因此迁移 019 的现有 `unresolved` 字段保持不变。

## 4. 数据库与接口

- Alembic 当前版本：`023 (head)`。
- 新增快照、解析运行、页级证据和元数据定位四张 append-only 表。
- 数据库触发器约束两个固定 Evidence ID、observed 原证据 Hash/字节、CNINFO `review_required/unverified` 使用审查及同一解析运行的页级绑定。
- 四张表的 UPDATE/DELETE 均被 PostgreSQL 拒绝。
- `GET /api/v1/research/evidence` 新增 `financial_report_snapshot_location` 只读旁路；原 `financial_report_detail` 未被覆盖。
- API 返回快照 Hash/字节、解析器与规范化版本、页数、文本页数以及带物理页码和 anchor Hash 的定位记录。

## 5. 验收证据

执行：

```powershell
scripts\verify_financial_report_snapshot_location.ps1
scripts\verify_research_source_usage_evidence.ps1
scripts\verify_research_evidence_readiness_audit.ps1
```

结果均为 PASS。已验证：

- 两份 PDF 本地文件存在，SHA-256 与字节数准确。
- 页级解析和 API 定位计数与数据库一致。
- 快照 UPDATE/DELETE 被真实 PostgreSQL 拒绝，验收事务已回滚。
- 27 条原始证据的 ID、Hash、可得时间和 `usage_status` 未变化。
- 来源许可仍为 `review_required/unverified`，`authorization_granted=false`。
- 三类多维资格预审保持 observed-only、`research_readiness=not_granted`。
- 22 条 rejected 证据保持拒绝。
- 六个发布与交易锁关闭，AI 与定时任务来源订单均为 0。
- 后端核心只读契约 41 项、前端只读契约 3 项、TypeScript 检查和生产构建通过。

## 6. 实施中发现并解决的问题

1. 快照数据库写入失败的回滚逻辑最初可能删除本次执行前已存在的有效同 Hash 文件。已收紧为只删除本次新建文件。
2. Sprint14.9 验收脚本最初为 UTF-8 无 BOM，Windows PowerShell 5.1 将中文按系统代码页解析并报语法错误。已改为 UTF-8 BOM 后真实重跑通过。
3. 年报内同一日期、单位和章节标题重复出现，简单命中不能证明唯一语义。定位器因此全部保留为 `ambiguous`，没有把候选误写成 validated 财务事实。

## 7. 保持关闭的边界

- 不解析或发布资产、负债、收入、利润、现金流等财务数值。
- 不使用 OCR、AI 或人工猜测补齐无文本页和冲突候选。
- 不扩大 CNINFO Provider、证据样本、自动抓取或定时任务范围。
- 不改变 `market.research_financial_report_details`、`fundamental.financial_reports`、策略、风险、组合、回测或订单语义。
- `ready=0`，六个发布与交易锁关闭。

## 8. 下一阶段建议

建议 Sprint14.10 先建设“章节/表头锚点消歧规则与人工复核输入”，目标是把当前 `ambiguous` 候选缩小为可复核的页级候选集，而不是直接写入财务事实。应先固定章节边界、候选排序证据、人工复核身份和 append-only 复核记录；继续不解析财务数值、不授予 Research Readiness、不扩大自动采集范围。
