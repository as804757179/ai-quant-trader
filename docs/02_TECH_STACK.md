# 技术选型

## 1. 总览

| 层次 | 选型 | 用途 |
|------|------|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design Pro | 管理端 UI、交易/回测/告警 |
| API | FastAPI + Uvicorn | REST + WebSocket |
| ORM/迁移 | SQLAlchemy 2 async + Alembic | 异步访问 PostgreSQL |
| 数据库 | PostgreSQL 15 + TimescaleDB | 时序 K 线、业务表 |
| 缓存/队列 | Redis 7 | 缓存、Pub/Sub、Celery Broker |
| 异步任务 | Celery + RedBeat | 行情同步、订单同步、日终、对账 |
| AI | OpenAI / Anthropic / DeepSeek / 通义（可配） | 多 Agent 分析 |
| 向量 | ChromaDB | 研报/公告 RAG |
| 数据计算 | Pandas / NumPy | 指标与回测辅助 |
| 监控 | Prometheus + Grafana + prometheus-client | 指标与告警规则 |
| 通知 | 钉钉机器人 Webhook | CRITICAL/ERROR 等可配级别 |
| 交易适配 | 自研 QmtAdapter + Mock + XtQuant 骨架 | 统一 paper/live |
| 行情微服务 | a-stock-data（FastAPI） | 外部数据源封装 |

---

## 2. 选型理由（简要）

### 2.1 后端 FastAPI

- 异步友好，适合 IO 密集（行情、AI HTTP、WS）  
- 自带 OpenAPI：`/api/docs`  
- 与 Pydantic Settings 配合环境配置清晰  

### 2.2 TimescaleDB

- K 线、行情类时序写入/查询友好  
- 与 PostgreSQL 生态兼容，业务表同库不同 schema  

### 2.3 Celery + Redis

- 定时/长任务与 API 进程隔离  
- RedBeat 基于 Redis 的分布式调度  
- Worker Dockerfile 已设置 `PYTHONPATH=/app:/backend`，可直接 `import app`  

### 2.4 多模型 Agent

- 不同能力拆分到不同厂商模型，单点故障可降级  
- `run_safe` 超时与中性结果，避免整链路挂死  

### 2.5 交易分层

```
API → OrderManager（风控/熔断/幂等）
    → SimulationTrader | LiveTrader
         └─ QmtAdapter（Mock / XtQuant）
```

- **simulation**：纯本地规则撮合，不碰券商  
- **paper**：Mock 适配器，方便无 QMT 时测全链路  
- **live**：真 QMT；开发可 Mock 降级，生产应关闭  

### 2.6 前端 React + Ant Design Pro

- 管理后台形态匹配（表格、表单、布局）  
- Vite 开发体验好；K 线用 lightweight-charts  

---

## 3. 端口一览（默认）

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 Vite / Nginx | 3000 | UI |
| Backend API | 8000 | REST + WS + `/metrics` |
| a-stock-data | 8080 | 行情微服务 |
| PostgreSQL | 5432 | 仅绑定 127.0.0.1 |
| Redis | 6379 | 仅绑定 127.0.0.1 |
| Prometheus | 9090 | 指标 |
| Grafana | 3001 | 看板（容器映射 3000→3001） |
| Flower（可选） | 5555 | Celery 监控 |

---

## 4. 目录与技术对应

```
backend/app/
  api/          # 路由
  ai/           # Agent 与聚合
  backtest/     # 回测引擎与服务
  data/         # 数据服务、回填
  risk/         # 预检、熔断、监控
  trade/        # 交易、QMT、订单同步
  rag/          # 向量检索与索引
  monitoring/   # Prometheus 指标
  notify/       # 钉钉、静默时段
  ws/           # WebSocket

worker/         # Celery 任务入口
frontend/src/   # 页面与 API 客户端
a-stock-data/   # 行情服务
docker/         # 中间件配置
```

---

## 5. 已知依赖注意点

| 点 | 说明 |
|----|------|
| Python | 推荐 3.11+（Docker 镜像 3.11） |
| Windows | 真 QMT 仅 Windows |
| 密码特殊字符 | `DATABASE_URL` / `REDIS_URL` 需 URL 编码（`#`→`%23` 等） |
| xtquant | 由券商提供，不在公开 PyPI 标准依赖中强制安装 |
