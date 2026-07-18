# L0：旧接口治理实施基线

状态：已建立  
日期：2026-07-16  
对应计划：2026-07-16-legacy-api-clearance-and-new-api-entry-gate.md

## 1. 工作区保护

L0 开始前已执行 scripts\doctor.ps1，结果为 PASS；唯一提示是当前 Python 缺少可选 chromadb，RAG 按既有设计降级为空检索。

开始时工作区共有 95 条 git status 记录；并行 L0 产物写入后变为 96 条。它包含既有 Sprint14.x、前端只读页面、研究证据、运行脚本和子模块修改，均视为实施前已有资产：

- 已跟踪修改：治理状态快照、主应用 AI/Backtest/Portfolio/Stock/Strategy/Trade 路由与服务、风险监控、前端核心页面和 API client、运行脚本、Worker 行情数据链路。
- 已修改子模块：a-stock-data。子模块自身有 3091 条状态，其中含 Provider/服务源文件、测试、已跟踪 __pycache__ 和 3086 条 .venv 产物；不得 clean、reset、批量暂存或在顶层仓库中假装已固定。
- 未跟踪迁移：015 到 023。
- 未跟踪研究能力：research API、Research Evidence/Profile/Readiness 模块、研究证据脚本、财报快照与页定位 Worker、相应后端/Worker/前端测试。
- 未跟踪文档：ADR-012 到 ADR-019、Sprint14.0 到 Sprint14.9 追踪报告、handoffs 和既有 specs。
- 本计划与 L0 新增文件：legacy-api-clearance-and-new-api-entry-gate.md、legacy-api-inventory.json、test_legacy_api_inventory.py、verify_legacy_api_inventory.ps1、本文件。

后续实施不得 reset、clean、checkout、覆盖或删除上述既有资产；若必须触及同一文件，先读取当前内容并以最小差异叠加。

| 资产组 | 接口/实现 Owner | 关键依赖 | 禁止动作 | 后续阶段 |
| --- | --- | --- | --- | --- |
| 行情观察 | market_data | 015-017、quote_sync、quote_store、a-stock-data quotes | 拆散迁移或删除批次/血缘事实 | L3、L6 |
| 研究证据 | research | 018-023、Evidence/Profile/Readiness、Worker 采集和快照 | 重编号、改写 Hash/时间/ready=0 | L3 |
| 核心只读页面 | frontend | client、coreModels、readOnlyApi、页面与测试 | 删除现有页面接入或伪造数据 | L1、L6 |
| 运行稳定性 | platform | stop-local、repair-db-owner、Watchdog | 非标准启动、按端口杀进程 | L7 |
| 数据服务子模块 | data_service | service/main.py、providers.py、tests、gitlink | clean/reset/批量暂存 .venv 或假定已固定 | L1、L3 |
| 本轮治理产物 | legacy_api_governance | 账本、L0 测试、验收脚本 | 绕过账本直接新增或删除路由 | L1-L7 |

## 2. 接口账本

机器可读账本位于 docs/api/legacy-api-ledger.json。每个边界都有 owner、风险、处置、生命周期、消费者状态、已知问题和验证层级：

| 范围 | 数量 | 固化方式 |
| --- | ---: | --- |
| 主应用 HTTP | 61 | 由 FastAPI 实际注册路由校验 |
| 主应用 WebSocket | 4 | 由 FastAPI 实际注册路由校验 |
| a-stock-data 内部 HTTP | 11 | 由服务源代码 AST 校验 |
| 合计 | 76 | 新增或删除任一路由均需先更新账本和处置计划 |

账本不是发布许可。每个接口的最终保留、修复、异步化、隔离或弃用处置以主计划第 6 节为准。

## 3. L0 验收

运行：

    powershell -ExecutionPolicy Bypass -File scripts\verify_legacy_api_l0.ps1

通过条件：

1. 主应用 HTTP、WebSocket 和内部数据服务的实际接口集合分别等于账本。
2. 每个范围的实际数量分别为 61、4、11，合计 76。
3. 账本中每条接口都有 owner、风险、处置、消费者状态和验证层级；已知消费者引用可追踪。
4. 主应用与内部数据服务的规范化 OpenAPI SHA-256 快照均未漂移。
5. 未登记的接口变更使测试失败，而不是静默进入后续阶段。

L0 还修复并测试了 Worker fund-flow 调用中的下划线路径错配：内部服务注册的是 /fund-flow/{code}，Worker 现已使用同一路径。测试同时验证空 data 数组保持为空，而不是被包装成一条伪数据记录。

L0 通过后，L1 才可以开始统一契约、身份和权限改造。
