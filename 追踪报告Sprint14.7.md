# Sprint14.7 追踪报告

生成日期：2026-07-15（Asia/Shanghai）

## 任务

完成公告、财报和新闻证据的多维 Research Readiness 资格预审：只验证显式授权键、Requirement Profile、字段证据与拒绝路径；不授予 Research Readiness，不改变证据、人工复核、候选、回测、策略、风险或订单数据。

## 当前结论

**PASS（真实端到端验收）**。标准 `scripts\stop-local.ps1` / `scripts\start-local.ps1` 已安全重启并等待 Watchdog 就绪；只读预审 API、真实验收脚本、后端完整回归和核心只读前端回归均通过。

本 Sprint 的正确结果是 **0 条 `ready`**，不是放行任何研究或交易路径。

## 已实现

- 新增 ADR-017，冻结多维证据 Profile、授权键、阻塞代码、输入指纹和不传播边界。
- 新增独立 `ResearchEvidenceRequirementProfile`；不修改既有 K 线 `ResearchDataRequirementProfile` 或 `ResearchReadinessService`。
- 新增纯只读 `ResearchEvidenceReadinessService`，每次调用必须显式声明 `research_use_scope`、`requirement_profile` 与完整 `required_fields`。
- 新增 `GET /api/v1/research/evidence/readiness-audit`。它只读取既有证据、财报详情、新闻详情和最新新闻人工复核，不新增表、不写入审计快照。
- 每个结果返回授权键、已验证/未解决/拒绝字段、稳定阻塞代码、中文阻塞说明、`policy_version` 和规范化输入 SHA-256 指纹。
- 所有响应持续返回 `observed_only=true`、`research_readiness=not_granted`、`tradable=false`、`order_created=false`。
- 新增 `scripts\verify_research_evidence_readiness_audit.ps1`；脚本只发出 GET 请求，并验证原始证据快照不变。

## 真实预审结果

| Profile | 实际证据数 | `review_required` | `rejected` | `ready` | 验收样本输入指纹 |
| --- | ---: | ---: | ---: | ---: | --- |
| `ANNOUNCEMENT_EVENT_RESEARCH_V1` | 1 | 1 | 0 | 0 | `304b6173fc395afb1de93387ca7ae79418da031cad89d5e3b7c0c9615454f075` |
| `FINANCIAL_REPORT_FUNDAMENTAL_RESEARCH_V1` | 14 | 2 | 12 | 0 | `02e4dbba426c88d5807dece5bb2944e4be97729ba36b713db602c9d62023a2c2` |
| `NEWS_EVENT_RESEARCH_V1` | 12 | 2 | 10 | 0 | `50ab37c1fd0181593d0fbb6d65ac0c10d47ffd1b3d1f7291c9f25a9386dbb9ce` |
| 合计 | 27 | 5 | 22 | 0 | — |

### 当前有效阻塞

- 公告：来源自动化使用权限未批准、公开时间只有日期精度、事件内容未解析、修订链未验证，以及最终 `READINESS_GRANT_NOT_IMPLEMENTED`。
- 财报：来源自动化使用权限未批准；报告期截止日、合并口径、币种/单位、审计意见和财务事实未解析；12 条原始 rejected 证据继续 rejected。
- 新闻：RSS 条目 Hash 不是正文 Hash、来源公开时间未确认、标题别名关联未完成验证、人工复核人未认证、15 分钟滚动窗口不代表完整覆盖；10 条原始 rejected 证据继续 rejected。
- 即使新闻人工复核为 `title_link_relevant`，仍不能跨越正文、时间、身份、来源许可和最终授权阻塞；`title_link_irrelevant` 在单元测试中稳定返回 `NEWS_ASSOCIATION_REJECTED` 与 `rejected`。

## 已验证

| 验证项 | 实际结果 |
| --- | --- |
| 标准启停与 Watchdog | PASS：两次受管 `stop-local/start-local` 循环完成，最终前端/API 与 Watchdog 验收均通过 |
| 显式声明 | PASS：缺少 `required_fields` 返回 422 `INVALID_EVIDENCE_READINESS_DECLARATION`；Profile/证据类型不匹配返回 422 `EVIDENCE_PROFILE_TYPE_MISMATCH` |
| 真实资格预审 | PASS：三类 Profile 的真实 observed 证据均为非 ready；22 条 rejected 证据保持拒绝 |
| 不可变性 | PASS：预审前后证据总数、证据 ID、原始 Hash、可得时间和 `usage_status` 快照一致 |
| 安全边界 | PASS：六个发布与交易锁关闭；AI 与定时任务订单均为 0 |
| 预审定向回归 | PASS：`python -m unittest discover -s tests -p "test_research_evidence*.py"`，17 项通过 |
| 后端完整回归 | PASS：`python -m pytest`，27 项通过 |
| 核心只读回归 | PASS：后端只读契约 27 项、前端只读契约 3 项、TypeScript 检查和 Vite 构建通过 |

## 实施中发现并修复的边界问题

- 缺少 `required_fields` 初始会触发 500。现改为显式空声明校验，稳定 fail closed 并返回 422。
- PowerShell 把 `$Profile` 解释为自动变量 `$PROFILE`，导致验收脚本丢失 Profile 参数。现统一改为 `$AuditProfile`，并保留 UTF-8 BOM 以兼容 Windows PowerShell 5.1 的中文日志解析。

## 未改变的边界

- 没有数据库迁移、数据写入、前端页面或第三方依赖。
- 没有把 `usage_status` 改为 `approved`，没有写入 `market.research_readiness_reviews`。
- 没有开启回测、选股、Paper、Live、AI 下单或定时下单开关。
- 没有抓取新闻正文、解析 PDF 财务数值、引入第二 Provider、定时采集或全市场扫描。

## 后续准入建议

1. 先建立来源自动化使用许可与审批主体的可审计登记；未获明确授权时继续保持 `review_required`。
2. 在许可和独立 ADR 确认后，优先处理财报原文元数据、修订关系与财务事实定位。
3. 随后处理公告精确公开时点、事件内容与修订链验证。
4. 最后才评估新闻正文级合法来源、正文 Hash、来源发布时间和已认证复核身份。

上述任一阶段若尝试改变 Research Readiness 或下游研究/交易授权，必须单独进行 ADR、安全评审、真实验收和用户确认。
