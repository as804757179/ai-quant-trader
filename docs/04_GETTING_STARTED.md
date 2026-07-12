# 项目启动流程

以下默认在 **Windows PowerShell**，路径以仓库根目录为准。  
**Desktop 日常推荐：宿主机混合模式**（§3）；Docker 全栈见 §9。

---

## 1. 前置条件

| 依赖 | 版本建议 | 用途 |
|------|----------|------|
| Docker Desktop | 最新稳定版 | 可选：Postgres / Redis / 全栈 |
| PostgreSQL / Redis | 本机已装亦可 | 宿主机混合时可不经 Docker 跑应用 |
| Python | 3.11+ | Backend / Worker / a-stock-data |
| Node.js | 18+ | Frontend |
| Git | - | 代码 |

可选：

- 各 AI 厂商 API Key（否则 AI 分析会降级/失败）  
- 真盘：Windows + miniQMT + 券商 xtquant  

---

## 2. 配置环境变量

```powershell
cd <仓库根目录>
copy .env.example .env
# 宿主机混合：另准备 .env.host（DATABASE_URL/REDIS_URL 指向 127.0.0.1）
```

**至少修改：**

```env
SECRET_KEY=随机长字符串
DB_PASSWORD=强密码
REDIS_PASSWORD=强密码
DATABASE_URL=postgresql+asyncpg://quant_admin:<URL编码密码>@127.0.0.1:5432/quant_trader
REDIS_URL=redis://:<URL编码密码>@127.0.0.1:6379/0
A_STOCK_DATA_URL=http://127.0.0.1:8080
DATA_CACHE_TTL_QUOTE=15
```

注意：密码含 `#`、`$`、`@` 时必须 **URL 编码** 后再写入 `DATABASE_URL` / `REDIS_URL`。

开发期可暂留：

```env
APP_ENV=development
API_KEY=
TRADE_MODE=simulation
ALLOW_MOCK_LIVE=true
BACKTEST_ALLOW_SYNTHETIC_KLINE=true
SIM_ALLOW_OFF_HOURS=true
SQL_ECHO=false
```

本地跑 backend 时，若 Postgres 在 Docker 内而 API 在宿主机，`DATABASE_URL` 主机用 `127.0.0.1`，不要用 `postgres`（那是容器网络主机名）。

---

## 3. 宿主机混合模式（推荐 · Desktop）

要求：**5432 / 6379 已监听**（本机服务或 `docker compose up -d postgres redis`）。

### 3.1 一键 API + 行情

```powershell
.\scripts\start-host-api.ps1
```

会加载 `.env.host`，释放并启动 **8080（a-stock-data）** 与 **8000（Backend）**，并做健康检查与股票池 total 探测。

### 3.2 分进程手动启动

**代理建议清空**（避免 127.0.0.1 被错误代理）：

```powershell
$env:HTTP_PROXY=""; $env:HTTPS_PROXY=""; $env:ALL_PROXY=""
$env:NO_PROXY="127.0.0.1,localhost"
$env:TZ="Asia/Shanghai"; $env:PYTHONUTF8="1"
```

```powershell
# 1) 行情
cd a-stock-data\service
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8080

# 2) Backend（另开终端，先加载 .env.host 中的 DATABASE_URL 等）
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3) Frontend
cd frontend
npm run dev -- --host 127.0.0.1 --port 3000

# 4) Celery（可选）
cd worker
# 使用 backend venv 或 worker venv
python -m celery -A celery_app worker -l info -P solo
```

### 3.3 端口一览

| 服务 | 端口 |
|------|------|
| Frontend | 3000 |
| Backend | 8000 |
| a-stock-data | 8080 |
| Postgres | 5432 |
| Redis | 6379 |

### 3.4 验证

```powershell
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8000/api/v1/health
curl "http://127.0.0.1:8000/api/v1/stock/list?page_size=1"
# 期望 data.total ≈ 5500+
```

浏览器：http://localhost:3000

---

## 4. 启动基础设施（Docker 仅中间件）

```powershell
docker compose up -d postgres redis
# 也可把 a-stock-data 放进 compose：
docker compose up -d postgres redis a-stock-data
```

检查：

```powershell
docker compose ps
curl http://127.0.0.1:8080/health
```

可选监控：

```powershell
docker compose up -d prometheus grafana
# Grafana: http://127.0.0.1:3001  （密码见 .env GRAFANA_PASSWORD）
```

---

## 5. 数据库迁移与初始化

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

alembic upgrade head
```

可选种子数据：

```powershell
python -m scripts.seed_stocks
python -m scripts.init_simulation_account
python -m scripts.backfill_kline --codes 000001 --years 1 --allow-synthetic
```

或通过 API 同步全市场股票池（较慢）：

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/stock/sync-universe?backfill_top_n=0"
```

---

## 6. 启动 Backend（通用）

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

验证：

- 健康检查：http://127.0.0.1:8000/api/v1/health  
- API 文档：http://127.0.0.1:8000/api/docs  
- 指标：http://127.0.0.1:8000/metrics  

---

## 7. 启动 Frontend

```powershell
cd frontend
npm install
npm run dev
```

打开：http://127.0.0.1:3000  

若生产启用了 `API_KEY`，前端需：

```env
# frontend/.env.development 或构建时
VITE_API_KEY=与后端一致
```

实盘确认令牌（可选）：

```env
VITE_LIVE_CONFIRM_TOKEN=与 LIVE_CONFIRM_TOKEN 一致
```

---

## 8. 启动 Worker（可选但推荐）

行情同步、订单同步、日终 T+1 释放等依赖 Celery。

```powershell
cd worker
# 与 backend 共用依赖时可复用 venv，或单独安装 requirements
$env:PYTHONPATH="<仓库>\worker;<仓库>\backend"
$env:DATABASE_URL="..."
$env:REDIS_URL="..."
celery -A celery_app worker -Q high,normal,low --loglevel=info -P solo
```

另开终端（beat，可选）：

```powershell
celery -A celery_app beat --loglevel=info --scheduler redbeat.RedBeatScheduler
```

Docker 方式：

```powershell
docker compose up -d worker scheduler
```

Worker 镜像已设置 `PYTHONPATH=/app:/backend`。

**无 Worker 时**：模拟盘可手动释放 T+1 可卖：

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/trade/simulation/release-t1"
```

---

## 9. 一键 Docker（含 API/前端）

```powershell
copy .env.example .env
# 按模板改密码后
docker compose up -d --build
```

注意：

- 真 **QMT 不能** 指望容器内 backend；实盘 backend 应在 Windows 宿主机与 miniQMT 同机。  
- 容器内服务互联主机名用 compose 服务名（`postgres`、`redis`、`api`）。  

---

## 10. 验证清单

| 步骤 | 命令/操作 | 期望 |
|------|-----------|------|
| 健康 | `GET /api/v1/health` | `status` ok，`database` ok |
| 行情服务 | `GET http://127.0.0.1:8080/health` | `status` ok |
| 股票池 | `GET /stock/list?page_size=1` | `total` ≈ 5500+ |
| 行情 | `GET /stock/000001/quote` | 有 `price`；二次请求应明显更快 |
| 策略 | 前端「策略」页 | 4 个内置策略 |
| 回测 | 前端回测，允许合成 K 线 | 返回 metrics |
| 模拟交易 | 交易页 mode=simulation | 有行情时能下单；次日/释放后可卖 |
| Paper | mode=paper | Mock 成交/同步 |
| 告警 | 告警页 | WS 连接状态可见 |
| 指标 | `/metrics` | 含 `quant_` 前缀 |

实盘预检：

```powershell
cd backend
python -m scripts.live_verification --dry-run --mode paper
python -m scripts.live_verification --mode paper --execute --code 000001 --qty 100 --price 0.01
```

---

## 11. 测试

```powershell
cd backend
python -m pytest tests/ -q

cd ..\worker
python -m pytest tests/ -q
```
