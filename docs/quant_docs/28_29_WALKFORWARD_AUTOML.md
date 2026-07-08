# 28 & 29 — Walk-Forward验证 + AutoML参数优化（V1: Interface Only）

**V1范围**：保留完整架构设计、数据库表、API接口、扩展点。
**V2实现**：完整AutoML优化执行 + 高级Walk-Forward并行计算。

## V1必须实现
- WalkForwardConfig + generate_windows 接口
- AutoMLOptimizer 基础接口（Optuna TPE采样框架）
- OverfittingDetector 接口
- 相关数据库表（backtest.walkforward_results）

## V2计划（Phase 5+）
完整贝叶斯优化 + 多目标复合函数 + 硬约束淘汰 + 并行窗口执行。

## Integration with 56 Investment Decision Pipeline
Walk-Forward + AutoML 属于 Pipeline “策略优化” 闭环步骤。
V1仅提供接口，V2实现后将自动用于 Rebalancing 参数优化和 Capital Allocation 动态调整。
