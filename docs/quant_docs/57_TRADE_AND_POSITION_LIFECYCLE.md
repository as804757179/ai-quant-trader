# 57 — Trade and Position Lifecycle（交易与持仓生命周期） V1核心

> 任何订单和持仓必须有完整、可审计的状态机。禁止“黑盒”持仓。

## 1. Trade Lifecycle（订单生命周期）

**状态流转图**：
```
DRAFT (信号生成)
  ↓ (风控通过 + Capital Allocation确认)
SUBMITTED (已提交至撮合/券商)
  ↓
PARTIALLY_FILLED (部分成交)
  ↓
FILLED (全部成交) → 触发 Position OPEN
  ↓ (或)
CANCELLED / REJECTED (风控/价格/流动性原因)
```

**数据库扩展**（在 trade.orders 表新增字段）：
```sql
ALTER TABLE trade.orders ADD COLUMN lifecycle_state VARCHAR(30) DEFAULT 'DRAFT';
ALTER TABLE trade.orders ADD COLUMN state_history JSONB;
ALTER TABLE trade.orders ADD COLUMN capital_allocation_id UUID;  -- 关联资金分配记录
```

**API扩展**（在 /api/v1/trade/ 下新增）：
- GET /order/{id}/lifecycle-history
- POST /order/{id}/force-cancel (Emergency Exit)

## 2. Position Lifecycle（持仓生命周期）—— V1新增核心

**完整状态机（V1强制）**：
```
OPEN (新开仓，成交确认，创建Position Lifecycle记录)
  ↓ (风控监控启动 + 动态参数初始化)
ACTIVE (正常持仓监控中)
  ↓ (浮盈达到8% 或 策略信号强化)
PROTECTED (保护模式激活：Break Even上移 + Trailing Stop启动)
  ↓ (继续浮盈 或 回撤控制)
TRAILING_PROFIT (追踪止盈模式：最高价回撤3%触发部分减仓)
  ↓ (达到部分止盈目标 或 风险事件)
PARTIAL_EXIT (部分平仓，记录部分退出原因)
  ↓ (剩余仓位达到最终退出条件)
CLOSED (全部平仓，计算最终PnL + 触发复盘)
  ↓ (Lesson Learned人工/自动确认)
ARCHIVED (归档 + 更新Failure Library + Performance KPI)
```

**明确状态触发事件（V1必须实现监控任务每30秒检查）**：
- **OPEN → ACTIVE**：成交回报确认 + Capital Allocation记录关联
- **ACTIVE → PROTECTED**：浮盈 ≥ 8%（或策略特定阈值）→ 自动激活Break Even + Trailing Stop
- **ACTIVE/PROTECTED → TRAILING_PROFIT**：回撤超过3%（从最高浮盈点）→ 启动追踪止盈，自动挂出减仓单
- **PROTECTED / TRAILING_PROFIT → PARTIAL_EXIT**：达到预设部分止盈目标（如+15%）或单日回撤>5%
- **任何状态 → CLOSED**：策略反转信号 + Market State切换到BEAR/HIGH_VOL + 硬止损触发 + Emergency熔断
- **CLOSED → ARCHIVED**：复盘完成 + FailureDetector扫描 + 更新KPI

**数据库字段扩展**（position_lifecycle表新增）：
```sql
exit_trigger_event VARCHAR(50),      -- 'PROFIT_8PCT', 'DRAWDOWN_3PCT', 'STRATEGY_REVERSE', 'MARKET_STATE_CHANGE'
trailing_high_price NUMERIC,
protected_activated_at TIMESTAMPTZ,
trailing_profit_activated_at TIMESTAMPTZ
```

**数据库新增表**：
```sql
CREATE TABLE trade.position_lifecycle (
    position_id UUID PRIMARY KEY,
    current_state VARCHAR(30) NOT NULL,
    state_history JSONB NOT NULL,
    dynamic_tp_price NUMERIC,
    dynamic_sl_price NUMERIC,
    trailing_stop_pct NUMERIC,
    break_even_activated BOOLEAN DEFAULT FALSE,
    last_monitor_time TIMESTAMPTZ,
    exit_reason VARCHAR(100),
    lesson_learned TEXT
);
```

**集成到 Pipeline**：
- Execution 步骤 → 自动创建 Position Lifecycle 记录
- 每日风控监控任务必须驱动状态流转
- CLOSED 后自动触发 FailureDetector / Performance Evaluation

## 3. V1实现要求
- 状态机必须在 SimulationTrader 和 QMTTrader 中完整实现
- 所有退出必须记录 exit_reason 并关联 Decision Trace
- 禁止任何持仓处于“无状态”或“未知状态”

## 4. Live Trading Gate（实盘守门员）—— V1最大遗漏补充

**严格准入规则（任何策略/信号必须通过此Gate才能进入小资金实盘）**：

```
Paper Trading 连续运行 ≥ 180天
    ↓
System KPI 全部达标：
  - Sharpe Ratio > 1.2
  - Profit Factor > 1.5
  - Max Drawdown < 15%
  - Win Rate + Payoff Ratio 组合健康
    ↓
Risk Review + 合规双签字
    ↓
允许小资金实盘（初始仓位 ≤ 总资金 5%）
    ↓
实盘连续 60天 表现稳定 + 无熔断
    ↓
逐步放开至正常仓位
```

**禁止路径**：AI生成策略 → Paper → 直接QMT实盘（必须经过Gate）。

**数据库表**：
```sql
CREATE TABLE risk.live_trading_gate (
    strategy_id INT PRIMARY KEY,
    paper_start_date DATE,
    paper_sharpe NUMERIC,
    paper_profit_factor NUMERIC,
    paper_max_dd NUMERIC,
    gate_passed BOOLEAN DEFAULT FALSE,
    approved_by VARCHAR(50),
    approved_at TIMESTAMPTZ,
    live_start_date DATE
);
```

**集成**：QMTTrader.submit() 前必须检查此Gate。未通过直接拒绝并告警。

## 5. Integration with Investment Decision Pipeline
属于 Pipeline 的 “执行层” + “持仓生命周期” 步骤。
输入：Transaction Plan + 成交回报
输出：状态流转 + 持仓快照更新
下游：Daily Review + Performance Evaluation
直接服务：风险控制（动态退出降低Max Drawdown） + 可维护性（完整审计链）
