# 系统架构

## 1. 逻辑架构

```
                    ┌─────────────────────────────────────┐
                    │           浏览器 / 前端               │
                    │  Dashboard · 交易 · 回测 · 告警 · …  │
                    └─────────────────┬───────────────────┘
                                      │ HTTP / WS
                    ┌─────────────────▼───────────────────┐
                    │         FastAPI Backend              │
                    │  REST API · 鉴权(API_KEY) · /metrics │
                    │  OrderManager · 风控 · 回测 · AI     │
                    └─────┬───────────┬───────────┬───────┘
                          │           │           │
           ┌──────────────▼──┐  ┌─────▼─────┐  ┌──▼──────────────┐
           │ PostgreSQL/     │  │   Redis   │  │ a-stock-data    │
           │ TimescaleDB     │  │ 缓存/Pub  │  │ 行情 HTTP       │
           └─────────────────┘  │ Celery    │  └─────────────────┘
                                └─────┬─────┘
                                      │
                          ┌───────────▼───────────┐
                          │  Celery Worker/Beat    │
                          │  行情·订单同步·日终    │
                          └───────────────────────┘
                                      │
                          ┌───────────▼───────────┐
                          │  miniQMT (live only)   │
                          └───────────────────────┘
```

---

## 2. 后端模块职责

| 模块 | 职责 |
|------|------|
| `api/*` | HTTP 路由，参数校验，统一 `ok/error` 响应 |
| `services/*` | 用例编排（交易、组合、AI 等） |
| `trade/*` | 下单、幂等、模拟撮合、LiveTrader、QMT 适配、订单同步、事件桥 |
| `risk/*` | 预检规则、熔断、组合快照 |
| `backtest/*` | 撮合引擎、绩效、任务落库 |
| `strategy/*` | 策略目录与配置存储 |
| `data/*` | 行情封装、缓存、K 线回填/合成 |
| `ai/*` | Agent、编排、聚合 |
| `rag/*` | Chroma 检索与公告索引 |
| `ws/*` | 连接管理、Redis 订阅转发 |
| `monitoring/*` | Prometheus 计数器/仪表 |
| `notify/*` | 钉钉与静默时段 |

---

## 3. 交易链路

```
POST /trade/order
  → 数量/限价校验
  → OrderManager
       → live 安全闸（TRADE_MODE / live_confirm / 金额上限）
       → 幂等键查询 (mode + hash)
       → 熔断检查（DB is_active）
       → 风控预检
       → SimulationTrader | LiveTrader
            LiveTrader → QmtAdapter.submit_order
            → INSERT trade.orders
            → 成交则更新持仓/现金（Mock 则镜像适配器账本）
            → emit_order_event（落库后）
  → WS portfolio / alerts（可选）
  → 成交后可自动对账（AUTO_RECONCILE_ON_FILL）
```

### 3.1 订单状态同步

| 路径 | 说明 |
|------|------|
| 轮询 | Celery `sync_open_orders` 约每 15s |
| 回调 | QMT Callback / Mock force_fill → OrderEventBridge |
| 手动 | `POST /trade/orders/sync` |

---

## 4. 回测链路

```
POST /backtest/run
  → 可选 ensure_range 回填 K 线
  → 无数据且允许时用合成 K 线
  → BacktestEngine（T+1、涨跌停、费用）
  → 策略信号生成器（dual_ma 等）
  → 写 backtest.tasks / results
  → 记录 Prometheus backtest 指标
```

---

## 5. 数据 Schema（库）

PostgreSQL 多 schema 划分（见 Alembic `001`）：

- `market` — K 线、行情、资金流  
- `fundamental` — 股票主数据、财报、公告  
- `ai` — 信号、Agent 日志  
- `trade` — 订单、持仓、账户  
- `risk` — 规则、事件、熔断  
- `backtest` — 任务与结果  
- `strategy` / `audit` — 预留  

---

## 6. 安全边界

| 机制 | 说明 |
|------|------|
| API_KEY | 非空时要求 `X-API-Key` 或 `Bearer`（健康检查与 `/metrics` 放行） |
| 实盘确认 | `LIVE_CONFIRM_TOKEN` |
| 熔断 | DB `risk.fuse_records.is_active` 为准，Redis 作缓存 |
| CORS | `ALLOWED_ORIGINS` |
| 端口 | compose 默认仅绑定本机 127.0.0.1 |

---

## 7. 监控与告警

| 组件 | 路径/说明 |
|------|-----------|
| 指标 | `GET /metrics` → Prometheus 抓取 |
| 规则 | `docker/prometheus/alerts.yml` |
| 看板 | Grafana `quant-overview` |
| 业务告警 | Redis `alerts:history` + WS `/ws/alerts` + 钉钉 |

主要指标名：

- `quant_alerts_total{level,type}`
- `quant_orders_total{mode,status}`
- `quant_risk_fuse_active{mode}`
- `quant_dingtalk_sent_total{result}`
- `quant_ws_connections`
- `quant_backtest_total{status}`
