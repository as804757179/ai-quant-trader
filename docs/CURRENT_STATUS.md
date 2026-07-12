# 当前实现状态（2026-07-10）

描述本仓库 **Desktop 副本**（`ai-quant-trader-pro-v1-GrokBuild`）的真实能力边界与推荐运行方式。

---

## 1. 推荐运行形态：宿主机混合模式

日常开发/演示优先使用 **PG/Redis 本机或 Docker 仅基础设施 + 应用进程在宿主机**：

| 组件 | 端口 | 启动方式（示意） |
|------|------|------------------|
| PostgreSQL / Timescale | 5432 | 本机服务或 `docker compose up -d postgres` |
| Redis | 6379 | 本机服务或 `docker compose up -d redis` |
| a-stock-data | 8080 | 宿主机 venv + uvicorn（见下） |
| Backend API | 8000 | 宿主机 venv + uvicorn，环境用 `.env.host` |
| Frontend | 3000 | `frontend` 下 `npm run dev` |
| Celery Worker | — | 可选；模拟 T+1 日终释放等依赖任务时建议启动 |

### 一键脚本

```powershell
# 仅 API + 行情（要求 5432/6379 已就绪）
.\scripts\start-host-api.ps1

# 或完整开发脚本（含 Docker 基础设施）
.\scripts\start-dev.ps1
```

宿主机环境文件：**`.env.host`**（`DATABASE_URL` / `REDIS_URL` / `A_STOCK_DATA_URL=http://127.0.0.1:8080` 等指向本机）。

手动启动示例见 [04_GETTING_STARTED.md](./04_GETTING_STARTED.md)。

---

## 2. 测试规模

| 套件 | 规模（约） |
|------|------------|
| backend pytest | 130+ |
| worker pytest | 21 |

---

## 3. 已实现（与桌面副本对齐）

| 领域 | 内容 |
|------|------|
| **股票池** | 全市场 A 股入库，active 约 **5500+**（新浪列表缓存 + `POST /stock/sync-universe` / `seed_stocks`） |
| **时区 / 语言** | 业务时区 `Asia/Shanghai`；前端 UI 简体中文 |
| **行情** | a-stock-data：腾讯完整盘口优先、通达信/东财/新浪降级；Backend 直连新浪 K 线兜底 |
| **缓存与性能** | L1 进程内 + Redis；行情 TTL 默认 **15s**；共享 httpx 连接池；批量 `/quotes`；持仓批量取价；K 线异步落库 |
| **K 线** | 多周期（1/5/15/30/60min、日/周/月）；库优先日线，分钟线偏远程；回填 API |
| **模拟交易** | 真实行情优先撮合；A 股规则：整手、涨跌停、T+1、佣金/印花税；`POST /trade/simulation/release-t1` 手动释放可卖 |
| **前端** | 统一 `PageShell` + 固定侧栏；股票分析同花顺风格盘口/五档/多周期 K 线；交易页账户/持仓/下单 |
| **AI / 选股 / 策略 / 回测** | API + 页面已接通（AI/选股深度依赖数据与 Key） |
| **三模式交易** | simulation / paper(Mock) / live(QMT 适配) |
| **风控** | 预检、熔断 DB、确认令牌、暴露 |
| **监控** | `/metrics`、Grafana 预置、钉钉级别/静默、告警中心 |

### 性能参考（本机热缓存，2026-07-10）

| 接口 | 热路径约值 |
|------|------------|
| `GET /stock/{code}/quote` | 1–30ms |
| `GET /stock/{code}/kline`（日线） | ~30ms |
| `GET /portfolio/positions` | ~25ms |
| `GET /stock/list` | ~25–30ms |
| 冷启动首次行情（外网） | ~200–400ms |

---

## 4. 未完全产品化 / 环境依赖

| 项 | 说明 |
|----|------|
| 真 QMT | 需 Windows + miniQMT + 券商 xtquant **实机验收** |
| Walk-Forward / AutoML UI | 规划中有，主产品未完整交付 |
| AI-Trader 子项目 | 独立实验，未接主前端 |
| quant_docs 全量能力 | 历史设计，不等于当前已交付 |
| 长驻进程 | 宿主机用 Job/后台启动时，关闭会话可能导致进程退出；需常驻请用独立终端或系统服务 |
| Celery | 可选；未启动时 T+1 自动释放等定时任务不跑，可用手动 release-t1 |

---

## 5. 数据库迁移

```powershell
cd backend
alembic upgrade head
```

| 版本 | 说明 |
|------|------|
| `001` | 初始 schema（含 orders `(mode, idempotency_key)`） |
| `002` | 幂等唯一键按 mode 隔离迁移 |
| `003` | 对齐缺失列 |
| `004` | 回测结果列扩展 |

---

## 6. 关键配置

| 变量 | 建议 | 说明 |
|------|------|------|
| `A_STOCK_DATA_URL` | `http://127.0.0.1:8080` | 宿主机模式 |
| `DATA_CACHE_TTL_QUOTE` | `15` | 行情缓存秒数 |
| `DATA_CACHE_TTL_KLINE` | `300` | 日 K 缓存秒数 |
| `TRADE_MODE` | `simulation` | 开发默认 |
| `SIM_ALLOW_OFF_HOURS` | `true` | 非交易时段仍可按最近行情模拟成交 |
| `SQL_ECHO` | `false` | 全市场写入时务必关闭 |

完整变量表见 [05_CONFIGURATION.md](./05_CONFIGURATION.md)。

---

## 7. 文档入口

| 文档 | 用途 |
|------|------|
| [README.md](../README.md) | 总览 + 完整手册源 |
| [docs/manual.html](./manual.html) | 带侧栏浏览器手册 |
| [04_GETTING_STARTED.md](./04_GETTING_STARTED.md) | 启动步骤 |
| [06_TROUBLESHOOTING.md](./06_TROUBLESHOOTING.md) | 排障 |
| [07_API_OVERVIEW.md](./07_API_OVERVIEW.md) | API 速查 |
| [PROGRESS.md](./PROGRESS.md) | 开发进度追踪 |
