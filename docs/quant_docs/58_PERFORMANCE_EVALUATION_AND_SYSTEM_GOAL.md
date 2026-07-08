# 58 — Performance Evaluation and System Goal（绩效评估与系统最终目标） V1北极星

> **系统不是量化平台、不是AI聊天工具、不是研究系统。**
> **它是持续提升真实资金盈利能力的A股AI自动交易系统。**

## 1. System Goal（系统最终目标）

**唯一使命**：
构建一个能够 **自动选股 → 自动分析 → 自动风控 → 自动组合管理 → 自动交易 → 自动复盘 → 持续学习 → 持续优化**，并在真实资金上长期稳定运行的企业级A股AI自动交易系统。

**唯一评判标准**（所有模块、所有优化、所有代码改动必须服务于此）：
- **盈利能力**：Annual Return、Benchmark Excess Return、Profit Factor
- **风险控制**：Max Drawdown、Calmar Ratio、Sortino Ratio
- **稳定性**：Sharpe Ratio、Information Ratio、Win Rate + Payoff Ratio 组合
- **效率**：Turnover、Average Holding Days、Transaction Cost Ratio

任何不能直接或间接提升以上指标的设计，均为过度设计，必须删除或推迟。

## 2. System KPI 体系（V1必须实现 Dashboard）

**核心KPI**（每日/每周自动计算并展示）：

| 类别 | KPI | 目标方向 | 计算频率 | Pipeline关联 |
|------|-----|----------|----------|---------------|
| 收益 | Annual Return / Benchmark Excess | ↑ | 日 | Performance Evaluation 步骤 |
| 风险调整 | Sharpe / Sortino / Calmar | ↑ | 日 | 同上 |
| 盈利质量 | Profit Factor / Payoff Ratio | ↑ | 周 | 同上 |
| 风险 | Max Drawdown / VaR / CVaR | ↓ | 日 | Risk Check + Rebalancing |
| 交易效率 | Win Rate / Avg Holding Days / Turnover | 优化 | 周 | Position Lifecycle |
| 成本 | Transaction Cost Ratio | ↓ | 日 | Execution |
| 相对基准 | Information Ratio / Alpha | ↑ | 周 | Performance Evaluation |

**系统级 vs 策略级**：
- 策略级KPI：单个策略回测/实盘表现
- **系统级KPI（北极星）**：整个Pipeline运行后的综合表现（含Rebalancing、Capital Allocation、动态退出等全部影响）

## 3. 优化闭环

所有上游改动必须回答：
1. 这个改动如何提升 System KPI 中的至少一项？
2. 是否引入了新的风险（Max Drawdown上升）？
3. 是否增加了不必要的复杂度（影响可维护性）？

**示例**：
- 修改 Capital Allocation 规则 → 必须在回测和纸盘中证明 Sharpe 提升且 Max Drawdown 不上升
- 重构 TrendAgent Prompt → 必须证明整体 Win Rate + Payoff Ratio 组合改善

## 4. V1实现范围
- 完整 System KPI 计算引擎 + Dashboard（前端58页面）
- 每日自动生成 Performance Report（邮件/钉钉可选）
- 所有新模块（Rebalancing、Capital Allocation、Position Lifecycle）必须暴露 KPI 影响接口

## 5. Integration with Investment Decision Pipeline
属于 Pipeline 末端 “绩效评估北极星” + “学习闭环” 步骤。
输入：全量交易记录 + 持仓曲线 + Market State 历史
输出：KPI Dashboard + 优化建议 + 反哺信号
下游：Strategy Optimization + Prompt 迭代
直接服务：Profit Optimization（唯一北极星） + 可维护性（清晰目标）
