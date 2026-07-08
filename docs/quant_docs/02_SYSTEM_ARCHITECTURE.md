# 02 — 企业级系统架构

---

## 1. C4 架构模型

### Level 1: 系统上下文图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        外部系统边界                                   │
│                                                                       │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐       │
│  │  OpenAI  │    │Anthropic │    │DeepSeek  │    │  阿里云  │       │
│  │  GPT-4o  │    │ Claude   │    │   API    │    │  Qwen    │       │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘       │
│       │               │               │               │               │
└───────┼───────────────┼───────────────┼───────────────┼───────────── ┘
        │               │               │               │
        └───────────────┴───────────────┴───────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  AI Quant Trader Pro  │
                    │  （本系统）            │
                    └───────────┬───────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
┌───────▼──────┐      ┌─────────▼──────┐      ┌────────▼───────┐
│ a-stock-data │      │   QMT券商接口  │      │   交易员/用户  │
│  A股数据源   │      │   （实盘）      │      │   Web Browser  │
└──────────────┘      └────────────────┘      └────────────────┘
```

### Level 2: 容器架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         AI Quant Trader Pro                              │
│                                                                           │
│  ┌─────────────────┐          ┌──────────────────────────────────────┐   │
│  │   Nginx反向代理  │◄────────►│           React 前端                 │   │
│  │   :80           │          │  React18 + TypeScript + AntD Pro     │   │
│  └────────┬────────┘          │  ECharts + WebSocket Client          │   │
│           │                   └──────────────────────────────────────┘   │
│           │ /api/*                                                        │
│           ▼                                                               │
│  ┌─────────────────┐          ┌──────────────────────────────────────┐   │
│  │  FastAPI 后端   │◄────────►│         PostgreSQL + TimescaleDB     │   │
│  │  :8000          │          │  Schema: market/fundamental/         │   │
│  │  - REST API     │          │  ai/strategy/trade/risk/audit        │   │
│  │  - WebSocket    │          └──────────────────────────────────────┘   │
│  │  - 业务逻辑     │                                                      │
│  │  - AI编排       │          ┌──────────────────────────────────────┐   │
│  └────────┬────────┘◄────────►│              Redis 7                 │   │
│           │                   │  - 行情缓存（TTL 3s）                │   │
│           │                   │  - Celery Broker & Backend           │   │
│           │                   │  - WebSocket Pub/Sub                 │   │
│           │                   │  - 分布式锁（防重复下单）             │   │
│           │                   └──────────────────────────────────────┘   │
│           │                                                               │
│           ▼                   ┌──────────────────────────────────────┐   │
│  ┌─────────────────┐          │           Celery Worker              │   │
│  │  ChromaDB       │          │  - 行情同步任务                      │   │
│  │  向量数据库      │          │  - AI信号扫描任务                    │   │
│  │  - 研报向量      │          │  - 回测异步任务                      │   │
│  │  - 公告向量      │          │  - 数据维护任务                      │   │
│  │  - 新闻向量      │          └──────────────────────────────────────┘   │
│  └─────────────────┘                                                      │
│                               ┌──────────────────────────────────────┐   │
│                               │        Celery Beat（调度器）          │   │
│                               │  - 定时触发各类任务                   │   │
│                               └──────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Level 3: 后端组件图

```
FastAPI 后端内部组件

API层（路由）
├── /api/v1/stock/*        → StockRouter
├── /api/v1/ai/*           → AIRouter
├── /api/v1/screener/*     → ScreenerRouter
├── /api/v1/strategy/*     → StrategyRouter
├── /api/v1/backtest/*     → BacktestRouter
├── /api/v1/risk/*         → RiskRouter
├── /api/v1/trade/*        → TradeRouter
├── /api/v1/portfolio/*    → PortfolioRouter
└── /ws/*                  → WebSocketRouter

Service层（业务逻辑）
├── StockService           → 股票数据查询、缓存
├── AIService              → 触发AI分析、获取信号
├── ScreenerService        → 执行选股
├── StrategyService        → 策略CRUD、启停
├── BacktestService        → 启动回测任务、查询结果
├── RiskService            → 风控检查、规则管理
├── TradeService           → 下单、撤单、持仓查询
└── PortfolioService       → 资产汇总、收益计算

核心引擎层
├── DataLayer
│   ├── DataClient         → 封装 a-stock-data HTTP调用
│   ├── CacheManager       → Redis读写、TTL管理
│   └── DataSyncManager    → 定时同步调度
│
├── AILayer
│   ├── AgentOrchestrator  → 多Agent调度、并发控制
│   ├── TrendAgent         → GPT趋势分析
│   ├── FundamentalAgent   → Claude基本面
│   ├── SentimentAgent     → Qwen情绪
│   ├── ShortTermAgent     → DeepSeek短线
│   ├── RiskAgent          → 风控评估Agent
│   ├── PortfolioAgent     → 仓位建议Agent
│   ├── RAGEngine          → 向量检索增强
│   ├── MCPClient          → MCP工具调用
│   └── SignalAggregator   → 信号加权聚合
│
├── StrategyLayer
│   ├── StrategyFactory    → 策略注册、实例化
│   ├── FactorLibrary      → 因子计算库
│   ├── TechnicalEngine    → 技术指标引擎
│   └── ScreenerEngine     → 选股条件引擎
│
├── BacktestLayer
│   ├── BacktestEngine     → 回测撮合引擎
│   ├── LookaheadChecker   → 防未来函数检查器
│   ├── WalkForwardRunner  → WF验证执行器
│   ├── AutoMLOptimizer    → 参数自动优化
│   └── MetricsCalculator  → 绩效指标计算
│
├── RiskLayer
│   ├── RiskChecker        → 交易前检查（同步）
│   ├── RiskMonitor        → 实时监控（异步）
│   ├── FuseManager        → 熔断管理
│   └── VaRCalculator      → VaR计算
│
└── TradeLayer
    ├── OrderManager       → 订单生命周期管理
    ├── SimulationTrader   → 模拟盘执行
    ├── PaperTrader        → 纸盘执行
    └── QMTTrader          → 实盘执行
```

---

## 2. 服务依赖关系与启动顺序

```
启动顺序（docker-compose depends_on）：

1. postgres     （数据库，无依赖）
2. redis        （缓存，无依赖）
3. api          （依赖 postgres + redis）
4. worker       （依赖 redis + postgres）
5. scheduler    （依赖 redis）
6. frontend     （依赖 api）
7. nginx        （依赖 frontend + api）

健康检查：
- postgres: pg_isready
- redis: redis-cli ping
- api: GET /api/v1/health
- worker: celery inspect ping
```

---

## 3. 关键数据流

### 3.1 AI分析请求流

```
用户点击"分析"
     │
     ▼
POST /api/v1/ai/analyze/{code}
     │
     ▼
AIService.analyze(code)
     │
     ├─► DataClient.get_snapshot(code)     → Redis缓存 or a-stock-data
     ├─► DataClient.get_kline(code, '1d')  → TimescaleDB
     ├─► DataClient.get_fund_flow(code)    → Redis缓存
     ├─► DataClient.get_news(code)         → PostgreSQL
     └─► RAGEngine.retrieve(code)          → ChromaDB（研报/公告）
     │
     ▼
AgentOrchestrator.run_parallel([
    TrendAgent,          → OpenAI API
    FundamentalAgent,    → Anthropic API
    SentimentAgent,      → Qwen API
    ShortTermAgent,      → DeepSeek API
])   （并发执行，超时30s，单Agent失败不影响其他）
     │
     ▼
RiskAgent.evaluate(agent_results)    → 内部风控评估（不调用外部AI）
     │
     ▼
SignalAggregator.aggregate(all_results)
     │
     ▼
db.save(signal)
     │
     ├─► WebSocket推送: ws_manager.broadcast("signals", signal)
     └─► 返回API响应
```

### 3.2 自动交易流

```
Celery Beat触发 (每60秒)
     │
     ▼
tasks.run_signal_scan()
     │
     ▼
获取活跃策略列表 + 关注股票池
     │
     ▼
for each stock in universe:
     │
     ├─► AIService.analyze(stock)    → 生成信号
     │
     ▼
signal = SignalAggregator.aggregate()
     │
if signal.action != 'HOLD' and signal.confidence > threshold:
     │
     ▼
RiskChecker.check_before_trade(order)   ← 硬约束检查
     │
if PASS:
     │
     ▼
TradeService.submit_order(order)
     │
     ├─► mode == 'simulation': SimulationTrader.execute()
     ├─► mode == 'paper':      PaperTrader.execute()
     └─► mode == 'live':       QMTTrader.execute()
     │
     ▼
OrderManager.update_status()
     │
     ▼
PortfolioService.update_positions()    ← 事务：订单+持仓+账户余额
     │
     ▼
WebSocket推送 → 前端实时更新
```

### 3.3 实时行情推送流

```
Celery Worker (每3秒)
     │
     ▼
tasks.sync_realtime_quotes()
     │
     ▼
DataClient.get_quotes(active_stocks)   → a-stock-data
     │
     ▼
CacheManager.set_quotes(quotes, ttl=5) → Redis
     │
     ▼
redis.publish("channel:quotes", quotes_json)
     │
     ▼
FastAPI WebSocket订阅者
     │
     ▼
ws_manager.broadcast_to_subscribers(quotes)
     │
     ▼
前端 WebSocket 接收 → 更新行情显示
```

---

## 4. 关键非功能性设计

### 4.1 高可用保障

```python
# 每个外部AI调用都有超时和降级
async def call_agent_with_fallback(agent, inputs, timeout=30):
    try:
        result = await asyncio.wait_for(
            agent.analyze(inputs),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        logger.warning(f"{agent.name} timeout after {timeout}s, using degraded result")
        return agent.get_degraded_result(inputs)  # 降级：返回中性结果
    except Exception as e:
        logger.error(f"{agent.name} error: {e}")
        return agent.get_degraded_result(inputs)
```

### 4.2 幂等性保证

```python
# 所有下单操作使用幂等键
def create_order(signal_id: str, stock_code: str, side: str, quantity: int):
    idempotency_key = f"{signal_id}:{stock_code}:{side}:{quantity}"

    # 检查是否已存在相同幂等键的订单
    existing = db.query(Order).filter_by(idempotency_key=idempotency_key).first()
    if existing:
        logger.warning(f"Duplicate order attempt, returning existing: {existing.id}")
        return existing

    # 使用数据库唯一约束兜底
    try:
        order = Order(idempotency_key=idempotency_key, ...)
        db.add(order)
        db.commit()
        return order
    except IntegrityError:
        db.rollback()
        return db.query(Order).filter_by(idempotency_key=idempotency_key).first()
```

### 4.3 事务一致性

```python
# 订单执行：持仓+账户余额必须在同一事务
def execute_order_transaction(order: Order, fill_price: float):
    with db.begin():  # 事务开始
        try:
            # 1. 更新订单状态
            order.status = 'FILLED'
            order.avg_fill_price = fill_price
            order.filled_at = datetime.utcnow()

            # 2. 更新持仓
            position = get_or_create_position(order.stock_code, order.mode)
            if order.side == 'BUY':
                update_position_buy(position, order.quantity, fill_price)
            else:
                update_position_sell(position, order.quantity, fill_price)

            # 3. 更新账户余额
            account = get_account(order.mode)
            amount = fill_price * order.quantity
            if order.side == 'BUY':
                account.cash -= amount + calculate_commission(amount)
            else:
                account.cash += amount - calculate_commission(amount) - calculate_stamp_tax(amount)

            # 4. 记录审计日志
            audit_log.record_order_execution(order, fill_price)

            db.commit()  # 全部成功才提交
        except Exception as e:
            db.rollback()  # 任何失败全部回滚
            raise OrderExecutionError(f"Transaction failed: {e}")
```

### 4.4 熔断器模式（Circuit Breaker）

```python
# 外部API调用的熔断器
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
async def call_openai(prompt: str) -> str:
    """
    失败5次后熔断，60秒后尝试恢复
    熔断期间直接抛出异常，不等待超时
    """
    response = await openai_client.chat.completions.create(...)
    return response.choices[0].message.content
```

---

## 5. 环境配置完整版

```yaml
# docker-compose.yml（生产版）
version: "3.9"

x-common-env: &common-env
  env_file: .env
  restart: unless-stopped
  logging:
    driver: "json-file"
    options:
      max-size: "100m"
      max-file: "5"

services:
  postgres:
    image: timescale/timescaledb:latest-pg15
    <<: *common-env
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./docker/postgres/postgresql.conf:/etc/postgresql/postgresql.conf
      - ./docker/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "127.0.0.1:5432:5432"   # 只绑定本地，不对外暴露
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    <<: *common-env
    command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 2gb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    ports:
      - "127.0.0.1:6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s

  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    <<: *common-env
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./vector_db:/app/vector_db    # ChromaDB持久化
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  worker:
    build:
      context: ./worker
      dockerfile: Dockerfile
    <<: *common-env
    command: celery -A celery_app worker -Q high,normal,low --concurrency=4 --loglevel=info
    depends_on:
      - redis
      - postgres
    deploy:
      resources:
        limits:
          memory: 2G

  scheduler:
    build:
      context: ./worker
      dockerfile: Dockerfile
    <<: *common-env
    command: celery -A celery_app beat --loglevel=info --scheduler redbeat.RedBeatScheduler
    depends_on:
      - redis

  flower:
    image: mher/flower:2.0
    <<: *common-env
    command: celery flower --broker=${REDIS_URL} --port=5555
    ports:
      - "127.0.0.1:5555:5555"   # Celery任务监控

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./docker/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "127.0.0.1:9090:9090"

  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
    volumes:
      - grafana_data:/var/lib/grafana
      - ./docker/grafana/dashboards:/etc/grafana/provisioning/dashboards
    ports:
      - "127.0.0.1:3001:3000"

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "127.0.0.1:3000:3000"
    depends_on:
      - api

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./docker/nginx/ssl:/etc/nginx/ssl
    depends_on:
      - api
      - frontend

volumes:
  postgres_data:
  redis_data:
  prometheus_data:
  grafana_data:
```

---

## 6. 完整 .env 配置

```env
# ==============================================
# AI Quant Trader Pro — 环境变量配置
# 复制此文件为 .env 并填写实际值
# 警告：.env 文件绝对不能提交到Git！
# ==============================================

# ── 数据库 ──
DB_HOST=postgres
DB_PORT=5432
DB_NAME=quant_trader
DB_USER=quant_admin
DB_PASSWORD=YOUR_STRONG_PASSWORD_HERE
DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}

# ── Redis ──
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=YOUR_REDIS_PASSWORD
REDIS_URL=redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/0
CELERY_BROKER_URL=${REDIS_URL}
CELERY_RESULT_BACKEND=${REDIS_URL}

# ── AI 模型 API Keys ──
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4o
OPENAI_TIMEOUT=30

ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_TIMEOUT=30

DEEPSEEK_API_KEY=xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT=20

QWEN_API_KEY=xxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/api/v1
QWEN_MODEL=qwen-turbo
QWEN_TIMEOUT=20

# ── 系统配置 ──
APP_ENV=production          # development / production
SECRET_KEY=YOUR_SECRET_KEY_MIN_32_CHARS
LOG_LEVEL=INFO
ALLOWED_HOSTS=localhost,127.0.0.1

# ── 数据同步 ──
DATA_SYNC_INTERVAL_REALTIME=3       # 实时行情同步间隔（秒）
DATA_SYNC_INTERVAL_FUNDFLOW=60      # 资金流向同步间隔（秒）
DATA_CACHE_TTL_QUOTE=5              # 行情缓存TTL（秒）
DATA_CACHE_TTL_KLINE=300            # K线缓存TTL（秒）
DATA_CACHE_TTL_FUNDAMENTAL=3600     # 基本面数据缓存（秒）

# ── 交易配置 ──
TRADE_MODE=simulation               # simulation / paper / live
# 警告：修改为live之前必须完成所有验证步骤

# ── 风控参数（硬编码到DB，此处为默认值） ──
MAX_SINGLE_POSITION_RATIO=0.10
MAX_TOTAL_POSITION_RATIO=0.80
MAX_DAILY_LOSS_RATIO=0.03
MAX_DRAWDOWN_RATIO=0.15
MAX_DAILY_ORDER_COUNT=20

# ── AI信号阈值 ──
SIGNAL_MIN_CONFIDENCE=0.65          # 低于此置信度不产生信号
SIGNAL_BUY_THRESHOLD=0.70           # BUY信号置信度阈值
SIGNAL_SELL_THRESHOLD=0.30          # SELL信号置信度阈值
SIGNAL_VALIDITY_HOURS=24            # 信号有效期（小时）

# ── ChromaDB ──
CHROMA_PERSIST_DIR=/app/vector_db
CHROMA_COLLECTION_REPORTS=research_reports
CHROMA_COLLECTION_ANNOUNCEMENTS=announcements
CHROMA_COLLECTION_NEWS=news

# ── 监控 ──
GRAFANA_PASSWORD=YOUR_GRAFANA_PASSWORD
PROMETHEUS_RETENTION=30d

# ── 通知（可选）──
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
ENABLE_DINGTALK_NOTIFY=false
```

---

## 4. Investment Decision Pipeline（全系统主线）—— V1核心

**这是整个系统的灵魂。所有模块必须挂接到此Pipeline。任何孤立模块必须消除。**

```
[数据层] 市场数据 (DataService + Trading Calendar Engine)
    ↓
[数据质量] Data Quality Center (54) → Health Score < 阈值 → BLOCK交易
    ↓
[市场状态] Market State Engine (51) → regime + 策略映射表 → 决定允许的策略子集
    ↓
[特征工程] Feature Engine + FactorLibrary
    ↓
[股票排序] Stock Ranking (多因子 + ScreenerEngine)
    ↓
[AI分析] AI Analysis (15_16 AgentOrchestrator)
         ├─ 优先读取 Failure Library (55) 历史教训
         ├─ TrendAgent (中短周期趋势, daily/weekly输入)
         ├─ ShortTermAgent (超短周期机会, 5min/15min + 盘口输入)
         ├─ FundamentalAgent + RAG
         ├─ SentimentAgent + MCP (Interface Only in V1)
         └─ RiskAgent (内部规则)
    ↓
[信号聚合] SignalAggregator + Confidence Engine (V1: Interface + 计算逻辑; V2: 高级ML)
    ↓
[风险检查] Risk Check (31_34 PreTradeRiskChecker + 新增组合风险)
         ├─ 单票/总仓位/行业暴露/相关性/Beta
         └─ Capital Allocation (新增) → Position Sizing / Risk Budget / ATR Sizing
    ↓
[组合管理] Portfolio Engine (新增 Rebalancing + Capital Allocation)
         ├─ Portfolio Score
         ├─ Holding Ranking
         ├─ Target Weight vs Current
         └─ Rebalance Plan → Transaction Plan
    ↓
[交易决策] Trade Decision (最终信号 + Decision Trace 解释)
    ↓
[执行] Execution (35_38 OrderManager + SimulationTrader/QMTTrader)
    ↓
[持仓生命周期] Position Lifecycle (新增状态机: OPEN→ACTIVE→PROTECTED→PARTIAL_EXIT→CLOSED→ARCHIVED)
         ├─ 动态止盈/止损/Trailing Stop/Break Even
         └─ Forced/Emergency/Strategy Deprecated Exit
    ↓
[每日复盘] Daily Review + FailureDetector (55) → 记录详细失败案例 (股票+策略+市场状态+AI Prompt+新闻+资金流+行业+原因+修复建议)
    ↓
[绩效评估] Performance Evaluation (新增 System KPI 北极星)
         ├─ Annual Return / Benchmark Excess / Sharpe / Sortino / Calmar
         ├─ Profit Factor / Max Drawdown / Win Rate / Payoff Ratio
         ├─ Turnover / Avg Holding Days / Transaction Cost Ratio / Information Ratio
         └─ 所有优化 (AI/策略/参数) 必须服务于提升这些指标
    ↓
[学习闭环] Knowledge Base 更新 (55) + Strategy Optimization (基于绩效)
         └─ 失败案例优先反哺 AI Prompt (下一轮分析必须读取)
    ↓
返回 Pipeline 起点 (持续循环)
```

**每个模块 Integration 要求**（已在各文档末尾添加）：
- 明确属于Pipeline哪一步
- 输入/输出
- 下游模块
- 如何服务盈利/风控/学习

**V1范围**：完整Pipeline流程 + 状态机 + 核心计算。高级ML部分 (Confidence Engine高级、AutoML完整、MCP完整实现) 标记为 V1: Interface Only + DB/API/扩展点保留，V2实现。

---

## 5. 新增核心引擎（V1必须实现，服务Pipeline）

### 5.1 Trading Calendar Engine（交易日历引擎）

**职责**：统一A股交易日历，避免非交易日执行策略/回测/交易。

**功能**：
- 交易日/节假日/停牌/ST/退市整理/集合竞价/午间休市/涨跌停/T+1限制
- 提供 is_trading_day(date), next_trading_day(), adjust_for_t1() 等接口
- 所有 BacktestEngine, SimulationTrader, QMTTrader, Celery任务 必须依赖此Engine

**Integration with Pipeline**：
- 属于第一步 "市场数据"
- 输入：日期/股票代码
- 输出：是否交易日 + 调整后日期
- 下游：DataService, Backtest, Trade Execution
- 盈利影响：防止无效交易/回测偏差，提升稳定性

**V1实现**：完整日历数据 + 接口 (从交易所日历 + 自定义规则DB表)

### 5.2 Portfolio Rebalancing Engine（组合再平衡引擎）

**职责**：每天自动计算持仓调整计划，避免持仓混乱。

**核心输出**：
- Portfolio Score (健康度)
- Holding Ranking (按Score排序)
- Target Weight (基于Capital Allocation + Market State)
- Weight Difference
- Rebalance Plan (加/减/卖/替换列表)
- Transaction Plan (风控过滤后的可执行订单)

**Integration with Pipeline**：
- 属于 "组合管理" 步骤
- 输入：当前持仓 + Market State + Performance Evaluation
- 输出：Rebalance Plan
- 下游：Risk Check → Execution
- 盈利影响：动态优化仓位，降低集中风险，提升风险调整收益 (Sharpe/Calmar)

### 5.3 Capital Allocation Engine（资金分配引擎）

**职责**：AI不仅决定买什么，还决定买多少 (Position Sizing)。

**核心组件**：
- Position Sizing (ATR Sizing / Volatility Targeting)
- Risk Budget ( per trade / daily / portfolio)
- Kelly Fraction (可选，保守版)
- Maximum Position / Maximum Daily Exposure
- Cash Reserve (动态，依赖Market State)

**Integration with Pipeline**：
- 属于 "风险检查" + "组合管理"
- 输入：信号 + 账户资产 + 波动率 + Market State
- 输出：建议仓位大小 + 风险预算分配
- 下游：PreTradeRiskChecker + Rebalancing
- 盈利影响：优化资金使用效率，提升Profit Factor，控制Max Drawdown

**注意**：与31_34硬约束协同，Allocation建议值不能突破硬阈值。

---

## 6. V1/V2 标注规范（贯穿全文）

对于 MCP / AutoML / Confidence Engine / 高级RAG 等：
```text
V1: Interface Only + 完整架构/DB/API/扩展点保留
V2: Full Implementation (Phase 5+)
```
原因：保证长期扩展性，同时V1聚焦可落地盈利闭环。
