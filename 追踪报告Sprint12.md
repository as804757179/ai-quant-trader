# Sprint12 Tracking Report

## 1. 本次任务与结论

Sprint12 已完成企业行动 Point-in-Time、不可变事件存储、毛分红总收益会计、独立 Reference 对账、字段级 Readiness 和完整回归验收。范围严格限定为 `300502.SZ`、2026-06-01 至 2026-06-30、`period=1d`、`adjustment=raw`。未扩大数据、未修改 Certified Store 原始 K 线、未运行策略盈利验证，也未开放任何发布或交易权限。

最终结论：`return_backtest + OHLCV_TOTAL_RETURN_GROSS_V1 = ready`；原 `OHLCV_RETURN_V1` 仍为 `rejected`，净税后收益、`AMOUNT_FACTOR_V1`、`EXECUTION_REFERENCE_V1` 与公共回测均继续阻止。

## 2. 官方事件证据

- 来源：巨潮资讯（CNINFO）官方《2025 年年度权益分派实施公告》，公告 ID `1225351859`
- 官方 PDF：<https://static.cninfo.com.cn/finalpage/2026-06-04/1225351859.PDF>
- 证据 SHA-256：`bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d`
- 公告日：2026-06-04
- 股权登记日：2026-06-10
- 除权除息日：2026-06-11
- 现金支付日：2026-06-11
- 转增股份到账/上市日：2026-06-11
- 权益比例：每 10 股派发毛现金 10 元并转增 4 股

事件保存于 `market.corporate_actions`。表 Owner 为 `quant_admin`；UPDATE/DELETE 由数据库触发器拒绝，修订必须新增版本，不能覆盖原事件。

## 3. Point-in-Time 与会计

- 查询硬边界为 `announcement_date <= as_of`，2026-06-03 看不到事件，2026-06-04 才可见。
- 登记日日终合法持仓形成权益快照；除权日前不改变股份、现金或成本。
- 股份仅在 `share_credit_date` 入账，现金仅在 `cash_payment_date` 入账，不以除权日替代未知日期。
- 每日顺序固定为：企业行动入账 → T+1 释放 → 订单执行 → 登记日权益快照 → 收盘估值 → 信号生成 → 日终审计。
- 100 股产生 40 股转增与 100 元毛现金分红；转增后总成本不变，平均成本由 100 股成本摊至 140 股。
- 分红单列 `corporate_action_income`，不伪装成交易 `realized_pnl`。
- `GROSS_PRETAX_TOTAL_RETURN_V1` 不实现投资者持有期红利税，净税后口径明确 blocked。
- raw K 线、provider、batch_id、raw_hash 均未修改。

## 4. Engine / Reference 与 Hash

独立 Decimal Reference 未调用 Engine 企业行动处理函数。登记日前无持仓、登记日持有 100 股、登记日前卖出、登记日后买入、部分持仓、100→140、140 全卖、100+40 分次清仓、延迟现金、延迟股份、公告日前不可见、事件版本变化等 12 个固定场景全部通过；其中企业行动核心持仓逐日对账，以及复用 Sprint11.1 独立 Reference 的 140 股卖出会计对账，差异均为 0。逐日审计覆盖 `total_qty / available_qty / avg_cost / total_cost / cash / corporate_action_income / realized/unrealized pnl / market_value / total_assets`。

事件版本、证据 Hash、处理器版本、毛总收益政策和每日处理顺序进入 lineage/hash；相同输入 Hash 稳定，事件版本或比例变化会改变 Hash。Sprint11.1 无企业行动输入的既有结果 Hash 保持 `8374c619f0be8a2b917999c6c990c789a4098d06df652652276b3749d683c670`，未被静默覆盖。

## 5. 文件变更

新增：

- `backend/alembic/versions/012_corporate_action_pit.py`
- `backend/app/backtest/corporate_actions.py`
- `backend/app/backtest/corporate_action_validation.py`
- `backend/tests/test_corporate_action_pit.py`
- `scripts/verify_corporate_action_pit.ps1`
- `docs/adr/ADR-010-corporate-action-point-in-time.md`
- `追踪报告Sprint12.md`

修改：

- `backend/app/backtest/engine.py`
- `backend/app/data/research_profiles.py`
- `backend/app/data/certified_kline_repository.py`
- `scripts/verify_local_env.ps1`
- `scripts/verify_research_readiness.ps1`
- `scripts/verify_field_level_readiness.ps1`
- `README.md`

## 6. 验收结果

- Alembic：`012`，迁移成功
- `scripts/verify_corporate_action_pit.ps1`：PASS
- 全部既有验收脚本：PASS
- Backend：192 passed，0 failed，0 skipped，0 xfailed，0 xpassed
- Worker：19 passed，0 failed，0 skipped，0 xfailed，0 xpassed
- Engine / Reference：差异 0
- 所有发布与交易锁：保持 false

测试存在 2 条既有 `RuntimeWarning`（异步 mock 清理），不影响测试结果，列为 P2，不在本 Sprint 越界修复。

## 7. 剩余优先级与下一步

- P0：无。
- P1：净税后红利税仍未实现，任何净收益 Profile 必须继续 blocked；扩大样本前仍需逐事件取得同等级官方证据。
- P2：Backend/Worker 各有一条既有异步 mock `RuntimeWarning`，应在后续测试基础设施 Sprint 处理。

允许进入“受控数据扩展 Sprint”，但仅指扩展已认证、已审核的数据样本；不代表允许公共回测、Screener、Paper 自动交易、Live Trading 或 AI Order。扩展时必须继续逐事件执行官方证据、PIT、企业行动会计和 scoped Readiness 验收。
