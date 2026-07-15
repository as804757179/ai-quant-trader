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
