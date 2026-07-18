# 旧接口遗留问题清零与新接口准入计划

状态：实施中；L0 已验收通过；L1 已验收通过；L2 正在实施  
日期：2026-07-16  
适用范围：主应用 API、WebSocket、内部 a-stock-data 接口、前端与 Worker 调用链

## 1. 决策摘要

本轮目标冻结为：

1. 先把现有接口的安全、语义、契约、调用、测试和弃用问题全部处理完。
2. 在旧接口清零验收通过前，不开发新的业务能力接口。
3. 为修复旧接口而必须新增的认证、审批、异步任务、详情查询或兼容替代端点，属于旧接口治理，不算新增业务能力。
4. 旧路由不能因仓内暂时无调用就直接删除；必须完成调用遥测、消费者确认、安全兼容和弃用流程。
5. 六个发布与交易锁继续关闭；本计划不授权回测、选股、Paper、Live、AI 或定时任务下单。

只有最终产出 LEGACY_API_CLEARANCE=PASS 的验收报告后，才能进入新接口设计与开发。

## 2. 当前审计基线

| 范围 | 当前数量 | 审计结论 |
| --- | ---: | --- |
| 主应用 /api/v1 HTTP | 60 | 9 个业务 Router，无完全重复 method + path |
| 主应用 /metrics | 1 | 当前公开，无独立访问控制 |
| WebSocket | 4 | 当前无认证、无频道授权，仓内无客户端 |
| 内部 a-stock-data HTTP | 11 | 路径未版本化，响应和错误语义不统一 |
| 合计接口边界 | 76 | 全部纳入本计划 |
| 前端实际消费 | 21 个方法、20 条路径 | 集中于 8 个页面；另 61 个页面仍为静态或 pending |
| 前端未消费 | 39 个主应用 HTTP 方法、4 个 WebSocket | 不等于可删除，Worker 和脚本仍使用其中部分写接口 |
| OpenAPI 响应契约 | 60 个 /api/v1 中 55 个成功响应为空 schema | 其余也仅为通用 Any 包装 |
| 现有后端测试 | 41 项通过 | 主要是源码字符串和局部契约，不能证明接口安全 |
| 现有前端契约测试 | 3 项 | 其中把响应时间当数据截止时间的错误语义已被固化 |

当前六个开关均为 false：

- CERTIFIED_BACKTEST_EXECUTION_ENABLED
- CERTIFIED_SCREENER_OUTPUT_ENABLED
- TRADING_EXECUTION_ENABLED
- LIVE_TRADING_ENABLED
- AI_ORDER_ENABLED
- ALLOW_SCHEDULED_ORDER

因此当前未发现绕过六锁直接产单的即时路径，但存在多项“一旦开锁即 P0”的条件风险。清零期间不得以“当前开关关闭”为理由跳过修复。

## 3. 范围与非目标

### 3.1 纳入范围

- 60 个 /api/v1 HTTP 操作、/metrics 和 4 个 WebSocket。
- 11 个 a-stock-data 内部接口及 backend DataClient 适配边界。
- 前端实际消费者、静态页面、Worker、Celery、脚本和本地启动验收。
- API 身份、权限、响应、错误、验证、分页、幂等、并发、审计、版本、弃用和可观测性。
- 行情、研究证据、回测、选股、策略、风险、组合、交易和 AI 的安全语义。
- 必要的追加式数据库迁移、ADR、契约测试、故障注入和验收脚本。

### 3.2 不纳入范围

- 不新增新的交易、策略、研究或组合业务能力。
- 不开启任何发布或交易锁。
- 不接真实资金，不把 AI 接到订单。
- 不用 Mock、Synthetic、fallback 或旧成功记录伪造通过。
- 不重写 a-stock-data Provider；仅治理本项目依赖的接口和适配契约。
- 不新增第三方依赖，除非后续单独说明必要性并取得确认。
- 不清理、覆盖或重置当前工作区已有修改。

## 4. 问题分级

### 4.1 P0：发布和开锁硬阻断

| 编号 | 问题 | 必须达到的目标 |
| --- | --- | --- |
| P0-01 | 生产缺少 API_KEY 时仅告警，全部接口继续放行 | 生产认证配置缺失必须启动失败；写接口在所有环境都不得匿名 |
| P0-02 | 浏览器内嵌 VITE_API_KEY，且没有真实用户、角色和服务身份 | 浏览器使用服务端会话；Worker 使用独立服务凭证；角色和 Scope 最小授权 |
| P0-03 | WebSocket 全部匿名开放 | 握手认证、Origin 校验、频道级权限、连接审计 |
| P0-04 | 任意非空 approval_id 即被视为人工批准 | 审批由服务端生成并绑定动作 Hash、模式、请求者、审批者、有效期和状态 |
| P0-05 | 熔断恢复可自填 approved_by，Live 撤单无等价强授权 | 恢复、撤单和高风险运维必须强认证并校验审批记录 |
| P0-06 | DB 异常且 Redis 无有效缓存时，熔断状态返回未熔断 | DB、Redis 或状态不可判定时一律 blocked/unknown，禁止执行 |
| P0-07 | Live 订单先提交券商、后写本地数据库 | 先持久化订单意图和幂等键，再调用券商；异常可恢复、自动熔断并对账 |
| P0-08 | 数据认证状态由订单请求方自报 | 只接受服务端生成、可验证且未过期的执行数据授权引用 |

### 4.2 P1：正确性、语义和操作风险

| 领域 | 已确认问题 |
| --- | --- |
| 统一契约 | 拒单和风控拒绝被包装为 HTTP 200、外层 success=true；错误至少有三种结构；底层异常文本直接泄露 |
| 输入与分页 | mode、status、adjustment 等未枚举；多处 limit/page_size 缺下界；多处 total 实际只是当前页长度 |
| 交易 | 人工订单幂等键永久误伤合法重复订单；MARKET 单可绕过 LIVE_MAX_ORDER_VALUE；拒绝尝试未形成完整持久化审计 |
| 风险 | 风控使用未认证或不够新鲜的行情；上市日期未知可放行；规则读取失败静默回配置；pre-check 与真实下单规则不一致 |
| 回测 | 未真正启用 trusted_mode、认证日历、未来函数检查和 PIT 企业行动；结果缺 dataset、策略、规则、费用、引擎和结果 Hash |
| 数据 | 普通 K 线混用 legacy、内部服务和 Sina fallback；hfq/非法 adjustment 可能静默返回 raw；失败与真实空数据都可能折叠为空 |
| 研究 | 最新 rejected/failed 可被旧 observed/success 掩盖；来源许可最新复核排序不正确；observed_only 标志与返回内容矛盾 |
| Sprint14.9 | 解析失败缺失败审计；快照缺失或损坏缺显式修复；网络响应缺硬上限和稳定错误分类；专项验收脚本不完整 |
| 选股 | 主题选股直接读取 legacy 公告，绕过 Evidence Profile、来源许可和当前人审；缓存未绑定数据与审核版本 |
| AI | 子源失败被吞掉；未审新闻和财报可进入上下文；tradable 仅由日 K 状态推断；缓存命中不重验当前 Readiness |
| 策略 | JSON 损坏静默恢复默认，默认可启用；参数无 schema；写文件无锁、无版本、无审计；回测不检查 enabled |
| 组合 | GET /portfolio/positions 会释放 T+1 并写库；报价失败后用 raw K 线或成本价冒充当前估值 |
| 长任务 | 股票同步/回填、AI 分析、回测在 HTTP 请求内完成；券商同步/对账也缺统一任务语义 |
| Research payload | evidence 列表内嵌全部快照、解析和页级定位，page_size 可达 200，响应和 SQL 聚合可失控 |

### 4.3 P2：治理、前端和维护一致性

- 绝大多数接口没有具体 response model。
- Health 在数据库失败时仍返回 200，并返回底层错误文本；liveness 与 readiness 未分开。
- API Docs、OpenAPI 和 metrics 的生产暴露策略未冻结。
- API 版本硬编码，无 Deprecation、Sunset、Link 和兼容策略。
- 动作式与资源式命名混用，旧 create/update 兼容接口仍承载独立逻辑。
- 策略、行情、AI、风险、组合等响应字段与前端类型存在漂移。
- 前端把响应生成时间当数据截止时间，把 unknown/unavailable 显示成 false、0、关闭、通过或未使用。
- 前端安全状态只在挂载时请求，整次会话可能永久陈旧。
- 前端列表是固定第一页加本地切片，不能访问后端其余数据。
- AI signals 被前端错标为 Agent 调用日志。
- 人工复核提交无幂等键；已写库但响应超时时，重试会追加重复记录。
- WebSocket 成交事件可能把请求总数量误报为已成交数量。
- candidate-status 只凭开关宣称 published，未绑定候选快照或 Hash。
- 无仓内调用的接口缺少访问遥测，当前没有可直接安全删除的证据。

## 5. 目标接口治理基线

### 5.1 身份与权限

推荐采用现有依赖和标准库可实现的最小方案：

- 人工用户：服务端保存 Hash 后的随机凭证，登录后换取 HttpOnly、Secure、SameSite 会话；写请求校验 CSRF。
- 服务调用：Worker 使用单独的可轮换服务凭证，不复用人工会话，不进入浏览器构建。
- 最小角色：viewer、data_operator、research_reviewer、strategy_admin、risk_admin、trader、auditor、service_worker。
- 每个路由声明所需 Scope；拒绝记录 actor_id、credential_id、request_id 和原因。
- Health liveness 可公开；readiness、OpenAPI、Docs、metrics 是否公开由环境策略显式决定。
- 生产缺失认证配置、会话密钥或服务凭证时启动失败。

### 5.2 响应与错误

所有活动 HTTP 接口必须：

- 有具体请求和响应模型，不再使用 Any 作为最终公开契约。
- 成功响应统一包含 data、message、timestamp、request_id 和 contract_version。
- 失败响应统一包含 error_code、message、request_id、retryable 和可选 field_errors。
- 认证、权限、校验、资源不存在、冲突、门禁拒绝、上游失败和内部错误使用稳定 HTTP 状态。
- 门禁拒绝不得使用外层 success=true；底层异常不得原样返回。
- 422 detail 数组、鉴权失败和业务错误由全局异常处理器统一。
- 对追加式审计列表使用稳定排序和游标；普通资源列表返回真实 total。

### 5.3 数据与执行授权

- observed、certified、research_eligible、backtest_authorized、execution_authorized 分层，任何上一层都不自动授权下一层。
- Provider、source、endpoint、retrieved_at、available_at、raw_hash、quality_status、usage_status、fallback_used 和版本按用途显式返回。
- unknown、synthetic、uncertified、stale、missing、rejected 和 revoked 一律 fail closed。
- 订单不接收调用者自报的 data_certification_status；只接收服务端签发的 authorization reference。
- AI 始终是 recommendation，不得出现可被理解为订单授权的 tradable=true。

### 5.4 异步任务

复用现有 Celery 和数据库，不另建任务平台：

- 创建长任务返回 202、job_id 和 Location。
- 任务记录输入 Hash、调用者、状态、进度、结果引用、错误码、重试次数和时间。
- 客户端提供 Idempotency-Key；相同意图重复请求返回同一任务。
- 提供状态、结果和受权限控制的取消；客户端断开不影响任务审计。
- 股票同步/回填、AI 分析、回测、券商批量同步和对账迁入统一任务模型。

### 5.5 弃用

- 先加入路由级调用遥测和消费者标识，再判断是否弃用。
- 旧路由在兼容期只能转发到唯一的新实现，不保留第二套业务逻辑。
- 兼容响应必须同样安全、可鉴权、可审计，并返回 Deprecation、Sunset 和 successor Link。
- 外部消费者未确认前不直接删除；最终清零报告必须列明每个旧路由是活动、兼容适配还是已移除。

## 6. 全量接口处置矩阵

处置代码：

- K：保留并原位修复契约与语义
- J：改为异步 Job，旧路径只做安全兼容
- A：隔离为高权限管理或审批能力
- S：拆分摘要列表与详情
- D：弃用候选，先遥测和迁移
- I：仅限内部服务，不作为公共 API

### 6.1 主应用 HTTP

| 模块 | 现有接口 | 处置 | 目标 |
| --- | --- | --- | --- |
| system | GET /api/v1/health | K | 兼容入口；内部区分 live/readiness，依赖失败返回非 2xx readiness |
| stock | GET /stock/market/status | K | 补真实 fallback、覆盖、截止时间和质量状态 |
| stock | GET /stock/market/batches | K | 返回每批自己的来源、fallback、Hash、状态和真实分页 |
| stock | POST /stock/sync-universe | J/A | data_operator 创建任务，禁止请求内全市场同步 |
| stock | GET /stock/list | K | 明确快照时间、来源、覆盖和分页 |
| stock | POST /stock/backfill-kline | J/A | data_operator 创建任务；Synthetic 仅隔离测试环境 |
| stock | GET /stock/{code}/profile | K | 股票代码规范化，补来源和 as_of |
| stock | GET /stock/{code}/quote | K | 仅 observed display；显式 provider、freshness 和 fallback |
| stock | GET /stock/{code}/kline | K | 明确 legacy/observed/certified；period/adjustment 枚举，禁止静默 raw |
| stock | GET /stock/{code}/fund-flow | K | 区分 no_data 与 fetch_failed，返回来源和时点 |
| stock | GET /stock/{code}/news | K/S | 展示查询与 Research Evidence 分层；列表不伪装为已认证研究 |
| ai | GET /ai/signals | K | 明确信号不是 Agent 调用日志；返回当前有效性和数据授权状态 |
| ai | GET /ai/audit-summary | K | 补真实授权拒绝审计和模型调用语义 |
| ai | POST /ai/{code}/analyze | J | 创建分析任务；输入 Hash、额度、身份和结果血缘可审计 |
| ai | GET /ai/{code}/latest-signal | K | 每次读取重验当前 Readiness、revocation 和有效期 |
| ai | GET /ai/{code}/signal-history | K | 稳定分页，保留当时与当前两套资格状态 |
| screener | POST /screener/screen | K | 计算接口；门禁拒绝使用明确非成功状态，缓存绑定授权版本 |
| screener | GET /screener/presets | K | 具体 schema、版本和只读来源 |
| screener | POST /screener/theme | K | 只读 Evidence/Profile，不再读取 legacy 公告 |
| strategy | GET /strategy/list | K/D | 迁移到版本化资源，旧路径成为只读适配 |
| strategy | GET /strategy/runtime-status | K | 返回实际版本 Hash、enabled、审批和运行资格 |
| strategy | GET /strategy/{strategy_type} | K/D | 返回不可变版本；旧路径适配当前版本 |
| strategy | POST /strategy/create | D/A | 替换为受权的版本创建，不再覆盖内置策略 |
| strategy | POST /strategy/{strategy_type}/update | D/A | 替换为新版本提交加乐观锁，不原地覆盖 |
| backtest | POST /backtest/run | J | 202 创建可信回测任务 |
| backtest | GET /backtest/tasks | K | 真实 total、稳定分页和可信状态摘要 |
| backtest | GET /backtest/validation-summary | K | 只依据持久化 Hash 和独立 Reference，不把缺失当通过 |
| backtest | GET /backtest/{task_id}/status | K/S | 状态与大结果分离，权限校验和结果引用 |
| risk | GET /risk/rules | K | 返回规则版本、Hash、来源和生效时间 |
| risk | GET /risk/fuse-status | K | unknown 即 blocked，返回状态版本和证据 |
| risk | GET /risk/exposure | K | mode 枚举；价格来源、as_of、freshness 和 stale |
| risk | POST /risk/fuse/activate | A | risk_admin，幂等并追加审计 |
| risk | POST /risk/fuse/recover | A | 服务端审批记录、强身份、并发版本检查 |
| risk | GET /risk/alerts | K | 持久化审计、稳定分页 |
| risk | GET /risk/alerts/summary | K | 与持久化告警同源，不仅依赖 Redis |
| risk | POST /risk/pre-check | K/D | 迁移为统一 ExecutionGate dry-run，避免第二套规则 |
| risk | POST /risk/alerts/test-dingtalk | D/A | 移到受限运维命令或 admin-only 集成测试 |
| risk | GET /risk/dashboard | K | 所有字段同一 as_of，unknown 不变成安全 |
| trade | POST /trade/order | A | trader、服务端审批和数据授权、拒绝审计、正确 HTTP 状态 |
| trade | POST /trade/simulation/release-t1 | D/A | 移出普通业务面；默认不得 force_all |
| trade | POST /trade/order/cancel | A | 资源化取消、审批与模式一致，Live 强授权 |
| trade | GET /trade/orders | K | 真实 total、游标/稳定分页、模式和状态枚举 |
| trade | GET /trade/orders/{order_id} | K | 所有权/Scope 校验和完整状态时间线 |
| trade | POST /trade/orders/sync | J/A | 批量券商同步任务 |
| trade | POST /trade/orders/{order_id}/sync | A | 单订单受控同步，幂等和审计 |
| trade | GET /trade/mode | K | 返回配置模式、实际可用模式和阻塞原因 |
| trade | GET /trade/broker-status | K | 统一前后端字段，脱敏路径和账户信息 |
| trade | GET /trade/execution-status | K | 六锁、身份、审批、数据授权和依赖状态的同一快照 |
| trade | POST /trade/reconcile | J/A | 受控对账任务，产生不可变差异报告 |
| portfolio | GET /portfolio/summary | K | 快照时间、估值来源和 stale 状态 |
| portfolio | GET /portfolio/positions | K | 删除 T+1 写副作用；只读快照 |
| portfolio | GET /portfolio/equity-curve | K | 数据版本、as_of 和真实空数据语义 |
| research | GET /research/source-usage-evidence | K | 最新条款后再验证复核，不掩盖 rejected |
| research | GET /research/readiness | K | 精确 Profile、当前状态和稳定分页 |
| research | GET /research/evidence | S | 仅摘要列表；状态标志与实际过滤一致 |
| research | GET /research/evidence/readiness-audit | K | 当前最新事实优先，失败和拒绝不可被旧成功覆盖 |
| research | GET /research/evidence/batches | K | 批次自己的状态、失败原因和分页 |
| research | GET /research/evidence/{evidence_id}/reviews | K | reviewable 状态明确，身份和当前决定可验证 |
| research | POST /research/evidence/{evidence_id}/reviews | A | research_reviewer、幂等键、服务端身份、追加式审计 |
| research | GET /research/candidate-status | K | 绑定候选快照、Hash、Profile 和实际发布记录 |

### 6.2 监控与 WebSocket

| 现有接口 | 处置 | 目标 |
| --- | --- | --- |
| GET /metrics | A | 仅监控身份或内网可访问，生产暴露策略显式化 |
| WS /ws/quotes/{stock_code} | K/D | 认证、代码校验、频道 Scope、事件版本；无消费者时进入弃用评审 |
| WS /ws/signals | K/D | 认证并重验信号资格；无消费者时进入弃用评审 |
| WS /ws/alerts | K/D | 仅风险/审计角色，频道隔离；无消费者时进入弃用评审 |
| WS /ws/portfolio | K/D | 账户和 mode 级授权；无消费者时进入弃用评审 |

### 6.3 内部 a-stock-data

| 现有接口 | 处置 | 目标 |
| --- | --- | --- |
| GET /health | I/K | 内部 typed health，区分 live/readiness |
| GET /stock/list | I/J | force_refresh 拆为任务；查询只读快照 |
| GET /quote/{code} | I/K | 始终统一 envelope 和 provenance，不返回裸对象 |
| GET /quotes | I/K | 批量上限、逐项状态、统一 meta；禁止无声单票 fallback |
| GET /kline/{code} | I/K | period/limit 校验；明确 observed 与 adjustment，不授予 certified |
| GET /fund-flow/{code} | I/K | 错误分类、来源和时点 |
| GET /announcements/{code} | I/K | 固定 Provider、Hash、available_at、大小上限 |
| GET /financial-reports/{code} | I/K | 固定 Provider、原文 Hash、快照/页定位状态和大小上限 |
| GET /news/{code} | I/D | legacy generic news 仅兼容展示，不能进入 Research Readiness |
| GET /news-evidence/{code} | I/K | 固定范围和 usage 状态，禁止扩大到新闻正文 |
| GET /financial/{code} | I/D | legacy 数值事实与新财报证据分离，不能作为可信研究事实 |

内部接口统一迁入版本化内部前缀；旧路径在迁移期只保留安全适配。DataClient 不再把 timeout、HTTP error、no_data 和 malformed_response 全部折叠为 None。

## 7. 开发顺序

### 阶段 L0：基线冻结与消费者清单

目标：防止边修边漂移，并保护当前大规模未提交工作。

任务：

1. 固化 76 个接口的机器可读清单、OpenAPI 快照、方法、风险级别、Owner、消费者和处置状态。
2. 扫描前端、Worker、Celery、脚本和 a-stock-data 调用；给每个请求增加调用者标识和路由遥测。
3. 为当前 95 项工作区变化建立只读归属清单；未经用户授权不提交、不暂存、不清理。
4. 增加“旧接口治理期间禁止新增业务路由”的 CI 契约检查。
5. 记录当前 41 项后端测试、3 项前端契约测试和现有专项脚本基线。

验收：

- 76 个接口全部可追踪，无未知 Owner。
- 路由新增或删除会使快照测试失败。
- 当前用户修改未被覆盖。

### 阶段 L1：统一契约、身份和权限

目标：先建立所有后续修复共同依赖的安全地基。

任务：

1. 新增身份与权限 ADR，冻结人工会话、服务凭证、角色、Scope、CSRF、WebSocket 和生产启动策略。
2. 新增统一响应、错误码、全局异常处理、request_id、分页、枚举和版本模型。
3. 给 60 个 /api/v1、11 个内部接口和 4 类 WebSocket 事件补具体契约。
4. 移除 VITE_API_KEY；迁移 Worker 到独立 service_worker 凭证。
5. 为 WebSocket 增加握手认证、Origin、频道权限、心跳、断线和事件版本。
6. 分离 liveness/readiness；限制 Docs、OpenAPI 和 metrics。

验收：

- 生产缺失认证配置启动失败。
- 匿名写、越权角色、过期/撤销凭证、CSRF 和跨频道订阅均被拒绝并审计。
- 60 个主接口成功与失败响应均有非 Any schema。
- 401、403、404、409、422、429、502、503 和门禁拒绝结构一致。
- 前端与 Worker 完成新身份链路，不再依赖浏览器共享密钥。

### 阶段 L2：交易、风险和审批 P0 清零

当前进度：已完成熔断和风险规则读取 fail-closed、追加式审批/订单意图/outbox 迁移（025）、服务端审批 Hash/主体/期限/认证数据批次校验、券商调用前 outbox 持久化、订单请求旧授权字段拒绝、Worker 与命令行直接下单旁路关闭，以及 L2 静态契约验收脚本。尚待 Docker 数据库迁移、受控运行时和券商恢复路径验收；取消、熔断恢复与对账的同等审批边界仍待收口。

目标：即使未来开锁，也不存在可伪造审批、fail-open 或不可追踪 Live 单。

任务：

1. 建立追加式审批记录，绑定 action_type、payload_hash、mode、requester、approver、expiry、status 和 policy_version。
2. 订单数据资格改为服务端 execution authorization reference，移除客户端自报状态。
3. 熔断状态在 DB、Redis、解析或版本异常时 fail closed。
4. Live 下单改为“先持久化意图与幂等键，再提交券商”，增加 outbox/recovery/reconcile 状态机。
5. 撤单、熔断恢复、T+1 运维和对账接入同一强授权与审计。
6. 拒单返回正确外层状态并持久化 attempt；Worker 不再只检查外层 success。
7. MARKET 和 LIMIT 都用可信执行参考检查单笔上限。
8. 修正人工订单幂等：客户端意图键有明确作用域和有效窗口，合法重复订单不永久冲突。

验收：

- 伪造 approval_id、approved_by、data status 全部失败。
- DB、Redis、行情、规则、审批任一不可用，订单均不发送。
- 注入“券商已接受、本地后续故障”，系统能恢复意图、自动熔断并形成对账记录。
- 六锁全组合负测通过，AI 和 Celery 订单数为 0。
- Live 仍保持关闭。

### 阶段 L3：数据与 Research 当前事实修复

当前进度：已新增 backend/Worker 类型化数据读取结果并保留兼容方法；DataService 已消费类型化结果且移除未追踪 Sina K 线 fallback；研究来源查询改为先取最新条款，再取该条款的最新复核；新闻人工复核已绑定认证主体、幂等键和请求 Hash（迁移 026）。上游 a-stock-data 的统一 envelope、参数收紧、失败批次覆盖旧事实、安全抓取、详情拆分及运行时迁移验收仍待完成。

目标：旧展示数据、证据数据和授权数据完全分层，最新失败或拒绝不可被隐藏。

任务：

1. 统一 a-stock-data 与 DataClient 的 typed result，保留所有失败类别和 provenance。
2. 删除 K 线、新闻、财报和资金流的无声 fallback；确需展示 fallback 时明确标为 observed-only。
3. 修正 adjustment、period、code、limit、date 等校验；非法值不得静默返回 raw。
4. 修正 Research 的“先取最新，再判断状态”逻辑，以及来源许可复核排序。
5. 修正 observed_only、usage_status、reviewable 和 candidate published 语义。
6. 为 parse failure 写失败审计；增加快照缺失/损坏的显式 refetch repair。
7. 对网络响应设置字节、类型、重定向、超时和 Hash 验证上限，稳定分类错误。
8. evidence 拆摘要列表和单条详情；页级定位按需加载。
9. 人工复核绑定已认证 reviewer，并增加幂等提交。

验收：

- 最新 rejected/failed 一定覆盖旧 observed/success。
- timeout、no_data、fetch_failed、validation_failed、rejected 和 revoked 可区分。
- legacy/observed 数据不能进入 certified、Research Readiness、回测、选股或执行。
- Sprint14.9 所有阻断项和专项验收脚本闭环。
- 现有证据历史不改写，六锁和 ready=0 基线不被静默改变。

### 阶段 L4：统一异步 Job 与可信回测

目标：清除同步长请求，并补齐回测可信性而不开放公共回测。

任务：

1. 复用 Celery 建立统一持久化 Job 模型。
2. 迁移股票同步、K 线回填、AI 分析、回测、券商批量同步和对账。
3. 增加 202、Location、状态、结果、取消、幂等、进度和失败重试契约。
4. 回测强制 trusted_mode、认证交易日历、PIT 企业行动、未来函数检查和明确 strategy_code。
5. 持久化 dataset、requirement profile、策略参数、规则、费用、引擎、Reference 和结果 Hash。
6. 历史缺失 Hash 的任务明确标为 legacy_unverifiable，不补造证据。

验收：

- HTTP 断连或重试不会重复创建任务。
- 任务可恢复、可取消、可审计，状态和结果分离。
- 缺任一可信输入时回测 fail closed。
- 固定样本独立 Reference 差异为 0；未来函数、未认证日历和未授权 Profile 负测通过。
- CERTIFIED_BACKTEST_EXECUTION_ENABLED 仍为 false。

### 阶段 L5：AI、选股、策略、组合和风险一致性

目标：消除剩余领域旁路、缓存陈旧和读写混杂。

任务：

1. AI 将 tradable 改为 research_eligible 或固定 false；每次缓存命中重验当前门禁和 revocation。
2. 任何关键子源失败、降级或未授权时，AI 不输出可操作 BUY/SELL。
3. 主题选股只读 Evidence/Profile；所有缓存键绑定数据、规则、审核和授权版本。
4. 策略配置改为不可变版本、参数 schema、乐观锁、审批和审计；损坏不回默认启用；回测检查 enabled。
5. 删除 GET /portfolio/positions 的写副作用；T+1 释放迁入确定的结算任务。
6. 组合与风险估值返回 source、as_of、freshness、stale；成本价不得伪装当前市价。
7. 风控 pre-check 复用实际 ExecutionGate dry-run，删除第二套手数和模式规则。
8. 关键风险告警持久化；修正订单事件 filled_quantity。

验收：

- Readiness 撤销后 AI/选股缓存立即失效。
- Strategy disabled、配置损坏和参数非法均 fail closed。
- 所有 GET 在数据库写入监控下为零写操作。
- unknown/stale 报价不产生通过、当前估值或可执行结论。

### 阶段 L6：前端迁移与既有页面接回

目标：前端不再掩盖后端错误，并把已有安全接口接到已有原型页面。

任务：

1. 更新唯一 Axios 客户端：严格校验 success、统一解析 field_errors、422 数组、timeout、取消和 request_id。
2. 修正 broker status、risk exposure、candidate lock 和 portfolio snapshot_time 字段漂移。
3. 禁止用 wrapper timestamp 代替 data_cutoff。
4. unknown/unavailable 显示未知或不可用，不再显示 0、关闭、通过或未使用。
5. 安全状态支持规定刷新窗口、手动刷新和失效；断线时顶部不得默认 SIMULATION。
6. 改为服务端分页和搜索；total 大于 page_size 时必须能访问后续页面。
7. 将已有 orders、positions、risk、strategy、research、stock 接口接回现有页面，不新增业务页面。
8. 修正 AI 信号与 Agent 调用审计的标签和数据源。
9. WebSocket 若保留，则接入认证、重连、事件版本和 stale 展示；否则完成弃用证据。
10. 人工复核只允许 reviewable 行，超时重试保持幂等。

验收：

- 401/403/404/409/422/500/timeout/cancel/200 success=false 都显示正确失败态。
- 任一锁或 mode 变化在规定刷新窗口内全局一致；接口断开时显示 unknown。
- 不同历史批次显示自己的 fallback 和时点，缺字段显示未记录。
- total 大于 page_size 时可访问第二页，UI 不声称本地切片是全量。
- 69 个页面逐项标记 connected、intentionally_pending 或 deprecated，无伪造数据。

### 阶段 L7：弃用收口与全量验收

目标：所有旧路由都有最终归宿，形成允许开发新接口的唯一准入结论。

任务：

1. 依据调用遥测和消费者确认，逐项确定活动、兼容适配或移除。
2. 将 strategy create/update、simulation release-t1、DingTalk 测试和无人使用 WebSocket 作为首批弃用评审对象。
3. 兼容路由只转发到单一安全实现，加入 Deprecation/Sunset/Link 和调用告警。
4. 删除确认无消费者的死代码、无界兼容分支和旧响应适配；不删除审计历史。
5. 新建 scripts/verify_legacy_api_clearance.ps1，编排契约、安全、数据、回测、前端、WebSocket、故障注入和运行时验收。
6. 运行标准 start-local/stop-local 周期，验证 Watchdog、端口、运行登记和日志边界。
7. 生成旧接口清零 Tracking Report，列出 76 个接口最终状态和证据。

验收：

- P0、P1、P2 未解决项均为 0。
- 无未知 Owner、未知消费者或无期限兼容接口。
- 所有活动接口、兼容接口和内部接口都有契约、权限、测试、审计和回滚。
- 后端全量测试、前端契约/typecheck/build、专项脚本和真实运行时验收全部通过。
- 六锁关闭，AI/Celery 订单为 0，无真实资金路径。
- Tracking Report 明确写出 LEGACY_API_CLEARANCE=PASS。

### 阶段 N0：新接口开发

只有 L7 通过后才开始。进入时需重新从长期目标选择第一项新业务能力，单独完成设计、数据授权、权限、测试和回滚确认。不得把旧接口兼容代码复制到新接口，也不得用新版本路径隐藏未修复的旧逻辑。

## 8. 新接口准入硬门禁

| 门禁 | PASS 条件 |
| --- | --- |
| G0 接口账本 | 76 个现有接口全部有 Owner、消费者、处置和测试 |
| G1 契约 | 所有活动接口有具体 schema、统一错误、稳定版本和分页 |
| G2 身份 | 无浏览器共享密钥；人工、服务、WebSocket 和管理权限分离 |
| G3 安全 | 审批不可伪造，熔断 fail closed，Live 意图先落库，拒绝可审计 |
| G4 数据语义 | observed/certified/readiness/backtest/execution 不传播；最新失败优先 |
| G5 领域正确性 | 回测、AI、选股、策略、组合、风险不存在已知旁路 |
| G6 前端 | unknown 不伪装安全，字段、分页、时点、刷新和错误状态真实 |
| G7 弃用 | 每条旧路由为活动、单一安全适配或已移除，无未知消费者 |
| G8 回归 | 自动测试、故障注入、真实启动停止和安全锁验收全部 PASS |

G0 至 G8 必须全部通过；任何一项 BLOCKED 或 FAIL 都不得开始新业务接口。

## 9. 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| 路由契约 | 60 个 /api/v1、/metrics、11 个内部接口、4 个 WS 的方法、schema、错误和版本 |
| 身份权限 | 匿名、角色越权、Scope、过期/撤销、CSRF、Worker 凭证、WS 频道隔离 |
| 输入边界 | code、mode、status、period、adjustment、日期、分页、大小、枚举和非法组合 |
| 幂等并发 | 下单、审批、复核、策略版本、Job、熔断恢复和券商同步 |
| GET 安全性 | 每个 GET 在数据库审计下零写入、零外部运维副作用 |
| 数据故障 | Provider timeout、空数据、坏 JSON、Hash 变化、fallback、stale、revoked |
| Research | 最新 rejected/failed、解析失败、修复、复核身份、usage 和 Profile 隔离 |
| 回测 | trusted calendar、PIT 企业行动、未来函数、费用、规则、Hash 和 Reference |
| 交易风险 | 六锁组合、审批伪造、熔断故障、MARKET 上限、券商成功/DB 失败 |
| AI/选股 | 子源失败、Readiness 撤销、缓存失效、legacy 公告旁路和零订单 |
| 前端 | 契约 fixture、失败态、unknown、刷新、分页、时点、取消和复核幂等 |
| 运行时 | doctor、标准启动停止、Watchdog、端口、运行登记、日志与资源释放 |

## 10. 预计产出

- 本计划对应的接口治理、身份权限、执行审批和异步任务 ADR。
- 下一可用编号的追加式数据库迁移；不改写现有审计事实。
- 机器可读接口账本与 OpenAPI 快照。
- 统一 response/error/auth/pagination/job 基础模块。
- 9 个业务 Router、WebSocket、DataClient 和 a-stock-data 的最小必要修改。
- 前端 client、类型、coreModels 和既有页面的契约迁移。
- 后端 HTTP/WS 集成测试、内部服务契约测试、前端契约测试和故障注入测试。
- scripts/verify_legacy_api_clearance.ps1。
- 旧接口清零 Tracking Report。

## 11. 实施注意事项与回滚

1. 当前工作区有大量已修改和未跟踪文件，实施前先建立文件归属清单；不得 reset、clean 或覆盖。
2. a-stock-data 是已有改动的子模块，只做经确认的接口契约修改，主仓和子模块版本必须成对记录。
3. 数据库迁移优先追加表、列和索引；真实审批、订单、证据和审计记录不得通过 downgrade 删除。
4. 身份切换先配置人工和服务凭证、迁移调用者，再开启强制校验；生产环境不得保留匿名兼容窗口。
5. 响应迁移期间旧路由只做薄适配，业务逻辑保持单一来源；适配也必须 fail closed。
6. 异步任务失败可停用新任务创建并保留已写记录，不回退到同步长请求。
7. Live、AI 下单和定时任务下单始终关闭；任何开锁另立任务和验收。
8. 每阶段独立提交、独立 Tracking Report、独立回滚；前一阶段未 PASS 不进入下一阶段。

## 12. 完成定义

旧接口清零不是“接口能返回 200”，而是同时满足：

- 76 个接口边界全部有明确归属。
- 所有已确认 P0、P1、P2 均已修复、移除或收敛为有截止条件的安全薄适配。
- 没有匿名写、伪造审批、客户端自报授权、fail-open、GET 写库或不可追踪 Live 单。
- 没有旧数据、fallback、unknown 或旧成功记录冒充可信当前事实。
- 没有同步长任务、永久幂等冲突、假 total、假分页或不统一错误。
- 前端不再把未知显示为关闭、通过、零或未使用。
- 所有验证来自真实测试、故障注入和标准运行命令。
- 安全锁保持关闭，原始长期目标和数据边界不变。

满足以上全部条件后，旧接口阶段结束，下一任务才能开始新接口开发。
