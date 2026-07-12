# 项目介绍

## 1. 项目是什么

**AI Quant Trader Pro** 是一套面向 **A 股** 的量化交易辅助与执行系统，把以下能力串成一体：

| 能力域 | 说明 |
|--------|------|
| 行情与数据 | 通过 `a-stock-data` 微服务获取行情/K 线等，落库 TimescaleDB，Redis 缓存 |
| AI 分析 | 多 Agent（趋势/基本面/情绪/短线/风控）并行分析，信号聚合与落库 |
| 选股 | 因子/预设/主题选股 API |
| 策略 | 内置双均线、布林带、RSI、MACD；参数与启停可配置 |
| 回测 | A 股规则撮合引擎（T+1、涨跌停、费用等）+ HTTP 任务 |
| 交易 | `simulation` 本地模拟、`paper` Mock 券商、`live` QMT 适配 |
| 风控 | 下单前预检、熔断（DB 为准）、实盘二次确认、暴露度 |
| 监控 | Prometheus 指标、Grafana 预置看板、钉钉告警、WebSocket 推送 |

目标用户：个人/小团队在 **自研研究 + 模拟验证 +（可选）券商实盘** 场景下使用，而非直接替代券商终端。

---

## 2. 当前版本定位

| 项 | 说明 |
|----|------|
| 版本 | V1.0（可运行、可持续维护） |
| 文档更新 | **2026-07-10** |
| 测试 | backend pytest **约 130+**；worker pytest **约 21** |
| 推荐部署 | **宿主机混合**：本机/容器 PG+Redis + 本机 Backend/行情/前端（见 `.env.host`） |
| 股票池 | 全市场 A 股 active **约 5500+** |
| 实盘 | **代码具备 QMT 适配**；真盘必须 Windows + miniQMT + 券商 `xtquant` 实机验收 |
| 规划文档 | `docs/quant_docs/` 为历史设计，**部分能力未完全产品化**（如 Walk-Forward UI、AutoML） |

更细的能力边界见：[CURRENT_STATUS.md](./CURRENT_STATUS.md)。

---

## 3. 交易模式说明

| 模式 | 含义 | 资金 |
|------|------|------|
| `simulation` | 本地撮合 + DB 账本；**真实行情优先**；A 股 T+1 / 整手 / 涨跌停 / 费用 | 纯本地模拟 |
| `paper` | Mock 券商适配器 + 本地镜像 | 假券商，用于联调下单/对账/WS |
| `live` | 优先真实 QMT；无 SDK 时可 Mock 降级 | 生产务必 `ALLOW_MOCK_LIVE=false` |

实盘下单额外要求：

- 系统 `TRADE_MODE=live`
- 请求体带正确 `live_confirm`（等于 `LIVE_CONFIRM_TOKEN`）
- 单笔金额不超过 `LIVE_MAX_ORDER_VALUE`（默认 5 万，可配）

---

## 4. 不包含 / 非目标

- 不提供投资建议，回测/合成 K 线不代表未来收益  
- 不替代券商风控与合规审查  
- `AI-Trader/` 为独立实验子项目，**未接入主前端**  
- 默认开发环境 **可不设 API_KEY**（生产强烈建议开启）

---

## 5. 文档导航

| 文档 | 内容 |
|------|------|
| [manual.html](./manual.html) | 浏览器侧栏完整手册（由 README 生成） |
| [02_TECH_STACK.md](./02_TECH_STACK.md) | 技术选型与理由 |
| [03_ARCHITECTURE.md](./03_ARCHITECTURE.md) | 系统架构与数据流 |
| [04_GETTING_STARTED.md](./04_GETTING_STARTED.md) | 启动流程（含宿主机混合） |
| [05_CONFIGURATION.md](./05_CONFIGURATION.md) | 环境变量与缓存配置 |
| [06_TROUBLESHOOTING.md](./06_TROUBLESHOOTING.md) | 常见问题与解决办法 |
| [07_API_OVERVIEW.md](./07_API_OVERVIEW.md) | 主要 API 一览 |
| [CURRENT_STATUS.md](./CURRENT_STATUS.md) | **实现状态边界（优先读）** |
| [PROGRESS.md](./PROGRESS.md) | 开发进度追踪 |
| [quant_docs/](./quant_docs/) | 历史规划（参考，非验收标准） |
