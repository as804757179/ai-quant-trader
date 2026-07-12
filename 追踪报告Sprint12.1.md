# Sprint12.1 Tracking Report

## 1. 结论

Sprint12.1 验收加固已通过。12 个企业行动场景均真实执行且逐项 PASS；数据库 UPDATE/DELETE 不可变性、版本修订链、官方文件 Hash、完整 Readiness 授权键、Certified raw 前后快照、六个发布锁、既有验收链和全量测试全部通过。

Sprint12 可以正式签收。允许进入后续“受控数据扩展 Sprint”，但不代表公共回测、Screener、Paper 自动交易、Live Trading 或 AI Order 已开放。

## 2. 修改范围

修改：

- `scripts/verify_corporate_action_pit.ps1`
- `backend/app/backtest/corporate_action_validation.py`（仅增强验收场景执行，不改变 Processor 业务语义）

新增：

- `evidence/corporate_actions/cninfo/1225351859_bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d.pdf`
- `evidence/corporate_actions/cninfo/1225351859.json`
- `追踪报告Sprint12.1.md`

未修改 Corporate Action Processor、会计政策、数据库结构、迁移、Certified/legacy K 线、ADR-010、发布锁或交易权限。没有新增策略、AI Agent、净税后红利税或数据范围。

## 3. 固定场景

`actual_scenario_count=12`，`expected_scenario_count=12`，返回映射非空，预期行为名称集合精确匹配，失败场景为空。数量来自实际返回值，不再写死为执行结果；空、少于或多于 12、缺少预期名称、任一 false 都会失败。

| 场景 | 结果 |
|---|---|
| 登记日前无持仓 `no_holding_no_entitlement` | PASS |
| 登记日持有 100 股 `record_date_100_shares` | PASS |
| 登记日前卖出 `sold_before_record_no_entitlement` | PASS |
| 登记日后买入 `bought_after_record_no_entitlement` | PASS |
| 部分持仓权益 `partial_holding` | PASS |
| 100 股转增为 140 股 `one_hundred_becomes_140` | PASS |
| 140 股全部卖出 `sell_140_supported` | PASS |
| 100 股加 40 股分次清仓 `sell_100_then_odd_lot_40_supported` | PASS |
| 现金支付日晚于除权日 `cash_not_before_payment_date` | PASS |
| 股份到账日晚于除权日 `shares_not_before_credit_date` | PASS |
| 公告日前事件不可见 `pre_announcement_hidden` | PASS |
| 事件版本或比例变化改变 Hash `event_version_changes_hash` | PASS |

场景使用固定交易日历、实际 Engine、订单、持仓和企业行动审计执行。Engine/独立 Reference 既有对账差异仍为 0；19 个市场微观与会计场景由串联验收再次确认通过。

## 4. 数据库不可变性和版本链

- `update_blocked=true`，捕获到预期 immutable 数据库异常。
- `delete_blocked=true`，捕获到预期 immutable 数据库异常。
- UPDATE 后原关键字段未变化：是。
- DELETE 后原事件仍存在：是。
- `new_version_inserted=true`：事务内成功插入测试 v2。
- `supersedes_link_valid=true`：v2 指向正式 v1。
- `old_version_preserved=true`：旧版本存在且内容未变化。
- `duplicate_version_blocked=true`：重复版本由唯一约束拒绝。
- `transaction_rolled_back=true`：测试 v2 未留在数据库。

UPDATE、DELETE 和版本链分别在独立事务中实测，不依赖触发器名称静态判断，也未修改正式事件。

## 5. 官方证据 Hash

- 文件：`evidence/corporate_actions/cninfo/1225351859_bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d.pdf`
- 文件大小：138,391 bytes
- 官方 URL：`https://static.cninfo.com.cn/finalpage/2026-06-04/1225351859.PDF`
- 实际文件 SHA-256：`bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d`
- 数据库 `evidence_hash`：`bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d`
- 预期 SHA-256：`bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d`
- 三者一致：是。

验收读取 PDF 实际字节重新计算 Hash，不再只比较硬编码字符串。归档清单记录公告 ID、名称、来源 URL、下载时间、文件大小和实际 Hash。

## 6. Readiness 完整授权键

Gross 授权键：

```text
stock_code=300502.SZ
period=1d
adjustment=raw
research_use_scope=return_backtest
requirement_profile=OHLCV_TOTAL_RETURN_GROSS_V1
date_from=2026-06-01
date_to=2026-06-30
```

结果：

- 300502 Gross Profile：`ready`
- 300502 原 `OHLCV_RETURN_V1`：`rejected`
- 300502 `AMOUNT_FACTOR_V1`：`rejected`
- 300502 `EXECUTION_REFERENCE_V1`：`rejected`
- 净税后 ready Profile 数量：0，Gross 权限未传播。
- 300308 原 `OHLCV_RETURN_V1`：`ready`；Gross Profile 不存在授权。
- 603986 原 `OHLCV_RETURN_V1`：`ready`；Gross Profile 不存在授权。

所有查询均包含股票、period、日期区间、adjustment、用途和 Profile，不使用模糊股票查询。

## 7. Certified raw 不变性

- 行数：21
- before snapshot Hash：`0ee9ebfda2c79ec947716057a056a81e5c9ef3fbc2331ef3cf868280792c870c`
- after snapshot Hash：`0ee9ebfda2c79ec947716057a056a81e5c9ef3fbc2331ef3cf868280792c870c`
- changed rows：0
- raw_hash mismatch：0
- provider/source/batch_id mismatch：0
- OHLCV/amount mismatch：0
- adjustment 全部为 raw：是

快照按 `stock_code, period, trading_date, adjustment` 排序，Decimal 和日期规范化后生成 deterministic SHA-256。企业行动场景执行前后再次读取，未发现平滑、复权、覆盖、重写或会计结果写回 K 线。

## 8. 发布锁与业务输出

以下六个开关均为 `false`：

- `CERTIFIED_BACKTEST_EXECUTION_ENABLED`
- `CERTIFIED_SCREENER_OUTPUT_ENABLED`
- `TRADING_EXECUTION_ENABLED`
- `LIVE_TRADING_ENABLED`
- `AI_ORDER_ENABLED`
- `ALLOW_SCHEDULED_ORDER`

订单数 before=7、after=7，本验收创建订单数=0。没有调用公共 Backtest、没有输出 Screener 候选、没有启用 Paper 自动交易或 Live Trading。Execution Safety 串联验收确认 AI 与 Celery 仍不能创建订单。

## 9. 测试与验收

- Corporate Action PIT：PASS
- Data Certification：PASS
- Execution Safety：PASS
- Research Readiness：PASS
- Field-Level Readiness：PASS
- Backtest Integrity：PASS
- Market Rules：PASS
- Market Microstructure Boundaries：PASS
- 19 个市场微观与会计场景：PASS，差异 0
- 12 个企业行动场景：PASS
- Backend：192 passed，0 failed
- Worker：19 passed，0 failed
- skipped=0，xfailed=0，xpassed=0

Backend 和 Worker 各保留 1 条既有异步 `RuntimeWarning`，未隐藏、未 skip，列为 P2。

## 10. 剩余问题和准入

- P0：无。
- P1：净税后红利税仍未实现，必须继续 blocked；未来每个企业行动仍需同等级官方证据和 PIT 验收。
- P2：两条既有异步 mock/连接清理 RuntimeWarning。

Sprint12 正式签收：是。

允许进入受控数据扩展 Sprint：是，但必须继续保持当前发布锁，不得将本次 Gross scoped readiness 传播到其他股票、区间、Profile 或执行用途。
