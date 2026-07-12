# ADR-003：认证历史数据小样本导入

日期：2026-07-11  
状态：已接受

## 决策

Sprint06 只导入 `300308.SZ`、`603986.SH`、`300502.SZ` 在 2026-06-01 至 2026-06-30 的日线。采用固定 `SohuDailyKlineImporter`：`provider=sohu`、`source=sohu_daily_kline`，不允许切换 unknown、Mock、Synthetic 或其他隐式 fallback。

Provider 返回的交易量单位为手、成交额单位为万元；Normalizer 仅按接口公开单位转换为股和元，并统一日线时间为 `15:00:00 Asia/Shanghai`。原始响应保存 SHA-256，batch 保存实际请求端点、抓取时间、优先级和 fallback 状态。

## 为什么先做小样本

旧 `market.klines` 不可追踪，直接导入全市场会扩大污染、冲突和回滚范围。三只股票、一个完整交易月足以验证 fetch、normalize、quality、provenance、batch 和 certification 的最小闭环，同时把写入风险限制在 63 条尝试数据以内。

## 认证与隔离

只有 provider/source 明确、质量 100 分、非 synthetic、无自然日重复、时间为中国时区 15:00、OHLC/成交量/成交额均合法的 batch 才能 certified。任何目标自然日已有 Kline 时整批拒绝，禁止覆盖 legacy 行或更新其 unknown provenance。

旧 unknown 数据永远不自动认证。Synthetic 数据永远不能认证。Provider 请求失败会建立 failed batch；质量或 collision 失败会建立 rejected batch并记录原因。

## 为什么导入后仍不恢复回测和选股

两只股票的一个月样本只能证明数据管线可追踪，不能证明覆盖率、复权一致性、停牌处理或长期数据质量。Backtest 和 Screener 本 Sprint 仅做 certified availability check，不输出收益结论或投资候选。

因此 `CERTIFIED_BACKTEST_EXECUTION_ENABLED=false` 与 `CERTIFIED_SCREENER_OUTPUT_ENABLED=false` 保持默认关闭。底层读取函数可验证 certified 数据可见性，但回测执行入口会明确失败，Screener 业务入口只返回 blocked 空结果。导入 certified 数据本身不构成业务发布授权。

## 回滚

导入写入在单个数据库事务内完成，异常会整体回滚。failed/rejected batch 不删除，作为审计证据保留。若 certified batch 后续发现问题，应通过受控修复任务将其 provenance 降级为 rejected 并记录原因；不得删除、覆盖或改写成其他 provider。

## 扩大范围的前置条件

扩大到全市场前必须完成多批次稳定性、复权口径、交易日历、停牌、企业行动、限速与断点续传验证，并保留同样的 provider metadata、质量门禁和批次级隔离。

## 验证

运行 `powershell -ExecutionPolicy Bypass -File scripts/verify_certified_ingestion_pilot.ps1`。脚本同时调用 Data Certification 与 Execution Safety 验收。
