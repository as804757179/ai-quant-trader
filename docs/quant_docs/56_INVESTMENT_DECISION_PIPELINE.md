# 56 — Investment Decision Pipeline（投资决策流水线） V1核心主线

> **这是整个系统的灵魂。所有模块必须挂接到此Pipeline。任何孤立模块必须消除。**

## 1. 完整端到端流程图

```
[数据层] 市场数据 (DataService)
    ↓
[交易日历] Trading Calendar Engine (新增56集成)
    ↓
[数据质量] Data Quality Center (54) → Health Score < 阈值 → BLOCK所有交易
    ↓
[市场状态] Market State Engine (51) → 输出 regime + 策略启用映射表
    ↓
[特征与排序] Feature Engine + FactorLibrary + Stock Ranking
    ↓
[AI多Agent分析] AI Analysis (15_16 AgentOrchestrator) — **强制前置步骤**
         ├─ **必须先检索 Failure Library (55)**：同股票 + 同Market State + 同行业轮动历史失败案例
         │   示例：中际旭创 当前行业轮动 + 高波动 → 先查“过去3次类似状态下买入的失败原因 + 后续新闻 + Prompt”
         ├─ 只有检索后才允许TrendAgent / ShortTermAgent / FundamentalAgent 执行
         ├─ TrendAgent (中短期: 日/周线 + MA/MACD/RSI排列)
         ├─ ShortTermAgent (超短线: 5min/15min + 盘口不平衡 + momentum burst)
         ├─ FundamentalAgent + RAG (研报/公告)
         ├─ SentimentAgent + MCP (V1: Interface Only)
         ├─ RiskAgent (内部规则)
         └─ PortfolioAgent (仓位初步建议)
    ↓
[信号聚合与可信度] SignalAggregator + Confidence Engine (V1: Interface + 6维度计算; V2: 高级ML)
    ↓
[风险与资金分配] Risk Check (31_34) + Capital Allocation Engine (新增52扩展)
         ├─ 硬约束检查 (单票/总仓位/行业暴露/相关性/Beta/流动性)
         └─ Position Sizing (ATR/波动率目标 + Risk Budget + 保守Kelly)
    ↓
[组合再平衡] Portfolio Rebalancing Engine (新增52扩展)
         ├─ Portfolio Score (健康度)
         ├─ Holding Ranking
         ├─ Target Weight (基于Market State + Capital Allocation)
         ├─ Weight Difference
         └─ Rebalance Plan → Transaction Plan (风控过滤后)
    ↓
[最终交易决策] Trade Decision
         ├─ 最终BUY/SELL/HOLD + 置信度
         └─ Decision Trace (Explainable AI: 资金流+新闻+行业+技术+风险+AI各因素贡献度)
    ↓
[执行层] Execution (35_38 OrderManager + SimulationTrader / QMTTrader)
    ↓
[持仓生命周期] Position Lifecycle (新增57)
         OPEN → ACTIVE → PROTECTED (Break Even + Trailing Stop)
         → PARTIAL_EXIT → CLOSED → ARCHIVED
         支持: 动态止盈/止损 / Trailing Stop / Break Even / Forced Exit / Emergency Exit / Strategy Deprecated Exit
    ↓
[每日复盘与失败检测] Daily Review + FailureDetector (55)
         ├─ 记录详细失败案例 (股票+策略+market_state+完整AI Prompt+post_signal_news+资金流+行业+最终原因+修复建议+Lesson Learned)
         └─ 失败案例优先反哺下一轮AI分析
    ↓
[绩效评估北极星] Performance Evaluation (新增58)
         ├─ System KPI: Annual Return / Benchmark Excess Return
         ├─ Sharpe / Sortino / Calmar / Profit Factor / Max Drawdown
         ├─ Win Rate / Payoff Ratio / Turnover / Avg Holding Days
         ├─ Transaction Cost Ratio / Information Ratio
         └─ 所有优化 (AI Prompt / 策略参数 / Rebalance规则 / Capital Allocation) 必须服务于提升这些指标
    ↓
[学习闭环] Knowledge Base 更新 (55) + Strategy Optimization
         └─ Lesson Learned 人工确认后反哺对应Agent Prompt
    ↓
返回 Pipeline 起点（持续循环，每日/每分钟触发）
```

## 2. 每一步详细说明（输入 / 输出 / 责任模块 / AI调用 / Integration）

### 2.1 数据层 + Trading Calendar
**输入**：原始行情/基本面/另类数据  
**输出**：清洗后数据 + 是否交易日标记  
**责任模块**：DataService + Trading Calendar Engine  
**AI调用**：无  
**Integration**：Pipeline第一步。所有下游（Backtest/Trade/AI）必须通过Trading Calendar过滤非交易日。

### 2.2 数据质量
**输入**：清洗后数据  
**输出**：Health Score + blocking决策  
**责任模块**：Data Quality Center (54)  
**Integration**：低于阈值直接BLOCK，保护整个Pipeline不被脏数据污染。

### 2.3 Market State Engine
**输入**：指数K线 + 市场广度  
**输出**：regime (BULL/BEAR/.../THEME_DRIVEN) + 策略映射表  
**责任模块**：Market State Engine (51)  
**AI调用**：MarketStateAgent (语义复核POLICY/THEME)  
**Integration**：决定本轮允许运行的策略子集 + 仓位系数。StrategySelector严格执行映射表。

### 2.4 AI分析
**输入**：股票快照 + Market State + Failure Lessons  
**输出**：各Agent JSON + 聚合信号  
**责任模块**：AgentOrchestrator (15_16)  
**AI调用**：TrendAgent / ShortTermAgent / FundamentalAgent 等（Prompt已差异化）  
**Integration**：必须优先读取Failure Library。TrendAgent专注中短期，ShortTermAgent专注超短线。

### 2.5 风险 + 资金分配
**输入**：信号 + 当前持仓 + 账户  
**输出**：风控通过/阻断 + 建议仓位大小  
**责任模块**：PreTradeRiskChecker (31_34) + Capital Allocation Engine (52扩展)  
**Integration**：硬约束 + 智能仓位 sizing 结合，防止过度交易或资金闲置。

### 2.6 组合再平衡
**输入**：当前持仓 + Market State + Performance KPI  
**输出**：Rebalance Plan + Transaction Plan  
**责任模块**：Portfolio Rebalancing Engine (52扩展)  
**Integration**：每日/触发式运行，避免持仓混乱。输出必须经过Risk Check。

### 2.7 执行 + 持仓生命周期
**输入**：Transaction Plan  
**输出**：订单状态 + 持仓状态流转  
**责任模块**：OrderManager + SimulationTrader/QMTTrader (35_38) + Position Lifecycle (57)  
**Integration**：任何持仓必须有完整状态机，支持动态风控退出。

### 2.8 复盘 + 学习闭环
**输入**：已执行信号 + 实际盈亏 + 后续新闻  
**输出**：Failure Case + Lesson Learned  
**责任模块**：FailureDetector + KnowledgeDistiller (55)  
**Integration**：失败案例优先反哺AI分析。人工确认Lesson后反哺Prompt。

### 2.9 绩效评估
**输入**：所有交易记录 + 持仓曲线  
**输出**：System KPI Dashboard + 优化建议  
**责任模块**：Performance Evaluation (58) + MetricsCalculator  
**Integration**：是所有上游优化的唯一北极星。任何改动必须证明能提升这些KPI。

## 3. V1实现范围与扩展点
- V1必须完整实现：Pipeline流程 orchestration、Trading Calendar、Capital Allocation基础逻辑、Rebalancing基础计划生成、Position Lifecycle状态机、System KPI计算。
- V1: Interface Only（保留完整设计）：MCP高级调用、AutoML完整优化、Confidence Engine高级ML模型、Knowledge Graph。
- 所有新引擎必须暴露标准接口，供未来V2增强。

## 4. 与其他文档的集成点
- 03_DEVELOPMENT_ROADMAP：Phase 3必须上线Pipeline主线 + Trading Calendar + Capital Allocation。
- 15_16：AgentOrchestrator必须在analyze()末尾调用Decision Trace构建并注入Failure Lessons。
- 51：Market State结果必须通过Redis实时供Pipeline各步读取。
- 52：扩展Capital Allocation + Rebalancing。
- 55：Failure Library必须成为AI分析的优先输入。
- 57/58：新增状态机与KPI作为Pipeline末端闭环。

此文档为V1最高优先级主线文档，所有其他模块必须以此为准进行对齐。
