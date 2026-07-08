# 27 — 防未来函数完整指南（Look-ahead Bias Prevention）

> ⚠️ **这是回测系统最关键的文档。未来函数导致的回测失真是量化交易亏损的头号原因之一。**

---

## 1. 什么是未来函数（Look-ahead Bias）

**定义：** 在回测中，某个时间点 T 的交易决策使用了 T 时刻之后才能获得的数据。

**危害：** 回测结果看起来很美，但实盘必然亏损，因为实盘时你根本没有"未来数据"。

---

## 2. A股特有的时间陷阱

### 2.1 交易时间轴

```
09:25          09:30          14:57          15:00          15:00+
  │              │              │              │              │
  ▼              ▼              ▼              ▼              ▼
集合竞价开始  正式开盘      收盘集合竞价    收盘价确定    数据发布延迟
                                                           （财务/公告）
```

### 2.2 各类数据的"可用时刻"

| 数据类型 | 数据产生时间 | 最早可用时间 | 常见错误用法 |
|---------|------------|------------|------------|
| 当日K线收盘价 | 15:00 | 15:00之后 | 用当日收盘价在当日14:59买入 |
| 当日资金流向 | 15:00后 | 15:30后 | 回测当日用了盘后数据 |
| 财务报告 | 报告期后1-4月 | 公告发布日 | 用报告期日期而非发布日期 |
| 分析师研报 | 发布日 | 发布日次日开盘 | 当日发布当日买入 |
| 龙虎榜 | 收盘后发布 | 次日 | 当日盘中用了龙虎榜 |
| 北向资金 | 盘中实时 | 实时可用（有延迟） | 忽略延迟 |
| 股东数据 | 季报披露 | 披露日 | 用季报期末日而非披露日 |
| 新闻 | 发布时间 | 发布时间 | 忽略发布时间只看标题日期 |

---

## 3. 常见未来函数类型及修复方案

### 3.1 类型一：收盘价信号当日成交

**错误代码：**
```python
# ❌ 错误：用今日收盘价判断，当日收盘前买入
def generate_signal(stock_code, date):
    kline = get_kline(stock_code, date)  # 获取当日K线
    if kline['close'] > kline['ma20']:   # 收盘价在MA20上方
        return 'BUY'                      # 当日买入 ← 未来函数！

# 回测撮合错误
for date in trading_dates:
    signal = generate_signal(code, date)
    if signal == 'BUY':
        execute_order(code, date, price=get_close(code, date))  # ❌ 用收盘价成交
```

**正确代码：**
```python
# ✅ 正确：昨日收盘判断，明日开盘成交
def generate_signal(stock_code, date):
    prev_date = get_prev_trading_date(date)
    kline = get_kline(stock_code, prev_date)  # 使用昨日K线
    if kline['close'] > kline['ma20']:
        return 'BUY'                           # 信号在昨日收盘后产生

# 回测撮合
for date in trading_dates:
    prev_date = get_prev_trading_date(date)
    signal = generate_signal(code, prev_date)  # 昨日信号
    if signal == 'BUY':
        # 今日开盘成交，考虑滑点
        execute_order(code, date, price=get_open(code, date) * (1 + SLIPPAGE))
```

### 3.2 类型二：财务数据使用报告期而非发布日

**错误代码：**
```python
# ❌ 错误：在季报"报告期"使用财务数据
def get_roe(stock_code, date):
    # 2024-03-31的季报在2024-04-30才发布！
    report = db.query("""
        SELECT roe FROM financial_reports
        WHERE stock_code = %s AND report_date <= %s
        ORDER BY report_date DESC LIMIT 1
    """, [stock_code, date])
    return report.roe
```

**正确代码：**
```python
# ✅ 正确：按发布日期（publish_date）查询
def get_roe(stock_code, date):
    report = db.query("""
        SELECT roe FROM financial_reports
        WHERE stock_code = %s AND publish_date <= %s  -- 关键：用publish_date
        ORDER BY publish_date DESC LIMIT 1
    """, [stock_code, date])
    return report.roe

# 数据库中必须存储 publish_date（发布日）而非只存 report_date（报告期）
# 示例：2024年一季报
# report_date = 2024-03-31（季报结束日）
# publish_date = 2024-04-28（实际发布日）← 回测应使用这个日期
```

### 3.3 类型三：技术指标计算包含当前K线

**错误代码：**
```python
# ❌ 错误：MA20包含当日收盘价，但信号在当日产生
def calc_ma20(prices: list, current_index: int) -> float:
    return sum(prices[current_index-19:current_index+1]) / 20  # 包含了current_index！

# 当 current_index 对应今日时，prices[current_index] = 今日收盘价
# 在今日收盘前就使用了今日收盘价 ← 未来函数
```

**正确代码：**
```python
# ✅ 正确：MA20只使用昨日及之前的数据
def calc_ma20(prices: list, current_index: int) -> float:
    # 使用 current_index-1 到 current_index-20 共20个数据点
    return sum(prices[current_index-20:current_index]) / 20

# 更清晰的写法：明确用"昨日之前"的数据
def calc_ma20_safe(df: pd.DataFrame, date: str) -> float:
    prev_20_days = df[df['date'] < date].tail(20)  # 严格小于，不包含当日
    if len(prev_20_days) < 20:
        return None
    return prev_20_days['close'].mean()
```

### 3.4 类型四：向前填充（ffill）引入未来数据

**错误代码：**
```python
# ❌ 错误：对整个数据集做ffill后再切分
df = pd.DataFrame(...)
df['pe'] = df['pe'].ffill()  # 对全量数据向前填充
train_df = df[df['date'] < '2023-01-01']  # 切分后，训练集的某些值可能来自2023年后
```

**正确代码：**
```python
# ✅ 正确：先切分再处理，或使用expanding window
def get_feature_at_date(df: pd.DataFrame, date: str, feature: str):
    # 只使用该日期之前的数据
    hist = df[df['date'] <= date][feature]
    return hist.ffill().iloc[-1]  # 只对历史数据做ffill
```

### 3.5 类型五：标准化/归一化泄露

**错误代码：**
```python
# ❌ 错误：用全量数据的均值和标准差做归一化
from sklearn.preprocessing import StandardScaler
scaler = StandardScaler()
features_scaled = scaler.fit_transform(all_features)  # 用了未来的统计量！
train_features = features_scaled[:train_size]
```

**正确代码：**
```python
# ✅ 正确：只用训练集的统计量，在测试集上transform
train_features = all_features[:train_size]
test_features = all_features[train_size:]

scaler = StandardScaler()
train_scaled = scaler.fit_transform(train_features)   # fit只在训练集
test_scaled = scaler.transform(test_features)          # 用训练集的统计量转换测试集
```

### 3.6 类型六：AI模型训练数据泄露

**错误代码：**
```python
# ❌ 错误：用"未来标签"训练模型
def create_training_data(df):
    df['label'] = df['close'].shift(-5)  # 5天后的价格作为标签
    # 这没错，但要确保回测时模型只用了历史数据训练
    model.fit(df[features], df['label'])  # 全量数据训练

# 回测时用的这个模型见过了"未来数据"
```

**正确代码：**
```python
# ✅ 正确：Walk-Forward训练，确保模型训练窗口不泄露
class WalkForwardModel:
    def predict_at_date(self, features, date):
        # 只用该日期之前的数据训练的模型版本
        model_version = self.get_model_version_for_date(date)
        return model_version.predict(features)

    def get_model_version_for_date(self, date):
        # 找到在date之前最近一次训练完成的模型
        versions = self.model_versions  # [(train_end_date, model), ...]
        for train_end, model in reversed(versions):
            if train_end < date:
                return model
        raise ValueError(f"No model available before {date}")
```

---

## 4. 防未来函数检查器（自动化检测）

```python
# backend/app/backtest/lookahead_checker.py

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import ast

@dataclass
class LookaheadIssue:
    severity: str           # ERROR / WARNING
    location: str           # 代码位置或数据位置
    description: str
    suggestion: str

class LookaheadChecker:
    """回测运行前自动检查潜在的未来函数问题"""

    def check_strategy(self, strategy_code: str) -> List[LookaheadIssue]:
        """静态分析策略代码，查找潜在的未来函数"""
        issues = []
        tree = ast.parse(strategy_code)
        issues.extend(self._check_ast(tree))
        return issues

    def check_data_timeline(
        self,
        decisions: pd.DataFrame,  # columns: date, stock_code, action
        data_used: pd.DataFrame   # columns: date, data_type, data_date
    ) -> List[LookaheadIssue]:
        """
        检查每个决策点使用的数据是否都早于决策时间
        decisions: 每次交易决策的时间和使用的数据
        data_used: 数据的实际产生时间
        """
        issues = []
        for _, decision in decisions.iterrows():
            decision_date = decision['date']
            for _, data_row in data_used[
                data_used['decision_id'] == decision['id']
            ].iterrows():
                # 数据的实际可用时间必须早于决策时间
                if data_row['available_date'] > decision_date:
                    issues.append(LookaheadIssue(
                        severity='ERROR',
                        location=f"Decision on {decision_date}, Stock {decision['stock_code']}",
                        description=f"Used {data_row['data_type']} data from {data_row['available_date']} "
                                   f"which was not available on {decision_date}",
                        suggestion="Use data with available_date <= decision_date"
                    ))
        return issues

    def check_financial_data_dates(self, db_session) -> List[LookaheadIssue]:
        """检查数据库中财务数据是否都有正确的publish_date"""
        issues = []
        result = db_session.execute("""
            SELECT stock_code, report_date, publish_date
            FROM fundamental.financial_reports
            WHERE publish_date IS NULL OR publish_date < report_date
        """)
        for row in result:
            issues.append(LookaheadIssue(
                severity='ERROR',
                location=f"financial_reports: {row.stock_code} {row.report_date}",
                description="publish_date is missing or earlier than report_date",
                suggestion="Ensure publish_date is set to actual announcement date"
            ))
        return issues

    def _check_ast(self, tree) -> List[LookaheadIssue]:
        """检查代码AST中的危险模式"""
        issues = []
        for node in ast.walk(tree):
            # 检查是否使用了当日收盘价做决策
            if isinstance(node, ast.Subscript):
                if hasattr(node, 'slice') and 'close' in str(node.slice):
                    # 简化检查：如果在信号生成函数中使用了'close'
                    issues.append(LookaheadIssue(
                        severity='WARNING',
                        location=f"Line {node.lineno}",
                        description="Detected usage of 'close' price - verify it's not same-day close",
                        suggestion="Ensure you use previous day's close for signal generation"
                    ))
        return issues


# 回测任务中自动运行检查
def run_backtest_with_checks(task_id: int, strategy_code: str):
    checker = LookaheadChecker()

    # 1. 静态检查
    issues = checker.check_strategy(strategy_code)
    data_issues = checker.check_financial_data_dates(db)
    all_issues = issues + data_issues

    errors = [i for i in all_issues if i.severity == 'ERROR']
    if errors:
        # 记录到数据库
        update_task_lookahead_issues(task_id, all_issues)
        raise LookaheadError(
            f"Found {len(errors)} look-ahead bias errors. "
            f"Fix before running backtest. See task #{task_id} for details."
        )

    warnings = [i for i in all_issues if i.severity == 'WARNING']
    if warnings:
        update_task_lookahead_issues(task_id, warnings)
        # 警告不阻断，但记录在报告中
```

---

## 5. 回测撮合引擎的时间规则

```python
# backend/app/backtest/engine.py

class BacktestEngine:
    """
    标准A股回测撮合规则：
    - 信号产生：基于T日收盘后的数据
    - 订单执行：T+1日开盘集合竞价（默认）或T+1日随机时间（更真实）
    - 成交价格：T+1日开盘价 + 滑点
    """

    COMMISSION_RATE = 0.0003       # 万三手续费（买+卖）
    STAMP_TAX_RATE = 0.0005        # 印花税（卖方单向）
    DEFAULT_SLIPPAGE = 0.002       # 0.2% 滑点

    def execute_order(
        self,
        signal_date: str,          # 信号产生日（T日）
        stock_code: str,
        side: str,
        quantity: int,
    ) -> dict:
        """
        在T+1日执行订单
        """
        execution_date = self.get_next_trading_date(signal_date)  # T+1

        # 检查T+1是否正常交易（是否停牌、涨跌停）
        next_day_kline = self.data.get_kline(stock_code, execution_date)
        if next_day_kline is None:
            return {'status': 'FAILED', 'reason': 'SUSPENDED'}

        # 检查是否涨跌停（A股特有约束）
        limit_up = next_day_kline['prev_close'] * 1.10    # 涨停价
        limit_down = next_day_kline['prev_close'] * 0.90  # 跌停价

        if side == 'BUY' and next_day_kline['open'] >= limit_up:
            return {'status': 'FAILED', 'reason': 'LIMIT_UP'}  # 涨停买不进

        if side == 'SELL' and next_day_kline['open'] <= limit_down:
            return {'status': 'FAILED', 'reason': 'LIMIT_DOWN'}  # 跌停卖不出

        # 成交价 = 开盘价 + 滑点
        slippage_factor = 1 + self.DEFAULT_SLIPPAGE if side == 'BUY' else 1 - self.DEFAULT_SLIPPAGE
        fill_price = next_day_kline['open'] * slippage_factor

        # 计算成本
        amount = fill_price * quantity
        commission = amount * self.COMMISSION_RATE
        stamp_tax = amount * self.STAMP_TAX_RATE if side == 'SELL' else 0
        total_cost = amount + commission + stamp_tax

        return {
            'status': 'FILLED',
            'execution_date': execution_date,
            'fill_price': fill_price,
            'quantity': quantity,
            'amount': amount,
            'commission': commission,
            'stamp_tax': stamp_tax,
            'total_cost': total_cost,
        }
```

---

## 6. 数据时间标签规范

所有存入数据库的数据必须记录两个时间：

```sql
-- 每张数据表都应有这两个字段
data_time       TIMESTAMPTZ  -- 数据所描述的时间点（如K线收盘时间）
available_time  TIMESTAMPTZ  -- 数据实际可用时间（可能晚于data_time）

-- 示例：
-- 2024-01-15 15:00:00 收盘的日K线
-- data_time     = 2024-01-15 15:00:00
-- available_time = 2024-01-15 15:00:00（行情数据实时可用）

-- 2024Q1财报（报告期2024-03-31，但4月28日才发布）
-- data_time     = 2024-03-31
-- available_time = 2024-04-28 19:00:00（财报发布时间）
```

**回测查询模板：**
```python
def get_data_available_at(stock_code: str, query_date: str, data_type: str):
    """获取在 query_date 时刻可用的最新数据"""
    return db.query(f"""
        SELECT * FROM {data_type}
        WHERE stock_code = %s
          AND available_time <= %s    -- 只用已发布的数据
        ORDER BY available_time DESC
        LIMIT 1
    """, [stock_code, query_date])
```

---

## 7. 回测完成后的自查清单

```
□ 策略信号产生时间是否使用了T日收盘后的数据？
□ 订单执行是否在T+1日（或更晚）？
□ 财务数据是否使用了publish_date而非report_date？
□ 技术指标计算是否排除了当日数据？
□ 机器学习模型是否经过Walk-Forward训练？
□ 归一化/标准化是否只用了训练集的统计量？
□ 回测结果的夏普比率是否经过样本外验证？
□ 结果是否包含手续费、印花税、滑点？
□ 是否考虑了涨跌停无法成交的情况？
□ 是否考虑了T+1持仓限制（当日买入不能当日卖出）？
□ LookaheadChecker是否运行通过（无ERROR）？
```
