---
name: ai-quant-trader-governance
description: Use when work in this repository changes quant-trading data semantics, backtest behavior, strategy, risk, portfolio, trading flows, AI-to-order boundaries, release gates, or related architecture.
---

# AI Quant Trader 项目导航

把本 Skill 当作上下文缓存与导航，不是不可变宪法或 Sprint 流水账。只加载当前任务需要的上下文。

## 优先级与冲突

按以下优先级判断：

1. 当前用户明确需求及最新补充
2. 当前任务引用的设计、验收标准和约束
3. 最新 Accepted ADR
4. 当前有效代码、迁移和自动化测试
5. 本 Skill
6. README、旧 Tracking Report、旧注释和历史实现

当前明确需求与 Skill 冲突时，以当前需求为准；简短指出冲突后执行，不机械拒绝合理演进。若长期原则改变，任务结束时建议更新 ADR 或 Skill。状态快照不能覆盖当前需求、最新 ADR、代码或测试。

涉及 Data Certification、Research Readiness、未来函数防护、Execution Gate、Risk Engine、Live 安全锁或 AI 下单边界时，不机械拒绝当前需求，也不静默改变安全语义。实施前在同一任务中明确变更原因、影响范围、ADR、测试、验收和回滚方案，再按用户最终明确决定执行。

## 长期目标与边界

面向 A 股，长期路径：真实数据 → 数据认证 → Research Readiness → 可信回测 → 策略验证 → 模拟盘 → 受控小资金实盘。先验证数据和策略，再开放交易。代码存在不等于能力已验证；AI 置信度不是 Alpha；引擎正确、小样本结果均不能证明盈利。不得保证盈利，盈利能力须经真实数据、可信回测、样本外和模拟盘验证。

### 数据

- `market.klines` 是 legacy/raw/uncertified 审计数据；`market.certified_klines` 是认证历史库。
- 历史研究统一经 `CertifiedKlineRepository`；先 Data Certification，再按用途、区间、Requirement Profile 做 Research Readiness。
- Certified 不等于全用途 ready；Profile 权限不传播。
- unknown、synthetic、uncertified 不进入可信研究或交易；legacy 不自动升级。
- raw/qfq/hfq 不混用；缺失不以假 K 线、前值或 Synthetic 补齐。
- Provider、单位、日历、企业行动和版本须可追踪；语义不明则 fail closed。

### 回测

- 禁止未来函数；只用当时公开可得信息。T 日收盘后信号最早下一交易日执行。
- 显式声明 profile、required_fields、adjustment、日期；只读 Certified 且 scoped-ready 数据和认证日历。
- 市场规则按日期/版本解析；明确费用、T+1、买入整手、卖出零股、停牌、涨跌停及企业行动 PIT。
- 记录数据/批次、规则/费用、策略/参数、引擎和 Hash 血缘；同输入可复现，数据或版本变化产生新 Hash。
- 计算正确不等于策略有效；小样本不得证明盈利。

### 交易安全

- AI 仅分析、解释、评分或 recommendation，不直接或间接创建订单；Celery 默认不产单。
- 所有订单经 Execution Gate 和 Risk Engine，并记录来源、调用者、审批和数据状态。
- Paper、Simulation、Live 明确区分；Live 初始化失败不得静默降级。
- 回测授权不等于执行授权；Execution Reference 独立审核；自动交易须显式授权。
- 当前安全默认值：`CERTIFIED_BACKTEST_EXECUTION_ENABLED=false`、`CERTIFIED_SCREENER_OUTPUT_ENABLED=false`、`TRADING_EXECUTION_ENABLED=false`、`LIVE_TRADING_ENABLED=false`、`AI_ORDER_ENABLED=false`、`ALLOW_SCHEDULED_ORDER=false`。
- 默认关闭不是永久禁令。未来明确授权时，按当期任务完成准入、ADR、测试和回滚后可演进。

## 工作流与定向读取

先分级再执行：

- 简单、局部、低风险：定向读取 → 修改 → 相关测试 → 简短结果。
- 跨模块、数据库迁移、架构、安全边界、发布权限或正式 Sprint：设计 → 实现与定向测试 → 全量测试 → 验收脚本 → 必要的 ADR/Tracking Report。

只做当前范围；不无关重构或提前堆模块。没有任务要求时，不为局部改动强制全量测试、验收脚本、ADR 或 Tracking Report。需要完整验收时，无证据、全量测试失败或验收失败不得称完成；不得删测、skip/xfail/xpass、降门禁或用 Mock/Stub/Synthetic 伪造 PASS。长期决策写 Accepted ADR；正式报告区分已验证/未验证、P0/P1/P2 和下一阶段准入。

默认只读：当前需求 → 本文件 → 目标文件 → 对应测试 → 最新直接相关 Accepted ADR；状态确有需要时才读 [current-project-state.md](references/current-project-state.md)。

使用精确路径、`rg`、调用方搜索、错误栈、对应测试和 `git diff`。数据任务聚焦数据/Certification/Readiness；回测聚焦 Backtest/Repository/Market Rules；交易聚焦 Gate/Risk/Order/Position；AI 聚焦调用链/Recommendation/解耦测试。不要默认扫全仓、全部迁移、全部 ADR/报告或重复项目摘要。

仅在全项目审计、跨模块改造、明显冲突、调用链不明、测试显示影响扩散、迁移跨模块或安全边界受影响时扩大范围；先说明原因，仍按模块定向读取。

## 更新

仅在长期架构/安全边界、核心访问路径、稳定阶段或 Accepted 开发纪律改变，或用户明确要求时更新。普通 Bug、数量变化、临时标的/日期/故障/P1-P2、重命名或单函数变化不更新。更新时删除失效内容，不追加历史；细节留 ADR。
