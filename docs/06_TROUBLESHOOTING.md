# 常见问题与解决办法

按现象分类。仍无法解决时，先看 `GET /api/v1/health` 与 backend 日志。

---

## 1. 启动与连接

### 1.1 `SECRET_KEY` / Settings 校验失败

**现象**：backend 启动即报错缺少环境变量。  

**处理**：

1. 确认根目录存在 `.env`（从 `.env.example` 复制）  
2. 工作目录在 `backend` 时，Settings 会读 `backend/.env` 或上层，建议在仓库根配置并保证启动目录能读到，或导出环境变量  

### 1.2 数据库连接失败

**现象**：health 中 `database: error:...`；日志 asyncpg 连接错误。  

**处理**：

| 场景 | DATABASE_URL 主机 |
|------|-------------------|
| API 在宿主机，DB 在 Docker | `127.0.0.1` |
| API 与 DB 都在 compose 网络 | `postgres` |

- 检查容器：`docker compose ps`、`pg_isready`  
- 密码特殊字符是否 URL 编码  
- 是否已执行 `alembic upgrade head`  

### 1.3 Redis 连不上

**现象**：缓存失败、WS 不跨进程、Celery 起不来。  

**处理**：

- `REDIS_URL` 密码与 `redis --requirepass` 一致  
- 宿主机访问用 `127.0.0.1`  
- 开发可临时关 WS Redis：`WS_REDIS_ENABLED=false`（仅单进程）  

### 1.4 前端空白 / 跨域

**处理**：

- 确认 backend `ALLOWED_ORIGINS` 包含前端源  
- Vite 代理：检查 `frontend/vite.config.ts` 是否把 `/api`、`/ws` 转到 8000  
- 浏览器控制台网络面板看 401/CORS  

### 1.5 8000 / 8080 / 3000 连不上（服务「掉了」）

**现象**：股票列表失败、K 线空、账户刷新失败；浏览器 Network 显示 `ERR_CONNECTION_REFUSED`。

**原因**：宿主机后台进程随会话/Job 退出，或未启动。

**处理**：

```powershell
# 看端口
foreach ($p in 3000,8000,8080,5432,6379) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { "PORT $p OK" } else { "PORT $p DOWN" }
}

# 中间件
# docker compose up -d postgres redis
# 或确认本机 PG/Redis 服务

# 应用（推荐脚本）
.\scripts\start-host-api.ps1
# 另开终端：cd frontend; npm run dev
```

确保 `A_STOCK_DATA_URL=http://127.0.0.1:8080`，且 HTTP 代理未劫持本机地址（清空 `HTTP_PROXY` / 设置 `NO_PROXY=127.0.0.1,localhost`）。

### 1.6 401 Unauthorized

**现象**：配置了 `API_KEY` 后接口 401。  

**处理**：

- 请求头：`X-API-Key: <API_KEY>` 或 `Authorization: Bearer <API_KEY>`  
- 前端：`VITE_API_KEY`  
- 健康检查与 `/metrics` 无需 Key  

---

## 2. 数据与回测

### 2.1 回测失败「无可用 K 线」

**处理**：

```powershell
# 允许演示合成
# .env: BACKTEST_ALLOW_SYNTHETIC_KLINE=true

# 或真实回填
cd backend
python -m scripts.backfill_kline --codes 000001 --years 1
# 远程失败时
python -m scripts.backfill_kline --codes 000001 --allow-synthetic
```

API：`POST /api/v1/stock/backfill-kline`  

前端回测可传 `auto_backfill` + `allow_synthetic`。

### 2.2 合成 K 线能跑但结果不可信

**说明**：合成数据仅用于打通链路，**不能**用于策略研究结论。请使用真实行情回填。

### 2.3 a-stock-data 无数据 / K 线为空

**处理**：

- `curl http://127.0.0.1:8080/health`  
- 检查上游数据源网络（服务内部 providers）；**禁用错误系统代理**  
- backend `A_STOCK_DATA_URL` 指向 `http://127.0.0.1:8080`  
- Backend 在 8080 不可用时会 **直连新浪 K 线** 兜底；若仍空，检查外网与代码周期参数（`1d` / `5min` 等）  

### 2.4 股票列表为空 / total 很小

**处理**：

```powershell
# 同步全市场（可能较久）
curl -X POST "http://127.0.0.1:8000/api/v1/stock/sync-universe?backfill_top_n=0"
# 或
cd backend
python -m scripts.seed_stocks
```

- 确认 `fundamental.stocks` 中 `is_active=TRUE` 数量  
- 同步时保持 `SQL_ECHO=false`，否则极慢甚至超时  

### 2.5 股票代码不存在

交易/风控会查 `fundamental.stocks`。先执行 §2.4 同步股票池。

### 2.6 行情很慢（每次 200ms+）

**说明**：冷启动需打腾讯/新浪，约 200–400ms 正常。热路径应在 **1–30ms**（L1+Redis）。

**处理**：

- 确认 Redis 可达、`DATA_CACHE_TTL_QUOTE` ≥ 15  
- 确认 Backend 为最新代码（共享 httpx + L1 缓存）  
- 多票场景应走批量接口/持仓批量取价，避免串行  

---

## 3. 交易

### 3.1 模拟卖出「可卖不足」

**原因**：A 股 T+1，买入当日 `available_qty=0`。  

**处理**：

- 等 Celery 任务 `update_available_quantity`（默认约 9:25）  
- **推荐 API**：`POST /api/v1/trade/simulation/release-t1`（释放非当日买入可卖）  
- 或手动 SQL：`UPDATE trade.positions SET available_qty = total_qty WHERE mode='simulation'`（仅调试）  

### 3.2 实盘下单被拒

| 错误信息关键词 | 处理 |
|----------------|------|
| 系统未开启实盘 | `.env` 设 `TRADE_MODE=live` 并重启 |
| LIVE_CONFIRM | 配置 `LIVE_CONFIRM_TOKEN`，请求带 `live_confirm` |
| 单笔金额超过 | 调高 `LIVE_MAX_ORDER_VALUE` 或减小数量 |
| 不支持的交易模式 | 检查 OrderManager 是否注册 live 适配器 |
| 熔断 | `/risk/fuse-status`，人工 recover |

### 3.3 Paper/Live 订单不更新

**处理**：

1. 前端点「同步挂单/成交」→ `POST /trade/orders/sync`  
2. 确认 Celery worker 在跑 `sync_open_orders`  
3. Mock deferred 需 `force_fill` 或等业务回填  
4. Worker 是否能 `import app`（PYTHONPATH）  

### 3.4 幂等「重复请求」

幂等键包含：mode、信号、代码、方向、类型、数量、限价。  

- 同参数重试会返回旧订单（预期）  
- 改价格/数量即新键  
- 已有库执行 `alembic upgrade head` 应用 `(mode, key)` 唯一索引  

### 3.5 对账 mismatch

**处理**：

- `POST /trade/reconcile?mode=paper|live`  
- Mock 与 DB：paper 成交会镜像适配器；若手动改库会不一致  
- live：以券商为准，检查是否漏同步  

---

## 4. AI / 选股

### 4.1 AI 分析 503 / 超时

**处理**：

- 检查对应厂商 API Key  
- 行情是否拿到（无 price 会直接失败）  
- 超时配置 `*_TIMEOUT`；编排总超时约 45s  

### 4.2 选股结果为空

**处理**：

- 股票池/因子数据是否入库  
- 预设条件过严  
- Redis 缓存旧结果：换条件或清 `screener*` 相关 key  

---

## 5. 监控与通知

### 5.1 Prometheus 抓不到指标

**处理**：

- `curl http://127.0.0.1:8000/metrics` 是否有 `quant_`  
- compose 中 target 为 `api:8000`；宿主机 Prometheus 需改 targets  
- 规则文件：`docker/prometheus/alerts.yml`  

### 5.2 Grafana 无数据

**处理**：

- 数据源 URL：`http://prometheus:9090`  
- 看板 `quant-overview` 是否加载  
- 先确认 Prometheus 能抓到 api  

### 5.3 钉钉收不到

**检查**：

1. `ENABLE_DINGTALK_NOTIFY=true`  
2. Webhook 正确  
3. 级别是否在 `DINGTALK_ALERT_LEVELS`  
4. 是否在 `DINGTALK_QUIET_HOURS` 静默（CRITICAL 默认可 bypass）  
5. 冷却：同内容 5 分钟内不重复  
6. `POST /risk/alerts/test-dingtalk`  

---

## 6. Worker / Celery

### 6.1 任务不执行

**处理**：

- worker 与 beat 是否都启动  
- Redis broker 是否通  
- 队列名是否匹配（high/normal/low）  
- Flower：`http://127.0.0.1:5555`  

### 6.2 `not_configured` / `backend not on PYTHONPATH`

**处理**：

- Docker worker 应有 `PYTHONPATH=/app:/backend`  
- 本地：`$env:PYTHONPATH=".../worker;.../backend"`  
- 或 `WORKER_BACKEND_MODE=http` 且 API 可达  

### 6.3 测试 RuntimeWarning coroutine never awaited

**说明**：worker 测试导入 Celery 任务时的 mock 副作用，**不影响生产**。可忽略或后续清理测试隔离。

---

## 7. 迁移与版本

### 7.1 幂等冲突 / 约束错误

```powershell
cd backend
alembic upgrade head
```

确认存在索引 `uq_orders_mode_idempotency`。

### 7.2 空库无表

```powershell
alembic upgrade head
# 必要时看 docker/postgres/init.sql 是否仅扩展/schema
```

---

## 8. 快速诊断命令

```powershell
# 健康
curl http://127.0.0.1:8000/api/v1/health

# 指标
curl http://127.0.0.1:8000/metrics | Select-String quant_

# 券商环境
curl http://127.0.0.1:8000/api/v1/trade/broker-status

# 实盘预检脚本
cd backend
python -m scripts.live_verification --dry-run --mode paper
```

---

## 9. 仍解决不了时提供的信息

1. `APP_ENV` / 是否 Docker  
2. `/api/v1/health` 完整 JSON  
3. 相关接口请求与响应  
4. backend / worker 最近错误日志（脱敏）  
5. `alembic current` 输出  
