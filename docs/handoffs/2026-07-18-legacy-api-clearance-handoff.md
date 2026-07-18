# 项目交接：旧接口清零完成后的新接口准入

生成日期：2026-07-18（Asia/Shanghai）  
用途：供新的 Codex 对话无缝继续。本文件是当前快照；用户的最新明确需求、代码、测试和实际命令结果优先于本文。

## 可直接复制到新对话的启动提示

```text
请在 C:\Users\as804\Desktop\ai-quant-trader-pro-v1-GrokBuild 继续工作。

当前旧接口扩展、改造与遗留问题已完成最终验收，LEGACY_API_CLEARANCE=PASS；在用户明确选择前，不要继续旧接口重构，也不要直接开始某个新业务接口。

先执行 scripts\doctor.ps1 和 git status --short，保留当前工作区；不要 reset、checkout、clean 或批量删除。然后阅读 AGENTS.md；若任务涉及数据语义、回测、策略、风险、组合、交易、AI 到订单边界、发布门禁或架构，必须完整阅读 .codex\skills\ai-quant-trader-governance\SKILL.md 及按其路由要求的资料。

请先说明目标、成功标准、最小方案和取舍；涉及会改变业务结果的歧义必须先提问。优先复用现有能力，不新增第三方依赖。所有长命令必须超时，超过 60 秒报告进度。启动和停止服务只使用 scripts\start-local.ps1、scripts\start-dev.ps1、scripts\stop-local.ps1，禁止直接运行 Vite、Uvicorn、Celery、docker compose up 或跟随日志。

旧接口清零的最新主仓提交是 1ef443bf03bec8f16182617e35e489755610451b；a-stock-data 子仓库提交是 996cf7d6d90c01d0de758ad91bd818b23603a906。先根据用户当前新需求选择一个独立的新接口能力，完成设计、数据授权、权限、测试、验收和回滚方案后再实施。
```

## 1. 当前事实快照

| 项目 | 状态 |
| --- | --- |
| 主仓分支与提交 | `master`，`1ef443b feat: 完成旧接口扩展改造与验收` |
| 子仓提交 | `a-stock-data`：`996cf7d fix: 完善股票数据刷新与证据采集` |
| 旧接口清零 | 已完成，最近一次全量验收结论为 `LEGACY_API_CLEARANCE=PASS` |
| 当前服务 | 上一轮验收结束后已停止受控本地服务；新对话须先检查，不能假设服务仍运行 |
| 诊断 | 2026-07-18 执行 `scripts\doctor.ps1` 通过；Chromadb 不可用时按设计降级为空检索 |
| 新接口状态 | 可以进入**设计与准入**，但尚未开始任何新业务接口实现 |

### 已完成的关键成果

1. 旧接口清理账本、路由归属、调用方、权限、兼容与弃用结论已写入 `docs/api/legacy-api-ledger.json`，旧接口全量验收脚本为 `scripts/verify_legacy_api_clearance.ps1`。
2. Backend、Worker 与 `a-stock-data` 的股票池刷新链路已完成：内部服务认证、任务队列、Celery 消费、执行阶段审计、可重试/永久失败分类和最终写入验证均已处理。验收使用正式 Backend API 投递两次 Job，非直接调用任务函数；两次均完成 `queued → running → succeeded`，并验证 `fundamental.stocks` 更新与重复执行幂等性。
3. `WORKER_API_CREDENTIAL` 与 `A_STOCK_DATA_COMMAND_TOKEN` 为独立凭据机制，均只由本地 `.env` 注入；源码、`.env.example`、Docker Compose 与启动检查已同步，日志不得输出真实值。
4. 多维研究证据（公告、财报、新闻）、来源使用审计、新闻人工复核、财报原文快照与页级定位、只读研究接口及其迁移/测试已纳入本次提交。它们仍保持 observed-only 和 fail-closed，不授予 Research Readiness、候选、回测或交易权限。
5. 前端已完成既定 Web 原型与只读接口契约接入；无后端能力处必须展示真实空态、失败态或“待接入”，不得伪造业务结果。

## 2. 旧接口验收边界

已通过的结论仅表示旧接口扩展、兼容、遗留清理和验收已经完成；它**不**表示下列能力可以开启：

- 认证回测执行、认证选股输出；
- 真实交易、模拟自动交易、AI 或定时任务创建订单；
- 将 observed、unknown、synthetic、未授权或无 Point-in-Time 证据的数据升级为研究/执行依据；
- 将部分覆盖的实时行情描述为全市场覆盖。

以下安全锁必须保持 `false`，除非用户在同一任务中明确授权完整设计、测试和回滚方案：

```text
CERTIFIED_BACKTEST_EXECUTION_ENABLED=false
CERTIFIED_SCREENER_OUTPUT_ENABLED=false
TRADING_EXECUTION_ENABLED=false
LIVE_TRADING_ENABLED=false
AI_ORDER_ENABLED=false
ALLOW_SCHEDULED_ORDER=false
```

## 3. 尚存风险与真正外部/数据阻塞

这些不是旧接口清零失败项，不能据此撤销 `LEGACY_API_CLEARANCE=PASS`；它们仍限制后续业务授权范围：

| 优先级 | 事实 | 限制 |
| --- | --- | --- |
| P1 | 认证交易日历尚未覆盖当前实时日期 | 实时行情只能 observed-only，不能进入研究或执行 |
| P1 | 实时同步配置仅覆盖 100/5532 | 不得描述为全市场实时覆盖 |
| P1 | 全市场逐日证券状态尚未自动化 | 不得授予全市场交易资格或价格限制判断 |
| P1 | 企业行动官方事件级审核、688981.SH 缺失交易日原因未闭环 | 相关 Point-in-Time 结论继续 fail-closed |
| P2 | 账户级真实佣金、`amount` Provider 验证、Execution Reference 未认证/未授权 | 真实执行与相关因子继续关闭 |
| P2 | Chromadb 当前不可用 | RAG 仅为空检索降级，不能称为完整研究能力 |

`docs/superpowers/specs/2026-07-16-legacy-api-clearance-and-new-api-entry-gate.md` 中的阶段进度文字停留在旧快照（显示 L2 进行中），不应覆盖本次全量验收结论；以提交 `1ef443b`、`docs/api/legacy-api-ledger.json`、`scripts/verify_legacy_api_clearance.ps1` 和实际重跑结果为准。

## 4. 当前工作区注意事项

主仓库当前仅显示 `m a-stock-data`。原因不是未提交源码：子仓库错误跟踪了以下运行产物，工作时会被 Python 改写：

- `a-stock-data/service/.venv/**/__pycache__/*.pyc`
- `a-stock-data/service/__pycache__/*.pyc`
- `a-stock-data/tests/__pycache__/*.pyc`
- `a-stock-data/service/cache/a_share_universe.json`

处理规则：

1. 不将这些文件暂存或提交。
2. 不使用 `git reset --hard`、`git checkout --` 或未限定的 `git clean` 清理它们；这些命令会破坏用户环境或已跟踪内容。
3. 若用户未来明确要求仓库卫生治理，应单独设计并确认：将运行目录移出子仓库/修正 `.gitignore` 与索引、保留可复现依赖清单，再进行受控迁移。该工作不属于新接口开发的前置条件。
4. 不提交真实 `.env`、`.env.host`、令牌、数据库密码或外部服务凭据。

## 5. 后续工作的正确入口

旧接口阶段已结束。下一步不是继续“补旧接口”，而是由用户从长期目标中选择第一项**新业务接口**。推荐的低风险候选是“研究证据页级候选的人工复核输入与消歧读取模型”：

- 先限定为 observed-only 的研究辅助，不解析或发布财务数值；
- 固定章节/表头锚点、候选排序证据、人工复核身份、幂等键和 append-only 复核记录；
- 不授予 Research Readiness，不扩大自动抓取，不改变策略、回测、风险、组合或订单语义。

这只是建议，未获用户确认前不得实施。若用户选择不同新能力，按以下顺序重新准入：

1. 写清业务目标、受益用户、数据源、Point-in-Time/来源/可得时间语义、权限和失败边界。
2. 评估与长期设计及现有 ADR 的一致性，必要时先提交 ADR/最小设计供用户确认。
3. 划定最小 API 契约、调用方、鉴权、审计、迁移、回滚和测试矩阵；禁止复制旧兼容路径掩盖旧逻辑。
4. 用户确认后实施、运行针对性测试和真实链路验收；未验证不得标记完成。

## 6. 新对话的最小阅读与验证路线

按任务相关性渐进读取，避免无界扫描：

1. `AGENTS.md`
2. `.codex/skills/ai-quant-trader-governance/SKILL.md`（仅当任务命中其适用范围时，必须完整阅读）
3. `.codex/skills/ai-quant-trader-governance/references/current-project-state.md`
4. 本交接文档
5. `docs/superpowers/specs/2026-07-13-continuous-full-market-paper-trading-design.md`
6. `docs/superpowers/specs/2026-07-16-legacy-api-clearance-and-new-api-entry-gate.md` 与 `docs/api/legacy-api-ledger.json`
7. 仅阅读当前任务直接相关的 ADR、调用链代码、迁移与测试。

常用命令：

```powershell
scripts\doctor.ps1
git status --short

# 需要重新确认旧接口全量门禁时才运行；不要用直接函数调用替代。
scripts\verify_legacy_api_clearance.ps1

# 启停仅使用项目脚本。
scripts\start-local.ps1
scripts\stop-local.ps1
```

## 7. 持续工作规则

- 所有说明、日志和对话使用中文；代码注释使用英文。
- 编码前说明目标、成功标准、最小方案与取舍；业务歧义先问，不猜测。
- 优先复用项目现有实现和依赖，不新增第三方包，且只做完成当前目标所需的最小修改。
- 证据必须来自真实命令、接口、数据库或浏览器验收；不能以 mock、直接任务函数调用、手工改状态或 HTTP 200 代替端到端成功。
- 搜索使用 `rg` 并限定目录；忽略虚拟环境、`node_modules`、缓存、运行日志和无关目录。
- 所有可能阻塞的命令必须设置超时；超过 60 秒给出进度或明确报告阻塞，禁止重复无效操作。
- 未经用户明确授权，不推送、不创建 PR、不改变交易/发布安全默认值、不删除功能或数据。

