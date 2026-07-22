# P3-1A Replay Input Profile 与 PIT/Hash 契约草案

状态：Draft，未登记、未激活。
Profile：`P3_REPLAY_DUAL_MA_RAW_OHLCV_V1`。
Policy version：`p3-replay-dual-ma-input-v1`。
唯一用途：`p3_shadow_replay`。

## 输入字段

| 分类 | 字段或规则 |
| --- | --- |
| required | `stock_code`、`trading_date`、`open/high/low/close/volume`、`adjustment=raw`、`market_close_time`、`timezone=Asia/Shanghai`、`provider`、`source`、`batch_id`、`raw_hash`、`quality_status=pass`、`certification_status=certified`、交易日历状态、公司行动状态 |
| required lineage | 不可变 `dataset_id/dataset_version/dataset_hash`、batch Hash、逐行 `row_hash`、`provider_time`、`fetched_at`、`received_at`、`available_at`、`availability_basis`、input snapshot Hash |
| optional | `amount`、`turnover_rate`，不得参与 dual_ma 信号或替代 required 字段 |
| forbidden | `qfq/hfq`、synthetic/unknown、实时行情、执行参考价格、AI 情绪、截止时间后的记录、未许可来源 |

## PIT 与业务时间

1. information cutoff 候选为信号交易日 `15:00:00 Asia/Shanghai`；仅 `available_at <= information_cutoff` 的记录可见。
2. `available_at` 必须有可审计依据，不能由当前时间、导入时间、认证时间或推测值回填。
3. `fetched_at <= received_at`；任一时间倒退、批次冲突、row Hash 不符或未来记录均 fail-closed。
4. 日历必须覆盖完整范围，SH/SZ 一致，`status=confirmed`、来源为交易所且时区为 `Asia/Shanghai`。
5. raw 日线只接受 `verified_no_event` 的公司行动状态；已验证但未按 PIT 处理的行动、`unresolved` 或缺失均 blocked。

## Hash 规则

- dataset Hash：对已批准 dataset manifest、范围、版本与有序样本的规范化内容计算。
- batch Hash：引用既有 `market.data_batches.raw_hash`；缺失即 blocked。
- row Hash：对规范化的 required 行字段及其 batch/provenance 计算；不可用时不得以 `raw_hash` 或认证时间猜测替代。
- input snapshot Hash：按有序 stock/date/row Hash、Profile Hash、策略引用、样本 Hash、cutoff 规范化计算。

## 现有字段复用与缺口

| 能力 | 现有证据 | 结论 |
| --- | --- | --- |
| K 线、provider/source、batch、raw Hash、认证 | `market.certified_klines` | 可复用 |
| batch provider/source/fetch 时间/raw Hash | `market.data_batches` | 可复用，但没有 `received_at` 或 `available_at` |
| 交易日历、公司行动 PIT | `market.trading_calendar`、`market.corporate_actions` | 可复用，仍需逐范围验证 |
| 逐行可得时间、逐行标准化 Hash | 无对应 Certified Store 字段 | 不满足；历史记录保持 null/unverified |

## 最小 Certified Store 追加式迁移草案（非迁移文件）

不得修改或回填 `market.certified_klines` 历史行。若未来获准实施，只新增 append-only sidecar，例如 `market.certified_kline_lineage`，以既有 K 线主键和 `batch_id` 为引用，追加 `provider_time`、`fetched_at`、`received_at`、`available_at`、`availability_basis`、`row_hash` 与验证状态。没有原始证据的历史行不插入 sidecar，读取时应返回 `unavailable/unverified` 并阻断 P3 replay。

## 本轮决议

本草案不登记 Requirement Profile，不改变 Certified Store schema，不授权 Sprint13 replay，也不解除任何实时、策略、样本或运行参数 blocked 状态。
