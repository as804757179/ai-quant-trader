# ADR-019：财报原文快照与页级事实定位证据

日期：2026-07-16  
状态：Accepted

## 背景

Sprint14.4 已为两份固定 CNINFO 年报记录 URL、原始响应 SHA-256、字节数、首次观察时间和财报观察详情，但采集实现没有保留 PDF 原始字节。Sprint14.7 的财报资格预审因此仍无法复核页级原文事实，报告期截止日、报表范围、币种单位、审计意见和财务事实血缘均为 unresolved。

Sprint14.8 已记录 CNINFO 官方页面及 `local_storage`、`derived_research` 预审；两种范围仍为 `review_required/unverified`。技术试点不能被解释为 Provider 许可批准，也不能解除 `PROVIDER_USAGE_PERMISSION_UNAPPROVED`。

## 决策

1. 首期只处理以下两个既有 observed 财报 Evidence ID：

   - `cef779d8-96d7-4a01-8ae3-2b9a023447e0` / `000001.SZ` / CNINFO `1225022887`
   - `522d97a3-ff33-4001-81da-6575cd4ad8e3` / `600000.SH` / CNINFO `1225062336`

2. 原文输入固定为人工显式 `explicit_refetch`。脚本只能读取证据行已经记录的 `static.cninfo.com.cn/finalpage/...PDF` URL，不查询新报告、不接受调用方 URL、不 fallback、不接入定时任务。
3. 响应必须重新计算 SHA-256 和字节数，并与既有证据完全一致。任一不一致记录 `hash_mismatch`，不得写入 accepted 快照、不得解析、不得把新 Hash 绑定到旧 Evidence ID。
4. 原始 PDF 保存到 `%LOCALAPPDATA%\AIQuantTrader\evidence\financial_reports\cninfo\`，数据库只保存相对 `storage_key`。文件使用临时文件、刷新到磁盘和原子重命名，仓库不提交大型 PDF。
5. 快照必须引用当前 CNINFO `local_storage` 预审；解析运行必须引用当前 `derived_research` 预审。首期只允许引用 `review_required/unverified`，用于记录治理状态而不是许可批准。
6. 使用项目现有 `pypdf==3.17.4` 做确定性页级文本提取。页码为 1-based PDF 物理页号；每页只持久化提取状态、规范化文本 SHA-256 和字符数，不在数据库保存整页文本。
7. 首期定位字段只允许：

   - `report_period_end`
   - `statement_currency_unit`
   - `audit_opinion_section`
   - `statement_scope_heading`

   定位保存最小原始值、规范化值、页号、字符区间和锚点 Hash；状态只允许 `located`、`ambiguous`、`unresolved`、`rejected`。
8. 年报可同时包含合并报表和母公司报表，`statement_scope` 只绑定当前定位，不能传播为整份文档唯一口径。币种单位和审计意见同样不能跨章节或跨事实传播。
9. 新增四张追加式 sidecar：快照、解析运行、页级证据和元数据定位。数据库触发器拒绝 UPDATE/DELETE；不修改 `market.research_financial_report_details`、`market.research_evidence` 或 `fundamental.financial_reports`。
10. 本 Sprint 不解析财务数值，不改变任何财报字段的 validated 状态，不授予 Research Readiness，不触达候选、回测、策略、风险、AI 或订单路径。

## 后果

- 两份固定年报可由本地原始字节和页级 Hash 复核，后续事实值解析不再依赖不可复现的网络响应。
- 无文本层、加密、乱码、冲突候选或解析失败会形成明确审计，而不是由 OCR、AI 或默认值补齐。
- 定位证据与原观察详情分离，避免后续解析覆盖历史 unresolved 事实。
- 真实定位成功仍不等于来源获批、事实已复核或研究可用。

## 回滚

功能回滚停止显式快照、解析和只读 sidecar。数据库审计记录及已形成的本地快照继续保留；存在真实快照时不得通过删除文件或 downgrade 伪造未发生，必须先制定导出、保留与审计方案。
