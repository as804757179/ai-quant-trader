# P4-1B synthetic/test-only 账务工程验证决策记录

状态：`test_only_draft_not_phase_d`

日期：2026-07-22

## 1. 运行范围与启动方式

| 项目 | 选择 | 依据与版本 | 选择理由 | 回滚方式 |
| --- | --- | --- | --- | --- |
| 环境 | 仅 `local_development` | `APP_ENV`；`p4-synthetic-paper-rules-v1` | 不向生产、共享环境或真实资金环境传播测试例外。 | 删除本地测试输出；不产生持久化业务事实。 |
| 启动 | 人工显式命令并要求 `--confirm-test-only` | 现有 `backend/scripts/verify_synthetic_shadow_replay.py` 的确认模式 | 禁止调度、API 和自动启动。 | 停止命令即可；不需要数据恢复。 |
| 输入 | `synthetic/test-only` fixture | `TestOnlyFixtureProvider`、`p3-shadow-test-fixture-v1` | 复用已验证的 Hash、lineage、`available_at` 和无网络能力。 | fixture 不写入 Certified Store 或正式数据表。 |

## 2. 测试账户与重置

| 项目 | 选择 | 依据与版本 | 选择理由 | 回滚方式 |
| --- | --- | --- | --- | --- |
| 账户 | `test:p4-synthetic-paper-account-v1` | `p4-synthetic-paper-rules-v1` | 明确 test-only 命名，避免与现有 simulation、paper、live 账户混淆。 | 每次命令和测试均新建内存账本；进程退出即清除。 |
| 币种 | `CNY` | `p4-synthetic-paper-rules-v1` | 仅为确定性金额计算单位，不代表正式 Paper 账户币种。 | 无持久化数据。 |
| 初始现金 | `100000.00` | `p4-synthetic-paper-rules-v1` | 足以覆盖最小成交、撤单和资金限制测试。 | 每次重置为固定值。 |

## 3. synthetic execution reference

| 项目 | 选择 | 依据与版本 | 选择理由 | 回滚方式 |
| --- | --- | --- | --- | --- |
| 执行参考 | 已验证可见 fixture 最后一行 close | `TestOnlyFixtureProvider`、`p3-shadow-test-fixture-v1` | 复用逐行 `available_at`、lineage、row Hash、manifest Hash 与未来数据隔离。 | 非 synthetic、Hash/lineage/PIT 异常或未来数据一律 fail-closed。 |
| 成交价 | 买入 `close + 0.01`，卖出 `close - 0.01` | `p4-synthetic-paper-rules-v1` | 最小确定性滑点模型，仅用于工程验证。 | 不写入正式费用或市场规则配置。 |

## 4. 测试订单、审批与账务规则

| 项目 | 选择 | 依据与版本 | 选择理由 | 回滚方式 |
| --- | --- | --- | --- | --- |
| 订单 | 仅 test-only LIMIT BUY/SELL；`limit_price` 必填 | `p4-synthetic-paper-rules-v1` | 覆盖成交、未成交、撤单、资金和可用数量边界。 | 无 API、任务或数据库入口。 |
| 提交与审批 | 必须先提交、再单独审批或拒绝，生成两条独立审计事件 | P3-1B local-development 单人例外；`p4-synthetic-paper-rules-v1` | 同一测试人工主体仅可在 local-development 显式使用 `single_operator_exception=true`，不得自动提交或自动审批。 | 不创建或修改正式 principal、审批或策略事实。 |
| 资金冻结 | 买单批准接受时冻结 `limit_price * quantity + 预估费用`；未成交撤单后释放 | `p4-synthetic-paper-rules-v1` | 可验证余额限制与资金释放。 | 内存账本重置。 |
| 持仓可用 | 卖单只能使用 `available_quantity`；买入成交后为 T+1 不可用，显式 test-only 结算事件后可用 | `p4-synthetic-paper-rules-v1` | 覆盖可用数量和 T+1 工程边界，不代表真实 A 股规则版本。 | 内存账本重置。 |
| 费用 | 成交金额的 `0.001`，最小 `0.01`，四舍五入至分 | `p4-synthetic-paper-rules-v1` | 最小且可复算的费用记账，不代表券商佣金、印花税或交易所费用。 | 不写入正式费率配置。 |

## 5. 账务不变量、对账与验收

| 项目 | 选择 | 依据与版本 | 选择理由 | 回滚方式 |
| --- | --- | --- | --- | --- |
| 事实链 | 仅内存追加式事件；从事件重建订单、资金冻结、现金、持仓和可用数量 | P4-1A 差距审计；`p4-synthetic-paper-rules-v1` | 当前目标是工程验证；避免把 test-only 事实写入正式 `trade` 表。 | 进程退出即清除；未新增迁移。 |
| Hash | 每个事件保存 payload Hash，运行保存输入、规则、事件流和输出 Hash | 现有 P3 SHA-256 约定 | 支持三次确定性重复与审计比较。 | Hash 不符立即失败，不回填。 |
| 对账 | 独立重建事件流并与运行快照逐字段比较 | `p4-synthetic-paper-rules-v1` | 差异必须 blocked，不允许静默修正。 | 不修改快照或事件。 |
| 验收 | 三次同输入 Hash 一致；成交/未成交/撤单/费用/限制/异常全部覆盖 | P4-1B 用户验收要求 | 证明确定性和 fail-closed 边界。 | 失败即非通过。 |

## 6. 固定安全边界

1. 本记录不是正式 Phase D 冻结，也不是 Paper 发布、真实市场验证、模拟实盘或阶段 D 通过。
2. 不接入 Sprint13、外部 Provider 或真实行情；非 synthetic 输入被拒绝，且不会调用订单、执行、资金或持仓服务。
3. 正式 P3 replay 继续 `blocked/deferred`，P3 Profile 保持 `draft/disabled`，P4 正式写入保持未授权。
4. 六个发布与交易锁必须始终为 `false`。任何锁变化、非本地环境、时间/Hash/lineage 异常、账务不变量异常或对账差异均 fail-closed。
