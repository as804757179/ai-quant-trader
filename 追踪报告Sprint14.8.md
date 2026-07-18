# 追踪报告 Sprint14.8：研究来源条款证据与许可预审登记

日期：2026-07-16  
状态：完成，真实验收通过

## 1. 结论

Sprint14.8 已按 A → B → C → D 顺序完成：

1. 固定 CNINFO 与 GDELT 的四个官方证据 URL 和精确 `source_scope`。
2. 通过 ADR-018 与迁移 022 建立两张数据库级追加式审计表。
3. 实现显式官方条款采集、失败审计、Hash 版本追加和本地预审追加。
4. 新增只读 `GET /api/v1/research/source-usage-evidence`，并在多维资格预审中附加来源证据引用。
5. 完成真实采集、拒绝路径、完整只读回归和安全边界验收。

本 Sprint 没有 `approved` 路径，没有修改现有证据的 `usage_status`，没有授予 Research Readiness，也没有开启候选、回测或交易能力。

## 2. 真实条款证据

| Provider | 文档 | `terms_evidence_id` | 字节数 | SHA-256 |
| --- | --- | --- | ---: | --- |
| CNINFO | 官网及免责声明 | `7eeff51b-b5fd-4f94-bd27-d0c3aaf0cf95` | 109516 | `0a626cbb7cf2f2674a4b22b72f35c476b613ff58cc2f295c2b7796d44bcdfa61` |
| CNINFO | 公告栏目 | `9697cbab-a9cd-432b-96d6-58a161dfa61a` | 66325 | `8519dfaebf64a92d982f5ba5c40257b3dc52ed1549f01362c899189ed64d84b4` |
| GDELT | Terms of Use | `7f5f0322-1144-4aa4-9891-79726afeca39` | 24355 | `384754b514042255c4542d51dc1e631da55c83c67d46a92b53b48a812d94be6b` |
| GDELT | GAL RSS 产品说明 | `32b16d61-766f-4edf-8c5f-2dce6feecb60` | 44741 | `8ed50b65ca1d61e52a411ef61610ec5d3eb6bf4b10ab637b0b8039e6f893f441` |

四条记录均为 `observed`，保存实际获取时间、原始响应 Hash、字节数、内容类型和采集器版本；未保存条款正文副本。

## 3. 许可预审状态

CNINFO 与 GDELT 均已分别记录以下五类使用范围：

- `manual_observation`
- `automated_fetch`
- `local_storage`
- `derived_research`
- `redistribution`

共 10 条预审，全部为：

- `decision_status=review_required`
- `identity_assurance=unverified`
- `policy_version=source-usage-pre-review-v1`

GDELT 再分发记录保留“引用 GDELT 并链接官网”的条款条件。该条款证据只覆盖 GAL RSS 元数据，不传播到第三方新闻正文、图片、附件或目标站点抓取权利。

## 4. 数据库与接口结果

- Alembic 当前版本：`022 (head)`。
- `market.research_source_terms_evidence`：数据库触发器拒绝 UPDATE/DELETE。
- `market.research_source_usage_reviews`：数据库触发器拒绝 UPDATE/DELETE，外键使用 `ON DELETE RESTRICT`。
- 数据库约束拒绝非固定来源、非官方 URL、无原因失败记录、`approved` 和已认证身份。
- 相同 URL+Hash 复用既有证据；新 Hash 追加新版本，旧记录保持不变。
- 只读 API 返回 2 个来源、4 条条款证据、10 条预审和各来源五类最新预审。
- 公告 1 条、财报 14 条、新闻 12 条资格预审均附带来源证据引用，并继续包含 `PROVIDER_USAGE_PERMISSION_UNAPPROVED`。

## 5. 验收证据

执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_research_source_usage_evidence.ps1
```

结果：PASS。

已验证：

- 固定来源与四个官方 URL。
- 原始响应 Hash、字节数和获取时间完整。
- 新 Hash 追加、旧版本保留。
- 非官方 URL、空失败原因、`approved`、UPDATE 和 DELETE 均被真实 PostgreSQL 拒绝。
- 验收事务完整回滚，没有产生测试审计记录。
- 27 条原始研究证据的 ID、Hash、可得时间和 `usage_status` 不变。
- 22 条 rejected 证据继续保持拒绝。
- 三个多维资格预审 Profile 均为 observed-only、`research_readiness=not_granted`。
- 六个发布与交易锁关闭，AI 与定时任务来源订单均为 0。
- 后端只读契约 35 项通过，前端只读契约、TypeScript 检查和生产构建通过。

## 6. 实施中发现并解决的问题

1. 首次资格预审真实调用暴露 SQL 未选择 `provider/source`，导致来源上下文关联出现 `KeyError`。已补充两个只读字段并通过三类 Profile 真实接口验证。
2. 一次标准停止流程遇到 Windows 前端进程树退出时序竞争。未直接强杀；确认登记 PID 及子进程已自然退出后，通过标准停止/启动脚本恢复并验收通过。
3. 新验收脚本最初为 UTF-8 无 BOM，Windows PowerShell 5.1 无法正确解析中文。已规范为 UTF-8 BOM，并设置 Python 管道 UTF-8 编码。

## 7. 保持关闭的边界

- CNINFO 与 GDELT 的许可状态仍未获有权主体认证批准。
- `authorization_granted=false`，`provider_usage_permission` 不会 validated。
- `ready=0`；不新增候选、回测、策略、风险、Paper、Live 或订单入口。
- 不抓取新闻正文，不扩大 Provider、样本、定时任务或前端审批页面。

## 8. 下一阶段建议

建议 Sprint14.9 仅对当前两份已观察但尚未本地归档的财报 PDF，先建立与既有 Hash 完全匹配的受控原文快照，再建设离线、只读的页级事实定位语义；继续保持 observed-only 与发布锁关闭。开始前先确认原文输入方式、字段范围、定位粒度、期间/报表范围/币种单位的 fail-closed 规则；不得借解析工作扩大 CNINFO 自动采集范围。
