# Sprint07 Provider 与复权口径验证报告

日期：2026-07-11

## Adjustment 结论

结论：`raw`，不是 qfq/hfq/unknown。

对 300308.SZ、603986.SH、300502.SZ 分别抽取 2020、2023、2025 全年，将 Sohu OHLC 与腾讯显式 raw/qfq/hfq 响应比较。九组 raw 共同交易日各为 242 或 243 天，Sohu 对 raw 的 OHLC 最大绝对差均为 0.00 CNY；对 qfq 的最大差为 1.09 至 213.084 CNY，对 hfq 的最大差为 260.678 至 4943.252 CNY。容差为 OHLC 绝对差不超过 0.01 CNY。

## 第二 Provider 只读交叉验证

第二 Provider 为新浪财经历史日线，只读、无 fallback、零写入 Store。解析使用固定 AKShare commit `fcdbf25aa864a218c54864c3f6ab6a2ed19cce28` 的公开解码逻辑。

抽查共同日期为 2026-06-01 至 2026-06-05，每只股票 5 天。容差：OHLC 绝对差 ≤0.01 CNY；volume 绝对差 ≤100 股；amount 绝对差 ≤5,000 CNY且相对差 ≤1e-6。

| 股票 | 日期匹配 | OHLC 最大绝对差 | Volume 最大绝对差 | Amount 最大绝对差 | Amount 最大相对差 | 逐字段结果 |
|---|---:|---:|---:|---:|---:|---|
| 300308.SZ | 5/5 | 0.00 CNY | 42 股 | 2,702 CNY | 5.01e-8 | PASS |
| 603986.SH | 5/5 | 0.00 CNY | 48 股 | 1,244 CNY | 5.41e-8 | PASS |
| 300502.SZ | 5/5 | 0.00 CNY | 46 股 | 519 CNY | 1.86e-8 | PASS |

Sohu 每只返回 21 条，新浪每只返回 20 条，20 个日期共同；新浪缺少 2026-06-30。该缺口没有被忽略或自动补齐，整体 `review_required=true`，Store 保持 `research_readiness_status=review_required`。新浪写入 Certified Store 的记录数为 0。

以上结论可由 `scripts/validate_sprint07_providers.py` 重现。
