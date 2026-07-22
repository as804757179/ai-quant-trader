# ADR-024：免费观测模拟模式

状态：Accepted

## 决策

新增 `FREE_OBSERVATION_SIMULATION_V1` 作为零成本、本地开发环境的观测型模拟产品轨道。其目标是尽可能复用免费且允许自动化调用的外部数据，形成“观测、候选筛选、规则推演、隔离模拟记录与复盘候选”的工程闭环。

该轨道与正式 P3 replay、P4 Paper 和 P5 完全隔离。免费不自动构成数据认证、Research Readiness、Execution Reference 或交易授权。来源条款、账户权限、字段口径、发布时间、血缘或 Hash 任一项未知时，数据必须标记为 `unverified` 或 `unavailable`，不得进入 Certified Store、可信回测、正式 Paper 或订单执行链路。

每个实际接入的免费来源必须记录 provider、source、条款链接及版本、访问账户权限范围、抓取时间、dataset/batch/row Hash 与已知限制。未能证明自动化、本地存储或二次处理权限的来源不得自动调用；不得通过抓取受限网站、绕过登录、反爬或服务条款来补足数据。

免费日线产物必须记录 Provider 实际返回行的覆盖清单（范围、行数和股票代码集合 Hash），并明确标记 `coverage_status=unverified`。该清单不是全 A 股、上市状态、可交易性或交易日历完整性的证明。

## 影响

- `FREE_OBSERVATION_SIMULATION_V1` 的输出只能声明为免费观测与非正式模拟，不得宣称真实历史 replay、可信收益、正式 Paper、模拟实盘或阶段 C/D 通过。
- `P3_REPLAY_DUAL_MA_RAW_OHLCV_V1` 继续保持 `draft/disabled`；`P3_PROVIDER_LICENSE_UNCONFIRMED`、PIT、lineage、Hash、公司行动和 realtime blockers 不解除。
- P4-1D 和 P5 继续 blocked；不创建正式订单、成交、资金、持仓或对账事实。
- 六个发布和交易锁继续保持 `false`；AI 不成为交易决策或下单核心。
- 既有 `SohuDailyKlineImporter` 的认证写入语义不得被免费观测轨道复用或放宽。

## 本地虚拟账户近似

免费观测可在 `local_development` 中使用调用方显式提供的虚拟初始资金，基于未认证观测日线的收盘价记录本地持仓开闭事件、现金和持仓快照。该收盘价仅是 `unverified_observed_close_only` 参考，绝不是订单、成交、执行参考或真实账户事实；费用模型保持 `unavailable_not_inferred`，不得伪造券商费率、滑点、盘口、日历、公司行动或实际成交能力。

账本只以新的 JSON 文件追加事件并可由事件重建；续跑必须校验既有账本 Hash，且不得覆盖文件。它不写入订单、执行、资金、持仓、Certified Store 或任何正式 P3/P4 表，也不改变发布和交易锁。

跨日方向复盘只能汇总观察统计；在未认证免费数据条件下，自动参数调整、策略版本创建或审批均必须保持 blocked。

## 验证与回滚

后续每个免费来源适配器必须有定向测试，证明未知许可、非观测模式、缺失 Hash 或时间语义、认证库写入、订单/资金/持仓副作用和外部来源异常均 fail closed。正式链路的现有回归测试必须保持通过。

如需停用该轨道，关闭其本地显式入口并保留已有审计记录；不得删除或改写认证、策略、订单与账务事实。
