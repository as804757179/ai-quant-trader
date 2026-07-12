# Sprint07 Corporate Action Readiness Report

日期：2026-07-11

## 当前结论

- Sohu 本批价格口径已用显式 Provider 对照证明为 raw。
- Store 主键包含 adjustment，不同 raw/qfq/hfq 不会互相覆盖；Repository 要求调用方显式传 adjustment。
- 系统不自动删除、平滑或修改分红、送转、配股可能造成的价格跳变。
- 系统尚无完整企业行动事件表、除权因子链、停牌与 Provider 缺失归因引擎。
- 第二 Provider 缺少 2026-06-30，原因未自动推断，已记录为待复核差异。

因此当前 63 条 Store 数据均为 `research_readiness_status=review_required`，而不是 ready。数据可用于 Store、查询和语义验收，不得用于策略收益回测、选股输出或交易判断。

## 成为 research-ready 的前置条件

需要引入可追踪的企业行动来源、按 adjustment 隔离的因子版本、停牌/缺失归因和逐批审核。无法解释的跳变继续标记 review_required，不得通过删价、补假 K 线或混合复权口径处理。
