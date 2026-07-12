# 当前项目状态快照

生成日期：2026-07-12

本文件仅是低优先级状态快照，不能覆盖当前需求、最新 Accepted ADR、当前代码与测试；发现冲突时不要沿用本快照。

## 当前稳定能力

- 已建立 Data Certification、独立 Certified Kline Store、Research Readiness 与字段级 Requirement Profile。
- 已建立 Execution Gate 和 AI 下单解耦。
- 已完成固定范围的可信回测完整性验证。
- 已建立 A 股版本化市场规则、认证交易日历、费用、T+1、买入整手、卖出零股和涨跌停边界。
- Engine 与独立 Reference 已完成固定范围对账。

## 当前阶段与阻塞

Corporate Action Point-in-Time 已完成，当前进入受控认证数据扩展。它不是永久开发顺序。

主要阻塞：受控数据集的企业行动官方事件级审核未完成；688981.SH 有 6 个交易日缺失原因 unresolved；全市场逐日证券状态未自动化；账户级真实佣金未认证；amount Provider 验证未闭环；Execution Reference 未授权。

## 当前默认权限

公共可信回测、真实选股输出、自动交易、Live Trading 和 AI 直接下单均关闭。这是当前安全状态，不是永久开发禁令。

## 核心 Accepted ADR 索引

- ADR-001 Data Certification：`docs/adr/ADR-001-data-certification.md`
- ADR-002 Execution Safety Gate：`docs/adr/ADR-002-execution-safety-gate.md`
- ADR-004 Certified Kline Store and Semantics：`docs/adr/ADR-004-certified-kline-store-and-semantics.md`
- ADR-005 Research Readiness Policy：`docs/adr/ADR-005-research-readiness-policy.md`
- ADR-006 Field-Level Research Readiness：`docs/adr/ADR-006-field-level-research-readiness.md`
- ADR-007 Backtest Integrity and Execution Model：`docs/adr/ADR-007-backtest-integrity-and-execution-model.md`
- ADR-008 A-share Market Rules and Accounting：`docs/adr/ADR-008-ashare-market-rules-and-accounting.md`
- ADR-009 Market Microstructure Boundaries：`docs/adr/ADR-009-market-microstructure-boundaries.md`

仅在重大阶段、主要阻塞、发布权限状态变化或用户明确要求时更新；普通 Bug 和小任务不更新。
