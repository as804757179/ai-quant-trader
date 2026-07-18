# AI Quant Trader Pro

面向 A 股的量化研究与模拟交易系统。当前前端为量化运营台，默认使用 `SIMULATION`，自动执行、Live Trading、AI Order 与定时下单保持关闭。

## 本地运行

首次准备依赖：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

启动完整本地环境：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
```

停止项目：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop-local.ps1
```

环境诊断：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1
```

### 股票池刷新命令 Token

`A_STOCK_DATA_COMMAND_TOKEN` 用于 Worker/Backend 对 `a-stock-data` 内部股票池刷新命令的认证；它不是浏览器或交易凭据。使用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成随机值，并仅写入本机 `.env`：

```dotenv
A_STOCK_DATA_COMMAND_TOKEN=replace-with-secure-random-token
```

  Docker Compose 会将同一变量显式传入 `api`、`worker` 与 `a-stock-data`。生产环境缺失或使用占位值会启动失败；开发环境会给出提示且刷新命令拒绝执行。启动后可提交股票池同步 Job，并检查 Job 状态、`fundamental.stocks` 与 `a-stock-data` 缓存；日志只显示“已配置”，不会输出 Token。

  ### Worker 服务主体凭据

  `WORKER_API_CREDENTIAL` 用于 Worker 以 `service_worker` 服务主体身份访问 Backend API。调用时使用 `Authorization: Bearer <credential>`；Backend 仅保存凭据摘要并校验主体、角色、有效期和撤销状态。它与 `A_STOCK_DATA_COMMAND_TOKEN` 用途不同，必须使用独立随机值。

  在数据库迁移完成后，从 `backend` 目录执行 `python -m scripts.provision_api_principal --display-name local-worker --role service_worker --principal-type service`。命令仅显示一次原始凭据；将其写入本地 `.env` 与 `.env.host` 的 `WORKER_API_CREDENTIAL`，不要提交到 Git，也不要写入日志。Docker Compose 只将该变量注入 Worker，因为 API 通过数据库中的摘要校验而不需要持有原始凭据。

  启动检查会拒绝空值、占位值和弱凭据。验证时确认 Worker 已就绪，提交股票池同步 Job，并检查 Job 成功、`fundamental.stocks` 写入和 `a-stock-data` 刷新日志；不得在任何日志中打印原始凭据。

启动后默认地址：

- 前端：`http://localhost:3000`
- Backend API：`http://localhost:8000`
- Data Service：`http://localhost:8080`

## 核心目录

- `frontend/`：React + Vite 运营台。
- `backend/`：FastAPI、数据认证、回测、风控和交易边界。
- `worker/`：Celery Worker 与定时任务。
- `a-stock-data/`：行情数据服务。
- `docker/`：PostgreSQL、Redis 与基础设施配置。
- `scripts/`：启动、停止、诊断和环境维护脚本。
- `docs/adr/`：当前有效的长期架构决策。

## 产品与开发基线

最新产品和开发流程以 [A 股全市场持续监控与模拟交易设计](docs/superpowers/specs/2026-07-13-continuous-full-market-paper-trading-design.md) 为准。

历史数据必须通过 Data Certification 和用途级 Research Readiness；AI 不得直接或间接创建订单；所有订单必须经过 Execution Gate 与 Risk Engine。默认关闭状态是安全基线，不是对未来能力的永久禁令。
