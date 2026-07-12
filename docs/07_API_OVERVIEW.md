# API 概览

- 文档交互：http://127.0.0.1:8000/api/docs  
- OpenAPI：http://127.0.0.1:8000/api/openapi.json  
- 统一响应：`{ success, data, message, timestamp, error_code? }`  
- 鉴权：配置 `API_KEY` 后需要 `X-API-Key` 或 `Bearer`  

以下为常用路径前缀 **`/api/v1`**。

---

## 1. 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/metrics`（根路径） | Prometheus，**无前缀 /api/v1** |

---

## 2. 股票 `/stock`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/stock/list` | 列表检索（支持 market/sector/board/keyword 模糊） |
| POST | `/stock/sync-universe` | 从 a-stock-data 同步全市场到 `fundamental.stocks` |
| GET | `/stock/{code}/profile` | 档案 |
| GET | `/stock/{code}/quote` | 实时行情（L1+Redis 缓存，默认 TTL 15s） |
| GET | `/stock/{code}/kline` | K 线；`period`：`1min`/`5min`/`15min`/`30min`/`60min`/`1d`/`1w`/`1M` |
| GET | `/stock/{code}/fund-flow` | 资金流 |
| GET | `/stock/{code}/news` | 新闻/公告摘要 |
| POST | `/stock/backfill-kline` | 批量回填 K 线 |

### 2.1 行情微服务 a-stock-data（`:8080`，无 `/api/v1` 前缀）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/stock/list` | 全市场列表（默认 24h 本地缓存） |
| GET | `/quote/{code}` | 单票行情（腾讯优先） |
| GET | `/quotes?codes=000001,600519` | **批量行情**（逗号分隔，最多约 80） |
| GET | `/kline/{code}?period=&limit=` | K 线 |

---

## 3. AI `/ai`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ai/signals` | 信号列表 |
| POST | `/ai/{code}/analyze` | 触发分析 |
| GET | `/ai/{code}/signal` 等 | 最新信号/历史（以 openapi 为准） |

---

## 4. 选股 `/screener`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/screener/screen` | 条件或预设筛选 |
| GET | `/screener/presets` | 预设列表 |
| POST | `/screener/theme` | 主题选股 |

---

## 5. 策略 `/strategy`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/strategy/list` | 内置策略+配置 |
| GET | `/strategy/{type}` | 单个策略 |
| POST | `/strategy/create` | 保存覆盖配置 |
| POST | `/strategy/{type}/update` | 启停/参数 |

类型：`dual_ma` | `bollinger` | `rsi` | `macd`。

---

## 6. 回测 `/backtest`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/backtest/run` | 同步执行回测 |
| GET | `/backtest/tasks` | 任务列表 |
| GET | `/backtest/{id}/status` | 任务状态与结果 |

`run` 常用 body：

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

## 7. 风控 `/risk`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/risk/rules` | 规则列表 |
| GET | `/risk/fuse-status` | 熔断状态 |
| POST | `/risk/fuse/activate` | 触发熔断 |
| POST | `/risk/fuse/recover` | 解除熔断 |
| GET | `/risk/exposure` | 暴露度 |
| POST | `/risk/pre-check` | 下单前检查 |
| GET | `/risk/alerts` | 告警历史 |
| GET | `/risk/alerts/summary` | 告警计数 |
| POST | `/risk/alerts/test-dingtalk` | 钉钉测试 |
| GET | `/risk/dashboard` | 仪表盘聚合 |

---

## 8. 交易 `/trade`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/trade/order` | 下单 |
| POST | `/trade/order/cancel` | 撤单 |
| GET | `/trade/orders` | 订单列表 |
| GET | `/trade/orders/{id}` | 订单详情 |
| POST | `/trade/orders/sync` | 同步未终态订单 |
| POST | `/trade/orders/{id}/sync` | 同步单笔 |
| POST | `/trade/simulation/release-t1` | 模拟盘：释放非当日买入的可卖数量（T+1） |
| GET | `/trade/mode` | 系统模式与适配器 |
| GET | `/trade/broker-status` | QMT/Mock 探测 |
| POST | `/trade/reconcile` | 本地 vs 券商对账 |

下单 body 示例：

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

实盘增加：`"mode":"live", "live_confirm":"<LIVE_CONFIRM_TOKEN>"`。

---

## 9. 组合 `/portfolio`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portfolio/summary` | 资产摘要 |
| GET | `/portfolio/positions` | 持仓列表（批量行情估值，避免 N 次串行 quote） |

查询参数常含 `mode`（如 `simulation`）。

---

## 10. WebSocket `/ws`

| 路径 | 说明 |
|------|------|
| `/ws/quotes/{code}` | 单股行情 |
| `/ws/signals` | AI 信号 |
| `/ws/alerts` | 告警 |
| `/ws/portfolio?mode=` | 组合/订单推送 |

心跳：客户端发 `ping`，服务端回 `pong`。

---

## 11. 错误与幂等

- 业务失败常仍 HTTP 200，看 `data.success` 或 `success` 字段（以实际封装为准）  
- 校验失败可 400 + `error_code`  
- 重复下单：相同幂等键返回已有订单（`idempotent: true`）  

幂等键包含：mode、信号、代码、方向、类型、数量、限价。
