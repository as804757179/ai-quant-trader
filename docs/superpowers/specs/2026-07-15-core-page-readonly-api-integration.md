# 五个核心页面只读接口对接说明

日期：2026-07-15  
状态：已实施，待最终验收

## 目标

在不改变 Data Certification、Research Readiness、Execution Gate、Risk Engine、订单路径和发布锁的前提下，让五个核心页面优先展示后端真实状态；不存在的数据继续明确显示“待接入”或“未记录”。

## 页面与接口

| 页面 | 复用接口 | 新增只读接口 | 明确保留的缺口 |
|---|---|---|---|
| 运行总览 | `/health`、`/risk/dashboard`、`/risk/alerts`、`/portfolio/summary` | `/trade/execution-status` | 行情延迟、研究候选、资产曲线、策略版本 |
| Research Readiness | 无 | `/research/readiness` | 覆盖率聚合、逐日缺失明细的独立页面 |
| 回测验证 | `/backtest/tasks` | `/trade/execution-status` | dataset/result hash、Engine/Reference 证据、策略和引擎版本 |
| 交易运行控制 | `/trade/mode`、`/trade/broker-status`、`/risk/exposure` | `/trade/execution-status` | 本页不调用订单、撤单、同步或对账写接口 |
| AI 审计 | `/ai/signals` | `/ai/audit-summary` | 越权拒绝事件目前没有独立计数器，显示“未记录” |

## 契约约束

1. 新增接口全部为 GET，只读数据库或当前配置。
2. 六个发布锁从后端真实配置返回，前端不把静态文案当成运行事实。
3. Readiness 返回股票、区间、复权口径、用途、Requirement Profile、字段证据和审核结论，不传播权限。
4. AI 审计同时检查 `order_source`、`caller` 和 `created_from_task`；AI 来源订单数必须真实展示。
5. API 时间戳和 `X-Request-ID` 映射为页面的数据截止时间与关联 ID；页面统一按 Asia/Shanghai 展示。
6. 标准响应和 `/health` 原生响应均由同一只读客户端兼容，不改变健康检查原契约。
7. 接口失败、空数据和无权限分别显示，不使用原型数据或合成数据补齐。

## 安全影响

本次没有开放公共回测、Screener、自动交易、Live Trading、AI Order 或定时任务下单。没有新增 POST/PUT/PATCH/DELETE，没有数据库迁移，没有数据写入路径。

## 外部参考取舍

参考成熟量化平台将健康、状态、余额和收益查询与启动、停止、强制交易等写操作分离的做法；本项目仍以现有 A 股数据认证、用途级 Readiness 和 Execution Gate 为准。未引入第三方依赖，也未复制外部交易架构。

## 验收与回滚

验收包括：前后端契约测试、TypeScript 类型检查、生产构建、标准启动、五页浏览器检查、接口实调、六个发布锁为 false、AI 来源订单数为 0。

如需回滚，仅移除新增 GET 路由和前端读取钩子；数据库、订单、认证状态和发布权限无需回滚。
