# ADR-009：A股市场微观规则边界

日期：2026-07-12  
状态：已接受（内部验证）

## 背景

Sprint11 后仍有三个边界缺陷：Worker skip 检测正则包含实际退格字符；BUY/SELL 共用整手向下规范化，无法保留送转形成的零股；可信涨跌停使用比例容差而不是按价格最小变动单位计算正式限制价。

## 测试摘要检测

Backend 和 Worker 共用单引号 PowerShell 正则：

`\b(?:skipped|xfailed|xpassed)\b`

脚本启动时使用模拟摘要自测：`1 skipped`、`1 xfailed`、`1 xpassed` 必须匹配，`19 passed` 不得匹配。同时读取验收脚本原始字节，禁止出现 `0x08`。自测不依赖新增真实 skip、xfail 或 xpass 测试。

## 买入与卖出数量政策

市场规则拆分为：

- `buy_lot_size=100`
- `sell_lot_size=100`
- `odd_lot_sell_policy=FULL_ODD_LOT_ONLY`
- `minimum_price_tick=0.01 CNY`

BUY 政策：

- 少于 100 股直接拒绝。
- 100 股以上但不是整手时，按 `BUY_FLOOR_TO_LOT` 向下规范化。
- requested_quantity、最终 quantity 和 quantity_policy 全部进入信号审计。
- 因此买入 40 股拒绝，买入 140 股明确规范为 100 股。

SELL 政策：

- 不在入队阶段修改请求数量。
- 100 股整数部分可以正常卖出。
- 请求包含零股时，请求零股数必须等于当前全部可用零股余额。
- 140 股可卖 140 股，也可卖 100 股留下 40 股。
- 40 股可一次性卖完，但卖 20 股拒绝。
- 零股余额不得拆分为多笔卖出。
- T+1 仍先约束 available_quantity，再判断零股规则。

独立 Reference 复制同一政策语义，但不调用 BacktestEngine 内部数量校验函数。

## 涨跌停限制价

可信规则新增：

- `minimum_price_tick=0.01`
- `price_rounding_mode=ROUND_HALF_UP`
- `price_limit_formula_version=PREV_CLOSE_RATE_TICK_V1`

计算使用 Decimal：

- limit_up = `(previous_close × (1 + rate)).quantize(0.01, ROUND_HALF_UP)`
- limit_down = `(previous_close × (1 - rate)).quantize(0.01, ROUND_HALF_UP)`

例如前收盘 10.03 元：主板 10% 上下限为 11.03/9.03，创业板 20% 上下限为 12.04/8.02。开盘价精确等于涨停价时拒绝买入，低一个 tick 不误拒；精确等于跌停价时拒绝卖出，高一个 tick 不误拒。

可信 Engine 不再包含 `0.999` 或 `1.001` 模糊比例。无有效前收盘价继续由 Market Rule Gate 拒绝。

## 会计与独立对账

独立会计场景由 12 个扩展为 19 个，新增：140 股全部卖出、140 卖 100 留 40、40 股全部卖出、40 卖 20 拒绝、零股拆分卖出拒绝、买 40 拒绝、买 140 规范为 100。

零股卖出沿用加权平均成本，费用按实际卖出数量计算，逐日对比现金、持仓成本、已实现/未实现盈亏、市值和总资产。Engine 与 Reference 差异必须为 0。

## Hash 与兼容性

lineage 显式保存 buy_lot_size、sell_lot_size、odd_lot_sell_policy、price_tick、price_rounding_mode 和 price_limit_formula_version；对应规则版本也进入 market_rule_versions。

相同规则重复或反序运行 Hash 不变；修改 price tick 或零股政策会改变 Hash。Sprint11.1 产生新结果，不覆盖 Sprint11 结果。

## 发布决定

本变更只修复市场微观边界，没有生成或处理企业行动，没有扩大数据范围。公共 Backtest、Screener、Paper、Live 和 AI Order 发布锁继续关闭。
