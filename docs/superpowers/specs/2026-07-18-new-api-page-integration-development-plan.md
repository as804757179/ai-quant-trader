# 新接口与前端缺失页面分阶段开发基线

日期：2026-07-18  
状态：Draft，用户确认后作为后续新接口开发与对接基线  
适用范围：现有前端页面缺失接口的设计、实现、测试、验收与回滚

## 1. 目标

在旧接口清零完成后，按“复用现有接口优先、真实数据优先、低风险只读优先、业务依赖顺序优先”逐步接通现有前端页面，不新增无页面消费者的业务接口，不为尚未具备可信数据或业务闭环的页面返回伪造结果。

本计划的业务顺序固定为：

`数据与证据 → 市场观察 → 研究分析 → 影子运行 → 自动模拟交易 → 组合账务 → 盘后复盘`

菜单顺序不是开发顺序。页面存在不等于对应能力已经获得数据、研究、回测或执行授权。

## 2. 成功标准

1. 每个现有前端页面最终标记为 `connected`、`intentionally_pending` 或 `deprecated`。
2. `connected` 页面只展示真实接口结果，正确区分加载、空数据、无权限、失败、超时、过期和未知状态。
3. 能复用现有接口时不新增重复接口；新增接口必须有唯一 Owner、消费者、权限、契约测试和回滚方案。
4. 所有列表使用服务端稳定分页、筛选和真实 `total`，不把本地切片描述为全量。
5. Provider、来源、业务时间、系统接收时间、数据截止时间、版本、批次和 Hash 按适用范围可追踪。
6. `unknown`、`synthetic`、`uncertified`、`rejected`、`revoked`、`stale` 和 Provider 失败不得被转换成通过、零值或可交易。
7. P0、P1 任务全部验收通过前，不进入影子运行、自动模拟交易、组合账务和策略优化接口。
8. 六个发布与交易安全锁在本计划 P0、P1、P2 阶段保持 `false`。

## 3. 固定安全边界

以下能力不因页面接入或只读接口存在而自动开放：

- Data Certification 不传播为 Research Readiness。
- Research Readiness 不传播为回测、候选发布或 Execution Reference。
- 历史回测授权不传播为实时估值或交易执行授权。
- AI 仅能分析、摘要、解释或 recommendation，不直接或间接创建订单。
- 页面 GET 请求不得触发采集、重试、认证、清算、审批、下单、撤单、同步或其他写副作用。
- observed-only 数据不得进入可信研究、候选、回测或订单路径。

以下开关保持关闭：

```text
CERTIFIED_BACKTEST_EXECUTION_ENABLED=false
CERTIFIED_SCREENER_OUTPUT_ENABLED=false
TRADING_EXECUTION_ENABLED=false
LIVE_TRADING_ENABLED=false
AI_ORDER_ENABLED=false
ALLOW_SCHEDULED_ORDER=false
```

任何未来开锁必须单独设计变更原因、范围、Accepted ADR、测试、真实验收和回滚，不属于普通页面接口接入。

## 4. 通用 API 契约

### 4.1 路径与响应

- 公共接口继续使用 `/api/v1` 前缀。
- 复用现有 `APIResponse`，不得建立第二套成功或错误 envelope。
- 新接口成功响应统一为：

```json
{
  "success": true,
  "data": {},
  "message": "ok",
  "timestamp": "服务器响应时间"
}
```

- `timestamp` 仅为响应时间，不得替代业务 `as_of`、`available_at`、`data_cutoff` 或 `received_at`。
- 响应头保留 `X-Request-ID`；前端将其映射为关联 ID。
- 401、403、404、409、422、429、502、503 使用现有统一错误结构和真实 HTTP 状态。

### 4.2 列表契约

所有新增列表默认采用：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 50,
  "has_more": false,
  "summary": {},
  "source_version": "版本"
}
```

共同要求：

- `page >= 1`，`1 <= page_size <= 200`；特殊上限必须在接口中显式声明。
- 稳定排序使用业务时间降序并追加唯一 ID 降序作为 tie-breaker。
- 空数据返回成功的空列表；接口不可用、无权限或查询失败不能伪装为空列表。
- 每个筛选条件在后端执行，前端不得先取固定数量再本地假分页。

### 4.3 数据血缘字段

按资源适用范围返回：

- `provider`、`source`、`source_document_id`
- `business_date`、`published_at`、`available_at`、`received_at`、`as_of`
- `batch_id`、`dataset_hash`、`raw_hash`、`content_hash`
- `collector_version`、`normalizer_version`、`policy_version`、`source_version`
- `quality_status`、`certification_status`、`readiness_status`、`freshness_status`
- `limitations` 或等价的明确用途限制

缺失字段返回 `null` 或明确状态，不使用默认值伪造事实。

### 4.4 权限与审计

- 只读页面接口至少要求已认证人工会话和对应 read scope。
- 人工复核写接口要求 `research_reviewer` 角色或等价 scope、CSRF、服务端主体、`Idempotency-Key` 和请求 Hash。
- 所有写入采用追加式记录；纠错通过新记录完成，不 UPDATE/DELETE 旧审核事实。
- 不接受客户端自报 reviewer、approval、数据授权或交易资格。

## 5. 已连接页面与复用基线

以下页面已有真实接口链路，后续任务不得重建重复 API：

| 页面 | 现有接口 |
| --- | --- |
| 运行总览 | `/health`、`/risk/dashboard`、`/risk/alerts`、`/portfolio/summary`、`/trade/execution-status`、`/stock/market/status`、`/portfolio/equity-curve`、`/research/candidate-status`、`/strategy/runtime-status` |
| Research Readiness | `/research/readiness`、`/trade/execution-status` |
| 回测验证 | `/backtest/tasks`、`/backtest/validation-summary`、`/trade/execution-status` |
| 交易运行控制 | `/trade/mode`、`/trade/broker-status`、`/risk/exposure`、`/trade/execution-status` |
| AI 审计 | `/ai/signals`、`/ai/audit-summary` |
| 全市场行情 | `/stock/market/status`、`/stock/market/batches` |
| 研究候选 | `/research/candidate-status`；当前仅显示资格状态，不等于已发布候选 |
| 新闻人工复核 | `/research/evidence`、`/research/evidence/{evidence_id}/reviews` |
| 策略版本 | `/strategy/runtime-status` |
| 全部订单 | `/trade/orders`；当前仅为 simulation、最近 7 天的只读窗口 |

## 6. 开发优先级总表

| 顺序 | 任务 | 页面 | 类型 | 准入依赖 |
| --- | --- | --- | --- | --- |
| P0-1 | 财报页级候选人工复核 | 官方公告、深度分析、AI 证据复核 | 扩展现有研究证据能力 | 现有财报快照与页级定位 |
| P0-2 | Certified Store 只读查询 | Certified Store | 新增只读 API | Data Certification 现有模型 |
| P0-3 | 认证批次与质量结果 | 数据批次、数据质量 | 新增只读 API | 现有认证批次与质量记录 |
| P0-4 | 数据阻塞归因 | 阻塞归因 | 新增只读 API | 日历、缺失和审核事实 |
| P0-5 | Provider 交叉验证 | Provider 验证 | 新增只读 API | Provider 验证记录 |
| P0-6 | 日历、证券状态与规则 | 认证交易日历、涨跌停与状态、交易规则、费用规则 | 新增只读 API | 版本化规则与官方证据 |
| P1-1 | 现有组合与风险接口接页 | 账户、持仓、资产曲线、风险总览、风险事件 | 仅前端复用 | 无新业务 API |
| P1-2 | 公告、新闻和 AI 证据接页 | 官方公告、新闻与事件、AI 证据复核 | 优先复用 | P0-1 |
| P1-3 | 价格、盘口、成交量与流动性 | 价格与盘口、成交量与流动性 | 新增/扩展只读 API | 行情 provenance 已验证 |
| P1-4 | 系统运行可观测性 | 服务健康、系统告警、任务时序、平台审计 | 新增聚合只读 API | 现有运行登记与审计来源 |
| P2-1 | 研究聚合与持仓复评 | 深度分析、排除与阻断、持仓再评估 | 新增只读聚合 API | P0、P1 全部通过 |
| P2-2 | 行业、板块与情绪观察 | 行业与板块、市场情绪 | observed-only API | 来源、时点、许可和质量明确 |
| P2-3 | AI 摘要与证据展示 | AI 摘要、AI 证据复核 | 优先复用 | P1-2、P2-1 |
| P3 | 影子运行与决策审计 | 决策队列、影子运行、扫描/选股/决策日志 | P3-0 通用基础设施最终验收通过；正式 replay 因无合规数据源而 `blocked/deferred` | 合格历史数据许可、逐行 PIT/血缘、正式样本/Profile/参数冻结；实时路径另需许可 |
| P4 | Paper 订单与组合账务 | 开放订单、拒绝、成交、授权、盈亏、清算、对账 | 延后设计 | 阶段 D 明确授权 |
| P5 | 盘后复盘与策略优化 | 复盘、错失机会、候选审批及相关日志 | 延后设计 | Paper 账务闭环稳定 |

同一优先级内按编号顺序实施；前一任务未通过验收，不开始依赖它的下一任务。

## 7. P0 接口冻结

### 7.1 P0-1 财报页级候选人工复核

#### 目标

复用现有 `market.research_financial_report_snapshots`、解析运行、页级证据和元数据定位记录，为财报页级候选增加人工消歧，不重做快照、PDF 解析或自动财务数值提取。

#### 接口

1. `GET /research/evidence/{evidence_id}/financial-location-candidates`
2. `GET /research/evidence/{evidence_id}/financial-location-reviews`
3. `POST /research/evidence/{evidence_id}/financial-location-reviews`

候选查询支持 `field_name`、`status`、`page`、`page_size`；只允许现有定位模型已经支持的字段。复核写入至少包含：

```json
{
  "location_id": "uuid",
  "conclusion": "confirmed|rejected|ambiguous|needs_more_evidence",
  "reason": "必填人工说明"
}
```

服务端记录 `reviewer_principal_id`、角色、请求 Hash、幂等键、复核时间和绑定的 `snapshot_id`、`parse_run_id`、`page_evidence_id`、`raw_hash`、`locator_version`。

#### 边界

- 不解析或发布财务数值。
- 人工确认只确认当前页级定位，不自动传播到整份报告或其他字段。
- 原文 Hash、解析版本或候选定位变化后，旧复核保留历史但不得自动视为当前有效。
- 不改变来源许可预审、Research Readiness、候选、回测、策略或交易权限。

#### 页面接入

- “官方公告”展示原始证据和页级定位状态。
- “深度分析”只展示各维度证据及人工复核状态，不生成投资结论。
- “AI 证据复核”展示 AI 使用的证据引用与当前复核状态；AI 不参与复核写入。

### 7.2 P0-2 Certified Store 只读查询

#### 接口

`GET /data/certified-klines`

查询参数：`stock_code`、`date_from`、`date_to`、`adjustment=raw|qfq|hfq`、`batch_id`、`page`、`page_size`。

每项至少返回 `stock_code`、`trading_date`、`adjustment`、`batch_id`、`provider`、`source`、`raw_hash`、`normalizer_version`、`quality_status`、`certification_status`、`certified_at`。

该接口只证明 Certification 状态，不返回或推导 Research Readiness。查询必须经现有 Certified Repository 或其只读查询层，不直接复制 legacy `market.klines` 逻辑。

### 7.3 P0-3 认证批次与质量结果

#### 接口

1. `GET /data/certification-batches`
2. `GET /data/quality-results`

批次支持 Provider、数据集、日期区间、终态和分页筛选；质量结果支持 `batch_id`、`stock_code`、`rule_code`、`result` 和分页筛选。

批次终态至少区分 `certified`、`rejected`、`fetch_failed`、`validation_failed`、`write_failed`；最新失败不得被旧成功覆盖。质量结果必须关联批次、规则版本、输入 Hash、审核范围和拒绝原因。

GET 不提供重试、修复或覆盖写入。任何未来重试必须使用已有统一 Job 机制并另立写任务。

### 7.4 P0-4 数据阻塞归因

#### 接口

`GET /data/blockers`

查询参数：`stock_code`、`date_from`、`date_to`、`classification`、`status`、`page`、`page_size`。

分类至少包含 `non_trading_day`、`suspended`、`security_ineligible`、`provider_missing`、`corporate_action_unresolved`、`calendar_uncovered`、`unresolved`。每项返回证据来源、证据版本、审核状态和当前是否阻断 Readiness。

不能证明原因时必须保持 `unresolved`；禁止用前值、零成交量 K 线、weekday 推断或人工文字直接改成已解决。

### 7.5 P0-5 Provider 交叉验证

#### 接口

`GET /data/provider-validations`

查询参数：`stock_code`、`date_from`、`date_to`、`field`、`conclusion`、`page`、`page_size`。

每项返回主/第二 Provider、字段、双方业务值或脱敏摘要、绝对差、相对差、容差版本、结论、审核时间和证据 Hash。第二 Provider 只用于验证，不写 Certified Store，不作为运行时静默 fallback。

`amount` 必须作为独立字段资格处理；其未闭环只阻断依赖 Amount 的 Profile，不自动撤销已独立证明的 OHLCV 范围。

### 7.6 P0-6 日历、证券状态与规则

#### 接口

1. `GET /rules/trading-calendar`
2. `GET /rules/trading`
3. `GET /rules/fees`
4. `GET /market/security-status`

共同查询支持适用日期或日期区间、市场/板块、证券代码和版本。规则结果必须返回官方依据、有效区间、版本、Hash 和解析状态。

安全规则：

- 交易日历缺失时不使用 weekday fallback。
- 证券状态不明时不推定为正常交易。
- 涨跌停、ST、停牌、上市状态和价格 Tick 按日期解析，不以代码前缀永久猜测。
- 费用按方向、日期和版本返回；账户真实佣金未认证时明确 `unavailable`，不得用默认费率伪装真实账户成本。
- 只读规则页面不开放回测、Screener 或交易执行。

## 8. P1 页面接入与接口设计

### 8.1 P1-1 只复用现有接口

| 页面 | 复用接口 | 禁止事项 |
| --- | --- | --- |
| 账户总览 | `/portfolio/summary` | 不伪造初始资金或账户余额 |
| 持仓与可用 | `/portfolio/positions` | GET 不释放 T+1，不补模拟持仓 |
| 资产曲线 | `/portfolio/equity-curve` | 缺少估值来源时不绘制假曲线 |
| 风险总览 | `/risk/dashboard`、`/risk/exposure`、`/risk/rules`、`/risk/fuse-status` | unknown/stale 不显示为通过 |
| 风险事件 | `/risk/alerts`、`/risk/alerts/summary` | 系统告警与风险告警不得混用 |
| 开放/拒绝订单 | `/trade/orders` 的 `status` 筛选 | 不新建重复订单列表接口 |

实现前先核对现有响应是否满足页面字段；仅在真实字段缺失且无法安全组合时，最小扩展现有 GET 响应。

### 8.2 P1-2 证据页面复用

- “官方公告”和“新闻与事件”优先复用 `/research/evidence` 的 `evidence_type` 筛选及 `/research/evidence/{evidence_id}` 详情。
- “AI 证据复核”复用研究证据详情、P0-1 财报复核状态和现有 AI 信号/审计接口，不创建 AI 私有证据副本。
- 新闻人工复核继续使用现有 `/research/evidence/{evidence_id}/reviews`；该路径语义保持仅限新闻。

### 8.3 P1-3 行情明细观察

#### 接口

1. `GET /stock/quotes`
2. `GET /stock/liquidity`

`/stock/quotes` 支持代码、市场、板块、行情时效状态和服务端分页；每项返回价格/盘口字段、Provider、endpoint、业务行情时间、接收时间、延迟、批次、Hash、fallback 状态和 observed-only 限制。

`/stock/liquidity` 返回成交量、成交额、换手或其他现有真实字段及各自单位、来源、时点和可用性。未验证 `amount` 时不把其用于 Research Readiness、排序或交易结论。

不得从单票接口发起前端 N+1 全市场查询，不得把当前配置的 100/5532 描述为全市场覆盖。

### 8.4 P1-4 系统运行可观测性

#### 接口

1. `GET /system/health`
2. `GET /system/alerts`
3. `GET /system/jobs`
4. `GET /system/audit-events`

`/system/health` 分离 infrastructure、data qualification 和 business release；某项健康不能替代其他两项。`/system/jobs` 只读已有任务与调度登记，不提供启动、停止或修改入口。`/system/audit-events` 支持事件类型、关联 ID、主体、时间范围和稳定分页。

系统告警、风险告警、数据资格阻断和发布锁必须使用不同类型，不能汇总成单一“正常”。

## 9. P2 任务准入

P2 仅在 P0、P1 全部通过后冻结具体契约。

### 9.1 研究聚合与持仓复评

预期页面：深度分析、排除与阻断、持仓再评估。

实施前必须确认：

- 每个维度的 Provider、PIT、available_at、用途许可和质量状态。
- 技术、财务、公告、新闻、行业、情绪、流动性和风险分开返回，不用单一综合分掩盖缺失。
- 当前持仓优先复评，但研究结论不直接生成订单。
- 任一关键维度失败时明确部分结果或阻断原因，不静默 fallback。

### 9.2 行业、板块与情绪

在 Provider、时间语义、覆盖范围和使用许可未确认前保持 `intentionally_pending`。首版只能 observed-only，不授予 Research Readiness，不作为独立交易触发。

### 9.3 AI 摘要与证据

AI 只读取已经登记的证据引用和资格状态。关键证据失败、过期、被拒绝或撤销时，不输出可操作 BUY/SELL；页面必须显示模型、调用版本、证据截止时间、限制和 recommendation-only 状态。

## 10. P3-0 已验收，P3 业务仍暂缓冻结

### 10.1 P3 影子运行与决策审计

P3-0 通用基础设施已完成最终验收，范围仅限 test-only shadow run、shadow decision、evidence/input lineage、只读审计接口、零写入隔离和迁移 `042`。验收记录见 `docs/superpowers/specs/2026-07-22-p3-0-final-acceptance.md`，状态账本见 `docs/superpowers/specs/2026-07-22-p3-0-status-ledger.md`。

该结论不代表完整 P3 或阶段 C 实时验收通过。策略治理状态不构成数据准入授权；正式固定样本、P3 input Profile、运行时间、时效阈值和稳定周期均未冻结，且 P3-1D 未找到合规 replay 数据源，正式 replay 保持 `blocked/deferred`。Sprint13 不得用于正式 replay；synthetic/test-only 仅用于工程验证，不得描述为真实历史 replay、模拟实盘或阶段 C 通过。`realtime_data_approved=false` 与 `P3_REALTIME_DATA_NOT_APPROVED` 必须继续保持 blocked。所有输出仍只记录系统“本来会做什么”，订单、执行、资金和持仓写入必须保持 0，六个发布和交易锁必须保持 false。

### 10.2 P4 Paper 订单与组合账务

页面包括范围化授权、开放订单、拒绝、成交、账户盈亏、归因、清算、对账和相关日志。必须先完成阶段 D 的明确授权、Execution Reference、模拟成交、费用、T+1、订单回报、会计和独立对账设计。

### 10.3 P5 盘后复盘与策略优化

页面包括每日复盘、交易复盘、错失机会、候选复核、策略变更审批和相关日志。必须有真实 Paper 账务闭环和足够运行样本；优化只能产生待审批候选，不能自动修改当前策略。

## 11. 单任务实施模板

后续每个任务开始前必须从本计划复制并填写：

1. 任务编号与对应阶段。
2. 目标页面和真实消费者。
3. 复用接口、新增接口及不做事项。
4. 数据源、Provider、PIT、available_at、Profile 和用途限制。
5. 请求参数、响应 schema、分页、排序、错误码和权限。
6. 数据库迁移是否必要；必要时只追加，不改写历史事实。
7. 后端、前端、迁移、脚本和文档的最小修改范围。
8. 定向测试、权限负测、数据故障测试、前端契约与浏览器验收。
9. 验收命令、真实证据和成功标准。
10. 功能、数据、配置和权限回滚方案。
11. 六锁状态及是否影响 Research/Backtest/Execution 边界。

存在会改变业务结果的歧义时，先向用户确认，不得自行选择。

## 12. 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| 路由契约 | 方法、路径、具体 schema、分页、枚举、错误码、OpenAPI |
| 身份权限 | 匿名、角色越权、scope、CSRF、过期/撤销主体 |
| 输入边界 | code、日期、adjustment、status、字段、分页和非法组合 |
| 数据语义 | observed/certified/readiness 隔离；PIT、Provider、Hash、版本 |
| 失败分类 | timeout、no_data、fetch_failed、validation_failed、rejected、revoked、stale |
| GET 安全 | 数据库零写入、零外部采集、零任务创建、零执行副作用 |
| 幂等并发 | 人工复核的幂等键、请求 Hash、并发重复提交 |
| 前端契约 | loading、empty、forbidden、error、timeout、unknown、分页与筛选 |
| 回归边界 | 六锁关闭、AI/Celery 订单为 0、现有 Readiness 不被改变 |
| 运行时 | doctor、标准启停、接口实调、浏览器逐页检查、日志脱敏 |

不能以 Mock、直接任务函数调用、手工改状态、HTTP 200 或合成数据代替真实链路验收。

## 13. 每项任务完成定义

单项任务只有同时满足以下条件才可标记完成：

1. 设计和契约已确认，实际实现与文档一致。
2. 页面只使用登记接口，真实成功、空态、失败、无权限和未知状态均正确。
3. 后端定向测试、权限负测、前端契约、typecheck 和 build 通过。
4. 需要真实运行时验证的接口已通过标准启动脚本、接口实调和浏览器验收。
5. 没有新增未经登记的路由、第三方依赖、静默 fallback 或数据权限传播。
6. 相关审计、request_id、业务时间和数据血缘可追踪。
7. 六锁保持预期状态；AI、Celery 和定时任务未创建订单。
8. 已报告实际完成、未完成、P0/P1/P2、回滚方式和下一任务准入结论。

## 14. 回滚原则

- 纯前端接入：移除对应读取 hook 和页面绑定，恢复真实“待接入”，不恢复原型假数据。
- 新增只读接口：移除路由与读取服务；已经存在的审计事实不删除。
- 追加式人工复核：停止新写入并移除入口，历史复核记录保留。
- 新增迁移：优先停用功能；存在真实记录时不通过 downgrade 删除数据。
- 配置与权限：恢复到任务前关闭状态，不通过放宽权限解决回滚问题。

## 15. 首个实施任务

用户确认本计划后，第一项实施任务固定为 **P0-1 财报页级候选人工复核**。开始编码前需进一步确认最小复核字段、角色/scope 名称和现有定位表的实际字段映射；该确认只影响 P0-1 具体实现，不改变本计划的总体优先级。
