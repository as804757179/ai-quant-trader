# ADR-001: Historical Data Certification

## Status

Accepted.

## Decision

Historical K-lines require a one-to-one provenance sidecar and batch record. Existing K-lines are migrated as `source=unknown` and `certification_status=uncertified`; they are never auto-certified. Synthetic data is permanently identifiable and cannot be certified.

Only certified, non-synthetic, known-source, quality-passed K-lines may be read by Backtest, Screener, or Simulation's K-line fallback. AI contexts label uncertified history and force a non-trading HOLD result.

## Rationale

The legacy `market.klines` table has no source or batch lineage and contains duplicate natural days, timestamp inconsistency, missing amount/turnover values, and Synthetic contamination risk. A separate table avoids deleting or rewriting legacy price records while allowing future certified ingestion.

## Consequences

No existing historical K-line is valid for real backtest or real screening until a provider-tagged batch passes quality validation and certification. Synthetic data is Smoke Test only and must display that it is not investment evidence.

## Future Provider Import

Provider importers must create a batch, validate rows, write provenance, then explicitly certify the batch. Unknown provider responses remain quarantined and cannot enter a trading-result path.

## Verification

Run `powershell -ExecutionPolicy Bypass -File scripts/verify_data_certification.ps1`.
The script verifies the sidecar tables, one-to-one provenance coverage, and that unknown or synthetic records are not certified. Until provider-tagged certified batches exist, real backtest and real screening are intentionally rejected.

## Regression Assertions

未认证、unknown 或 synthetic 历史数据进入 AI 展示上下文时，响应必须为 `HOLD`、`tradable=false`、`order_created=false`，并携带“当前历史数据未认证，仅可用于展示，不可用于交易判断”警告。没有 certified Kline 时，Screener 返回空候选和排除原因是门禁正确生效，不应被测试视为失败。
