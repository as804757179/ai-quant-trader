# 03 — 开发路线图（5阶段 + 详细里程碑）

> 每个阶段结束必须通过验收标准才能进入下一阶段。真实资金系统不允许跳过阶段。

---

## Phase 1 — MVP 基础骨架（预计2周）

### 目标
Docker一键启动，数据接通，前端框架跑起来，模拟账户可以手动下单。

### 任务清单

```
基础设施
□ docker-compose.yml 完整配置（postgres+timescaledb/redis/api/worker/frontend/nginx）
□ .env.example 配置模板
□ Makefile 快捷命令（up/down/migrate/seed/test）
□ alembic 迁移脚本：所有Schema和表
□ Git submodule 接入 a-stock-data 和 AI-Trader

数据层
□ DataClient：封装 a-stock-data HTTP 调用（含超时/重试）
□ CacheManager：Redis读写（quote/kline/fundamental分层TTL）
□ 基础数据同步：股票列表导入（~5000只）
□ 手动触发K线同步脚本（回填近1年日线）

后端API（v1基础）
□ GET /api/v1/stock/list（含搜索/筛选）
□ GET /api/v1/stock/{code}/quote（实时价格）
□ GET /api/v1/stock/{code}/kline（日线K线）
□ GET /api/v1/stock/{code}/fund-flow
□ GET /api/v1/stock/{code}/news
□ GET /api/v1/portfolio/summary（账户概览）
□ GET /api/v1/portfolio/positions（持仓）
□ POST /api/v1/trade/order（手动下单）
□ GET /api/v1/health

风控（基础版）
□ PreTradeRiskChecker：单票仓位/总仓位/ST/流动性检查
□ FuseManager：熔断状态写入Redis

交易
□ SimulationTrader：完整撮合逻辑（含T+1/涨跌停/手续费）
□ OrderManager：幂等键+熔断检查+风控检查
□ 模拟账户初始化（100万）

前端框架
□ ProLayout骨架：8个页面路由占位
□ Dashboard：资产概览卡片（静态数据联通API）
□ 股票搜索 + 基础K线图（lightweight-charts）
□ 手动下单面板（买/卖表单 + 风控拦截提示）
□ 持仓列表（实时盈亏）
```

### Phase 1 验收标准
```
✅ docker compose up -d 一键启动无报错
✅ 能搜索股票并显示K线图
✅ 能手动下单（模拟盘），持仓实时更新
✅ 风控拦截能正确工作（尝试买ST股被拒）
✅ 数据库有完整数据（股票列表+近1年日线）
```

---

## Phase 2 — AI核心（预计2周）

### 目标
4个Agent能正常工作，信号能生成并存库，AI分析页面可用。

### 任务清单

```
AI Layer
□ BaseAgent 抽象类（超时/降级/日志统一）
□ TrendAgent（GPT-4o）：完整Prompt + JSON输出解析
□ FundamentalAgent（Claude）：含RAG检索
□ SentimentAgent（Qwen）：新闻/资金流/龙虎榜
□ ShortTermAgent（DeepSeek）：短线形态
□ RiskAgent（内部规则，不调用LLM）
□ AgentOrchestrator：asyncio并发调度（超时30s）
□ SignalAggregator：加权聚合（5维度权重）
□ 信号存库（ai.signals + ai.agent_logs）

RAG系统
□ ChromaDB 初始化（3个collection）
□ DocumentProcessor：公告/研报/新闻分块
□ RAGEngine：检索接口（retrieve_research/announcements/news）
□ 定时向量化任务（index_new_announcements）

MCP
□ MCPClient：4个工具（实时行情/行业/宏观/日历）
□ 集成到 FundamentalAgent

后端API
□ POST /api/v1/ai/{code}/analyze
□ GET  /api/v1/ai/{code}/latest-signal
□ GET  /api/v1/ai/signals（信号列表）
□ GET  /api/v1/ai/{code}/signal-history

前端
□ AI决策页：股票搜索 + 触发分析
□ AnalysisProgress：4步骤进度动画
□ AgentDiscussion：5个Agent卡片展示
□ SignalSummary：最终信号（BUY/SELL/HOLD + 置信度进度条）
□ Dashboard：信号列表实时展示
```

### Phase 2 验收标准
```
✅ 对任意股票触发AI分析，15-30秒内返回结果
✅ 4个Agent均能正常返回（即使某个超时能降级）
✅ 信号正确存入数据库（含agent_logs）
✅ AI分析页面完整展示各Agent结果
✅ RAG能检索到相关研报/公告内容
```

---

## Phase 3 — 自动化与实时推送（预计2周）

### 目标
系统能自动运行：定时同步数据、自动扫描信号、WebSocket实时推送、选股模块可用。

### 任务清单

```
Celery调度
□ celery_app.py：完整队列配置（high/normal/low）
□ tasks/market.py：
  - sync_realtime_quotes（每3秒）
  - sync_fund_flow（每60秒）
  - update_available_quantity（开盘前T+1）
  - archive_daily_data（收盘后）
  - sync_live_positions_from_broker（收盘后）
□ tasks/ai.py：
  - run_signal_scan（每分钟）
  - run_ai_analysis（单股异步任务）
□ tasks/maintenance.py：
  - weekly_full_data_sync（周日）
  - index_new_announcements（每小时）
  - take_eod_snapshot（收盘后）
□ Celery Beat：beat_schedule 完整配置
□ Flower 任务监控（:5555端口）

WebSocket
□ WebSocketManager（Redis Pub/Sub订阅者模式）
□ 行情推送（ws/quotes/{code}）
□ 信号推送（ws/signals）
□ 持仓推送（ws/portfolio）
□ 告警推送（ws/alerts）
□ 前端WSClient（断线重连，心跳ping/pong）
□ useQuote/useSignals/useRiskStatus Hook

实时风控监控
□ RealTimeRiskMonitor（每30秒检查）
□ 熔断自动触发（日亏损/回撤）
□ 熔断通知推送（WebSocket + 钉钉可选）
□ FuseAlert 前端组件

选股系统
□ ScreenerEngine：条件过滤引擎
□ FactorLibrary：6个核心因子
□ 预设选股条件（3套：AI动量/低估回弹/行业龙头）
□ AI智能选股（主题词输入）
□ 选股结果缓存（Redis，1小时TTL）
□ 前端选股页面

前端完善
□ 实时行情更新（K线图实时刷新）
□ 信号实时气泡通知（右上角）
□ 持仓浮盈浮亏实时更新
□ 风控状态栏（顶部常驻）
□ FuseAlert 横幅（熔断时醒目显示）
```

### Phase 3 验收标准
```
✅ 交易时段行情每3秒自动更新
✅ AI信号每分钟自动扫描，有新信号立即推送前端
✅ 手动下单后持仓立即更新（WebSocket推送）
✅ 模拟亏损3%，熔断自动触发，前端显示告警
✅ 选股模块能返回结果（预设条件 + AI选股）
✅ Celery任务全部正常运行（Flower监控可见）
```

**V1范围严格控制（Phase 3-4）**：
- 必须实现：新增56_INVESTMENT_DECISION_PIPELINE.md（全系统主线）、57_TRADE_AND_POSITION_LIFECYCLE.md（状态机）、58_PERFORMANCE_EVALUATION_AND_SYSTEM_GOAL.md（System KPI北极星）、52_PORTFOLIO_ENGINE.md扩展（Capital Allocation + Rebalancing）、Trading Calendar Engine、Market State完整映射。
- **V1: Interface Only + 保留完整架构/DB/API/扩展点**（不删除）：MCPClient、AutoMLOptimizer、Confidence Engine高级部分、RAG高级能力（18_19、28_29）。
- **严禁在V1实现**：完整AutoML执行、MCP完整工具链执行、Knowledge Graph、Strategy Marketplace、Plugin Marketplace、论文自动研究、自动生成策略。
- Phase 3必须上线：56 Pipeline主线 + Trading Calendar + Capital Allocation + 51 Market State映射。
- Phase 4必须完成：57 Position Lifecycle + 58 System KPI Dashboard + 52 Rebalancing全流程 + 55 Failure反哺闭环。

---

## Phase 4 — 回测系统完善（预计2周）

### 目标
完整回测引擎上线，Walk-Forward验证可用，AutoML参数优化可用，回测结果可视化。

### 任务清单

```
回测引擎
□ BacktestEngine：完整撮合逻辑
  - T+1持仓限制
  - 涨跌停无法成交处理
  - 手续费/印花税/滑点
  - 停牌处理（跳过）
□ LookaheadChecker：
  - 静态代码分析（AST）
  - 数据时间线检查
  - financial_data publish_date 检查
  - 回测前自动运行，ERROR阻断
□ MetricsCalculator：15个绩效指标
  - 含t统计量/p值（统计显著性）
□ OverfittingDetector：IS vs OOS对比分析

Walk-Forward
□ WalkForwardConfig：窗口生成（滚动/锚定）
□ WalkForwardRunner：多窗口验证执行
□ 参数稳定性检测
□ 综合评判（是否通过验证）

AutoML
□ AutoMLOptimizer（Optuna TPE贝叶斯优化）
□ 复合目标函数（夏普70% + 卡玛30%）
□ 硬约束（交易次数<10 / 最大回撤>25% → 淘汰）
□ 支持MA/MACD/RSI/布林带参数空间

策略工厂
□ StrategyFactory（注册/创建/热加载）
□ MACrossoverStrategy
□ MACDStrategy（含顶底背离）
□ RSIStrategy
□ BollingerBandsStrategy
□ AIDrivenStrategy（异步）
□ HybridStrategy（技术+AI双确认）

后端API
□ POST /api/v1/backtest/run（异步任务）
□ GET  /api/v1/backtest/{id}/status（进度0-100）
□ GET  /api/v1/backtest/{id}/result（完整结果）
□ POST /api/v1/backtest/walk-forward
□ GET  /api/v1/strategy/list
□ POST /api/v1/strategy/create
□ PUT  /api/v1/strategy/{id}

前端
□ 回测参数配置面板
  - 时间范围 / 初始资金 / 股票池
  - Walk-Forward开关
  - 策略类型选择 + 参数配置
□ 实时进度条（轮询 + WebSocket）
□ 结果展示：
  - 关键指标卡片（16个指标）
  - 收益曲线（对比基准）
  - 回撤曲线
  - 月度收益热力图
  - 交易记录明细表
  - 过拟合检测结果
  - Walk-Forward窗口表现对比
□ 策略管理页（CRUD + 启停 + 一键回测）
```

### Phase 4 验收标准
```
✅ 对任意策略运行回测，5分钟内出结果
✅ LookaheadChecker 能检测出测试用例中的未来函数
✅ Walk-Forward验证产出IS/OOS对比报告
✅ AutoML 100次trial完成，输出最优参数
✅ 回测结果页面完整展示所有指标和图表
✅ 策略管理CRUD全部正常工作
```

---

## Phase 5 — 实盘接入（预计4周，谨慎推进）

### 目标
QMT实盘接入，完整对账机制，监控告警，压力测试通过，正式投入使用。

### 前提条件（必须全部满足）
```
✅ Phase 1-4全部完成并稳定运行
✅ 纸盘（paper mode）运行满90天
✅ 纸盘年化收益率 > 基准（沪深300）5%以上
✅ 纸盘最大回撤 < 12%（低于实盘熔断线15%，留余量）
✅ Walk-Forward验证通过（OOS胜率 > 60%）
✅ 所有测试用例100%通过
✅ 风控规则经过2人以上审核
✅ 有完整的应急回退方案
```

### 任务清单

```
QMT接入
□ QMTTrader：完整实现（submit/cancel/status/positions/account）
□ QMT回调处理（成交回报自动更新订单状态）
□ 连接监控（断线自动重连 + 告警）
□ 开盘/收盘自动sync_positions

实盘风控加固
□ 实盘专用风控规则（单票上限降至8%，总仓位降至70%）
□ 实盘下单必须二次确认（人工或API双重认证）
□ 实盘订单变更审计日志（全量记录）
□ 每日收盘后自动对账

对账系统
□ ReconciliationService：持仓/资金对账
□ 对账差异告警（微信/钉钉）
□ 自动修复（以券商数据为准）
□ 每日对账报告生成

监控完善
□ Prometheus 完整指标（含实盘特有指标）
□ Grafana 实盘Dashboard（持仓/收益/风控/AI费用）
□ 告警规则（回撤>10% / AI超时频率>20% / 对账异常）
□ 每日运营报告（邮件/钉钉）

压力测试
□ 模拟高频行情推送（1000 tick/s）
□ 并发AI分析（50个股票同时）
□ 连续24小时稳定性测试
□ 熔断恢复全流程测试
□ 断网/断电恢复测试

文档
□ 实盘操作手册（每日开盘/收盘流程）
□ 应急处置手册（QMT断线/熔断/数据异常）
□ 资金安全声明（风险告知）
```

### Phase 5 验收标准
```
✅ QMT下单后券商账户实际成交（小额测试：100股）
✅ 持仓对账零误差（连续5个交易日）
✅ 熔断触发后所有订单自动取消
✅ 压力测试24小时无崩溃
✅ 断线重连后数据一致性验证通过
✅ 2名负责人签字确认实盘开启
```

---

## 里程碑时间表

```
周次  │ 阶段    │ 里程碑
──────┼─────────┼──────────────────────────────────────
W1-2  │ Phase 1 │ MVP：Docker启动 + 手动模拟下单
W3-4  │ Phase 2 │ AI：4个Agent正常工作 + 信号生成
W5-6  │ Phase 3 │ 自动化：定时任务 + WebSocket实时推送
W7-8  │ Phase 4 │ 回测：Walk-Forward + 策略管理
W9-12 │ Phase 5 │ 纸盘验证（至少3个月，并行开发实盘接口）
W12+  │ 实盘    │ QMT接入 + 正式运行
```

---

## Codex 开发优先级

```
Priority 1（必须最先完成）：
  - 数据库Schema全部DDL
  - docker-compose.yml
  - 环境变量配置
  - alembic 迁移

Priority 2（核心业务）：
  - PreTradeRiskChecker（风控是基础）
  - SimulationTrader（撮合引擎）
  - OrderManager（订单管理）

Priority 3（AI功能）：
  - BaseAgent + 4个Agent
  - AgentOrchestrator
  - SignalAggregator

Priority 4（自动化）：
  - Celery任务
  - WebSocket推送
  - 实时风控监控

Priority 5（回测）：
  - BacktestEngine + LookaheadChecker
  - Walk-Forward + AutoML

Priority 6（前端）：
  - 与后端并行开发
  - 优先做Dashboard和交易页面
```
