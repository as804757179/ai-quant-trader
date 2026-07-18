# Sprint14.3 追踪报告

生成日期：2026-07-15（Asia/Shanghai）

## 任务

建立多维研究数据的最小证据观察能力：补齐当前年度沪深认证交易日历，试点归档固定 Provider 的上市公司公告，并保留来源、抓取时间、原文 Hash、可得时间与失败审计。范围只覆盖公告试点，不接入新闻、财报、候选、回测或订单。

## 当前结论

**PASS（真实端到端验收）**。2026-07-15 已确认 3000、8000、8080 的服务均由有效运行登记管理，PID、启动时间和命令指纹匹配；随后通过 `scripts\stop-local.ps1` 安全停止，并通过 `scripts\start-local.ps1` 应用迁移 018、加载当前代码和完成本地环境验收。

`scripts\verify_research_evidence.ps1` 已真实采集 `000001.SZ` 的 1 条巨潮公告，并完成数据库、只读 API、全年交易日历和交易安全锁的端到端验收。

## 已实现

- 新增 ADR-013 与 Sprint14.3 设计，定义多维证据为独立 `observed-only` sidecar，不写入 Data Certification 或 Research Readiness。
- 新增迁移 018：
  - `market.research_evidence_batches`：记录固定 Provider 请求、响应 Hash、状态和失败原因。
  - `market.research_evidence`：记录公告来源、发布者、原文 URL、外部文档 ID、PDF Hash、来源日期、首次观测时间、可得时间、版本和质量状态。
  - 按沪深交易所 2026 年官方休市安排补齐全年日历，重复日期保持既有记录不变。
- 巨潮公告试点固定 Provider 为 `cninfo`，不使用 fallback；每次显式调用最多读取 5 条公告并下载 PDF 计算 SHA-256。
- 当来源只提供日期时，保存 `source_published_date` 与 `publication_time_precision=date`；不伪造精确发布时间，`available_at` 仅为系统首次成功观测时间。
- 新增显式采集脚本、Worker 审计存储、只读 `/research/evidence` 与 `/research/evidence/batches` 接口；未加入 Celery Beat。

## 已验证证据

| 验证 | 实际结果 |
| --- | --- |
| Python 与 PowerShell 语法检查 | PASS |
| 补丁格式检查 | PASS |
| 后端测试 | `13 passed` |
| Worker 测试 | `4 passed` |
| a-stock-data 公告 Provider 测试 | `1 passed` |
| 固定 Provider 真实读取 | PASS：`000001.SZ` 返回 `cninfo`、无 fallback、查询响应 Hash 与 PDF Hash 均为 64 位、原文为 119959 字节 PDF |
| 标准停止与启动 | PASS：仅停止登记的 6 个服务，RedBeat 锁已清理；`scripts\start-local.ps1` 环境验收通过 |
| 迁移与真实端到端验收 | PASS：迁移 018 已生效，公告证据批次 `e9e931d0-3cb8-489c-8e85-688cd0e7a25a` 状态为 `success` |
| 证据 API 与时间语义 | PASS：`cninfo`、`cninfo_listed_company_disclosure`、64 位原文 Hash、日期精度、`system_first_observed`、`review_required` 均已返回 |
| 日历与安全边界 | PASS：市场状态为 `closed`，`observed_only=true`、`research_readiness=not_granted`、不可交易、不可创建订单；六个锁关闭，AI/定时订单均为 0 |

## 已解除的阻塞项

- 运行登记已恢复并完成 PID、启动时间和命令指纹核验；未执行按端口或模糊进程名终止。
- 迁移 018 已通过标准启动流程应用，研究证据表和只读 API 可用。
- 当前市场状态已从 `calendar_not_covered` 恢复为 `closed`，全年交易日历覆盖生效。

## 数据与安全边界

- 公告证据的 `usage_status` 固定为 `review_required`；巨潮公开页面的自动化使用许可没有被本任务静默批准。
- 公告证据始终返回 `observed_only=true`、`research_readiness=not_granted`、`tradable=false`、`order_created=false`。
- 未改动 Data Certification、Research Readiness、Backtest、Screener、Risk Engine、Execution Gate、AI 下单或六个发布/交易锁。
- 不接入新闻与财报；它们必须各自完成 Provider、许可、时间语义和失败策略设计后再实施。

## P0 / P1 / P2

- **P0（已解决）：** 旧运行版本在 Sprint14.3 文件写入前启动；已通过有效登记的标准停止/启动流程完成恢复。
- **P1：** 巨潮公告列表只提供日期精度，不能作为精确历史可得时间；本阶段已按 `system_first_observed` 保守处理。
- **P1：** 新闻、财报与第二 Provider 交叉验证尚未实施。
- **P2：** Chromadb/RAG 空检索与前端单包体积提示为既有问题。

## 回滚与下一步

代码回滚会停止显式公告采集和只读展示；已写入证据与失败批次属于审计事实，不能通过删除记录制造未发生。交易日历回滚仅删除本 Sprint 新增且官方来源引用匹配的行。

下一步进入 Sprint14.4-A：先设计财报证据的固定 Provider、授权状态、报告口径、修订链、时间语义和失败审计；在设计确认前不采集财报、不加入调度、不改变 Research Readiness 或交易边界。

本 Sprint 的标准验收命令为：

```powershell
scripts\start-local.ps1
scripts\verify_research_evidence.ps1
```

上述标准启动、迁移、真实公告入库、只读 API、日历覆盖和六个安全锁均已通过，Sprint14.3 已签收。
