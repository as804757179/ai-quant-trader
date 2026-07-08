# 06 — 数据库完整设计（PostgreSQL + TimescaleDB）

---

## 1. 数据库架构总览

```
PostgreSQL 15 + TimescaleDB 扩展
│
├── Schema: market          # 行情数据（时序）
│   ├── klines              # K线数据（超表 Hypertable）
│   ├── quotes              # 实时报价快照
│   └── fund_flows          # 资金流向（时序）
│
├── Schema: fundamental     # 基本面数据
│   ├── stocks              # 股票基础信息
│   ├── financial_reports   # 财务报表
│   ├── shareholders        # 股东数据
│   └── announcements       # 公告
│
├── Schema: ai              # AI决策数据
│   ├── signals             # AI交易信号
│   ├── agent_logs          # Agent分析日志
│   └── signal_feedback     # 信号结果反馈
│
├── Schema: strategy        # 策略数据
│   ├── strategies          # 策略配置
│   ├── strategy_versions   # 策略版本历史
│   └── watchlists          # 关注股票池
│
├── Schema: backtest        # 回测数据
│   ├── backtest_tasks      # 回测任务
│   ├── backtest_results    # 回测结果
│   └── backtest_trades     # 回测交易记录
│
├── Schema: trade           # 交易数据（核心）
│   ├── orders              # 订单表
│   ├── order_history       # 订单历史（状态流转）
│   ├── positions           # 当前持仓
│   ├── position_snapshots  # 持仓快照（每日）
│   └── account_records     # 账户资金记录
│
├── Schema: risk            # 风控数据
│   ├── risk_rules          # 风控规则配置
│   ├── risk_events         # 风控触发事件
│   └── fuse_records        # 熔断记录
│
└── Schema: audit           # 审计日志（不可删除）
    ├── operation_logs      # 所有操作日志
    └── data_change_logs    # 数据变更日志
```

---

## 2. 初始化脚本

```sql
-- 启用 TimescaleDB 扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- 支持股票名称模糊搜索

-- 创建 Schema
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS fundamental;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS strategy;
CREATE SCHEMA IF NOT EXISTS backtest;
CREATE SCHEMA IF NOT EXISTS trade;
CREATE SCHEMA IF NOT EXISTS risk;
CREATE SCHEMA IF NOT EXISTS audit;
```

---

## 3. Schema: fundamental（基本面）

### 3.1 stocks（股票基础信息）

```sql
CREATE TABLE fundamental.stocks (
    code            VARCHAR(10)     PRIMARY KEY,            -- 股票代码 如 000001
    name            VARCHAR(50)     NOT NULL,               -- 股票名称
    full_name       VARCHAR(100),                           -- 公司全称
    market          VARCHAR(5)      NOT NULL,               -- SH/SZ/BJ
    board           VARCHAR(20),                            -- 主板/创业板/科创板/北交所
    sector          VARCHAR(50),                            -- 申万一级行业
    sub_sector      VARCHAR(50),                            -- 申万二级行业
    list_date       DATE,                                   -- 上市日期
    delist_date     DATE,                                   -- 退市日期（NULL=正常）
    total_shares    BIGINT,                                 -- 总股本（股）
    float_shares    BIGINT,                                 -- 流通股本（股）
    is_st           BOOLEAN         DEFAULT FALSE,          -- 是否ST
    is_active       BOOLEAN         DEFAULT TRUE,           -- 是否正常交易
    currency        VARCHAR(5)      DEFAULT 'CNY',
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_stocks_sector ON fundamental.stocks(sector);
CREATE INDEX idx_stocks_board  ON fundamental.stocks(board);
CREATE INDEX idx_stocks_name   ON fundamental.stocks USING gin(name gin_trgm_ops);
```

### 3.2 financial_reports（财务报表）

```sql
CREATE TABLE fundamental.financial_reports (
    id              BIGSERIAL       PRIMARY KEY,
    stock_code      VARCHAR(10)     NOT NULL REFERENCES fundamental.stocks(code),
    report_type     VARCHAR(10)     NOT NULL,               -- Q1/Q2/Q3/annual
    report_date     DATE            NOT NULL,               -- 报告期
    publish_date    DATE,                                   -- 发布日期

    -- 利润表
    revenue         NUMERIC(20,2),                          -- 营业收入（元）
    gross_profit    NUMERIC(20,2),                          -- 毛利润
    operating_profit NUMERIC(20,2),                         -- 营业利润
    net_profit      NUMERIC(20,2),                          -- 净利润
    eps             NUMERIC(10,4),                          -- 每股收益

    -- 资产负债表
    total_assets    NUMERIC(20,2),                          -- 总资产
    total_liab      NUMERIC(20,2),                          -- 总负债
    equity          NUMERIC(20,2),                          -- 净资产
    bvps            NUMERIC(10,4),                          -- 每股净资产

    -- 现金流
    oper_cashflow   NUMERIC(20,2),                          -- 经营现金流

    -- 估值指标（基于报告期末价格计算）
    pe_ratio        NUMERIC(10,2),
    pb_ratio        NUMERIC(10,2),
    ps_ratio        NUMERIC(10,2),
    roe             NUMERIC(8,4),                           -- 净资产收益率（%）
    roa             NUMERIC(8,4),                           -- 总资产收益率（%）
    debt_ratio      NUMERIC(8,4),                           -- 资产负债率（%）
    gross_margin    NUMERIC(8,4),                           -- 毛利率（%）

    -- 同比增长
    revenue_yoy     NUMERIC(8,4),                           -- 营收同比（%）
    profit_yoy      NUMERIC(8,4),                           -- 净利润同比（%）

    data_source     VARCHAR(50),
    created_at      TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE(stock_code, report_type, report_date)
);

CREATE INDEX idx_reports_stock_date ON fundamental.financial_reports(stock_code, report_date DESC);
```

### 3.3 announcements（公告）

```sql
CREATE TABLE fundamental.announcements (
    id              BIGSERIAL       PRIMARY KEY,
    stock_code      VARCHAR(10)     REFERENCES fundamental.stocks(code),
    title           VARCHAR(500)    NOT NULL,
    category        VARCHAR(50),                            -- 定期报告/重大事项/分红/增减持...
    publish_time    TIMESTAMPTZ     NOT NULL,
    content_url     TEXT,
    content_text    TEXT,                                   -- 提取的纯文本内容
    is_vectorized   BOOLEAN         DEFAULT FALSE,          -- 是否已向量化进RAG
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_announcements_stock ON fundamental.announcements(stock_code, publish_time DESC);
CREATE INDEX idx_announcements_cat   ON fundamental.announcements(category);
```

---

## 4. Schema: market（行情数据）

### 4.1 klines（K线 - TimescaleDB超表）

```sql
CREATE TABLE market.klines (
    time            TIMESTAMPTZ     NOT NULL,               -- K线时间（收盘时间）
    stock_code      VARCHAR(10)     NOT NULL,
    period          VARCHAR(10)     NOT NULL,               -- 1min/5min/15min/30min/60min/1d/1w
    open            NUMERIC(12,4)   NOT NULL,
    high            NUMERIC(12,4)   NOT NULL,
    low             NUMERIC(12,4)   NOT NULL,
    close           NUMERIC(12,4)   NOT NULL,
    volume          BIGINT          NOT NULL,               -- 成交量（股）
    amount          NUMERIC(20,2)   NOT NULL,               -- 成交额（元）
    vwap            NUMERIC(12,4),                          -- 成交量加权均价
    turnover_rate   NUMERIC(8,4),                           -- 换手率（%）
    adj_factor      NUMERIC(12,6)   DEFAULT 1.0,            -- 复权因子

    -- 前复权价格（预计算，避免实时计算开销）
    adj_close       NUMERIC(12,4),

    PRIMARY KEY (time, stock_code, period)
);

-- 转为 TimescaleDB 超表（按时间分区，每月一个chunk）
SELECT create_hypertable(
    'market.klines',
    'time',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

-- 关键索引
CREATE INDEX idx_klines_stock_period ON market.klines(stock_code, period, time DESC);

-- TimescaleDB 连续聚合：日线自动聚合为周线
CREATE MATERIALIZED VIEW market.klines_weekly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 week', time) AS week,
    stock_code,
    first(open, time)   AS open,
    max(high)           AS high,
    min(low)            AS low,
    last(close, time)   AS close,
    sum(volume)         AS volume,
    sum(amount)         AS amount
FROM market.klines
WHERE period = '1d'
GROUP BY week, stock_code;

-- 数据保留策略：1min数据保留6个月，日线永久保留
SELECT add_retention_policy('market.klines',
    INTERVAL '6 months',
    if_not_exists => TRUE,
    schedule_interval => INTERVAL '1 day'
);
-- 注意：日线和周线不受此策略影响（通过period筛选另设）
```

### 4.2 quotes（实时报价快照）

```sql
CREATE TABLE market.quotes (
    time            TIMESTAMPTZ     NOT NULL,
    stock_code      VARCHAR(10)     NOT NULL,
    price           NUMERIC(12,4),                          -- 最新价
    open            NUMERIC(12,4),
    high            NUMERIC(12,4),
    low             NUMERIC(12,4),
    prev_close      NUMERIC(12,4),                          -- 昨收
    change          NUMERIC(12,4),                          -- 涨跌额
    change_pct      NUMERIC(8,4),                           -- 涨跌幅（%）
    volume          BIGINT,
    amount          NUMERIC(20,2),
    bid1_price      NUMERIC(12,4),  bid1_vol BIGINT,        -- 买一
    bid2_price      NUMERIC(12,4),  bid2_vol BIGINT,
    bid3_price      NUMERIC(12,4),  bid3_vol BIGINT,
    ask1_price      NUMERIC(12,4),  ask1_vol BIGINT,        -- 卖一
    ask2_price      NUMERIC(12,4),  ask2_vol BIGINT,
    ask3_price      NUMERIC(12,4),  ask3_vol BIGINT,

    PRIMARY KEY (time, stock_code)
);

SELECT create_hypertable('market.quotes', 'time',
    chunk_time_interval => INTERVAL '1 day');

-- 只保留最近7天的实时快照
SELECT add_retention_policy('market.quotes', INTERVAL '7 days');
```

### 4.3 fund_flows（资金流向）

```sql
CREATE TABLE market.fund_flows (
    time            TIMESTAMPTZ     NOT NULL,
    stock_code      VARCHAR(10)     NOT NULL,
    super_large_in  NUMERIC(20,2),                          -- 超大单净流入（元）
    large_in        NUMERIC(20,2),                          -- 大单净流入
    medium_in       NUMERIC(20,2),                          -- 中单净流入
    small_in        NUMERIC(20,2),                          -- 小单净流入
    main_net_in     NUMERIC(20,2),                          -- 主力净流入（超大+大）
    north_net_in    NUMERIC(20,2),                          -- 北向净流入

    PRIMARY KEY (time, stock_code)
);

SELECT create_hypertable('market.fund_flows', 'time',
    chunk_time_interval => INTERVAL '1 month');
```

---

## 5. Schema: ai（AI决策）

### 5.1 signals（AI交易信号）

```sql
CREATE TABLE ai.signals (
    id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    stock_code      VARCHAR(10)     NOT NULL REFERENCES fundamental.stocks(code),
    strategy_id     INT,                                    -- 触发策略（可NULL=手动触发）

    -- 信号内容
    action          VARCHAR(10)     NOT NULL                -- BUY/SELL/HOLD
                    CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    confidence      NUMERIC(5,4)    NOT NULL                -- 0.0000~1.0000
                    CHECK (confidence BETWEEN 0 AND 1),
    risk_level      VARCHAR(10)     NOT NULL DEFAULT 'MEDIUM'
                    CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'EXTREME')),

    -- 价格参考
    price_at        NUMERIC(12,4)   NOT NULL,               -- 信号产生时的价格
    target_price    NUMERIC(12,4),                          -- 目标价
    stop_loss       NUMERIC(12,4),                          -- 止损价

    -- AI分析详情
    reason          TEXT            NOT NULL,               -- 信号原因摘要
    agent_votes     JSONB           NOT NULL DEFAULT '{}',  -- 各Agent投票详情
    raw_agent_output JSONB,                                 -- 原始Agent输出（调试用）

    -- 信号生命周期
    signal_time     TIMESTAMPTZ     NOT NULL DEFAULT NOW(), -- 信号产生时间
    valid_until     TIMESTAMPTZ,                            -- 有效期
    status          VARCHAR(20)     DEFAULT 'active'
                    CHECK (status IN ('active','executed','expired','cancelled')),

    -- 信号结果追踪（事后填充）
    executed_at     TIMESTAMPTZ,                            -- 实际执行时间
    executed_price  NUMERIC(12,4),                          -- 实际成交价
    pnl             NUMERIC(12,4),                          -- 该信号最终盈亏
    pnl_pct         NUMERIC(8,4),
    feedback_note   TEXT,                                   -- 人工复盘备注

    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_signals_stock    ON ai.signals(stock_code, signal_time DESC);
CREATE INDEX idx_signals_status   ON ai.signals(status);
CREATE INDEX idx_signals_action   ON ai.signals(action, signal_time DESC);
```

### 5.2 agent_logs（Agent分析日志）

```sql
CREATE TABLE ai.agent_logs (
    id              BIGSERIAL       PRIMARY KEY,
    signal_id       UUID            REFERENCES ai.signals(id),
    stock_code      VARCHAR(10),
    agent_name      VARCHAR(50)     NOT NULL,               -- trend/fundamental/sentiment/...
    model_used      VARCHAR(50),                            -- gpt-4o/claude-3-5-sonnet/...
    input_tokens    INT,
    output_tokens   INT,
    latency_ms      INT,                                    -- 响应耗时（毫秒）
    status          VARCHAR(20)     DEFAULT 'success',      -- success/timeout/error/degraded
    error_msg       TEXT,
    output          JSONB,                                  -- Agent输出结果
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_agent_logs_signal ON ai.agent_logs(signal_id);
CREATE INDEX idx_agent_logs_time   ON ai.agent_logs(created_at DESC);
```

---

## 6. Schema: trade（交易核心）

### 6.1 orders（订单表）

```sql
CREATE TABLE trade.orders (
    id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    idempotency_key VARCHAR(64)     UNIQUE NOT NULL,        -- 幂等键（防重复下单）
    stock_code      VARCHAR(10)     NOT NULL REFERENCES fundamental.stocks(code),
    signal_id       UUID            REFERENCES ai.signals(id),
    strategy_id     INT,

    -- 订单内容
    side            VARCHAR(5)      NOT NULL
                    CHECK (side IN ('BUY', 'SELL')),
    order_type      VARCHAR(10)     DEFAULT 'LIMIT'
                    CHECK (order_type IN ('MARKET', 'LIMIT')),
    quantity        INT             NOT NULL CHECK (quantity > 0),
    limit_price     NUMERIC(12,4),                          -- 限价（LIMIT单必填）
    filled_quantity INT             DEFAULT 0,
    avg_fill_price  NUMERIC(12,4),
    commission      NUMERIC(12,4)   DEFAULT 0,              -- 手续费

    -- 订单状态
    status          VARCHAR(20)     DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','SUBMITTED','PARTIAL','FILLED','CANCELLED','FAILED')),
    mode            VARCHAR(15)     NOT NULL
                    CHECK (mode IN ('simulation', 'paper', 'live')),

    -- 来源追踪
    trigger_source  VARCHAR(20)     DEFAULT 'auto',         -- auto/manual/risk_reduce
    operator        VARCHAR(50),                            -- 手动操作时的操作员

    -- 时间戳
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    submitted_at    TIMESTAMPTZ,
    filled_at       TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,

    -- 外部订单ID（QMT等券商系统返回）
    broker_order_id VARCHAR(100),
    reject_reason   TEXT
);

CREATE INDEX idx_orders_stock    ON trade.orders(stock_code, created_at DESC);
CREATE INDEX idx_orders_status   ON trade.orders(status);
CREATE INDEX idx_orders_signal   ON trade.orders(signal_id);
```

### 6.2 order_history（订单状态流转历史）

```sql
-- 记录每一次状态变更，不可修改不可删除
CREATE TABLE trade.order_history (
    id              BIGSERIAL       PRIMARY KEY,
    order_id        UUID            NOT NULL REFERENCES trade.orders(id),
    from_status     VARCHAR(20),
    to_status       VARCHAR(20)     NOT NULL,
    changed_at      TIMESTAMPTZ     DEFAULT NOW(),
    changed_by      VARCHAR(50),                            -- system/operator name
    detail          JSONB                                   -- 附加信息
);

CREATE INDEX idx_order_hist_order ON trade.order_history(order_id);
```

### 6.3 positions（当前持仓）

```sql
CREATE TABLE trade.positions (
    id              BIGSERIAL       PRIMARY KEY,
    stock_code      VARCHAR(10)     NOT NULL REFERENCES fundamental.stocks(code),
    mode            VARCHAR(15)     NOT NULL,

    -- 持仓数量
    total_qty       INT             NOT NULL DEFAULT 0,     -- 总持仓
    available_qty   INT             NOT NULL DEFAULT 0,     -- 可卖数量（T+1限制）
    frozen_qty      INT             NOT NULL DEFAULT 0,     -- 冻结数量（待成交卖单）

    -- 成本
    avg_cost        NUMERIC(12,4),                          -- 持仓均价
    total_cost      NUMERIC(20,4),                          -- 总成本

    -- 实时盈亏（定时更新）
    current_price   NUMERIC(12,4),
    market_value    NUMERIC(20,4),
    unrealized_pnl  NUMERIC(20,4),                          -- 浮盈浮亏
    unrealized_pnl_pct NUMERIC(8,4),

    -- 已实现盈亏（平仓后累计）
    realized_pnl    NUMERIC(20,4)   DEFAULT 0,

    updated_at      TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (stock_code, mode)
);
```

### 6.4 account_records（账户资金记录）

```sql
CREATE TABLE trade.account_records (
    id              BIGSERIAL       PRIMARY KEY,
    mode            VARCHAR(15)     NOT NULL,
    record_time     TIMESTAMPTZ     DEFAULT NOW(),

    -- 账户资金
    total_assets    NUMERIC(20,4)   NOT NULL,               -- 总资产
    cash            NUMERIC(20,4)   NOT NULL,               -- 现金
    market_value    NUMERIC(20,4)   NOT NULL,               -- 持仓市值
    frozen_cash     NUMERIC(20,4)   DEFAULT 0,              -- 冻结资金

    -- 收益统计
    daily_pnl       NUMERIC(20,4),                          -- 今日盈亏
    total_pnl       NUMERIC(20,4),                          -- 累计盈亏
    total_pnl_pct   NUMERIC(8,4),                           -- 累计收益率

    -- 持仓统计
    position_count  INT             DEFAULT 0,
    position_ratio  NUMERIC(5,4),                           -- 仓位比例

    data_type       VARCHAR(10)     DEFAULT 'snapshot'      -- snapshot/eod（每日收盘）
);

CREATE INDEX idx_account_mode_time ON trade.account_records(mode, record_time DESC);
```

---

## 7. Schema: risk（风控）

### 7.1 risk_rules（风控规则配置）

```sql
CREATE TABLE risk.risk_rules (
    id              SERIAL          PRIMARY KEY,
    rule_code       VARCHAR(50)     UNIQUE NOT NULL,        -- 规则编码
    rule_name       VARCHAR(100)    NOT NULL,
    rule_type       VARCHAR(20)     NOT NULL,               -- position/loss/frequency/...
    is_hard         BOOLEAN         DEFAULT TRUE,           -- 硬约束=必须满足，软约束=告警
    threshold       NUMERIC(12,4)   NOT NULL,
    action          VARCHAR(20)     NOT NULL,               -- block/alert/reduce/fuse
    is_enabled      BOOLEAN         DEFAULT TRUE,
    description     TEXT,
    updated_at      TIMESTAMPTZ     DEFAULT NOW(),
    updated_by      VARCHAR(50)
);

-- 初始化默认风控规则
INSERT INTO risk.risk_rules VALUES
(DEFAULT,'MAX_SINGLE_POSITION','单票最大仓位','position',TRUE,0.10,'block',TRUE,'单票持仓不得超过总资产10%',NOW(),'system'),
(DEFAULT,'MAX_TOTAL_POSITION','总仓位上限','position',TRUE,0.80,'block',TRUE,'总持仓不得超过总资产80%',NOW(),'system'),
(DEFAULT,'MAX_DAILY_LOSS','日最大亏损','loss',TRUE,0.03,'fuse',TRUE,'单日亏损超过3%触发熔断',NOW(),'system'),
(DEFAULT,'MAX_DRAWDOWN','最大回撤熔断','loss',TRUE,0.15,'fuse',TRUE,'回撤超过15%停止所有交易',NOW(),'system'),
(DEFAULT,'MAX_ORDER_FREQ','单日最大下单次数','frequency',TRUE,20,'block',TRUE,'单日下单不超过20次',NOW(),'system'),
(DEFAULT,'WARN_SINGLE_POSITION','单票仓位预警','position',FALSE,0.08,'alert',TRUE,'单票仓位超过8%发出警告',NOW(),'system'),
(DEFAULT,'WARN_TOTAL_POSITION','总仓位预警','position',FALSE,0.70,'alert',TRUE,'总仓位超过70%发出警告',NOW(),'system');
```

### 7.2 risk_events（风控触发记录）

```sql
CREATE TABLE risk.risk_events (
    id              BIGSERIAL       PRIMARY KEY,
    rule_code       VARCHAR(50)     NOT NULL,
    trigger_value   NUMERIC(12,4)   NOT NULL,               -- 触发时的实际值
    threshold       NUMERIC(12,4)   NOT NULL,               -- 规则阈值
    action_taken    VARCHAR(20)     NOT NULL,               -- 实际执行的动作
    detail          JSONB,                                   -- 触发时的完整上下文
    order_id        UUID            REFERENCES trade.orders(id), -- 被拦截的订单
    is_resolved     BOOLEAN         DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    resolved_by     VARCHAR(50),
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);
```

### 7.3 fuse_records（熔断记录）

```sql
CREATE TABLE risk.fuse_records (
    id              SERIAL          PRIMARY KEY,
    mode            VARCHAR(15)     NOT NULL,
    fuse_reason     VARCHAR(200)    NOT NULL,
    triggered_at    TIMESTAMPTZ     DEFAULT NOW(),
    portfolio_snapshot JSONB,                               -- 熔断时的持仓快照

    -- 恢复流程
    recovery_approved_by VARCHAR(50),                       -- 审批人（必须人工）
    recovery_note   TEXT,                                   -- 恢复备注
    recovered_at    TIMESTAMPTZ,
    is_active       BOOLEAN         DEFAULT TRUE            -- TRUE=当前熔断中
);
```

---

## 8. Schema: audit（审计日志）

```sql
-- 审计日志：不可修改，不可删除（通过权限控制）
CREATE TABLE audit.operation_logs (
    id              BIGSERIAL       PRIMARY KEY,
    session_id      VARCHAR(64),
    operator        VARCHAR(50),
    ip_address      INET,
    operation       VARCHAR(100)    NOT NULL,               -- CREATE_ORDER/CANCEL_ORDER/...
    entity_type     VARCHAR(50),                            -- order/position/strategy/...
    entity_id       VARCHAR(100),
    before_data     JSONB,
    after_data      JSONB,
    result          VARCHAR(20),                            -- success/failed/blocked
    error_detail    TEXT,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

-- 审计表只能INSERT，禁止UPDATE和DELETE
REVOKE UPDATE, DELETE ON audit.operation_logs FROM PUBLIC;

-- 数据变更触发器示例（订单状态变更自动记录）
CREATE OR REPLACE FUNCTION audit.log_order_change()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit.operation_logs(operation, entity_type, entity_id, before_data, after_data)
    VALUES (
        'ORDER_STATUS_CHANGE',
        'order',
        NEW.id::text,
        to_jsonb(OLD),
        to_jsonb(NEW)
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_audit
AFTER UPDATE ON trade.orders
FOR EACH ROW EXECUTE FUNCTION audit.log_order_change();
```

---

## 9. Schema: backtest（回测）

```sql
CREATE TABLE backtest.tasks (
    id              SERIAL          PRIMARY KEY,
    strategy_id     INT,
    name            VARCHAR(200),
    start_date      DATE            NOT NULL,
    end_date        DATE            NOT NULL,
    initial_cash    NUMERIC(20,2)   DEFAULT 1000000,
    universe        VARCHAR(50),                            -- 股票池（沪深300/全市场/自定义）
    status          VARCHAR(20)     DEFAULT 'pending'
                    CHECK (status IN ('pending','running','done','failed','cancelled')),
    progress        INT             DEFAULT 0,              -- 0-100
    error_msg       TEXT,
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,

    -- 防未来函数检查标记
    lookahead_checked BOOLEAN       DEFAULT FALSE,          -- 是否经过Look-ahead检查
    lookahead_issues  JSONB                                 -- 发现的问题列表
);

CREATE TABLE backtest.results (
    id              SERIAL          PRIMARY KEY,
    task_id         INT             NOT NULL REFERENCES backtest.tasks(id),
    walk_forward_period VARCHAR(50),                        -- 如 "2023-01~2023-06"（IS样本内）

    -- 关键指标
    total_return    NUMERIC(10,4),                          -- 总收益率（%）
    annual_return   NUMERIC(10,4),                          -- 年化收益率（%）
    max_drawdown    NUMERIC(10,4),                          -- 最大回撤（%）
    sharpe_ratio    NUMERIC(8,4),
    calmar_ratio    NUMERIC(8,4),
    win_rate        NUMERIC(8,4),                           -- 胜率（%）
    profit_loss_ratio NUMERIC(8,4),                         -- 盈亏比
    total_trades    INT,
    avg_holding_days NUMERIC(8,2),
    benchmark_return NUMERIC(10,4),                         -- 沪深300基准收益率（%）
    alpha           NUMERIC(10,4),
    beta            NUMERIC(8,4),
    information_ratio NUMERIC(8,4),

    -- 详细数据（JSON存储曲线数据）
    equity_curve    JSONB,                                  -- [[date, value], ...]
    drawdown_curve  JSONB,
    monthly_returns JSONB,                                  -- {year: {month: return}}
    trade_list      JSONB,                                  -- 交易明细列表

    -- Walk-Forward样本外指标
    oos_return      NUMERIC(10,4),                          -- 样本外收益率
    oos_sharpe      NUMERIC(8,4),                           -- 样本外夏普

    created_at      TIMESTAMPTZ     DEFAULT NOW()
);
```

---

## 10. 数据库迁移（Alembic）

```python
# alembic/versions/001_initial.py
"""Initial database schema

Revision ID: 001
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # 按依赖顺序创建
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS uuid-ossp")
    op.execute("CREATE SCHEMA IF NOT EXISTS market")
    # ... 其余DDL

def downgrade():
    # 不允许降级（生产环境）
    raise RuntimeError("Downgrade not allowed in production")
```

```bash
# 常用命令
alembic upgrade head          # 升级到最新版本
alembic revision --autogenerate -m "add xxx table"  # 生成迁移文件
alembic history               # 查看迁移历史
alembic current               # 查看当前版本
```

---

## 11. 数据库配置（postgresql.conf 优化）

```ini
# 针对量化交易场景的PostgreSQL优化配置
# 内存配置（假设16GB内存服务器）
shared_buffers = 4GB            # 25%内存
effective_cache_size = 12GB     # 75%内存
work_mem = 256MB                # 复杂查询排序缓冲
maintenance_work_mem = 1GB      # 维护操作缓冲

# WAL配置
wal_level = replica
max_wal_size = 4GB
checkpoint_completion_target = 0.9

# 并发配置
max_connections = 200
max_worker_processes = 8

# TimescaleDB
timescaledb.max_background_workers = 8

# 日志（审计需要）
log_destination = 'csvlog'
log_directory = 'pg_log'
log_min_duration_statement = 1000   # 记录超过1秒的慢查询
log_checkpoints = on
log_connections = on
log_disconnections = on
```
