# ADR-005：Research Readiness Policy

日期：2026-07-11  
状态：已接受

## 背景

Data Certification 证明数据来源、质量和不可伪造性，但不等价于数据适合某一种研究或执行用途。Sprint07 的 63 条 raw certified 日线仍存在企业行动处理、第二 Provider 完整性和用途语义问题，因此必须在 Certified Store 之上增加独立的 Research Readiness Gate。

## 决策

新增三个审核存储：

- `market.research_readiness_reviews`：按股票、区间、adjustment 和用途记录最终审核。
- `market.research_date_reviews`：逐日记录 normal_trade、suspended、not_listed、delisted、provider_missing、exchange_closed 或 unresolved。
- `market.corporate_action_reviews`：记录企业行动事件与 verified_no_event 结论。

Readiness 状态为 `review_required`、`ready`、`rejected`。没有审核记录、审核区间不覆盖请求区间或任何必要状态不满足时一律 fail closed。

## 用途隔离

`research_use_scope` 分为：

- `raw_price_analysis`：不可变原始价格和成交量研究。
- `return_backtest`：收益率、趋势指标和跨日期回测。
- `execution_reference`：Simulation fallback 等执行价格参考。

同一数据在不同用途下可以有不同审核状态。Certified 不自动获得任何用途授权；raw/qfq/hfq 不能混用。

## Ready 条件

只有 certified、元数据完整、adjustment 明确、日历覆盖完整、无 unresolved 缺失、企业行动已审核、跨 Provider 校验 pass、无未解释重大跳变且用途政策匹配时才允许 ready。return_backtest 遇到已确认但未处理的企业行动会 rejected；execution_reference 没有显式时效审核会 rejected。

## Sprint08 审核结论

目标 Store 的 63 条数据仍为 0 ready、63 review_required：

- 三只股票各有 21 个正常交易日，交易日历范围内没有主数据缺失；另有 27 个股票×休市日记录为 exchange_closed。
- 新浪 `klc_kl` 归档端点缺少 2026-06-30，但新浪另一条日线端点及腾讯 raw 端点均包含该日期，且与 Sohu OHLCV 一致，因此缺失归因为 endpoint-specific provider_missing。
- 2026-06-30 的独立 amount 对照仍不可得，provider validation 只能是 partial_pass，不能 ready。
- 300502.SZ 在 2026-06-11 发生每 10 股转增 4 股并派现 10 元的企业行动。raw 数据保留不改，但 return_backtest 在未实现调整前 rejected。
- 300308.SZ 和 603986.SH 在目标区间内 verified_no_event，但仍受 amount 证据缺口阻塞。
- 历史 2026-06 数据没有执行时效授权，三只股票的 execution_reference 均 rejected。

## Repository 与业务门禁

`CertifiedKlineRepository` 继续只从 Certified Store 取 bar，但 `assert_dataset_ready` 必须额外指定 research_use_scope，并委托 `ResearchReadinessService` 校验审核记录。Backtest 使用 return_backtest；Screener 的趋势/因子数据使用 return_backtest；Simulation fallback 使用 execution_reference。无 ready review 时全部拒绝。

业务发布锁、Execution Gate 和 Data Certification Gate 不因 readiness 审核而放宽。

## Raw 数据政策

raw 是不可变审计基准，可用于原始价格与成交量调查。涉及收益率、趋势或跨企业行动区间的研究必须处理企业行动；当前 qfq 不能伪装为严格 point-in-time 数据。任何调整数据必须使用独立 adjustment 和明确版本，不得覆盖 raw。
