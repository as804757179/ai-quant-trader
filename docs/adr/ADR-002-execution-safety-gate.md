# ADR-002：交易执行安全闸与 AI 下单解耦

日期：2026-07-11  
状态：已接受

## 决策

所有订单在进入 Risk Engine 和 Trader 前必须经过 `ExecutionGate`。默认关闭交易执行、AI 下单、实盘交易和定时下单；默认要求人工审批。AI 扫描仅发布 `signal_recommendation`，其中固定标记 `review_required=true` 与 `order_created=false`。

## 原因

AI 输出是研究与解释结果，不是可执行订单。定时任务也不应绕开人工责任和系统授权。没有统一门禁时，新增数据或改变阈值可能意外恢复自动下单能力。

## 规则

- AI 来源永远返回 `AI_ORDER_DISABLED`，不因环境变量而获得下单权限。
- 订单缺少来源、调用者、人工审批或声明为 unknown/uncertified/synthetic 数据时，安全闸拒绝。
- 手工订单仅在 `TRADING_EXECUTION_ENABLED=true`、带 `approval_id` 且通过 Risk Engine 后才可提交。
- Live 还要求 `LIVE_TRADING_ENABLED=true`、`TRADE_MODE=live`、有效二次确认、真实 QMT 环境和风控通过；`QMT_FORCE_MOCK=true` 时拒绝。
- Scheduled Rule 只有显式开启执行与定时开关、关闭人工审批后才可能进入门禁；AI 永远不能成为该来源。

## 审计

`trade.orders` 记录 `order_source`、`order_reason`、`caller`、审批信息、风控检查标识、数据认证状态、创建者和任务来源。旧订单保持未知审计状态，不被伪造为已审批订单。

## 演进

未来可将人工复核后的 recommendation 显式转换为 paper manual order；从 paper 升级 live 时仍必须保留全局开关、审批、QMT 检查和风控。不得恢复 AI 直接下单。

## 验证

运行：`powershell -ExecutionPolicy Bypass -File scripts/verify_execution_safety.ps1`。

全量回归不得通过恢复 AI/Celery 下单、关闭 Execution Gate 或削弱人工审批断言来获得通过。AI 分析响应中的 `order_created` 始终为 `false`；数据达到 certified 只代表可用于分析，不授予 AI 下单权限。
