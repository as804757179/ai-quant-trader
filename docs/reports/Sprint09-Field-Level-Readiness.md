# Sprint09 Field-Level Readiness Report

日期：2026-07-11

## Profile 字段矩阵

| Profile | 必需字段 | 当前未解决字段 | 状态结论 |
|---|---|---|---|
| OHLCV_RETURN_V1 | trading_date、OHLCV、adjustment、trading_calendar、corporate_action_status | amount 仅为非必需字段 | 300308/603986 scoped ready；300502 rejected |
| AMOUNT_FACTOR_V1 | OHLCV_RETURN_V1 + amount、amount_unit、amount_provider_validation | amount、amount_provider_validation | 无 ready |
| EXECUTION_REFERENCE_V1 | quote_time、price_applicability、explicit_authorization、execution_gate | 时效、适用性、授权未满足 | 全部 rejected |

## 三只股票结果

| 股票 | OHLCV return | Amount factor | Execution reference | 主要原因 |
|---|---|---|---|---|
| 300308.SZ | ready | review_required | rejected | OHLCV 完整；amount 未独立验证；无执行时效授权 |
| 603986.SH | ready | review_required | rejected | OHLCV 完整；amount 未独立验证；无执行时效授权 |
| 300502.SZ | rejected | rejected | rejected | 6 月 11 日派现及转增未做 point-in-time 收益调整 |

Validated OHLCV 字段包括 trading_date、open、high、low、close、volume、raw adjustment、交易日历和企业行动审核状态。amount unresolved 仍明确保留，没有被标记为 validated。

Certified Store 的 63 条行状态仍全部是 review_required；ready 只存在于精确 Profile-scoped review，不会传播到 amount、execution、Screener 发布或交易权限。
