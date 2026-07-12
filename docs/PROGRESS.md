# AI Quant Trader Pro — 开发进度追踪

| 字段 | 值 |
|------|-----|
| **项目** | AI Quant Trader Pro V1 |
| **文档版本** | **v6.1（Desktop 运维增强）** |
| **最后更新** | 2026-07-10 |
| **项目状态** | **V1 可运行 · 维护 + 桌面副本增强** |
| **代码同步校验** | 以 Desktop 副本为准；详见 `docs/CURRENT_STATUS.md` |
| **Desktop 副本** | `C:\Users\as804\Desktop\ai-quant-trader-pro-v1-GrokBuild` |
| **当前任务** | 宿主机混合部署、全市场数据、模拟 A 股规则、接口性能 ✅ |

---

## 〇-B、Desktop 运维与体验增强 ✅（2026-07-09 ~ 2026-07-10）

在 **Desktop 副本** 上完成的可运行增强（与维护期主线兼容）：

| 项 | 交付 | 状态 |
|----|------|------|
| 宿主机混合栈 | `.env.host`、`scripts/start-host-api.ps1`、PG/Redis + 本机 8000/8080/3000 | ✅ |
| 全市场股票池 | 新浪列表缓存、active ≈ 5529、`POST /stock/sync-universe` | ✅ |
| 时区 / 语言 | `Asia/Shanghai`、前端 zh-CN | ✅ |
| 模拟交易 A 股规则 | 真实行情优先、T+1、整手、涨跌停、费用；`release-t1` API | ✅ |
| 股票分析 UI | 多周期 K 线、完整盘口/五档、同花顺风格布局 | ✅ |
| 统一前端壳 | `PageShell`、固定侧栏、响应式 | ✅ |
| 接口性能 | L1+Redis 缓存、TTL 行情 15s、共享 HTTP 池、批量 `/quotes`、持仓批量取价、K 线异步落库 | ✅ |
| 文档 | `CURRENT_STATUS` / 启动 / 排障 / API / README 同步 | ✅ |

**能力边界与端口速查**：见 [`docs/CURRENT_STATUS.md`](./CURRENT_STATUS.md)。

---

## 〇、整理与复盘 Phase 1 ✅（2026-07-08）

### 代码清理

| 项 | 处理 | 状态 |
|----|------|------|
| `TODO`/`FIXME`/`HACK` | 全局扫描 backend/frontend，无遗留标记 | ✅ |
| 重复 `/metrics` 端点 | 移除 `api/monitoring.py` 冗余路由，保留 `main.py /metrics` | ✅ |
| `strategies.py` | 整理乱序 import，移除未使用类型导入 | ✅ |
| `App.tsx` | 补全 `Placeholder` 组件 import | ✅ |
| 测试 | 全量 `pytest` 213 passed | ✅ |

### 文档整理

| 文档 | 动作 | 状态 |
|------|------|------|
| `README.md` | 新建：架构概览、核心能力、快速开始、限制说明 | ✅ |
| `docs/ARCHITECTURE.md` | 新建：分层架构、API/WS、数据流、技术栈 | ✅ |
| `docs/DEPLOYMENT.md` | 新建：开发/生产部署步骤与排障 | ✅ |
| `docs/QMT_REAL_INTEGRATION.md` | v1.3：修正路径、补充监控自检 | ✅ |
| `docs/OPS_REAL_TRADING.md` | v1.1：补充文档索引 | ✅ |

---

## 已完成核心能力

| 领域 | 交付物 |
|------|--------|
| **基础设施** | Docker 开发/生产 compose、TimescaleDB、Redis、Celery、Nginx |
| **数据** | a-stock-data 微服务、行情缓存、K 线查询 |
| **AI** | 多 Agent 编排 API、RAG 向量检索、信号聚合 |
| **选股** | 因子选股引擎 API（前端占位） |
| **策略** | 双均线/布林带/RSI/MACD、策略管理页、参数持久化 |
| **回测** | 异步任务、Walk-Forward、AutoML、多任务绩效对比 |
| **交易** | 模拟/实盘、QMT 全链路、订单状态机、补偿同步 |
| **风控** | 实盘预检、二次确认、熔断、暴露度监控 |
| **对账** | 本地 vs QMT 交叉验证、CRITICAL 告警 |
| **监控** | Prometheus、告警规则、WebSocket、Grafana、运维自检 |
| **前端** | 仪表盘、股票分析、策略、回测、交易、实盘监控 |
| **运维** | Windows 启停脚本、小额验证、应急处置手册 |

---

## 当前主要限制

| 限制 | 说明 | 后续方向 |
|------|------|----------|
| **前端占位** | `/ai`、`/screener` 页面未实现（后端 API 已有） | 按需补全 UI |
| **Windows 绑定** | QMT/xtquant 仅 Windows，backend 不可 Docker 化 | 架构约束，维持同机部署 |
| **策略实盘调度** | 策略可管理/回测，全自动实盘策略运行未产品化 | Phase 7 候选 |
| **AI-Trader 子模块** | 独立实验项目，未接入主前端 | 评估合并或废弃 |
| **回测 Phase 4** | 约 2% 边缘场景/文档对齐遗留 | 维护期按需修补 |
| **钉钉告警** | Webhook 接口已预留，需用户自行配置 | 生产 `.env` 启用 |
| **空目录** | `backend/app/models/` 为历史占位 | 可删除或迁移 ORM |

---

## 一、阶段总览

```
Phase 0  基础设施 + 项目骨架     ████████████████████  100%  ✅
Phase 1  数据层 + MVP 骨架       ████████████████████  100%  ✅
Phase 2  AI 核心                 ████████████████████  100%  ✅
Phase 3  自动化 + WS + 选股      ████████████████████  100%  ✅
Phase 4  回测系统                ███████████████████░   98%  ✅（维护期）
Phase 5  实盘准备                ████████████████████  100%  ✅
Phase 6  真实 QMT 对接           ████████████████████  100%  ✅  ← 已完成
```

| 阶段 | 状态 | 完成度 | 核心交付物 |
|------|------|--------|------------|
| Phase 5 | ✅ | 100% | 异步回测 + QMT 骨架 + 对账 + 实盘风控 + 监控 |
| Phase 6 | ✅ **已完成** | **100%** | 真实 QMT 全链路对接 + 生产部署 |

**质量指标**：后端 **213 passed** · 监控生产化 **12 passed** · 前端 **build ✓**

---

## 二、监控告警生产化验证 ✅（2026-07-08）

### 2.1 Prometheus 抓取与指标

| 模块 | 能力 | 状态 |
|------|------|------|
| `prometheus.prod.yml` | `host.docker.internal:8000/metrics` 抓取宿主机 backend | ✅ |
| `REQUIRED_METRICS` | 订单/风控/熔断/QMT/暴露/对账/告警 10 项指标清单 | ✅ |
| `risk_fuse_active` | 熔断状态 Gauge（live/simulation） | ✅ |
| `GET /monitoring/metrics/verify` | 生产自检 API（指标 + 规则 + 冷却） | ✅ |

### 2.2 告警规则与冷却

| 告警 | 级别 | 验证方式 | 状态 |
|------|------|----------|------|
| 熔断触发 | CRITICAL | `LiveOpsVerifier` + `alerts.yml` FuseActive | ✅ |
| QMT 断线 | ERROR | 模拟 snapshot + Prometheus `QMTDisconnected` | ✅ |
| 对账 CRITICAL | CRITICAL | 模拟 snapshot + Prometheus 规则 | ✅ |
| 日亏损接近上限 | WARNING | 模拟 snapshot + Prometheus 规则 | ✅ |
| 告警冷却 | — | `MONITORING_ALERT_COOLDOWN` 抑制重复推送 | ✅ |

### 2.3 告警通知与前端

| 模块 | 能力 | 状态 |
|------|------|------|
| WebSocket `/ws/alerts` | Redis 发布 → 前端实时订阅 | ✅ |
| 钉钉 Webhook | `notify_dingtalk()` 预留 + mock 测试 | ✅ |
| `Monitoring.tsx` | 指标卡片、熔断状态、WS 连接、手动/自动刷新 | ✅ |

### 2.4 产出文件

| 层级 | 文件 |
|------|------|
| 后端 | `monitoring/live_ops_verify.py`（扩展）、`monitoring/metrics.py`（fuse gauge） |
| 后端 | `api/monitoring.py`（`/metrics/verify`）、`collector.py` |
| 运维 | `docker/prometheus/alerts.yml`（FuseActive 规则） |
| 前端 | `pages/Monitoring.tsx` |
| 测试 | `test_monitoring_prod.py`（11） |
| 文档 | `docs/OPS_REAL_TRADING.md` §六 监控告警验证与排查 |

---

## 三、策略与回测深化 Phase 2 ✅（2026-07-08）

### 2.1 策略管理页

| 模块 | 能力 | 状态 |
|------|------|------|
| `Strategy.tsx` | 策略列表、描述/场景、启用禁用、参数编辑 | ✅ |
| 一键回测 | 跳转 `/backtest` 并带入策略类型与参数 | ✅ |
| `GET /strategy/list` | 返回目录 + 启用状态 + 当前参数 | ✅ |
| `POST /strategy/{type}/update` | 更新启用状态与参数覆盖 | ✅ |
| `strategy/catalog.py` | 内置策略元数据（含 MACD） | ✅ |
| `strategy/config_store.py` | JSON 持久化策略配置 | ✅ |

### 2.2 策略绩效对比

| 模块 | 能力 | 状态 |
|------|------|------|
| `strategy_name` | 回测结果 `trade_list` 中保存策略标识 | ✅ |
| `GET /backtest/history` | 已完成回测记录列表 | ✅ |
| `POST /backtest/compare` | 多任务指标对比 + 归一化权益曲线 | ✅ |
| `Backtest.tsx` | 多选对比表 + 叠加权益曲线图 | ✅ |
| 类型定义 | `frontend/src/types/strategy.ts` | ✅ |

### 2.3 产出文件

| 层级 | 文件 |
|------|------|
| 后端 | `api/strategy.py`, `services/strategy_service.py`, `services/backtest_compare_service.py` |
| 后端 | `strategy/catalog.py`, `strategy/config_store.py`, `schemas/strategy.py` |
| 后端 | `backtest/task_repository.py`, `api/backtest.py`（history/compare） |
| 前端 | `pages/Strategy.tsx`, `types/strategy.ts`, `App.tsx`, `Backtest.tsx` |
| 测试 | `test_strategy_api.py`（3）, `test_backtest_compare.py`（2） |

---

## 四、策略与回测深化 Phase 1 ✅（2026-07-08）

### 3.1 策略模板扩展

| 策略 | 文件 | 参数 | 状态 |
|------|------|------|------|
| 布林带均值回归 | `strategy/bollinger.py` | `period`, `std_dev_multiplier` | ✅ |
| 双均线交叉 | `strategy/dual_ma.py` | `short_window`, `long_window` | ✅ |
| RSI 均值回归 | `strategy/rsi_mean_reversion.py` | `period`, `oversold`, `overbought` | ✅ |
| 基类 + 注册 | `strategy/base.py`, `strategy/__init__.py` | `BaseStrategy`, `STRATEGY_REGISTRY` | ✅ |

### 3.2 回测报告增强

| 模块 | 能力 | 状态 |
|------|------|------|
| `build_walkforward_summary()` | IS/OOS 平均指标对比 + `comparison` 表 | ✅ |
| `build_optimization_history()` | 优化 score 曲线 + `best_score_so_far` | ✅ |
| `executor.py` | 任务配置 `run_walk_forward` / `run_automl` | ✅ |
| `result_store.py` | 结果 JSON 附带 WF/优化摘要 | ✅ |
| `Backtest.tsx` | WF 对比表、各折明细、优化曲线、权益+回撤图 | ✅ |

### 3.3 产出文件

| 层级 | 文件 |
|------|------|
| 策略 | `backend/app/strategy/{base,bollinger,dual_ma,rsi_mean_reversion,__init__}.py` |
| 回测 | `walkforward.py`, `automl.py`, `executor.py`, `result_store.py`, `strategies.py` |
| API | `schemas/backtest.py`, `services/backtest_task_service.py` |
| 前端 | `frontend/src/pages/Backtest.tsx` |
| 测试 | `test_strategies.py`（7）, `test_backtest_report.py`（3） |

---

## 四、实盘交易页强化 ✅（2026-07-08）

### 4.1 能力清单

| 模块 | 能力 | 状态 |
|------|------|------|
| `Trade.tsx` | 模拟/实盘 Segmented 切换 | ✅ |
| 账户概览 | 总资产、现金、持仓市值、今日盈亏（Card + Statistic） | ✅ |
| 持仓表 | QMT 数据、多列排序、市值占比 `weight_pct`、浮盈/浮盈率 | ✅ |
| 下单流程 | 风控拦截提示、熔断/QMT 未连接禁用、`requires_confirmation` 二次确认 Modal | ✅ |
| 订单列表 | 未完成 / 最近成交 Tab、Popconfirm 一键撤单 | ✅ |
| 状态栏 | QMT 连接 Badge、熔断状态、手动连接 QMT、WS 实时连接指示 | ✅ |
| 风控限额 | 实盘模式展示 `GET /risk/limits` 阈值卡片 | ✅ |
| WebSocket | `/ws/portfolio?mode=...` 订单推送刷新、`/ws/alerts` 告警横幅 | ✅ |
| 后端 API | 撤单、风控限额、持仓格式化、pre-check live 模式 | ✅ |
| 测试 | `test_trade_api.py`（3 passed） | ✅ |
| 构建 | `npm run build` 通过（~20s） | ✅ |

### 4.2 产出文件

| 层级 | 文件 | 变更说明 |
|------|------|----------|
| 前端页面 | `frontend/src/pages/Trade.tsx` | 重写：模式切换、持仓/订单/下单/状态栏/WS/二次确认 |
| 前端 API | `frontend/src/api/client.ts` | 新增 `postPath<T>()` 辅助（无 body POST，用于撤单等） |
| 后端 API | `backend/app/api/trade.py` | 新增 `POST /trade/order/{order_id}/cancel` |
| 后端 API | `backend/app/api/risk.py` | 新增 `GET /risk/limits`；`POST /risk/pre-check` 支持 live + `requires_confirmation` |
| 后端服务 | `backend/app/services/trade_service.py` | `cancel_order()`、`_format_positions()`（含 `name`/`weight_pct`）、`list_orders` 增加 `broker_order_id` |
| 测试 | `backend/tests/test_trade_api.py` | 风控限额 + 撤单成功/失败 共 3 用例 |

### 4.3 前端调用的 API 端点

| 方法 | 端点 | 用途 |
|------|------|------|
| GET | `/trade/positions?mode=` | 持仓（含 name、weight_pct） |
| GET | `/trade/account?mode=` | 账户资金 |
| GET | `/trade/orders?mode=` | 订单列表 |
| POST | `/trade/order` | 下单（`confirmed` 字段控制二次确认） |
| POST | `/trade/order/{id}/cancel?mode=` | 撤销未完成订单 |
| GET | `/trade/qmt/status` | QMT 连接状态 |
| POST | `/trade/qmt/connect` | 手动连接 QMT |
| GET | `/risk/fuse-status?mode=live` | 熔断状态 |
| GET | `/risk/limits?mode=live` | 风控阈值展示 |
| WS | `/ws/portfolio?mode=live` | 持仓/订单实时推送（`type: order_update`） |
| WS | `/ws/alerts` | 风控/系统告警推送 |

### 4.4 下单二次确认流程

1. 实盘模式首次提交 `confirmed=false`
2. 若响应 `requires_confirmation=true` → 弹窗展示 `risk_report.checks` / `warnings`
3. 用户确认后 `confirmed=true` 重新提交
4. 熔断（`fuse_triggered`）时禁止下单并显示 Alert

---

## 五、Phase 6 子任务进度（全部完成）

| Step | 任务 | 状态 | 核心文件 | 测试 |
|------|------|------|----------|------|
| 1 | RealQMTTrader + xtquant 桥接 | ✅ | `qmt_xt_client.py` | 13 |
| 2 | QMT 模拟盘端到端联调 | ✅ | `qmt_e2e.py`, `qmt_order_sync.py` | 11 |
| 3 | 成交回报 → 状态机 + 对账联动 | ✅ | `qmt_order_state_machine.py` | 12 |
| 4 | 生产部署与小额实盘验证 | ✅ | `docker-compose.prod.yml`, `OPS_REAL_TRADING.md` | 7 |

### Phase 6 Step 4 已交付能力

| 模块 | 能力 | 状态 |
|------|------|------|
| `docker-compose.prod.yml` | 生产基础设施 Docker 化（backend 宿主机） | ✅ |
| Windows 脚本 | `start-live.ps1` / `stop-live.ps1` / `collect-logs.ps1` | ✅ |
| `.env.production.example` | 生产环境变量模板 | ✅ |
| `live_startup.py` | 应用启动自动连接 QMT + 同步 | ✅ |
| `live_verification.py` | 100 股测试单验证脚本 | ✅ |
| `live_ops_verify.py` | 监控告警验证（熔断/断线/对账 CRITICAL） | ✅ |
| `OPS_REAL_TRADING.md` | 应急处置手册（4 大场景） | ✅ |
| Prometheus prod | `prometheus.prod.yml` 抓取宿主机 metrics | ✅ |

---

## 六、Step 完成日志

### 策略与回测深化 Phase 2 ✅（2026-07-08）

- `Strategy.tsx`：策略列表、启用/禁用、参数编辑、一键回测跳转
- `GET /strategy/list`、`POST /strategy/{type}/update`
- `GET /backtest/history`、`POST /backtest/compare`
- 回测结果保存 `strategy_name` / `strategy_type` / `strategy_params`
- `Backtest.tsx`：策略预填 + 多记录绩效对比 + 叠加权益曲线
- 测试 +5（`test_strategy_api`, `test_backtest_compare`）· 全量 **201 passed**

### 策略与回测深化 Phase 1 ✅（2026-07-08）

- `backend/app/strategy/`：`BaseStrategy` + 布林带 / 双均线 / RSI 三策略 + 注册表
- `build_walkforward_summary()`：IS/OOS 平均指标 `comparison` 对比表
- `build_optimization_history()`：AutoML score 曲线摘要
- `executor.py`：回测任务支持 `run_walk_forward` / `run_automl`
- `Backtest.tsx`：WF 对比表、优化历史曲线、权益+回撤双线图
- 测试 `test_strategies.py`（7）+ `test_backtest_report.py`（3）· 全量 **196 passed**

### 实盘交易页强化 ✅（2026-07-08）

- `frontend/src/pages/Trade.tsx`：模拟/实盘切换、账户卡片、持仓排序表、订单 Tab、撤单、二次确认 Modal
- `frontend/src/api/client.ts`：`postPath()` 无 body POST 辅助
- `backend/app/api/trade.py`：`POST /trade/order/{order_id}/cancel`
- `backend/app/api/risk.py`：`GET /risk/limits`；live 模式 pre-check 返回 `requires_confirmation` / `fuse_triggered`
- `backend/app/services/trade_service.py`：持仓 `name`/`weight_pct` 格式化、`cancel_order()`、`broker_order_id` 透出
- WebSocket 联动：`order_update` 触发页面自动刷新
- 测试 `test_trade_api.py`（3 passed）· 全量 **186 passed** · 前端 build ✓

### Phase 6 Step 4 — 生产部署与小额实盘验证 ✅（2026-07-08）

- `docker-compose.prod.yml`：postgres/redis/worker/prometheus/grafana 容器化
- Windows 启停脚本 + 日志归档 `collect-logs.ps1`
- `.env.production.example`：`TRADE_MODE=live` + QMT 实盘配置
- `bootstrap_live_trading()` 集成至 `main.py` lifespan
- `live_verification.py`：配置检查 → QMT 连接 → 对账 → 可选 100 股测试单
- `LiveOpsVerifier`：验证熔断/QMT断线/对账 CRITICAL 告警
- `docs/OPS_REAL_TRADING.md`：断线/状态不同步/对账差异/熔断恢复
- `docs/QMT_REAL_INTEGRATION.md` v1.2 补充生产部署与验证章节
- 测试 `test_live_ops.py`（7 passed）

### Phase 6 Step 1–3
（略，见 v4.1–v4.3）

---

## 七、生产部署快速指引

```powershell
copy .env.production.example .env.production
# 配置 QMT_PATH、QMT_ACCOUNT_ID

.\scripts\windows\start-live.ps1

cd backend
python -m scripts.live_verification --dry-run
```

应急手册：[`docs/OPS_REAL_TRADING.md`](OPS_REAL_TRADING.md)

---

## 八、维护期建议

1. 生产部署前执行 `python -m scripts.live_verification --dry-run`
2. 定期查看 `/monitoring` 与 Grafana 仪表盘
3. 按需补全 `/ai`、`/screener` 前端页面
4. 若恢复开发，优先考虑：策略实盘自动调度、AI 前端、Phase 4 收尾

---

## 九、更新规则

每完成 Step 后同步：版本号 · 测试数 · 子任务表 · Step 日志 · **Desktop 副本**

> **注意**：Grok Build 在 worktree 中开发，代码变更写入 worktree 路径；`PROGRESS.md` 需同步至 Desktop 副本，否则 Desktop 项目内看到的仍是旧版。