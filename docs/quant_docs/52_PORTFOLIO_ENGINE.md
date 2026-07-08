# 52 — Portfolio Engine（组合管理引擎） V1扩展

> 扩展 Capital Allocation + Portfolio Rebalancing。原有行业集中度等逻辑保留并协同。

## 1. Capital Allocation Engine（资金分配引擎）—— V1新增

**职责**：决定“买多少”（Position Sizing），而非仅“买什么”。

**核心算法**（V1实现）：
- **ATR Sizing**：单笔风险 = 账户 × Risk Budget% / ATR
- **Volatility Targeting**：目标组合波动率 → 反推单票权重
- **保守Kelly**：仅在高胜率+高赔率信号时使用小比例
- **Max Position / Max Daily Exposure**：硬上限（与31_34协同）
- **Cash Reserve**：动态（依赖51 Market State：熊市提高至40-50%）

**Integration with Pipeline**：
属于 “风险与资金分配” 步骤。
输入：信号 + 当前持仓 + 账户净值 + Market State
输出：建议仓位大小 + 风险预算分配
下游：PreTradeRiskChecker + Rebalancing Engine
直接提升：Profit Factor（优化资金使用） + 降低 Max Drawdown（避免过度集中）

## 2. Portfolio Rebalancing Engine（组合再平衡引擎）—— V1新增

**职责**：每日/触发式自动生成持仓调整计划，防止持仓混乱。

**核心输出**：
1. **Target Portfolio State**（V1新增核心目标锚点）：
   示例（可配置，依赖Market State动态调整）：
   - 现金：20%（熊市可提升至40%）
   - 科技/成长：30%
   - 消费：20%
   - 医药/防御：15%
   - 制造/周期：15%
   Rebalance Engine 的唯一目标就是让当前持仓逐步靠近这个Target State。

2. **Portfolio Score**：综合健康度（相关性 + Beta + 集中度 + 现金比例 + KPI趋势）
3. **Holding Ranking**：按Score对当前持仓排序
4. **Target Weight**：基于 Capital Allocation + Market State + 绩效 + Target Portfolio State
5. **Weight Difference**：当前 vs Target
6. **Rebalance Plan**：加仓/减仓/卖出/替换 列表（带优先级）
7. **Transaction Plan**：经过Risk Check过滤后的可执行订单

**触发条件**（V1）：
- 每日收盘后
- 单一股票权重偏离 Target > 3%
- Market State 切换（BULL ↔ BEAR）
- 重大Failure Case 发生后

**Integration with Pipeline**：
属于 “组合再平衡” 步骤。
输入：当前持仓快照 + Market State + Performance Evaluation
输出：Rebalance Plan + Transaction Plan
下游：Risk Check → Execution → Position Lifecycle
直接服务：风险控制（伪分散识别） + 盈利能力（动态优化仓位提升风险调整收益）

## 3. 与31_34 Risk Engine协同
- Rebalancing / Capital Allocation 产生的建议**必须经过** PreTradeRiskChecker 硬约束
- 建议值不得突破单票10%、总仓位80%、行业35%等硬阈值
- 冲突时以硬约束为准，并记录告警

## 4. V1实现要求
- 完整计算引擎 + API（/api/v1/portfolio/rebalance-plan）
- 前端支持 Rebalance Plan 可视化与一键执行（人工确认模式）
- 所有计划必须落库 audit.rebalance_plans

## 5. 与 Investment Decision Pipeline 集成
完整挂接 Pipeline “组合再平衡” 步骤，作为风险检查与执行之间的关键缓冲层。
