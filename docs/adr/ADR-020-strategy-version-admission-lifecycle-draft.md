# ADR-020：策略版本准入生命周期补全草案

状态：Draft，未批准、未实施。  
日期：2026-07-22。

## 已确认缺口

- `strategy.strategy_versions` 是不可变参数快照，`strategy_version_approvals` 仅表达 `pending/approved/rejected`。
- `strategy_version_heads` 对单一 `strategy_id` 只能保存一个 head，但 `strategy.strategies.is_active` 未进入 `StrategyVersionService` 的准入判定；当前提交路径默认写入 `false`。
- 当前 schema 没有撤销时间、撤销原因、有效起止时间或等价的 append-only 生命周期记录。因此不能无歧义证明 version 未撤销、未过期。
- 权威本地库当前的 `dual_ma` head 为 `active_version_id=NULL`；本草案不修复或修改既有四条版本记录。

## 拟议状态机

策略主体：`inactive -> active -> inactive`。主体 inactive 时不得解析可用策略快照。  
版本：`submitted -> approved -> active -> (revoked | expired)`；`rejected` 为终态。  
只有同时满足“唯一 active 主体、唯一 active head、approved、enabled、参数和双 Hash 有效、有效期覆盖运行时点、未撤销”的版本，才可被未来准入服务解析。

## 最小追加式迁移草案（非迁移文件）

1. 新建 append-only `strategy.strategy_version_validity_events`，记录 `event_id`、`version_id`、`event_type`（`activated/revoked/expired`）、`effective_at`、`valid_until`、`reason`、`actor_principal_id`、`created_at`。
2. 为 `event_type`、时间范围、撤销原因与 actor 建立检查约束；禁止 UPDATE/DELETE。
3. 为 `strategy.strategies(strategy_type)` 建立“active 主体唯一”部分唯一索引，或在同一事务的准入查询中拒绝同类型多主体。二者择一，实施前必须确认。
4. 不回填既有策略、审批、head 或 event；既有数据保持 `unconfirmed`，不能因迁移获得 active、未撤销或未过期结论。

## 兼容与回滚

- 兼容期内仅新增只读生命周期状态；现有 API 不自动绑定或激活任何版本。
- 准入服务在新证据缺失时返回明确 blocked，而非退回目录默认参数。
- 回滚只移除新建 event 表、索引、触发器及其新代码；不得删除或重写既有五张策略治理表中的记录。

## 本轮决议

本草案不授权迁移、Profile 登记、策略激活、审批或 P3 replay。`P3_STRATEGY_VERSION_UNCONFIRMED` 保持 blocked，待用户单独确认治理迁移方案后再实施。
