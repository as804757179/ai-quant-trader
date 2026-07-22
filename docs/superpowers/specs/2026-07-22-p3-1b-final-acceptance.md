# P3-1B 内部准入治理最终验收

状态：通过。日期：2026-07-22。

本验收仅覆盖策略生命周期治理基础、Certified K 线 lineage sidecar、draft Profile 与只读状态接口；不代表策略激活、Profile 批准、Sprint13 使用、P3 replay/realtime 启动或 P3-1 完成。

## 数据库迁移

- 权威 PostgreSQL：`127.0.0.1:5432/quant_trader`，PostgreSQL 17.10，升级前 `042`、升级后 `045`。
- 隔离方式：同一实例模板克隆 `quant_trader_p31b_validation_20260722_135000`，未再尝试 PG17→PG15 恢复。
- 隔离命令结果：`alembic upgrade 045`、`alembic downgrade 042`、再次 `alembic upgrade 045` 均退出码 0。
- 新对象：`strategy.strategy_version_validity_events`、`market.certified_kline_lineage`；Profile `P3_REPLAY_DUAL_MA_RAW_OHLCV_V1` 为 `draft`、`enabled=false`。
- 升级前备份：`C:\Users\as804\AppData\Local\Temp\ai-quant-p3-1b-20260722-134600\quant_trader-042-authority-before-045.dump`；512 个归档对象。

## 验证结果

- 生命周期合法写入、重复有效时点和无效有效期约束已在隔离事务中验证；事务回滚，未产生事实记录。
- lineage 合法写入、verified 缺少 `available_at` 的检查约束与非法 Hash 拒绝已验证；事务回滚。
- row Hash 定向测试通过；受保护字段变化会改变 Hash。
- 现有 `dual_ma` 主体保持 inactive，head 的 `active_version_id` 保持 `NULL`；未新增 activated、revoked 或 expired 事实。
- 三个新增接口均为 GET，账本 OpenAPI 基线已更新；Legacy L0 通过。

## 测试

- P3 定向：`scripts\verify_p3_shadow_infrastructure.ps1`，26 passed，退出码 0。
- Legacy L0：`scripts\verify_legacy_api_l0.ps1`，6 passed，退出码 0。
- 完整回归：`python -m unittest discover -s tests -p 'test_*.py'`，331 项，330 passed、0 failed、1 error，退出码 1。
- 唯一 error：`test_strategy_runtime_hash_is_stable_and_declares_data_profile`，`build_strategy_runtime_status() missing 1 required positional argument: 'items'`；分类 `PRE_EXISTING_NOT_INTRODUCED_BY_P3_0`。

## 保持阻断

`P3_STRATEGY_VERSION_UNCONFIRMED`、`P3_REALTIME_DATA_NOT_APPROVED` 与 `realtime_data_approved=false` 保持。正式样本、information cutoff、运行时间和稳定周期未冻结；P3 replay/realtime 未启动。
