# ADR-004：Certified Kline Store 与数据语义

日期：2026-07-11  
状态：已接受

## 背景与决策

`market.klines` 同时包含 legacy、unknown 与 Sprint06 认证记录，legacy 同自然日记录会阻塞新 Provider 数据，调用方也容易遗漏 provenance 过滤。新增 `market.certified_klines` 作为唯一认证历史 K 线读取源；`market.klines` 定义为 legacy/raw/uncertified 审计表。

Certified Store 主键是 `(stock_code, period, trading_date, adjustment)`。数据库约束直接拒绝 unknown、synthetic、非 pass 质量、非 certified 状态和 unknown adjustment。所有研究读取必须通过 `CertifiedKlineRepository`，显式指定 raw/qfq/hfq；无数据或非 research-ready 时关闭失败，不回退 legacy。

## 迁移策略

Alembic 009 在单一事务中创建 Store、索引和 2026-06 沪深交易日历，仅迁移 Sprint06 中 provider=`sohu`、source=`sohu_daily_kline`、quality=`pass`、certification=`certified`、非 synthetic 的 42 条记录。迁移保留 OHLCV、amount、turnover、batch、raw_hash、认证时间和 importer 版本，legacy 不删除、不更新。

603986.SH 由 Sprint07 专用写入器直接写 Store，legacy 同日记录不参与唯一性判断，也不被覆盖。失败 batch 只保留审计原因，不向 Store 写 rejected 数据。

## 数据语义契约

- 代码为六位代码加 `.SZ` / `.SH`。
- 日线使用真实 trading_date、15:00:00、Asia/Shanghai。
- 价格与成交额币种为 CNY，成交量单位为 share。
- Sohu 成交量从手乘 100 转为股；成交额从万元乘 10,000 转为元。已是 share/CNY 时不再转换，未知单位拒绝。
- 每行记录 importer、normalizer、schema 版本。

## 复权口径证据

没有根据价格走势猜测。可复现脚本将三只股票在 2020、2023、2025 三个完整年度的 Sohu OHLC，与腾讯接口显式返回的 raw、qfq、hfq 分别比较。九组 Sohu/raw 共同交易日为 242 或 243 天，OHLC 最大绝对差均为 0；qfq/hfq 均出现明显非零差异。因此本批 Sohu 响应认证为 `adjustment=raw`。证据脚本为 `scripts/validate_sprint07_providers.py`。

## 交易日历与企业行动

交易日不能仅用 weekday 判断。Sprint07 日历记录沪深交易所来源，明确 2026-06-19 端午节休市。Provider 出现非交易日或缺少已确认交易日时整批拒绝，不补假 K 线。

当前没有完整企业行动引擎。raw/qfq/hfq 不混用，价格跳变不自动删除或修改。全部 Sprint07 数据暂标 `research_readiness_status=review_required`，不能被 Backtest readiness gate 放行。

## 第二 Provider

新浪历史日线只用于只读交叉验证，禁止写 Store、禁止 fallback。每只股票抽查 5 个共同交易日，OHLC、volume、amount 均在容差内；新浪响应缺少 2026-06-30，而 Sohu 有该日期，因此差异被保留并使整体维持 `review_required`。

## 发布锁与回滚

`CERTIFIED_BACKTEST_EXECUTION_ENABLED`、`CERTIFIED_SCREENER_OUTPUT_ENABLED`、`TRADING_EXECUTION_ENABLED`、`LIVE_TRADING_ENABLED`、`AI_ORDER_ENABLED` 继续为 false。

Alembic 迁移失败会整体回滚。降级只删除新 Store 与交易日历，不触碰 legacy。后续发现问题应通过受控审核降低 readiness 或隔离，不得覆盖 legacy 或伪造来源。
