# Sprint14.4 追踪报告

生成日期：2026-07-15（Asia/Shanghai）

## 任务

在 Sprint14.3 的公告证据 sidecar 之上，完成财报全文的最小只读观察试点：固定巨潮资讯 Provider，仅由显式人工命令采集 `000001.SZ`、`600000.SH` 各 1 份年报全文 PDF，并保留来源、原文 Hash、时间语义、拒绝审计和未解析的财报详情。

## 当前结论

**PASS（真实端到端验收）**。标准 `start-local` 流程已应用迁移 019 并通过环境验收；随后 `scripts\verify_financial_report_evidence.ps1` 已完成真实采集、数据库写入、只读 API、安全锁和回归检查。

## 已实现

- 固定 Provider=`cninfo`、来源=`cninfo_listed_company_disclosure`、分类=`category_ndbg_szsh`，没有运行时 fallback。
- 仅接受规范化标题以 `YYYY年年度报告` 结尾的全文 PDF；允许公司名称前缀。摘要、修订关系未核验和超出 1 份上限的文件均保留 rejected 审计，不会静默丢弃或替代全文。
- 新增一对一 `market.research_financial_report_details` sidecar，未写入 `fundamental.financial_reports`。
- 固定语义：`source_published_at=NULL`、`publication_time_precision=date`、`available_at=first_observed_at`、`availability_basis=system_first_observed`、`usage_status=review_required`。
- 财报详情仅标记为 `metadata_observed`：报告类型为 `annual`，报告期末、合并口径、币种、单位和审计意见均为 `unresolved`，不从标题推断财务指标或可交易因子。
- 采集入口仅为显式脚本 `scripts\collect_financial_report_evidence.py`；未接入 Celery Beat、RAG、Data Certification、Research Readiness、候选、回测、策略、风控或订单链路。

## 已验证证据

| 验证项 | 实际结果 |
| --- | --- |
| 标准重启与迁移 | PASS：`scripts\stop-local.ps1` 后由 `scripts\start-local.ps1` 安全启动，迁移 019 生效 |
| 真实固定样本采集 | PASS：`000001.SZ` 批次 `b3840319-10a7-46b3-a9d6-1191c524d663`、`600000.SH` 批次 `98bcbac1-d195-409f-866a-6aeb59609b91`；各接受 1 份全文并审计拒绝 4 项，批次为预期的 `partial` |
| 原文与时间语义 | PASS：两条观察证据均有 64 位 SHA-256，发布时刻为空、日期精度为 `date`，可得时间为系统首次观察时间 |
| 财报详情 sidecar | PASS：两样本均返回 `annual`、`full_report`、`metadata_observed` 和全部约定的 `unresolved` 值 |
| Provider 单元测试 | PASS：4 passed |
| Worker 单元测试 | PASS：4 passed |
| 后端契约测试 | PASS：4 passed |
| 核心只读回归 | PASS：后端 14 passed、前端契约测试 3 passed、TypeScript 检查与前端构建通过 |
| 发布与交易边界 | PASS：六个发布/交易锁关闭，AI 与定时任务来源订单均为 0；结果保持 `observed_only=true`、`research_readiness=not_granted`、不可交易、不可创建订单 |

## 已处理的审计事件

首次采集 `600000.SH` 时，公司名称前缀使严格标题规则将全文误判为非全文，产生了保留的 `validation_failed` 批次 `87518793-84cb-44ce-9986-b0c8b55574ae`。规则已收紧为“允许公司名前缀但必须以 `YYYY年年度报告` 结尾”，并以新的真实批次成功验证；旧失败记录未删除，仍作为审计事实保留。

## 边界与后续工作

- P1：尚未解析 PDF 正文、三大报表或财务指标；修订关系没有可审计原文关联时继续拒绝，不推断关系。
- P1：试点限于两个固定样本和显式人工调用；全市场扩展、定时采集或第二 Provider 需要独立授权与验收。
- P2：当前环境仍提示 Chromadb 不可用，RAG 按既有设计降级为空检索；这不影响本次财报证据的采集、API 或安全边界。
- 建议下一步先进行新闻、公告、财报等多维研究数据的统一来源/时间/Hash/可得时间语义设计评审；未经新的确认，不启动自动采集或任何研究、交易链路接入。
