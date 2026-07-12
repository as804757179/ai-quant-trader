# 配置说明

主配置文件：仓库根目录 **`.env`**（从 `.env.example` 复制）。  
**宿主机混合模式**另用 **`.env.host`**：`DATABASE_URL` / `REDIS_URL` / `A_STOCK_DATA_URL` 指向 `127.0.0.1`；`scripts/start-host-api.ps1` 会加载该文件。

后端通过 `pydantic-settings` 读取（见 `backend/app/core/config.py`）；也可由启动脚本注入环境变量覆盖。

---

## 1. 基础系统

| 变量 | 默认 | 说明 |
|------|------|------|
| `APP_ENV` | development | `production` 时更严格（如 Mock live 默认倾向关闭） |
| `SECRET_KEY` | 必填 | 应用密钥，生产用长随机串 |
| `API_KEY` | 空 | 非空则全局鉴权（健康检查/metrics 除外） |
| `LOG_LEVEL` | INFO | 日志级别 |
| `ALLOWED_ORIGINS` | localhost:3000 等 | CORS 列表（JSON 数组字符串） |

---

## 2. 数据库与 Redis

| 变量 | 说明 |
|------|------|
| `DB_*` | 主机/库名/用户/密码（compose 用） |
| `DATABASE_URL` | SQLAlchemy 异步 URL：`postgresql+asyncpg://...` |
| `REDIS_URL` | `redis://:password@host:6379/0` |
| `CELERY_BROKER_URL` | 默认同 Redis |
| `CELERY_RESULT_BACKEND` | 默认同 Redis |

**密码特殊字符**：必须 URL 编码后再拼进 URL。

| 字符 | 编码 |
|------|------|
| `#` | `%23` |
| `$` | `%24` |
| `@` | `%40` |
| `/` | `%2F` |

---

## 3. 交易与 QMT

| 变量 | 说明 |
|------|------|
| `TRADE_MODE` | `simulation` / `live`（系统级；下单还可指定 mode） |
| `ALLOW_MOCK_LIVE` | live 无 xtquant 时是否降级 Mock；**生产 false** |
| `MOCK_QMT_CASH` | Mock 初始资金 |
| `LIVE_CONFIRM_TOKEN` | live 下单二次确认 |
| `LIVE_MAX_ORDER_VALUE` | 单笔金额上限（元），0=不限制 |
| `AUTO_RECONCILE_ON_FILL` | 成交后自动对账 |
| `QMT_PATH` | miniQMT userdata 路径 |
| `QMT_ACCOUNT_ID` | 资金账号 |
| `QMT_ACCOUNT_TYPE` | 默认 STOCK |
| `QMT_SESSION_ID` | 会话号 |
| `QMT_FORCE_MOCK` | 强制使用 Mock 适配器 |

---

## 4. 回测与数据

| 变量 | 默认建议 | 说明 |
|------|----------|------|
| `A_STOCK_DATA_URL` | 宿主机 `http://127.0.0.1:8080`；compose 内 `http://a-stock-data:8080` | 行情微服务 |
| `BACKTEST_AUTO_BACKFILL` | true | 回测前自动补 K 线 |
| `BACKTEST_ALLOW_SYNTHETIC_KLINE` | true（开发） | 无数据时合成 K 线（演示用，不可作研究结论） |
| `DATA_CACHE_TTL_QUOTE` | **15** | 行情缓存秒数（Backend L1+Redis；过短会导致每次打外网） |
| `DATA_CACHE_TTL_KLINE` | 300 | 日 K 缓存秒数 |
| `DATA_CACHE_TTL_FUNDAMENTAL` | 3600 | 基本面类缓存 |
| `SQL_ECHO` | **false** | true 时打印全部 SQL；全市场 seed 时极慢，勿开 |
| `SIM_ALLOW_OFF_HOURS` | true | 模拟盘非交易时段是否按最近真实行情成交 |

### 缓存层次（2026-07 起）

| 层 | 位置 | 作用 |
|----|------|------|
| L1 | Backend 进程内存 | 热路径毫秒级命中 |
| L2 | Redis | 跨请求共享 |
| L0 | a-stock-data 进程内存 | 降低腾讯/新浪重复拉取 |
| 批量 | `GET /quotes?codes=` | 持仓等多票一次拉取 |

---

## 5. 风控默认阈值

| 变量 | 默认 | 含义 |
|------|------|------|
| `MAX_SINGLE_POSITION_RATIO` | 0.10 | 单票上限 |
| `WARN_SINGLE_POSITION_RATIO` | 0.08 | 单票预警 |
| `MAX_TOTAL_POSITION_RATIO` | 0.80 | 总仓上限 |
| `MAX_DAILY_LOSS_RATIO` | 0.03 | 日亏损 |
| `MAX_DRAWDOWN_RATIO` | 0.15 | 回撤 |
| `MAX_DAILY_ORDER_COUNT` | 20 | 日下单次数 |
| `MAX_SECTOR_CONCENTRATION_RATIO` | 0.40 | 行业集中度 |
| `MIN_DAILY_AMOUNT` | 5e7 | 最低日成交额 |

实际预检还会尝试读取 DB `risk.risk_rules` 覆盖。

---

## 6. AI 与 RAG

| 变量 | 说明 |
|------|------|
| `OPENAI_*` / `ANTHROPIC_*` / `DEEPSEEK_*` / `QWEN_*` | 各厂商 Key 与模型 |
| `SIGNAL_*` | 买卖阈值、有效期、最低置信度 |
| `CHROMA_PERSIST_DIR` | 向量库目录 |
| `CHROMA_COLLECTION_*` | collection 名 |

---

## 7. 钉钉通知

| 变量 | 说明 |
|------|------|
| `ENABLE_DINGTALK_NOTIFY` | 是否启用 |
| `DINGTALK_WEBHOOK` | 机器人地址 |
| `DINGTALK_ALERT_LEVELS` | 推送级别，逗号分隔，默认 `CRITICAL,ERROR` |
| `DINGTALK_COOLDOWN_SECONDS` | 同内容冷却，默认 300 |
| `DINGTALK_QUIET_HOURS` | 静默时段如 `23:00-08:00`（上海时区） |
| `DINGTALK_QUIET_BYPASS_LEVELS` | 静默仍推送的级别，默认 `CRITICAL` |

测试推送：

```http
POST /api/v1/risk/alerts/test-dingtalk?level=CRITICAL&message=test
```

---

## 8. 前端环境变量

| 变量 | 说明 |
|------|------|
| `VITE_API_KEY` | 对应后端 API_KEY |
| `VITE_LIVE_CONFIRM_TOKEN` | 实盘确认令牌（可选） |

---

## 9. Worker 相关

| 变量 | 说明 |
|------|------|
| `API_BASE_URL` | HTTP 调 backend 时的基址，如 `http://api:8000` |
| `WORKER_BACKEND_MODE` | `http` 或 `direct` |
| `PYTHONPATH` | 需包含 backend（镜像已设） |
| `SIGNAL_SCAN_*` | 扫描并发、股票数、锁 TTL 等 |

---

## 10. 生产最低安全配置示例

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
QMT_PATH=C:\...\userdata_mini
QMT_ACCOUNT_ID=你的账号
BACKTEST_ALLOW_SYNTHETIC_KLINE=false
```
