# AI Quant Trader Pro

> 执行安全：默认 `TRADING_EXECUTION_ENABLED=false`、`AI_ORDER_ENABLED=false`、`LIVE_TRADING_ENABLED=false`、`ALLOW_SCHEDULED_ORDER=false`，并要求人工审批。AI 信号扫描只产生待复核建议；执行安全验收运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_execution_safety.ps1`。详见 `docs/adr/ADR-002-execution-safety-gate.md`。

> 数据安全：未认证、unknown 或 synthetic 历史数据下，AI 必须返回 HOLD 且 `tradable=false`；Screener 返回空候选及明确排除原因属于安全成功，不是业务失败。全量测试以 Data Certification Gate 和 Execution Gate 不被放宽为最高优先级。

> Sprint06 认证导入试点：在项目根目录运行 `backend\.venv\Scripts\python.exe backend\scripts\import_certified_pilot.py`，脚本自动读取 `.env.host`，且仅允许固定三只股票和 2026-06-01 至 2026-06-30 日线。查看 batch：查询 `market.data_batches` 中 `importer_version='sprint06-sohu-daily-v1'`；查看 provenance：以 `batch_id` 查询 `market.kline_provenance`。只有 `quality_status='pass'`、`certification_status='certified'`、`is_synthetic=false` 且 provider/source 明确的数据才可用。`CERTIFIED_BACKTEST_EXECUTION_ENABLED=false` 与 `CERTIFIED_SCREENER_OUTPUT_ENABLED=false` 默认保持关闭，导入成功不等于允许回测或候选输出。验收运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_certified_ingestion_pilot.ps1`，详见 `docs/adr/ADR-003-certified-historical-data-ingestion.md`。
>
> Sprint07 Certified Store：认证历史 K 线只存放于 `market.certified_klines`；`market.klines` 是 legacy/raw/uncertified 审计表，Backtest、Screener 与 Simulation fallback 不读取它。所有认证读取通过 `CertifiedKlineRepository` 并显式指定 adjustment。语义固定为完整股票代码、真实交易日期、15:00 Asia/Shanghai、CNY 和 share。当前 Sohu 数据已证明为 raw，但企业行动审核未自动化，故 research readiness 仍为 review_required，真实回测与选股发布继续关闭。运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_certified_kline_store.ps1` 验收，详见 `docs/adr/ADR-004-certified-kline-store-and-semantics.md`。
>
> Sprint08 Research Readiness：Certified 不等于可用于研究或执行。用途分为 `raw_price_analysis`、`return_backtest`、`execution_reference`，没有覆盖请求区间的 ready review 时 fail closed。当前 63 条 Store 数据仍为 0 ready、63 review_required：新浪归档端点的 2026-06-30 缺失已归因为 provider_missing，但独立 amount 证据仍 unresolved；300502.SZ 在 2026-06-11 存在未处理的转增及派现。运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_research_readiness.ps1` 验收，详见 `docs/adr/ADR-005-research-readiness-policy.md`。
>
> Sprint11.1 市场微观边界：已修复 Worker skip/xfail/xpass 检测、拆分买入整手与卖出零股规则，并使用 Decimal 按 0.01 CNY tick 精确计算涨跌停价。运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_market_microstructure_boundaries.ps1` 一键验收。所有发布和交易锁继续关闭。详见 `docs/adr/ADR-009-market-microstructure-boundaries.md`。

> Sprint11 A股市场规则与会计基线：可信回测按交易日期解析官方规则版本，已实现双向过户费、认证交易日历、显式证券状态、复杂持仓会计和标准 Hash。运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_backtest_market_rules.ps1` 一键验收。公共 Backtest、Screener 与全部交易发布锁仍关闭；结果不可用于投资或策略评价。详见 `docs/adr/ADR-008-ashare-market-rules-and-accounting.md`。

> Sprint10 Backtest Integrity：内部验证仅允许 300308.SZ、603986.SH 的固定 21 日 raw/OHLCV 样本，通过 Certified Repository 与 Readiness Gate 读取。运行 `python scripts/validate_backtest_integrity.py` 查看带完整血缘的验证结果，运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_backtest_integrity.ps1` 执行一键验收。公共 Backtest、Screener 与全部交易发布锁仍关闭；结果不可用于投资或策略评价。详见 `docs/adr/ADR-007-backtest-integrity-and-execution-model.md`。

> Sprint09 Field-Level Readiness：研究授权以 `股票 + 区间 + adjustment + use_scope + requirement_profile` 为单位。`OHLCV_RETURN_V1` 不要求 amount，300308.SZ 与 603986.SH 已获得 scoped ready；300502.SZ 因区间内企业行动仍 rejected。`AMOUNT_FACTOR_V1` 和 `EXECUTION_REFERENCE_V1` 均未放行，Store 行本身仍不是全用途 ready。运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_field_level_readiness.ps1` 验收，详见 `docs/adr/ADR-006-field-level-research-readiness.md`。

> Sprint12 Corporate Action PIT：300502.SZ 的旧 `OHLCV_RETURN_V1` 仍 rejected；仅在巨潮资讯官方事件证据、登记日权益、真实到账/支付日期和毛总收益会计均验证后，`OHLCV_TOTAL_RETURN_GROSS_V1` scoped review 可 ready。净税后收益与公共回测仍 blocked。运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_corporate_action_pit.ps1` 验收，详见 `docs/adr/ADR-010-corporate-action-point-in-time.md`。

面向 **A 股市场** 的桌面级 / 自托管 **AI 量化交易系统**。  
在同一仓库内打通：**行情接入 → 多 Agent 智能分析 → 因子选股 → 策略配置 → 规则化回测 → 模拟 / Paper / 实盘交易 → 风控熔断 → 对账同步 → 监控告警**，形成「研究 → 验证 → 执行 → 监控」闭环。

| 项目 | 说明 |
|------|------|
| **版本** | V1.0 |
| **文档更新** | 2026-07-10 |
| **后端测试** | pytest 约 **130+** passed |
| **Worker 测试** | pytest 约 **21** passed |
| **主要语言** | Python 3.11+（后端 / Worker）、TypeScript（前端） |
| **部署形态** | **推荐宿主机混合**（`.env.host` + `scripts/start-host-api.ps1`）；Docker 仅中间件或全栈均可 |
| **股票池** | 全市场 A 股 active 约 **5500+** |
| **交易通道** | simulation（本地模拟 + A 股规则）/ paper（Mock 券商）/ live（QMT 适配） |

> **风险声明**：本系统仅供学习、研究与个人/团队自研量化使用，**不构成任何投资建议**。回测与模拟收益不代表未来表现；实盘交易风险自负，须遵守券商与监管要求。合成 K 线仅用于链路演示，不可用于策略研究结论。

---

## 推荐阅读方式（左侧目录）

**请用浏览器打开带左侧导航的完整文档**（一级 / 二级目录，点击即可跳转正文）：

| 方式 | 说明 |
|------|------|
| **推荐** | 双击或浏览器打开 [`docs/manual.html`](docs/manual.html) |
| 命令行 | `start docs/manual.html`（Windows） |
| 重新生成 | 修改本 README 后执行：`python scripts/generate_docs_html.py` |

`docs/manual.html` 特性：

- **左侧固定目录**：一级章节 + 二级小节树形结构  
- **点击标题跳转**：平滑滚动到对应详情，并高亮当前章节  
- **顶部筛选**：可按关键字过滤目录项  
- **移动端**：顶部「目录」按钮展开侧栏  

> 下方为 GitHub / 纯 Markdown 预览用的简要目录；**完整带侧栏体验以 `docs/manual.html` 为准**。

### 简要目录

| 一级 | 二级入口 |
|------|----------|
| [1. 项目介绍](#s-1) | [1.1](#s-1-1) · [1.2](#s-1-2) · [1.3](#s-1-3) · [1.4](#s-1-4) · [1.5](#s-1-5) · [1.6](#s-1-6) · [1.7](#s-1-7) · [1.8](#s-1-8) · [1.9](#s-1-9) · [1.10](#s-1-10) · [1.11](#s-1-11) · [1.12](#s-1-12) |
| [2. 技术选型](#s-2) | [2.1](#s-2-1) · [2.2](#s-2-2) · [2.3](#s-2-3) · [2.4](#s-2-4) |
| [3. 系统架构](#s-3) | [3.1](#s-3-1) · [3.2](#s-3-2) · [3.3](#s-3-3) · [3.4](#s-3-4) · [3.5](#s-3-5) · [3.6](#s-3-6) · [3.7](#s-3-7) |
| [4. 项目结构](#s-4) | — |
| [5. 项目启动流程](#s-5) | [5.1](#s-5-1) · [5.2](#s-5-2) · [5.3](#s-5-3) · [5.4](#s-5-4) · [5.5](#s-5-5) · [5.6](#s-5-6) · [5.7](#s-5-7) · [5.8](#s-5-8) · [5.9](#s-5-9) |
| [6. 环境配置详解](#s-6) | [6.1](#s-6-1) · … · [6.10](#s-6-10) |
| [7. API 与 WebSocket](#s-7) | [7.1](#s-7-1) · … · [7.11](#s-7-11) |
| [8. 实现状态与边界](#s-8) | [8.1](#s-8-1) · [8.2](#s-8-2) · [8.3](#s-8-3) |
| [9. 常见问题与解决办法](#s-9) | [9.1](#s-9-1) · … · [9.7](#s-9-7) |
| [10. 测试](#s-10) | — |
| [11. 生产部署注意](#s-11) | — |
| [附录](#s-appendix) | — |

---

<h2 id="s-1">1. 项目介绍</h2>

[↑ 返回目录](#目录)

<h3 id="s-1-1">1.1 一句话定位</h3>

**AI Quant Trader Pro** = 可自托管的 A 股量化「研究 + 验证 + 执行 + 监控」一体化工程系统。  
它不是单一回测脚本，也不是券商终端替代品，而是一套把 **数据、AI、策略、回测、交易、风控、运维** 用统一 API 与前端串起来的可运行骨架。

---

<h3 id="s-1-2">1.2 项目背景</h3>

A 股量化从「想法」到「可执行系统」时，常见痛点会同时出现：

| 序号 | 痛点 | 典型表现 |
|------|------|----------|
| 1 | **数据分散** | 行情、基本面、公告分散在多个源；没有统一入库、缓存与回填 |
| 2 | **研究与交易割裂** | 回测是一套脚本，下单是手工/另一套工具，策略无法复用 |
| 3 | **AI 难安全落地** | 大模型输出无结构、无置信度、无风控、无幂等，无法接入交易 |
| 4 | **实盘门槛高** | QMT / xtquant 绑定 Windows + 券商环境，本地联调困难 |
| 5 | **风控与运维薄弱** | 缺少熔断、对账、指标、告警时，异常难以及时发现 |
| 6 | **A 股规则特殊** | T+1、涨跌停、印花税、佣金滑点等，通用回测框架常简化过度 |

传统做法往往是「多个脚本 + Excel + 手工下单」，难以形成可回归、可演示、可扩展的工程闭环。本项目正是为解决上述碎片化而生。

---

<h3 id="s-1-3">1.3 产品目标</h3>

在 **同一仓库** 内完成以下能力，并保证可启动、可测试、可向真盘扩展：

1. **统一数据接入**：通过 `a-stock-data` 微服务拉取行情/K 线等，落库 TimescaleDB，Redis 缓存。  
2. **AI 多 Agent 分析**：趋势 / 基本面 / 情绪 / 短线 / 风控等 Agent 并行，信号结构化聚合。  
3. **策略可配置**：内置双均线、布林带、RSI、MACD；参数与启停可持久化。  
4. **A 股规则回测**：T+1、涨跌停、费用与滑点、信号 T+1 开盘执行等。  
5. **三模式交易**：simulation 本地模拟、paper Mock 券商、live QMT 适配。  
6. **下单前风控 + 熔断**：仓位/行业/流动性/日亏损/回撤/频次；熔断以 DB 为准。  
7. **对账与订单同步**：轮询 + 回调桥（先落库再 emit）+ 手动同步。  
8. **生产级可观测性**：Prometheus 指标、Grafana 看板、钉钉级别/静默、前端告警中心。

**设计原则：**

- **可演示**：无 QMT 时也能用 simulation / paper 跑通全链路。  
- **可回归**：backend / worker 有自动化测试覆盖关键路径。  
- **可扩展**：交易适配层隔离 Mock 与 QMT；AI Agent 可按供应商降级。  
- **可守住底线**：实盘二次确认、单笔限额、熔断、API Key、生产禁 Mock。

---

<h3 id="s-1-4">1.4 解决什么问题</h3>

| 痛点 | 本系统做法 | 你能得到什么 |
|------|------------|--------------|
| 行情与业务库分离 | `a-stock-data` + TimescaleDB + Redis | 统一查询股票/K 线/资金流，回测可回填 |
| AI 结果不可执行 | 多 Agent 结构化输出 → 聚合 → 置信度/阈值 → 可选下单 | 信号可落库、可展示、可对接交易 |
| 回测规则不符合 A 股 | 自研引擎：T+1、涨跌停、佣金/印花税/滑点 | 更贴近实盘约束的绩效评估 |
| 无 QMT 无法测交易 | paper 模式 Mock 券商 | 下单、持仓、对账、WS 可全链路联调 |
| 实盘误操作 | `LIVE_CONFIRM_TOKEN`、单笔上限、熔断、API Key | 多层闸门降低误下单风险 |
| 异常无人知 | Prometheus + Grafana + 钉钉 + 告警中心 | 熔断/失败/告警可观测可通知 |
| 重复下单 | mode 感知幂等键 + DB 唯一约束 | 同请求重试返回已有订单 |

---

<h3 id="s-1-5">1.5 核心能力一览</h3>

| 模块 | 能力说明 | 主要入口 | 前端页面 |
|------|----------|----------|----------|
| **数据层** | 实时/日 K、回填、资金流、新闻摘要；不足时可合成 K 线打通链路 | `/api/v1/stock/*`、回填脚本 | 股票分析 |
| **AI 层** | 趋势/基本面/情绪/短线 LLM Agent + 规则风控 Agent；加权聚合买卖/持有 | `/api/v1/ai/*` | AI |
| **选股** | 自定义条件、预设方案、主题选股 | `/api/v1/screener/*` | 选股 |
| **策略** | 双均线、布林带、RSI、MACD；启停与参数 JSON 持久化 | `/api/v1/strategy/*` | 策略 |
| **回测** | 异步任务落库、绩效指标、可选自动回填/合成、Prometheus 计数 | `/api/v1/backtest/*` | 回测 |
| **交易** | simulation 本地撮合；paper Mock；live QMT/Mock 降级；撤单、同步、对账 | `/api/v1/trade/*` | 交易 |
| **组合** | 资产摘要、持仓列表（按 mode） | `/api/v1/portfolio/*` | 仪表盘 / 交易 |
| **风控** | ST/新股/仓位/行业/流动性/日亏损/回撤/频次；熔断激活与恢复 | `/api/v1/risk/*` | 风控 |
| **监控** | `/metrics`、Grafana 预置、钉钉级别与静默、WS 告警 | `/metrics`、钉钉 | 告警 |
| **任务** | 行情轮询、订单同步、日终归档、信号扫描等 | Celery Worker / Beat | — |

---

<h3 id="s-1-6">1.6 端到端业务闭环</h3>

系统推荐的完整使用路径如下（从零到可交易验证）：

```text
① 启动基础设施（Postgres / Redis / a-stock-data）
        ↓
② 迁移数据库 + 种子股票池 +（可选）初始化模拟账户
        ↓
③ 启动 Backend + Frontend（+ 可选 Worker / 监控栈）
        ↓
④ 回填或合成 K 线 → 策略页调参 → 回测页看绩效
        ↓
⑤ AI 分析观察信号质量；选股页筛选标的
        ↓
⑥ 交易页 simulation：验证 T+1、风控、持仓
        ↓
⑦ paper：验证 Mock 券商下单、订单同步、对账、WebSocket
        ↓
⑧（可选）Windows 真机 live + live_verification 小额验证
        ↓
⑨ 生产：关合成 K 线、关 Mock live、开 API_KEY / 钉钉 / 熔断与限额
```

**模块协作关系（简图）：**

```text
前端页面 ──HTTP/WS──► FastAPI
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   业务服务层      OrderManager       AI Orchestrator
        │               │                │
        ▼               ▼                ▼
   TimescaleDB     风控/熔断         多 Agent + RAG
        │               │                │
        ▼               ▼                ▼
   a-stock-data    Trader 适配层     信号落库
                        │
              simulation / paper / live
                        │
                   miniQMT（仅 live 真盘）
```

---

<h3 id="s-1-7">1.7 适用对象与典型场景</h3>

#### 适合谁

| 角色 | 典型诉求 | 推荐用法 |
|------|----------|----------|
| 个人量化开发者 | 本地练手、学 A 股规则与工程化 | Docker + simulation + 合成/回填 K 线 |
| 小团队 | 统一 API/前端，联调后再接 QMT | paper 全链路 → 真机 live |
| 研究向 | 策略参数对比、规则回测 | 策略 + 回测 + 绩效指标 |
| 运维/风控向 | 告警、熔断、指标看板 | Prometheus/Grafana + 钉钉 + 风控页 |

#### 不适合谁 / 哪些期望要调整

- 期望「一键荐股稳赚」→ 本系统不做投资建议。  
- 期望完整替代券商条件单/两融全部能力 → 以券商客户端为准。  
- 期望 Linux Docker 内直接跑真 QMT → 不可行，真盘需 Windows + miniQMT。

#### 典型场景示例

1. **周末复盘**：回填近一年 K 线 → 跑 dual_ma / macd 回测 → 对比夏普与回撤。  
2. **盘前准备**：AI 分析关注股 → 选股筛选 → 记录信号。  
3. **盘中模拟**：simulation 下单验证 T+1 与风控拒绝原因。  
4. **联调发版前**：paper 模式压测下单/撤单/同步/对账与 WS。  
5. **上真盘前**：`live_verification --dry-run` → 小额 live + 限额 + 钉钉。

---

<h3 id="s-1-8">1.8 三种交易模式详解</h3>

三种模式 **共用同一套 API 与风控入口**，差异在执行器与资金账本来源。请求体通过 `mode` 字段选择。

#### simulation（本地模拟 · A 股规则）

| 项 | 说明 |
|----|------|
| 实现 | `SimulationTrader` + `ashare_rules` |
| 资金 | 纯本地 DB 账本 |
| 撮合 | **真实行情优先**（a-stock-data / 腾讯等）；非交易时段见 `SIM_ALLOW_OFF_HOURS` |
| 规则 | 整手、涨跌停、佣金/印花税/滑点；买入后 `available_qty=0`（**T+1**） |
| T+1 释放 | Celery `update_available_quantity`，或 `POST /api/v1/trade/simulation/release-t1` |
| 适用 | 功能演示、风控联调、无券商环境 |
| 系统开关 | `TRADE_MODE=simulation`（开发默认） |

#### paper（模拟券商 / 联调）

| 项 | 说明 |
|----|------|
| 实现 | `LiveTrader` + `MockQmtAdapter` |
| 资金 | 适配器内独立账本；成交后 **镜像到本地 DB**，降低双账本漂移 |
| 特点 | 可测「下单 → 订单状态 → 同步 → 对账 → WS」全链路 |
| 适用 | 无 miniQMT 时验证生产路径代码 |
| 注意 | 不是真钱；但代码路径更接近 live |

#### live（实盘）

| 项 | 说明 |
|----|------|
| 实现 | `LiveTrader` + `XtQuantAdapter`（优先）或 Mock 降级 |
| 前置 | Windows、已登录 miniQMT、`QMT_PATH` / `QMT_ACCOUNT_ID`、`xtquant` |
| 安全闸门 | ① 系统 `TRADE_MODE=live` ② 请求 `live_confirm` ③ 单笔 `LIVE_MAX_ORDER_VALUE` ④ 熔断 ⑤ 风控预检 |
| 生产铁律 | **`ALLOW_MOCK_LIVE=false`**，避免误把 Mock 当真盘 |

**模式选择建议：**

```text
日常开发 / 演示     → simulation
交易链路联调 / 测试 → paper
Windows 真机实盘    → live（且关闭 Mock 降级）
```

---

<h3 id="s-1-9">1.9 系统边界与非目标</h3>

#### 本系统明确不做

- 代客理财、信号荐股、保证收益  
- 替代券商客户端的全部功能（条件单、融资融券细节等以券商为准）  
- 保证上游数据源 100% 稳定（依赖 `a-stock-data` 与外部行情）  
- 在 Linux Docker 容器内运行真实 QMT SDK  
- 将合成 K 线用于正式策略研究结论  

#### 刻意拆分 / 非主产品

| 路径 | 说明 |
|------|------|
| `AI-Trader/` | 独立实验项目，**未并入主前端菜单** |
| `docs/quant_docs/` | 历史完整设计稿，**部分章节超前于当前实现** |
| `docs/01_*.md` 等 | 分册草稿；**以本 README 为唯一完整入口** |

#### 合规与使用边界

- 使用实盘前请确认券商协议、权限与合规要求。  
- 生产环境务必配置 API Key、确认令牌、关闭 Mock live 与合成 K 线（除非明确仅演示）。  

---

<h3 id="s-1-10">1.10 版本与交付状态</h3>

| 类别 | 状态 | 说明 |
|------|------|------|
| 数据 / AI / 选股 / 策略 / 回测 API | **已实现并可测** | 见 backend 测试与 Swagger |
| 模拟 + Paper 交易 + 风控 + 对账 | **已实现并可测** | 含幂等、熔断 DB、镜像账本 |
| QMT 适配代码 | **已实现，待真机验收** | 需 Windows + miniQMT + 券商包 |
| Walk-Forward / AutoML 产品 UI | **未完整交付** | 见历史 quant_docs 规划 |
| 监控（Prometheus/Grafana/钉钉） | **已实现** | 含级别过滤与静默时段 |
| 自动化测试 | backend ~130+ / worker ~21 | 持续回归关键路径 |

更细的边界说明见 [第 8 章](#s-8)。

---

<h3 id="s-1-11">1.11 仓库内相关子项目说明</h3>

| 目录 | 是否主产品 | 说明 |
|------|------------|------|
| `backend/` | 是 | FastAPI 主应用 |
| `frontend/` | 是 | React 管理端 |
| `worker/` | 是 | Celery 定时/异步任务 |
| `a-stock-data/` | 是（数据依赖） | 行情微服务 |
| `docker/` | 是 | Prometheus / Grafana / Nginx / Postgres 配置 |
| `AI-Trader/` | 否 | 独立实验，勿与主系统混用配置 |
| `docs/quant_docs/` | 参考 | 设计蓝图，不等于验收清单 |
| `vector_db/` | 运行时 | Chroma 持久化目录（可本地生成） |

---

<h3 id="s-1-12">1.12 推荐阅读路径</h3>

| 你的目标 | 建议阅读顺序 |
|----------|--------------|
| 第一次跑起来 | 1.1 → 1.8 → [第 5 章启动](#s-5) → [5.9 验证清单](#s-5-9) |
| 理解整体设计 | 1 全文 → [第 3 章架构](#s-3) → [第 4 章结构](#s-4) |
| 接真盘 / 上生产 | 1.8 live → [第 6 章配置](#s-6) → [第 11 章](#s-11) → [第 9 章 FAQ](#s-9) |
| 调 API | [第 7 章](#s-7) + Swagger `http://127.0.0.1:8000/api/docs` |
| 排障 | [第 9 章](#s-9) |

---

<h2 id="s-2">2. 技术选型</h2>

[↑ 返回目录](#目录)

<h3 id="s-2-1">2.1 技术栈总表</h3>

| 层次 | 选型 | 用途 |
|------|------|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design Pro | 管理端 UI |
| 图表 | lightweight-charts | K 线展示 |
| API | FastAPI + Uvicorn | REST + WebSocket |
| ORM / 迁移 | SQLAlchemy 2 async + Alembic | 异步 PG 访问与版本迁移 |
| 数据库 | PostgreSQL 15 + TimescaleDB | 业务表 + 时序 K 线 |
| 缓存 / 队列 | Redis 7 | 缓存、Pub/Sub、Celery Broker |
| 任务 | Celery + RedBeat | 定时与异步任务 |
| AI | OpenAI / Anthropic / DeepSeek / 通义 | 多 Agent LLM |
| 向量 | ChromaDB | RAG 检索 |
| 计算 | Pandas / NumPy | 指标与数据处理 |
| 监控 | Prometheus + Grafana | 指标存储与看板 |
| 通知 | 钉钉 Webhook | 可配级别与静默时段 |
| 交易 | QmtAdapter / Mock / XtQuant | paper / live |
| 行情 | a-stock-data | 数据源 HTTP 封装 |

---

<h3 id="s-2-2">2.2 选型理由</h3>

| 技术 | 理由 |
|------|------|
| **FastAPI** | 异步 IO、自动 OpenAPI、Pydantic 校验，适合行情 / AI / WS 混合负载 |
| **TimescaleDB** | K 线按时间分区友好，业务表仍用标准 PostgreSQL 能力 |
| **Celery + Redis** | 将 3s 行情、15s 订单同步、日终归档与 API 进程解耦，避免阻塞请求 |
| **多 Agent** | 不同任务可绑定不同模型供应商；单厂商故障时其他 Agent 可降级为中性输出 |
| **交易适配层** | 统一接口屏蔽 Mock 与 QMT 差异，开发与生产切换主要改配置与 mode |
| **React + Ant Design Pro** | 后台表格 / 表单 / 布局成熟，适合交易与运维页面 |
| **Prometheus + Grafana** | 标准可观测栈，便于与现有运维体系对接 |
| **Alembic** | 订单幂等约束等 schema 变更可版本化迁移 |

---

<h3 id="s-2-3">2.3 默认端口</h3>

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 | 3000 | Vite dev 或 Nginx |
| Backend | 8000 | API + WS + metrics |
| a-stock-data | 8080 | 行情微服务 |
| PostgreSQL | 5432 | 默认建议仅本机绑定 |
| Redis | 6379 | 默认建议仅本机绑定 |
| Prometheus | 9090 | 指标存储与告警规则 |
| Grafana | 3001 | 映射容器内 3000 |
| Flower（可选） | 5555 | Celery 监控 |

---

<h3 id="s-2-4">2.4 依赖与运行注意</h3>

| 点 | 说明 |
|----|------|
| Python | 推荐 **3.11+** |
| Node.js | 推荐 **18+** |
| Docker | 用于 Postgres / Redis / 可选全栈与监控 |
| Windows | **真 QMT 仅 Windows** + 已登录 miniQMT |
| URL 密码 | `# $ @` 等特殊字符必须 **URL 编码** 后写入 `DATABASE_URL` / `REDIS_URL` |
| xtquant | 券商官方包，通常不在通用 `requirements.txt` 中强制安装 |
| PYTHONPATH（Worker） | 本地启动需同时包含 `worker` 与 `backend` 路径 |

---

<h2 id="s-3">3. 系统架构</h2>

[↑ 返回目录](#目录)

<h3 id="s-3-1">3.1 逻辑架构图</h3>

```text
                    ┌─────────────────────────────────────┐
                    │           浏览器 / 前端               │
                    │  仪表盘 · 股票 · AI · 选股 · 策略     │
                    │  回测 · 风控 · 告警 · 交易             │
                    └─────────────────┬───────────────────┘
                                      │ HTTP / WebSocket
                    ┌─────────────────▼───────────────────┐
                    │         FastAPI Backend (:8000)      │
                    │  鉴权 · OrderManager · 风控 · AI     │
                    │  回测服务 · /metrics · WS 管理        │
                    └─────┬───────────┬───────────┬───────┘
                          │           │           │
           ┌──────────────▼──┐  ┌─────▼─────┐  ┌──▼──────────────┐
           │ PostgreSQL +    │  │   Redis   │  │ a-stock-data    │
           │ TimescaleDB     │  │ 缓存/队列 │  │ (:8080)         │
           └─────────────────┘  │ Pub/Sub   │  └─────────────────┘
                                └─────┬─────┘
                                      │
                          ┌───────────▼───────────┐
                          │ Celery Worker / Beat   │
                          │ 行情 · 订单同步 · 日终  │
                          └───────────┬───────────┘
                                      │ live only
                          ┌───────────▼───────────┐
                          │ miniQMT + xtquant      │
                          └───────────────────────┘
```

---

<h3 id="s-3-2">3.2 后端模块职责</h3>

| 路径 | 职责 |
|------|------|
| `app/api/*` | HTTP 路由与入参校验 |
| `app/services/*` | 业务用例编排 |
| `app/trade/*` | 交易执行、幂等、QMT 适配、订单同步、事件桥 |
| `app/risk/*` | 预检、熔断、组合快照 |
| `app/backtest/*` | 回测引擎、绩效、任务 |
| `app/strategy/*` | 策略元数据与配置文件 |
| `app/data/*` | 行情客户端、缓存、K 线回填 / 合成 |
| `app/ai/*` | Agent、编排器、信号聚合 |
| `app/rag/*` | 向量检索与公告索引 |
| `app/ws/*` | WebSocket 与 Redis 转发 |
| `app/monitoring/*` | Prometheus 指标 |
| `app/notify/*` | 钉钉与静默时段 |
| `app/core/*` | 配置、鉴权、日志、统一响应 |

---

<h3 id="s-3-3">3.3 交易完整链路</h3>

```text
POST /api/v1/trade/order
  1) 校验数量 100 整数倍、限价单价格
  2) OrderManager
     - live：检查 TRADE_MODE、live_confirm、单笔金额
     - 幂等：mode + 信号 + 代码 + 方向 + 类型 + 数量 + 限价 → SHA256
     - 熔断：查询 DB is_active
     - 风控：PreTradeRiskChecker
  3) SimulationTrader 或 LiveTrader
     LiveTrader:
       - adapter.submit_order
       - INSERT trade.orders
       - FILLED：simulation 规则写仓；Mock 则镜像适配器账本到 DB
       - 落库后再 emit_order_event（避免回调找不到本地单）
  4) WS 推送 portfolio / alerts
  5) 可选 AUTO_RECONCILE_ON_FILL 对账
```

**订单后续状态更新机制：**

| 机制 | 说明 |
|------|------|
| Celery 轮询 | 约 15s 同步 SUBMITTED / PARTIAL 等未终态订单 |
| 券商回调 | XtQuant Callback / Mock force_fill |
| 手动同步 | `POST /trade/orders/sync` 或单笔 sync |

**关键设计点：**

1. **先 INSERT 再 emit**：避免回调 bridge 查不到本地订单。  
2. **幂等按 mode 隔离**：`UNIQUE (mode, idempotency_key)`，simulation 与 live 互不影响。  
3. **paper 镜像账本**：Mock 成交后写回本地 DB，减少双账本漂移。  
4. **熔断以 DB 为准**：避免仅 Redis 导致重启后状态丢失。

---

<h3 id="s-3-4">3.4 回测完整链路</h3>

```text
POST /api/v1/backtest/run
  → 创建 backtest.tasks 记录
  → 可选 ensure_range 回填 market.klines
  → 仍无数据且 allow_synthetic：内存/落库合成日 K
  → BacktestEngine + 策略信号生成器
  → 写 results（收益、回撤、夏普、成交明细等）
  → Prometheus quant_backtest_total 计数
```

引擎侧关注点：交易日历、T+1、涨跌停、费用、前视检查（lookahead checker）等。

---

<h3 id="s-3-5">3.5 AI 分析链路</h3>

```text
POST /api/v1/ai/{code}/analyze
  → Orchestrator 并行调度多个 Agent
      - TrendAgent / FundamentalAgent / SentimentAgent
      - ShortTermAgent / RiskAgent（规则向）
  → 聚合器按权重与阈值输出 BUY / HOLD / SELL
  → 置信度过滤（SIGNAL_MIN_CONFIDENCE 等）
  → 信号与 agent 日志落库
  → 可选 WS 推送 / 后续自动下单（受风控约束）
```

RAG（Chroma）可对公告/研报做检索增强，具体 collection 名称见环境变量 `CHROMA_COLLECTION_*`。

---

<h3 id="s-3-6">3.6 数据库 Schema</h3>

| Schema | 内容 |
|--------|------|
| `market` | K 线、行情、资金流 |
| `fundamental` | 股票、财报、公告 |
| `ai` | 信号、agent 日志 |
| `trade` | 订单、持仓、账户 |
| `risk` | 规则、事件、熔断记录 |
| `backtest` | 任务与结果 |
| `strategy` / `audit` | 预留扩展 |

订单唯一性：**`UNIQUE (mode, idempotency_key)`**（迁移 `002`）。

---

<h3 id="s-3-7">3.7 安全与监控</h3>

**安全：**

| 能力 | 说明 |
|------|------|
| API_KEY | 可选全局鉴权（生产强烈建议开启） |
| LIVE_CONFIRM_TOKEN | 实盘二次确认 |
| 熔断 | 激活后拦截交易；以 DB 状态为准 |
| CORS | `ALLOWED_ORIGINS` 白名单 |
| 端口绑定 | compose 默认建议本机，避免误暴露公网 |

**监控：**

| 组件 | 说明 |
|------|------|
| `GET /metrics` | Prometheus 抓取（无 API 前缀，免鉴权） |
| `docker/prometheus/alerts.yml` | 熔断、告警激增、钉钉失败、回测失败等规则 |
| Grafana `quant-overview` | 预置总览看板 |
| `/ws/alerts` + Redis 历史 | 业务告警流与前端告警中心 |
| 钉钉 | 级别过滤 + 冷却 + 静默时段 + 静默放行级别 |

---

<h2 id="s-4">4. 项目结构</h2>

[↑ 返回目录](#目录)

```text
ai-quant-trader-pro-v1-GrokBuild/
├── README.md                 # 本文档（完整说明，唯一主入口）
├── .env.example              # 环境变量模板（复制为 .env）
├── docker-compose.yml        # 基础设施与可选全栈
├── docker-compose.dev.yml    # 开发辅助（如有）
├── Makefile                  # 常用命令封装（可选）
│
├── backend/                  # FastAPI 主应用
│   ├── app/
│   │   ├── api/              # 路由
│   │   ├── ai/               # 多 Agent
│   │   ├── backtest/         # 回测引擎
│   │   ├── core/             # 配置/鉴权/响应
│   │   ├── data/             # 行情与回填
│   │   ├── monitoring/       # Prometheus
│   │   ├── notify/           # 钉钉
│   │   ├── rag/              # 向量检索
│   │   ├── risk/             # 风控熔断
│   │   ├── strategy/         # 策略
│   │   ├── trade/            # 交易执行与 QMT
│   │   ├── ws/               # WebSocket
│   │   └── main.py
│   ├── alembic/              # 数据库迁移
│   ├── scripts/              # 种子、回填、实盘预检等
│   ├── tests/                # 单元/集成测试
│   └── requirements.txt
│
├── frontend/                 # React + Vite 前端
│   └── src/
│       ├── pages/            # 仪表盘、交易、回测、告警等
│       ├── api/              # HTTP 客户端
│       └── hooks/            # 如 useWebSocket
│
├── worker/                   # Celery Worker / Beat
│   ├── tasks/                # market / maintenance / ai
│   ├── services/             # 同步、扫描、缓存等
│   ├── tests/
│   └── Dockerfile            # PYTHONPATH 含 /backend
│
├── a-stock-data/             # 行情微服务
│   └── service/
│
├── docker/
│   ├── prometheus/           # prometheus.yml + alerts.yml
│   ├── grafana/              # 数据源与看板 JSON
│   ├── postgres/             # init / 配置
│   └── nginx/                # 反代与 SSL 目录
│
├── docs/
│   ├── quant_docs/           # 历史设计规划（参考，非验收标准）
│   ├── PROGRESS.md           # 历史进度
│   └── 01_*.md …             # 分册草稿（以 README 为准）
│
└── AI-Trader/                # 独立实验项目（未接主前端）
```

---

<h2 id="s-5">5. 项目启动流程</h2>

[↑ 返回目录](#目录)

以下命令默认在 **Windows PowerShell**，路径以**仓库根目录**为准。

---

<h3 id="s-5-1">5.1 前置条件</h3>

| 依赖 | 版本建议 | 用途 |
|------|----------|------|
| Docker Desktop | 最新稳定版 | Postgres / Redis / 可选全栈 |
| Python | 3.11+ | Backend / Worker |
| Node.js | 18+ | Frontend |
| Git | - | 获取代码 |

**可选：**

- 任一 LLM 供应商 API Key（OpenAI / Anthropic / DeepSeek / 通义）  
- 真盘：Windows + 已登录 miniQMT + 券商 `xtquant`

---

<h3 id="s-5-2">5.2 配置环境变量</h3>

```powershell
cd <仓库根目录>
copy .env.example .env
```

用编辑器打开 `.env`，**至少**修改：

```env
SECRET_KEY=请换成足够长的随机字符串
DB_PASSWORD=强密码
REDIS_PASSWORD=强密码
DATABASE_URL=postgresql+asyncpg://quant_admin:<URL编码后的密码>@127.0.0.1:5432/quant_trader
REDIS_URL=redis://:<URL编码后的密码>@127.0.0.1:6379/0
```

**开发推荐：**

```env
APP_ENV=development
API_KEY=
TRADE_MODE=simulation
ALLOW_MOCK_LIVE=true
BACKTEST_ALLOW_SYNTHETIC_KLINE=true
```

**主机名注意：**

| 场景 | DATABASE_URL / REDIS_URL 主机 |
|------|-------------------------------|
| API 在宿主机，DB/Redis 在 Docker | `127.0.0.1` |
| 全部在 compose 网络内 | 服务名 `postgres` / `redis` |

**密码特殊字符必须 URL 编码**，例如：`#` → `%23`，`$` → `%24`，`@` → `%40`。

---

<h3 id="s-5-3">5.3 启动基础设施 / 宿主机混合</h3>

**Desktop 推荐（PG/Redis 已在本机或 Docker）：**

```powershell
# 加载 .env.host，启动 a-stock-data:8080 + Backend:8000
.\scripts\start-host-api.ps1
# 另开终端
cd frontend; npm run dev
```

**仅 Docker 中间件 + 可选容器化行情：**

```powershell
docker compose up -d postgres redis a-stock-data
docker compose ps
```

检查：

```powershell
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8000/api/v1/health
curl "http://127.0.0.1:8000/api/v1/stock/list?page_size=1"
# 期望 total ≈ 5500+
```

可选监控栈：

```powershell
docker compose up -d prometheus grafana
# Grafana: http://127.0.0.1:3001
# 默认管理员密码见 .env 中 GRAFANA_PASSWORD
```

详细分进程启动见 [`docs/04_GETTING_STARTED.md`](docs/04_GETTING_STARTED.md)。

---

<h3 id="s-5-4">5.4 数据库迁移与初始化</h3>

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
```

可选初始化：

```powershell
python -m scripts.seed_stocks
python -m scripts.init_simulation_account
python -m scripts.backfill_kline --codes 000001 --years 1 --allow-synthetic
```

| 脚本 | 作用 |
|------|------|
| `seed_stocks` | 写入/同步全市场股票池（约 5500+） |
| `init_simulation_account` | 初始化模拟账户资金 |
| `backfill_kline` | 回填 K 线（可合成） |
| `live_verification` | 实盘/paper 预检 |
| `health_check` | 健康检查脚本 |
| `scripts/start-host-api.ps1` | 宿主机启动 8080+8000 |
| `POST /stock/sync-universe` | API 同步股票池 |

---

<h3 id="s-5-5">5.5 启动 Backend</h3>

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

打开：

| 地址 | 用途 |
|------|------|
| http://127.0.0.1:8000/api/v1/health | 健康检查 |
| http://127.0.0.1:8000/api/docs | Swagger 交互文档 |
| http://127.0.0.1:8000/api/openapi.json | OpenAPI JSON |
| http://127.0.0.1:8000/metrics | Prometheus 指标 |

生产未配 `API_KEY`、live 未配 `LIVE_CONFIRM_TOKEN` 时，启动日志会打出 **WARNING**（提醒，不阻断启动）。

---

<h3 id="s-5-6">5.6 启动 Frontend</h3>

```powershell
cd frontend
npm install
npm run dev
```

浏览器访问：http://127.0.0.1:3000

**主要页面：** 仪表盘、股票分析、AI、选股、策略、回测、风控、告警、交易。

若后端启用了 `API_KEY`，在前端环境写入（例如 `frontend/.env.local`）：

```env
VITE_API_KEY=与后端一致
VITE_LIVE_CONFIRM_TOKEN=与 LIVE_CONFIRM_TOKEN 一致
```

---

<h3 id="s-5-7">5.7 启动 Worker</h3>

行情定时拉取、订单同步、日终快照、对账等依赖 Celery。

**本地 Worker：**

```powershell
cd worker
$env:PYTHONPATH="<你的仓库绝对路径>\worker;<你的仓库绝对路径>\backend"
$env:DATABASE_URL="与 backend 相同"
$env:REDIS_URL="与 backend 相同"
celery -A celery_app worker -Q high,normal,low --loglevel=info
```

**另开终端启动 Beat：**

```powershell
cd worker
$env:PYTHONPATH="..."   # 同上
celery -A celery_app beat --loglevel=info --scheduler redbeat.RedBeatScheduler
```

**Docker 方式：**

```powershell
docker compose up -d worker scheduler
```

镜像内已配置 `ENV PYTHONPATH=/app:/backend`。

---

<h3 id="s-5-8">5.8 Docker 一键启动</h3>

```powershell
copy .env.example .env
# 编辑密码与密钥
docker compose up -d --build
```

注意：

1. 真 **QMT 实盘 backend 不要只放在 Linux 容器**，应与 miniQMT 同机 Windows 运行。  
2. compose 内服务互访使用服务名（`api`、`postgres`、`redis`、`a-stock-data` 等）。  
3. 宿主机访问映射端口时，本地工具里的 URL 主机仍用 `127.0.0.1`。

---

<h3 id="s-5-9">5.9 启动后验证清单</h3>

| 步骤 | 操作 | 期望 |
|------|------|------|
| 健康 | 打开 `/api/v1/health` | `database` 为 ok |
| 策略 | 前端「策略」 | 看到 4 个内置策略 |
| 回测 | 开启合成 K 线跑 dual_ma | 返回收益等 metrics |
| 模拟交易 | mode=simulation 下单 | 有行情且过风控时可成交 |
| Paper | mode=paper | Mock 成交，可对账/同步 |
| 告警 | 打开「告警」 | WS 显示已连接 |
| 指标 | 打开 `/metrics` | 存在 `quant_` 系列指标 |

实盘 / Paper 预检脚本：

```powershell
cd backend
python -m scripts.live_verification --dry-run --mode paper
```

---

<h2 id="s-6">6. 环境配置详解</h2>

[↑ 返回目录](#目录)

主文件：仓库根目录 `.env`（从 `.env.example` 复制）。  
后端读取逻辑见 `backend/app/core/config.py`。

---

<h3 id="s-6-1">6.1 基础系统</h3>

| 变量 | 默认 | 说明 |
|------|------|------|
| `APP_ENV` | development | 设为 `production` 时行为更严格 |
| `SECRET_KEY` | 必填 | 长随机串，用于安全相关能力 |
| `API_KEY` | 空 | 非空则全局鉴权 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `ALLOWED_ORIGINS` | 含 localhost:3000 | CORS，JSON 数组字符串 |

---

<h3 id="s-6-2">6.2 数据库与 Redis</h3>

| 变量 | 说明 |
|------|------|
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | compose 与拼 URL 用 |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/db` |
| `REDIS_URL` | `redis://:pass@host:6379/0` |
| `CELERY_BROKER_URL` | 默认等于 Redis |
| `CELERY_RESULT_BACKEND` | 默认等于 Redis |

URL 编码示例：`#`→`%23`，`$`→`%24`，`@`→`%40`。

---

<h3 id="s-6-3">6.3 交易与 QMT</h3>

| 变量 | 说明 |
|------|------|
| `TRADE_MODE` | 系统级：`simulation` 或 `live` |
| `ALLOW_MOCK_LIVE` | 无 xtquant 时 live 是否降级 Mock；**生产必须 false** |
| `MOCK_QMT_CASH` | Mock 初始资金 |
| `LIVE_CONFIRM_TOKEN` | 实盘二次确认口令 |
| `LIVE_MAX_ORDER_VALUE` | 单笔上限（元），`0` 表示不限制 |
| `AUTO_RECONCILE_ON_FILL` | 成交后是否自动对账 |
| `QMT_PATH` | miniQMT userdata 路径 |
| `QMT_ACCOUNT_ID` | 资金账号 |
| `QMT_ACCOUNT_TYPE` | 默认 `STOCK` |
| `QMT_SESSION_ID` | 会话 ID |
| `QMT_FORCE_MOCK` | 强制走 Mock 适配器 |

---

<h3 id="s-6-4">6.4 回测与数据</h3>

| 变量 | 说明 |
|------|------|
| `A_STOCK_DATA_URL` | 行情服务地址 |
| `BACKTEST_AUTO_BACKFILL` | 回测前自动补 K 线 |
| `BACKTEST_ALLOW_SYNTHETIC_KLINE` | 允许合成 K 线（**仅演示**） |
| `DATA_CACHE_TTL_QUOTE` | 行情缓存秒数，建议 **15**（L1+Redis） |
| `DATA_CACHE_TTL_KLINE` | 日 K 缓存秒数，默认 300 |
| `SIM_ALLOW_OFF_HOURS` | 模拟盘非交易时段是否按最近行情成交 |
| `SQL_ECHO` | 是否打印 SQL；全市场同步务必 **false** |
| `DATA_SYNC_INTERVAL_REALTIME` | 实时同步间隔（秒） |

---

<h3 id="s-6-5">6.5 风控阈值</h3>

| 变量 | 默认 | 含义 |
|------|------|------|
| `MAX_SINGLE_POSITION_RATIO` | 0.10 | 单票仓位上限 |
| `WARN_SINGLE_POSITION_RATIO` | 0.08 | 单票预警线 |
| `MAX_TOTAL_POSITION_RATIO` | 0.80 | 总仓上限 |
| `MAX_DAILY_LOSS_RATIO` | 0.03 | 日亏损上限 |
| `MAX_DRAWDOWN_RATIO` | 0.15 | 回撤上限 |
| `MAX_DAILY_ORDER_COUNT` | 20 | 日下单次数上限 |
| `MAX_SECTOR_CONCENTRATION_RATIO` | 0.40 | 行业集中度上限 |
| `MIN_DAILY_AMOUNT` | 50000000 | 最低日成交额（元） |

也可通过表 `risk.risk_rules` 覆盖部分规则。

---

<h3 id="s-6-6">6.6 AI 与 RAG</h3>

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_*` / `QWEN_*` | 各模型供应商 |
| `SIGNAL_MIN_CONFIDENCE` | 最低置信度 |
| `SIGNAL_BUY_THRESHOLD` / `SIGNAL_SELL_THRESHOLD` | 买卖阈值 |
| `SIGNAL_VALIDITY_HOURS` | 信号有效小时数 |
| `CHROMA_PERSIST_DIR` | 向量库目录 |
| `CHROMA_COLLECTION_*` | 各 collection 名称 |

未配置任何 LLM Key 时，AI 分析可能降级或返回中性结果，不影响 simulation 交易主链路。

---

<h3 id="s-6-7">6.7 钉钉通知</h3>

| 变量 | 说明 |
|------|------|
| `ENABLE_DINGTALK_NOTIFY` | 总开关 |
| `DINGTALK_WEBHOOK` | 机器人 Webhook |
| `DINGTALK_ALERT_LEVELS` | 推送级别列表，逗号分隔 |
| `DINGTALK_COOLDOWN_SECONDS` | 同内容冷却秒数 |
| `DINGTALK_QUIET_HOURS` | 静默时段，如 `23:00-08:00` |
| `DINGTALK_QUIET_BYPASS_LEVELS` | 静默时仍推送的级别（如 CRITICAL） |

测试接口：

```http
POST /api/v1/risk/alerts/test-dingtalk?level=CRITICAL&message=hello
```

---

<h3 id="s-6-8">6.8 前端环境变量</h3>

| 变量 | 说明 |
|------|------|
| `VITE_API_KEY` | 与后端 `API_KEY` 一致 |
| `VITE_LIVE_CONFIRM_TOKEN` | 与 `LIVE_CONFIRM_TOKEN` 一致 |

前端通过 Vite 代理访问 `/api` 与 `/ws`（详见 `frontend/vite.config.ts`）。

---

<h3 id="s-6-9">6.9 Worker</h3>

| 变量 | 说明 |
|------|------|
| `API_BASE_URL` | HTTP 模式调用 backend 的基址 |
| `WORKER_BACKEND_MODE` | `http` 或 `direct` |
| `SIGNAL_SCAN_CONCURRENCY` 等 | 信号扫描并发与参数 |
| `DATABASE_URL` / `REDIS_URL` | 与 backend 保持一致 |

---

<h3 id="s-6-10">6.10 生产最低安全配置</h3>

```env
APP_ENV=production
API_KEY=<长随机>
SECRET_KEY=<长随机>
TRADE_MODE=live
ALLOW_MOCK_LIVE=false
LIVE_CONFIRM_TOKEN=<长随机>
LIVE_MAX_ORDER_VALUE=10000
ENABLE_DINGTALK_NOTIFY=true
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=...
DINGTALK_ALERT_LEVELS=CRITICAL,ERROR
DINGTALK_QUIET_HOURS=23:00-08:00
QMT_PATH=C:\path\to\userdata_mini
QMT_ACCOUNT_ID=你的资金账号
BACKTEST_ALLOW_SYNTHETIC_KLINE=false
```

---

<h2 id="s-7">7. API 与 WebSocket</h2>

[↑ 返回目录](#目录)

- **Swagger UI**：http://127.0.0.1:8000/api/docs  
- **OpenAPI JSON**：http://127.0.0.1:8000/api/openapi.json  
- **统一响应形态**：`{ "success", "data", "message", "timestamp", "error_code?" }`  
- **鉴权**：配置了 `API_KEY` 时，请求头带 `X-API-Key` 或 `Authorization: Bearer <key>`  

下列路径默认加前缀 **`/api/v1`**（`/metrics` 除外）。完整字段以 Swagger 为准。

---

<h3 id="s-7-1">7.1 系统</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查（含 database） |
| GET | `/metrics` | Prometheus 指标（**无** `/api/v1` 前缀，免鉴权） |

---

<h3 id="s-7-2">7.2 股票 `/stock`</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/stock/list` | 股票列表 / 搜索 |
| GET | `/stock/{code}/profile` | 档案 |
| GET | `/stock/{code}/quote` | 实时行情 |
| GET | `/stock/{code}/kline` | K 线 |
| GET | `/stock/{code}/fund-flow` | 资金流 |
| GET | `/stock/{code}/news` | 新闻 / 公告摘要 |
| POST | `/stock/backfill-kline` | 批量回填 K 线（可 `allow_synthetic`） |

---

<h3 id="s-7-3">7.3 AI `/ai`</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ai/signals` | 信号分页列表 |
| POST | `/ai/{code}/analyze` | 触发完整分析 |
| GET | `/ai/{code}/...` | 最新信号 / 历史（详见 Swagger） |

---

<h3 id="s-7-4">7.4 选股 `/screener`</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/screener/screen` | 自定义条件或 `preset_id` |
| GET | `/screener/presets` | 预设列表 |
| POST | `/screener/theme` | 主题选股 |

---

<h3 id="s-7-5">7.5 策略 `/strategy`</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/strategy/list` | 全部内置策略与当前配置 |
| GET | `/strategy/{type}` | 单个策略 |
| POST | `/strategy/create` | 写入 / 覆盖配置 |
| POST | `/strategy/{type}/update` | 启停、改参数 |

`type` 取值：`dual_ma` | `bollinger` | `rsi` | `macd`。

---

<h3 id="s-7-6">7.6 回测 `/backtest`</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/backtest/run` | 执行回测并返回绩效 |
| GET | `/backtest/tasks` | 历史任务 |
| GET | `/backtest/{task_id}/status` | 状态与结果 |

请求示例：

```json
{
  "strategy_type": "dual_ma",
  "stock_codes": ["000001"],
  "start_date": "2024-01-02",
  "end_date": "2024-06-28",
  "initial_cash": 1000000,
  "auto_backfill": true,
  "allow_synthetic": true
}
```

---

<h3 id="s-7-7">7.7 风控 `/risk`</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/risk/rules` | 规则列表 |
| GET | `/risk/fuse-status` | 熔断状态与历史 |
| POST | `/risk/fuse/activate` | 激活熔断 |
| POST | `/risk/fuse/recover` | 人工恢复 |
| GET | `/risk/exposure` | 仓位暴露 |
| POST | `/risk/pre-check` | 下单前检查 |
| GET | `/risk/alerts` | 告警历史（可按 level 过滤） |
| GET | `/risk/alerts/summary` | 告警计数 |
| POST | `/risk/alerts/test-dingtalk` | 钉钉测试 |
| GET | `/risk/dashboard` | 仪表盘聚合（资产 + 熔断 + 告警） |

---

<h3 id="s-7-8">7.8 交易 `/trade`</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/trade/order` | 下单 |
| POST | `/trade/order/cancel` | 撤单 |
| GET | `/trade/orders` | 订单列表 |
| GET | `/trade/orders/{id}` | 订单详情 |
| POST | `/trade/orders/sync` | 批量同步未终态 |
| POST | `/trade/orders/{id}/sync` | 同步单笔 |
| GET | `/trade/mode` | 系统模式与适配器信息 |
| GET | `/trade/broker-status` | QMT / Mock 环境探测 |
| POST | `/trade/reconcile` | 本地 vs 券商对账 |

下单示例（模拟）：

```json
{
  "stock_code": "000001",
  "side": "BUY",
  "order_type": "LIMIT",
  "quantity": 100,
  "limit_price": 10.5,
  "mode": "simulation"
}
```

实盘额外字段：

```json
{
  "mode": "live",
  "live_confirm": "与 LIVE_CONFIRM_TOKEN 相同"
}
```

---

<h3 id="s-7-9">7.9 组合 `/portfolio`</h3>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portfolio/summary` | 总资产 / 现金 / 盈亏等 |
| GET | `/portfolio/positions` | 持仓明细 |

查询参数通常包含 `mode=simulation|paper|live`。

---

<h3 id="s-7-10">7.10 WebSocket</h3>

| 路径 | 说明 |
|------|------|
| `/ws/quotes/{code}` | 单股行情 |
| `/ws/signals` | AI 信号 |
| `/ws/alerts` | 业务告警 |
| `/ws/portfolio?mode=` | 组合与订单更新 |

心跳：客户端发送文本 `ping`，服务端回复 `pong`。

---

<h3 id="s-7-11">7.11 错误与幂等</h3>

| 点 | 说明 |
|----|------|
| 业务失败 | 有时仍返回 HTTP 200，需看 body 内 `success` / `data.success` |
| 参数错误 | 多为 400，并带 `error_code` |
| 鉴权失败 | 401（配置了 API_KEY 时） |
| 幂等命中 | 相同幂等键重复提交：返回已有订单且 `idempotent: true` |
| 幂等键要素 | mode、signal_id、代码、方向、订单类型、数量、限价 → SHA256 |
| DB 约束 | `UNIQUE (mode, idempotency_key)` |

---

<h2 id="s-8">8. 实现状态与边界</h2>

[↑ 返回目录](#目录)

<h3 id="s-8-1">8.1 已实现</h3>

| 领域 | 内容 |
|------|------|
| 数据 | 全市场股票池、行情 / 多周期 K 线、回填、新浪兜底、合成兜底 |
| 性能 | L1+Redis 缓存、共享 HTTP 池、批量 `/quotes`、持仓批量估值 |
| AI | 多 Agent、编排、聚合、信号列表 / 分析 |
| 选股 | 预设、主题、自定义条件 |
| 策略 | 四类内置、启停、参数持久化 |
| 回测 | 引擎、HTTP、绩效、任务表、Prometheus |
| 交易 | simulation（A 股规则）/ paper / live 三模式 |
| 前端 | 简体中文、统一壳、股票分析盘口/五档、交易页 |
| 风控 | 预检、熔断、确认令牌、暴露、仪表盘 |
| 同步 | 15s 轮询 + 回调桥 + 手动同步 |
| 监控 | metrics、Grafana、钉钉级别/静默、告警页 |
| 幂等 | mode 感知哈希键 + DB 唯一约束 |

能力边界速查：[`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md)。

---

<h3 id="s-8-2">8.2 未完全产品化 / 环境依赖</h3>

| 项 | 说明 |
|----|------|
| 真 QMT 实盘 | 代码具备，需 Windows + miniQMT + 券商包 **实机验收** |
| Walk-Forward / AutoML UI | 历史规划中有，当前未完整产品化 |
| AI-Trader 子项目 | 独立实验仓，未挂主菜单 |
| quant_docs 全量蓝图 | 设计参考，**不等于**当前已交付 |

---

<h3 id="s-8-3">8.3 数据库迁移</h3>

```powershell
cd backend
alembic upgrade head
```

| 版本 | 说明 |
|------|------|
| `001` | 初始全量 schema |
| `002` | 订单幂等改为 `(mode, idempotency_key)` 唯一 |

---

<h2 id="s-9">9. 常见问题与解决办法</h2>

[↑ 返回目录](#目录)

<h3 id="s-9-1">9.1 启动与连接</h3>

#### SECRET_KEY / Settings 启动失败

1. 确认仓库根存在 `.env`  
2. 从 `.env.example` 复制并填写必填项  
3. 确认进程工作目录或环境变量能加载到该文件  

#### 数据库连接失败

| 场景 | `DATABASE_URL` 主机 |
|------|---------------------|
| API 在宿主机，DB 在 Docker | `127.0.0.1` |
| 全部在 compose 网络 | `postgres` |

检查：`docker compose ps`、密码 URL 编码、`alembic upgrade head`。

#### Redis 连不上

- 核对 `REDIS_URL` 密码与编码  
- 宿主机访问用 `127.0.0.1`  
- 单进程开发可试关闭依赖 Redis 的 WS 转发（若配置支持）  

#### 前端空白 / 跨域

- `ALLOWED_ORIGINS` 包含前端源（如 `http://localhost:3000`）  
- Vite 是否代理 `/api`、`/ws` 到 8000  
- 浏览器 Network 查看 CORS / 401  

#### 401 Unauthorized

- 请求头加 `X-API-Key` 或 `Bearer`  
- 前端配置 `VITE_API_KEY`  
- `/api/v1/health` 与 `/metrics` 无需 Key  

#### 8000 / 8080 / 3000 连接拒绝

- 宿主机进程可能已退出：`.\scripts\start-host-api.ps1` + `frontend` 的 `npm run dev`  
- 确认 5432/6379 监听；清空错误代理（`NO_PROXY=127.0.0.1,localhost`）  
- 详见 [`docs/06_TROUBLESHOOTING.md`](docs/06_TROUBLESHOOTING.md) §1.5  

---

<h3 id="s-9-2">9.2 数据与回测</h3>

#### 股票列表为空

- `POST /api/v1/stock/sync-universe?backfill_top_n=0` 或 `python -m scripts.seed_stocks`  
- 保持 `SQL_ECHO=false`  

#### 模拟卖出「可卖不足」

- T+1：`POST /api/v1/trade/simulation/release-t1` 或等 Celery 日终任务  

#### 行情偏慢

- 冷启动外网约 200–400ms；热缓存应约 1–30ms  
- 检查 Redis 与 `DATA_CACHE_TTL_QUOTE`  

#### 回测提示无 K 线

```powershell
# 演示：.env 中 BACKTEST_ALLOW_SYNTHETIC_KLINE=true

cd backend
python -m scripts.backfill_kline --codes 000001 --years 1
python -m scripts.backfill_kline --codes 000001 --allow-synthetic
```

或 `POST /api/v1/stock/backfill-kline`。  
**合成数据仅演示，不可作研究结论。**

#### 股票代码不存在

```powershell
python -m scripts.seed_stocks
```

---

<h3 id="s-9-3">9.3 交易</h3>

#### 买入后无法卖出

- 检查是否 T+1：当日买入 `available_qty` 可能为 0  
- 次日或模拟日切后才可卖  

#### 实盘下单失败

1. `TRADE_MODE=live`  
2. 请求带正确 `live_confirm`  
3. 金额 ≤ `LIVE_MAX_ORDER_VALUE`  
4. 熔断未激活  
5. 风控预检通过  
6. miniQMT 已登录且 `QMT_*` 配置正确  
7. 生产 `ALLOW_MOCK_LIVE=false`  

#### 订单状态不更新

- 启动 Worker（15s 同步）  
- 手动 `POST /trade/orders/sync`  
- 检查回调 bridge 日志（是否先落库再 emit）  

#### 幂等返回旧订单

- 相同 mode + 关键字段会命中幂等  
- 需要新单时：改数量/价格或换 signal_id  

---

<h3 id="s-9-4">9.4 AI / 选股</h3>

| 现象 | 排查 |
|------|------|
| 分析很慢或失败 | 检查对应 LLM API Key / 网络 / 超时配置 |
| 信号总是 HOLD | 阈值过严、Agent 降级、置信度不足 |
| 选股为空 | 股票池未 seed、条件过严、数据未回填 |

---

<h3 id="s-9-5">9.5 监控与钉钉</h3>

| 现象 | 排查 |
|------|------|
| `/metrics` 无数据 | backend 是否启动；抓取地址是否正确 |
| Grafana 无面板 | 是否导入 `quant-overview`；Prometheus 数据源 |
| 钉钉不推送 | `ENABLE_DINGTALK_NOTIFY`、Webhook、级别过滤、静默时段、冷却 |
| 想强制测一条 | `POST /risk/alerts/test-dingtalk` |

---

<h3 id="s-9-6">9.6 Worker</h3>

| 现象 | 排查 |
|------|------|
| 任务不执行 | Worker + Beat 是否都在跑；Redis 是否通 |
| ImportError | `PYTHONPATH` 是否同时包含 worker 与 backend |
| 订单不同步 | 队列 `high,normal,low` 是否监听；日志是否有异常 |

---

<h3 id="s-9-7">9.7 目录跳转说明</h3>

**推荐**：用浏览器打开 [`docs/manual.html`](docs/manual.html)，使用**左侧一级 / 二级目录**点击跳转（已做锚点对齐与滚动高亮）。

| 查看方式 | 跳转是否可用 |
|----------|--------------|
| **docs/manual.html（浏览器）** | **推荐**；左侧目录点击即跳到详情 |
| GitHub 上的 README | 支持 `#s-1` 等锚点（无左侧栏） |
| VS Code / Cursor Markdown 预览 | 部分场景对 HTML 标题支持不稳定 |
| 重新生成侧栏文档 | `python scripts/generate_docs_html.py` |

若 Markdown 预览点击无反应：请改用 `docs/manual.html`，或直接搜索章节标题（如 `1.8 三种交易模式`）。

---

<h2 id="s-10">10. 测试</h2>

[↑ 返回目录](#目录)

```powershell
# Backend
cd backend
.\.venv\Scripts\Activate.ps1
pytest -q

# Worker
cd ..\worker
# 确保 PYTHONPATH 含 worker + backend
pytest -q
```

| 套件 | 规模（约） | 覆盖方向 |
|------|------------|----------|
| backend | 130+ | 交易幂等、熔断、风控、回测、AI、钉钉、WS、对账等 |
| worker | 21 | Celery 配置、行情/运维任务、组合同步等 |

建议在改动交易 / 风控 / 回测后至少跑一遍 backend 相关用例。

---

<h2 id="s-11">11. 生产部署注意</h2>

[↑ 返回目录](#目录)

| 序号 | 项 | 要求 |
|------|----|------|
| 1 | 密钥 | 强 `SECRET_KEY`、`API_KEY`、`LIVE_CONFIRM_TOKEN`、DB/Redis 密码 |
| 2 | Mock | `ALLOW_MOCK_LIVE=false`；`QMT_FORCE_MOCK=false` |
| 3 | 合成数据 | `BACKTEST_ALLOW_SYNTHETIC_KLINE=false` |
| 4 | 实盘限额 | 合理 `LIVE_MAX_ORDER_VALUE`；先小额验证 |
| 5 | QMT 部署 | Backend 与 miniQMT **同 Windows 机**；勿仅放 Linux 容器 |
| 6 | 网络 | 数据库 / Redis / 管理端口勿裸奔公网 |
| 7 | 监控 | 打开 Prometheus + Grafana + 钉钉关键级别 |
| 8 | 熔断 | 熟悉激活 / 恢复流程；确认 DB 状态 |
| 9 | 备份 | 定期备份 PostgreSQL；关注迁移版本 |
| 10 | 合规 | 遵守券商协议与当地监管；本系统不承担投资责任 |

**推荐上线顺序：**

1. simulation / paper 全链路验收  
2. `live_verification --dry-run`  
3. 生产配置（关 Mock / 关合成 / 开鉴权）  
4. 小额 live  
5. 再逐步放开策略与额度  

---

<h2 id="s-appendix">附录：历史文档与设计稿</h2>

[↑ 返回目录](#目录)

| 路径 | 用途 |
|------|------|
| 本 `README.md` | **内容源**（以当前代码为准的完整说明） |
| [`docs/manual.html`](docs/manual.html) | **推荐阅读界面**：左侧一级/二级目录 + 点击跳转 |
| `scripts/generate_docs_html.py` | 从 README 重新生成 `manual.html` |
| `docs/quant_docs/` | 历史规划与蓝图，部分超前，仅供参考 |
| `docs/PROGRESS.md` | 历史开发进度记录 |
| `docs/01_INTRODUCTION.md` 等 | 分册草稿；内容可能滞后，请以本 README 为准 |
| `AI-Trader/` | 独立实验项目文档与代码 |

---

**文档结束。** 若需补充某一模块的更深设计细节，可指定章节（例如交易幂等、熔断状态机、回测撮合规则）再单独展开。
