# ADR-007：Backtest Integrity 与执行模型

日期：2026-07-12  
状态：已接受（仅内部验证）

## 背景

Sprint09 只为 300308.SZ、603986.SH 在 2026-06-01 至 2026-06-30 的 raw 日线授予了 `return_backtest + OHLCV_RETURN_V1` scoped ready。本决策验证回测计算是否正确，不评价策略盈利能力，也不开放公共回测入口。

## 数据边界

内部验证必须通过 `CertifiedKlineRepository.get_bars_for_profile()` 读取数据，并显式声明股票、日期、adjustment、用途、Profile 和 required_fields。该读取只选择 OHLCV 与必要血缘字段，不选择 amount 或 turnover_rate，不查询 legacy 表。300502.SZ 继续被 Readiness Gate 拒绝。

## 信号与成交时序

- 第 t 日信号只允许读取 `date <= t` 的 K 线。
- `information_cutoff` 等于 signal_date。
- 收盘后信号最早在下一交易日成交。
- 固定执行价格模型为下一交易日 open。
- 指标窗口不足时不产生信号。
- 逐日记录信号、成交、现金、持仓和资产审计。

## A 股交易约束

- 买卖数量按 100 股整手向下规范化。
- 资金不足、超持仓、停牌或无合法成交量时拒绝成交。
- 买入股份当日不可用，下一交易日释放。
- 涨跌停比例按代码板块规则判断；ST 使用 5%。
- 当前模型包含佣金、卖出印花税、滑点和最低佣金。
- 当前模型未实现过户费。该缺口必须明确披露，不得将 0 伪装为已实现费用；扩大样本或用于正式研究前应补齐。

## 独立参考计算

验证入口包含一个基于 Decimal 的最小参考实现，不调用 BacktestEngine 的成交、资金、持仓、费用或指标函数。固定会计基准的信号日期、成交日期、价格、数量、逐日现金、持仓、资产、最终资产与指标必须逐项一致。金额统一比较到小数点后 8 位，交易记录使用引擎已声明的价格 4 位、金额与费用 2 位规则。

## 指标公式

- total_return：`final_assets / initial_cash - 1`
- max_drawdown：每日资产相对历史峰值的最大跌幅绝对值
- win_rate：已闭合交易中净利润大于 0 的比例
- profit_factor：总盈利 / 总亏损绝对值；无交易返回 0，有盈利且无亏损返回 null
- sharpe：日收益均值 / 日收益总体标准差 × `sqrt(242)`；无样本或零标准差返回 0
- turnover：成交金额合计 / 平均每日资产
- fees：佣金与印花税分别汇总，滑点单列；过户费标记未实现

21 个交易日样本的所有指标都必须附带 `validation_only=true`、`not_for_investment=true`、`sample_size_insufficient=true`，不得用于策略评价。

## 未来函数防护与确定性

dual_ma 仅通过截至信号日的 close 序列计算；测试会修改未来 K 线并确认当前信号不变。结果哈希排除 generated_at，纳入数据集 hash、raw_hash、batch、readiness review、策略版本、参数 hash、引擎版本、执行模型和费用 hash。同输入连续三次以及反转股票输入顺序必须产生相同 result_hash。

## 发布决定

`CERTIFIED_BACKTEST_EXECUTION_ENABLED`、`CERTIFIED_SCREENER_OUTPUT_ENABLED`、`TRADING_EXECUTION_ENABLED`、`LIVE_TRADING_ENABLED`、`AI_ORDER_ENABLED` 继续为 false。内部验证成功不构成公共回测、选股、模拟成交或实盘授权。
