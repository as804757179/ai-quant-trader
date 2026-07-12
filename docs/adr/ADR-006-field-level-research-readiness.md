# ADR-006：Field-Level Research Readiness

日期：2026-07-11  
状态：已接受

## 背景

Sprint08 以整批 Provider 校验状态作为 readiness 条件，导致 2026-06-30 的 amount 未验证时，已经完成 OHLCV 验证的独立研究用途也被阻止。amount 的证据缺口不能被伪装为已解决，但也不应无条件阻止不依赖 amount 的研究。

## 决策

Readiness 的授权键升级为：

`股票 + 日期区间 + adjustment + research_use_scope + requirement_profile`

Certified Store 行继续保持 `research_readiness_status=review_required`，不代表全用途 ready。唯一授权依据是带字段证据的 scoped review。

每条 review 必须保存 requirement_profile、required_fields、validated_fields、unresolved_fields、rejected_fields 和 policy_version。未声明 Profile、未声明 required_fields、Profile 与字段集合不匹配或 Profile 与用途不匹配时 fail closed。

## Requirement Profiles

### OHLCV_RETURN_V1

必需字段为 trading_date、open、high、low、close、volume、adjustment、trading_calendar、corporate_action_status。amount 与 turnover_rate 不是必需字段。

### AMOUNT_FACTOR_V1

在 OHLCV_RETURN_V1 基础上额外要求 amount、amount_unit、amount_provider_validation。2026-06-30 amount 独立证据 unresolved，因此不能 ready。

### EXECUTION_REFERENCE_V1

要求 quote_time、price_applicability、explicit_authorization、execution_gate。本 Sprint 没有时效与执行价格授权，全部 rejected。

## 字段判定规则

- required_fields 与 unresolved_fields 相交：review_required。
- required_fields 与 rejected_fields 相交：rejected。
- 必需字段既未 validated、也未明确 unresolved/rejected：review_required。
- 非必需字段 unresolved 必须保留记录，但不会阻塞独立 Profile。
- 一个 Profile ready 不授予其他 Profile 或用途权限。

## 样本审核结果

- 300308.SZ：`return_backtest + OHLCV_RETURN_V1 = ready`。
- 603986.SH：`return_backtest + OHLCV_RETURN_V1 = ready`。
- 300502.SZ：同一 Profile 为 rejected；2026-06-11 的派现和转增尚未做收益调整。
- AMOUNT_FACTOR_V1：300308/603986 review_required；300502 rejected。
- EXECUTION_REFERENCE_V1：三只股票全部 rejected。

300308 最大相邻收盘跳变约 8.3551%，603986 约 10.0008%，均无未解释重大跳变。300502 在 6 月 11 日约 31.91% 的跳变已由企业行动解释，但“已解释”不等于“已处理”，因此不能绕过 return-backtest 阻断。

## 调用方契约

Backtest reader 必须传 requirement_profile、required_fields、adjustment 和日期区间。策略目录为每个现有策略显式声明字段；调用声明与策略目录不一致时拒绝。Screener 当前使用 amount 排序/因子，声明 AMOUNT_FACTOR_V1 并继续被阻止。Simulation fallback 声明 EXECUTION_REFERENCE_V1 并继续 rejected。

`CERTIFIED_BACKTEST_EXECUTION_ENABLED` 和 `CERTIFIED_SCREENER_OUTPUT_ENABLED` 继续关闭；scoped ready 只证明数据可见性，不授权运行策略或发布候选。
