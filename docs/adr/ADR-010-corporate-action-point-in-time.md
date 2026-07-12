# ADR-010：企业行动 Point-in-Time 与毛总收益会计

## 决策

仅对 `300502.SZ`、2026-06、raw 数据建立 `OHLCV_TOTAL_RETURN_GROSS_V1`。事件证据采用巨潮资讯官方《2025 年年度权益分派实施公告》（公告 ID `1225351859`）：公告日 2026-06-04、登记日 2026-06-10、除权除息日/现金支付日/转增股份到账日均为 2026-06-11，每 10 股派 10 元并转增 4 股。证据 PDF SHA-256 为 `bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d`。

事件写入 `market.corporate_actions`，UPDATE/DELETE 由数据库触发器拒绝；修订必须新增 `event_version` 并通过 `supersedes_action_id` 关联。来源、关键日期或比例不完整时 fail closed。

## Point-in-Time 边界

事件查询以 `announcement_date <= as_of` 为硬边界。公告日前策略上下文不可见。登记日日终合法持仓形成不可变权益快照；股份和现金只在官方证明的到账/支付日入账，绝不以除权日推断未知日期。raw K 线、provider、batch 与 raw_hash 不修改。

每日顺序固定为：应用当日企业行动、释放 T+1、执行订单、捕获登记日权益、收盘估值、生成信号、日终审计。该顺序、事件版本、证据 Hash、处理器版本与政策均进入 result lineage/hash 输入。

## 会计政策

采用 `GROSS_PRETAX_TOTAL_RETURN_V1`。登记日持有 100 股产生 40 股转增和 100 元毛现金分红；转增不增加总持仓成本，平均成本按新股数重算。现金分红单列 `corporate_action_income`，不计作交易 realized PnL。投资者持有期相关红利税未实现，所有净税后收益 Profile 继续 blocked。

转增形成的零股沿用 ADR-009：140 股可全部卖出，或先卖 100 股后将剩余 40 股一次清仓，零股不可拆分。

## 发布边界

旧 `OHLCV_RETURN_V1` 对 300502 仍为 rejected；只有 Gross Total Return scoped review 可以 ready。公共 Backtest、Screener、Paper 自动交易、Live 与 AI Order 开关继续关闭。本决策只验证数据和会计正确性，不产生策略盈利结论。
