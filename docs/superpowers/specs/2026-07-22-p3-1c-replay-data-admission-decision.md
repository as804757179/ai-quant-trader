# P3-1C Replay 数据准入与参数冻结决策单

状态：已归档；未冻结。

日期：2026-07-22

## 已确认的候选项

以下内容仅是后续冻结候选，不构成正式样本、Profile、数据集或运行参数授权：

- Sprint13 十股名单及既有顺序。
- 候选 `sample_version`：`p3-replay-sprint13-10-candidate-v1`。
- 候选 `sample_hash`：`f5c702b8c04ecc9346cbc0786a5e87ebe962a5162c4f0c21238ff979fa274845`。
- 候选 information cutoff：`15:00:00 Asia/Shanghai`。
- 候选最小历史窗口：21 个确认交易日。
- 候选完整性规则：全样本 100% 完整。
- 候选确定性规则：相同不可变输入重复 3 次，结果 Hash 一致。
- 既有决策去重、中断恢复及 fail-closed 契约。

Sprint13 名单仅复用成员和顺序，不继承其 Provider、许可、工程验证或投资样本语义。来源：[Sprint13 manifest](../../../config/datasets/sprint13_universe.yaml)。

## Replay 数据准入结论

当前不存在合格的 P3 replay 数据集，P3 replay 保持 blocked。Sprint13 数据不可用于正式 replay。

现有数据的可确认事实如下：

- manifest 为 `sprint13-controlled-certified-v1`，且其用途为工程验证，不是投资样本授权。
- manifest Hash 为 `d4936757c7c1a669e82ad13f0a5e8593e8f844549478c6f8181f29301ccc9b25`。
- 目标覆盖期为 `2025-07-01` 至 `2026-06-30`；十股应有 2,420 个交易日行，当前仅有 2,414 行。
- `688981.SH` 缺少 2025-09-01 至 2025-09-08 之间的 6 个交易日行。
- 现有 Sprint13 记录仍为 `review_required`。
- 当前不存在逐行 verified lineage、可审计 `available_at`、可复算 `row_hash` 或公司行动 PIT 证据。
- 当前未找到 Sohu 或 Tencent 对自动化处理、本地存储、二次处理和 replay 使用的许可证据。

## Profile 决定

`P3_REPLAY_DUAL_MA_RAW_OHLCV_V1` 与 policy `p3-replay-dual-ma-input-v1` 保持：

- `status=draft`
- `enabled=false`
- `runner_usable=false`

本轮不批准、启用或登记新的 Profile 版本。候选数据集未满足 Profile 所要求的 raw-only、PIT、`available_at`、dataset/batch/row/input snapshot Hash、交易日历和公司行动证据条件。

## 保持 blocked 的状态

- `P3_PROVIDER_LICENSE_UNCONFIRMED`
- `P3_INPUT_LINEAGE_UNVERIFIED`
- `P3_INPUT_AVAILABLE_AT_MISSING`
- `P3_INPUT_HASH_MISSING`
- `P3_INPUT_CORPORATE_ACTION_UNVERIFIED`
- `P3_REALTIME_DATA_NOT_APPROVED`
- `realtime_data_approved=false`

同时保持：P3 replay/realtime 未启动、正式样本未冻结、Profile 未批准、覆盖区间和运行参数未冻结，六个发布和交易锁均为 `false`。

## 后续准入材料

在单独冻结样本、Profile 或 replay 参数前，必须提供并验证：

1. 对实际使用主体有效的 Provider 许可或可验证条款版本，且明确覆盖自动化处理、本地存储、二次处理及历史 replay。
2. Provider、source、dataset version、许可版本、生效时间和 `license_evidence_ref`。
3. 不可变 dataset manifest、dataset snapshot Hash、batch/raw Hash 的对应关系。
4. 每行原始 evidence、非推测的 `available_at` 和可复算 `row_hash`。
5. 全覆盖交易日历及公司行动或无事件的 PIT 证据。
6. 十股完整覆盖所缺的 6 行数据及其同等许可、PIT 和 Hash 证据。

不得以公开、免费、已有缓存、导入时间、认证时间或技术可调用性替代上述许可和证据。

## 非授权边界

本归档不授权使用 Sprint13 数据，不启动 P3 replay/realtime，不创建订单，不调用执行服务，不写入资金或持仓，不修改 dual_ma v5，也不改变任何发布或交易锁。
