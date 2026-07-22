# ADR-024：免费观测模拟模式

状态：Accepted

## 决策

新增 `FREE_OBSERVATION_SIMULATION_V1` 作为零成本、本地开发环境的观测型模拟产品轨道。其目标是尽可能复用免费且允许自动化调用的外部数据，形成“观测、候选筛选、规则推演、隔离模拟记录与复盘候选”的工程闭环。

该轨道与正式 P3 replay、P4 Paper 和 P5 完全隔离。免费不自动构成数据认证、Research Readiness、Execution Reference 或交易授权。来源条款、账户权限、字段口径、发布时间、血缘或 Hash 任一项未知时，数据必须标记为 `unverified` 或 `unavailable`，不得进入 Certified Store、可信回测、正式 Paper 或订单执行链路。

每个实际接入的免费来源必须记录 provider、source、条款链接及版本、访问账户权限范围、抓取时间、dataset/batch/row Hash 与已知限制。未能证明自动化、本地存储或二次处理权限的来源不得自动调用；不得通过抓取受限网站、绕过登录、反爬或服务条款来补足数据。

## 影响

- `FREE_OBSERVATION_SIMULATION_V1` 的输出只能声明为免费观测与非正式模拟，不得宣称真实历史 replay、可信收益、正式 Paper、模拟实盘或阶段 C/D 通过。
- `P3_REPLAY_DUAL_MA_RAW_OHLCV_V1` 继续保持 `draft/disabled`；`P3_PROVIDER_LICENSE_UNCONFIRMED`、PIT、lineage、Hash、公司行动和 realtime blockers 不解除。
- P4-1D 和 P5 继续 blocked；不创建正式订单、成交、资金、持仓或对账事实。
- 六个发布和交易锁继续保持 `false`；AI 不成为交易决策或下单核心。
- 既有 `SohuDailyKlineImporter` 的认证写入语义不得被免费观测轨道复用或放宽。

## 验证与回滚

后续每个免费来源适配器必须有定向测试，证明未知许可、非观测模式、缺失 Hash 或时间语义、认证库写入、订单/资金/持仓副作用和外部来源异常均 fail closed。正式链路的现有回归测试必须保持通过。

如需停用该轨道，关闭其本地显式入口并保留已有审计记录；不得删除或改写认证、策略、订单与账务事实。
