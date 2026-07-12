# Sprint13 Provider Validation

每只股票按月抽取一个共同交易日，共 120 个样本。Sohu 与腾讯 raw 的 open/high/low/close 绝对差容差为 0.01 CNY；120 个样本全部 PASS。腾讯写入 Certified Store 数量为 0，无运行时 fallback。

腾讯该端点在本实现中未作为可靠 amount 独立证据，因此 amount 明确 unresolved，`AMOUNT_FACTOR_V1` 未放行。volume/amount 未以未经证明的单位作跨源一致性结论。
