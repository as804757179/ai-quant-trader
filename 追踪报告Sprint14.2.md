# Sprint14.2 追踪报告

生成日期：2026-07-15（Asia/Shanghai）

## 任务

建立“固定真实 Provider、可追踪、可持续同步”的实时行情观察链路，并将真实状态接入只读市场页面。范围是当前配置的实时同步股票集合，不代表已恢复全市场研究、选股、回测或交易。

## 结果

**PASS（当前配置范围）**。固定 Provider 实时行情已按批次取得、写入行情及血缘记录、在页面显示，并完成验收。所有数据仍是 `observed-only`；未改变 Data Certification、Research Readiness、Backtest、Screener、Risk、Execution Gate 或任一交易权限。

## 实现摘要

- 主 Provider 固定为腾讯行情（`tencent`），来源、端点、采集时间、原始响应 Hash、行级 raw hash、collector/normalizer 版本均随批次或行记录。
- `/quotes?fresh=true` 只走固定 Provider；失败记录 `fetch_failed`，不会降级到 unknown、Synthetic、Mock 或第二 Provider。
- 新增 `market.quote_batches` 与 `market.quote_provenance`，行情和血缘在同一事务写入；创建中的批次显式为 `running`，写完后才成为 `success/partial`。失败批次保留审计，不能伪装为成功。
- 历史 `market.quotes` 缺少实时 OHLC/盘口字段的问题，以只增列的兼容迁移处理；未改写既有行情行。
- Worker 改为固定批量同步、限额批次和显式状态记录；当前配置为 100 个活跃标的、40 条/批。
- `stop-local.ps1` 在确认本项目 Beat 已停止且不存在其他 Beat 后清理 RedBeat 锁，避免重启后调度被陈旧锁阻塞。
- 市场监控页面展示真实 Provider、端点、批次、延迟、范围、fallback 状态及“仅观察，不授权研究/执行”边界。

## 本次文件

新增：

- `backend/alembic/versions/015_realtime_quote_provenance.py`
- `backend/alembic/versions/016_align_realtime_quote_columns.py`
- `backend/alembic/versions/017_quote_batch_running_status.py`
- `worker/services/quote_store.py`
- `worker/tests/test_quote_sync.py`
- `backend/tests/test_realtime_quote_provenance_contracts.py`
- `scripts/verify_realtime_quote_provenance.ps1`
- `docs/adr/ADR-012-realtime-quote-provenance.md`
- `docs/superpowers/specs/2026-07-15-realtime-quote-provenance.md`

修改：

- `a-stock-data/service/providers.py`
- `a-stock-data/service/main.py`
- `worker/services/data_client.py`
- `worker/services/quote_sync.py`
- `backend/app/api/stock.py`
- `frontend/src/presentation/coreModels.ts`
- `frontend/src/pages/market/MarketLivePage.tsx`
- `scripts/repair-db-owner.ps1`
- `scripts/stop-local.ps1`
- `.codex/skills/ai-quant-trader-governance/references/current-project-state.md`

未新增第三方依赖；未改动 legacy K 线、Certified Store 原始数据、企业行动原始证据或发布锁。

## 数据与安全边界

- `market.klines`、`market.certified_klines`、Data Certification 与 Research Readiness 没有被本任务写入或放宽。
- 未认证、unknown、Synthetic 数据不会通过此链路变为可信研究数据。
- 交易日历对当前实时日期尚未覆盖，市场会话显示为 `calendar_unresolved`；因此实时行情只能观察，不能成为研究或执行依据。
- 六个默认锁继续为 `false`：可信回测发布、选股输出、交易执行、Live、AI 下单、定时订单。
- 本任务未创建订单、未输出候选、未开启 Paper 自动交易或 Live Trading。

## 数据库兼容性与审计

`market.quotes` 曾由旧数据库对象所有者持有，且缺少实时同步所需的字段。已使用本机管理员连接将相关对象 Owner 修复为 `quant_admin`，再执行只增列迁移。旧记录未被删除、重写或认证。

初次结构不匹配产生的 `write_failed` 批次已保留，作为真实审计记录；后续成功批次不会覆盖它们。

## 验证证据

| 验证 | 实际结果 |
| --- | --- |
| `scripts/doctor.ps1` | PASS；运行环境可用（Chromadb 空库提示为既有 P2） |
| 标准 `scripts/start-local.ps1` | PASS；数据库迁移至 017、API/Data Service/Worker/Beat/Frontend 启动成功 |
| 手动一次 Quote Sync | 100 个当前配置标的、3 个固定 Provider 批次、成功 100、失败 0 |
| 停止再标准启动 | PASS；RedBeat 陈旧锁已被受控清理，启动后获得新的定时同步批次 |
| 批次状态可见性修复 | PASS；发现 `success + 0 行` 的并发中间态后，新增 `running` 状态与迁移 017；只有完成写入后才显示 `success/partial` |
| `scripts/verify_realtime_quote_provenance.ps1` | PASS；Provider=`tencent`、无 fallback、最新新鲜批次成功写入 20 条行情、Hash/版本已记录、批次 API 可读、六个锁关闭 |
| `scripts/verify_core_readonly_data.ps1` | PASS；后端契约测试 10 passed、前端契约测试 3 passed、类型检查和构建通过 |
| `worker/tests/test_quote_sync.py` 与 `worker/tests/test_quote_store.py` | `2 passed` |
| 浏览器市场监控页 | PASS；显示腾讯、固定端点、最近批次、约 1 秒延迟、`100/5532` 范围和观察用途提示；控制台错误为 0 |

当前页面数字随定时批次变化；验收确认的是来源、血缘和状态语义，不是某一瞬时价格或行数。

## P0 / P1 / P2

- **P0：无。**
- **P1：** 当前认证交易日历未覆盖实时日期，实时行情必须维持观察用途；当前同步范围仅为配置的 100/5532，不能声明为全市场实时覆盖。
- **P2：** 前端构建仍提示单个产物体积偏大；Chromadb/RAG 为空库提示为既有环境问题；历史 `write_failed` 批次应保留作审计，不应删除掩盖。

## 回滚方案

若需停止实时观察链路，使用 `scripts/stop-local.ps1` 停止登记的项目进程，并回退应用代码版本即可。已写入的批次和血缘属于审计事实，不应通过删除数据库记录回滚；两项迁移均为新增表/列，后续若要回退数据库必须另行评审数据保留方案。

## 下一步建议

1. 扩展并认证交易日历覆盖，再决定实时行情是否能用于受控研究。
2. 为新闻、公告、财报建立 Provider、抓取时间、原文 Hash 与可得时间语义；先做只读研究数据，不接入订单。
3. 增加第二 Provider 的只读交叉校验，保持禁止 fallback 和禁止写入 Certified Store。
4. 在样本、日历、企业行动和多维数据均完成 Research Readiness 前，继续保持回测发布、选股输出与交易锁关闭。

## Sprint 结论

Sprint14.2 可在“当前固定 Provider 与配置范围的实时观察链路”层面签收；它**不**构成全市场覆盖、真实研究准入、策略盈利证明或任何自动交易授权。下一阶段应先完善数据时点语义与 Readiness，而不是打开交易能力。
