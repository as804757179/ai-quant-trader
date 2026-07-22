# P3-0 决策与契约包

状态：决策冻结准备与契约草案；不是 P3 实施、不是阶段 C 实时验收。

核查范围：当前有效代码、配置、迁移、测试与版本文档。未启动服务、未调用外部 Provider、未查询运行中数据库；因此“可调用”仅表示代码路径存在，运行可用性均按“未验证”处理。

## 1. 已确认事实

### 1.1 P3 当前实现边界

- P3 在当前开发计划中仍为“延后设计 / 阶段 C 准入”；接口只可在固定样本实时影子盘准入后设计，且订单数必须保持 0：`docs/superpowers/specs/2026-07-18-new-api-page-integration-development-plan.md` 第 150、335-337 行。
- P3 相关前端路由已经存在，但均明确显示“接口待接入”：`frontend/src/pages/trading/TradePages.tsx` 第 77 行、`frontend/src/pages/review/ReviewPages.tsx` 第 45-46 行、`frontend/src/pages/logs/LogPages.tsx` 第 29-30 行。
- 本轮未找到后端 P3 shadow-run / shadow-decision 领域模型、迁移或 API 实现。现有 `worker/services/signal_scan.py` 是 AI 建议扫描，不是 P3：它从动态策略与股票池读取、调用 AI，发布 recommendation；虽然 `order_created=false`，但不满足固定样本、规则策略、输入快照与影子决策契约。

### 1.2 固定股票样本证据

| 定义 | 证据路径 | 数量与名单/规则 | 当前代码引用 | 可重复生成 | PIT | 可冻结和版本化 |
| --- | --- | --- | --- | --- | --- | --- |
| Sprint13 历史工程验证集 | `config/datasets/sprint13_universe.yaml`；`backend/scripts/import_sprint13_dataset.py` 第 42-66 行 | 10 只：`600519.SH, 601318.SH, 600276.SH, 000001.SZ, 000333.SZ, 002415.SZ, 300308.SZ, 300750.SZ, 688981.SH, 600036.SH`；固定日期 `2025-07-01..2026-06-30`、raw 日线 | 是，导入脚本读取该 manifest | 是，文件 `frozen: true` 且脚本校验 10 只、日期、Provider 与 Hash | 未证明为 P3 PIT 样本；其用途字段为 `engineering_validation_not_investment_universe`，仅声明不以目标期收益选择 | 已作为历史 manifest 冻结；不能据此推导已存在 P3 样本版本 |
| Sprint06 认证历史小样本 | `backend/scripts/import_certified_pilot.py` 第 23、38-40 行；`docs/adr/ADR-003-certified-historical-data-ingestion.md` | 3 只：`300308.SZ, 603986.SH, 300502.SZ`；`2026-06-01..2026-06-30` 日线 | 是，脚本常量 | 是，常量可重复执行 | 只支持该历史导入的 provenance/certification；不是实时或 P3 PIT 样本 | 未以 manifest 或样本版本登记；不可直接视为 P3 冻结版本 |
| Sprint07 认证历史单股 | `backend/scripts/import_sprint07_certified_store.py` 第 13-33 行 | 1 只：`603986.SH`；`2026-06-01..2026-06-30` 日线 | 是，脚本限制入参 | 是，常量和 CLI choices 固定 | 同上，仅历史日线 | 未以 P3 样本版本登记 |
| 财报 observed 证据样本 | `scripts/collect_financial_report_evidence.py` 第 14 行；`scripts/verify_financial_report_evidence.ps1` 第 10 行；`docs/superpowers/specs/2026-07-15-financial-report-evidence-observation.md` 第 26-31、71-74 行 | 2 只：`000001.SZ, 600000.SH`；每次最多各 1 份最新年报全文 | 是，只读财报证据采集/验证 | 是，固定常量 | 不具备行情或策略 PIT；财报使用状态仍为 `review_required` | 未冻结为 P3 样本；文档本身要求另行确认 |
| 新闻 observed 证据样本 | `scripts/collect_news_evidence.py` 第 14、36、46 行；`scripts/verify_news_evidence.ps1` 第 10 行 | 2 只：`002594.SZ, 300750.SZ`；每只最多 1 条新闻证据 | 是，只读新闻证据采集/验证 | 是，固定常量 | 不具备行情或策略 PIT；新闻证据为 observed/review 路径 | 未冻结为 P3 样本 |
| 动态活跃股票池 | `worker/services/stock_pool.py` 第 25-42 行；`worker/services/quote_sync.py` 第 18、44 行 | 从 `fundamental.stocks` 的 `is_active=true` 按代码排序、最多 `QUOTE_SYNC_STOCK_LIMIT`（默认 100）读取 | 是，行情同步实际引用 | 只能在相同数据库快照和 limit 下复现 | 否；无样本版本、无有效期，也不是固定名单 | 否；不能作为 P3 固定样本 |
| 测试 fixture | 例如 `backend/tests/test_l4_async_job_contracts.py` 第 34-52 行、`worker/tests/test_quote_sync.py` 第 80-87 行 | 测试输入，如单股 `300308.SZ` 或五只模拟代码 | 仅测试 | 是 | 否 | 否；不得当作业务样本 |

冲突：上述集合的股票数量、用途、时间区间和来源均不同。Sprint13 是唯一文件级冻结且包含 10 只股票的历史工程验证集；其余为证据采集或历史小样本。动态活跃池不是固定样本。没有证据表明其中任一集合已获 P3 使用批准。

### 1.3 行情与证据来源、许可事实

| Provider/接口 | 实际底层源和数据类型 | 时效属性与当前可调用性 | 账户/凭据 | 许可、自动化、存储/二次处理证据 | 已确认事实 | 无法证明/结论 |
| --- | --- | --- | --- | --- | --- |
| `a-stock-data` 内部 HTTP 服务 | `backend/app/data/client.py` 的 `/quote`、`/quotes`、`/kline` 等；服务实现：`a-stock-data/service/main.py` | 服务地址由 `A_STOCK_DATA_URL` 配置；本轮未启动或调用 | 内部刷新需要 `A_STOCK_DATA_COMMAND_TOKEN`：`backend/app/core/config.py` 第 42-43 行、`docker-compose.yml` 第 55、71、99 行 | `a-stock-data/README.md` 的 Apache-2.0 仅覆盖该代码；不覆盖其下游行情数据 | 是内部传输层，非底层数据许可主体 | 运行可达性、下游来源许可、自动化/存储/二次处理授权均未知；不可作 P3 合格 Provider |
| `tencent` / `tencent_qt_gtimg_l1` | `https://qt.gtimg.cn/q` 的 L1 批量行情；`a-stock-data/service/providers.py` 的 `_tencent_quote_with_raw` 与 `fetch_quotes_batch_with_metadata`；`worker/services/data_client.py` 第 460-507 行 | 代码称为实时 L1；`worker/services/quote_sync.py` 实际采集路径会写 `market.quote_batches`；本轮未调用验证 | 代码未使用账户或凭据 | 未找到底层条款、许可、自动化、存储或二次处理授权记录；`docs/adr/ADR-012-realtime-quote-provenance.md` 明确该技术实现不构成商业授权或执行准入 | Provider/source/endpoint、Hash、批次、时间和无 fallback 的技术溯源已实现；`backend/alembic/versions/015_realtime_quote_provenance.py` | `realtime_data_approved=false`；按本轮决定不得用于阶段 C 或 P3 实时运行 |
| 通达信 / `mootdx` | `a-stock-data/service/providers.py` 的 `tdx_client()`，K 线、盘口、逐笔等；依赖声明在 `a-stock-data/service/requirements.txt` | 可能提供近实时/历史；本轮未调用验证 | 无项目账户变量 | 未找到下游许可、自动化、存储/二次处理授权证据 | 代码及依赖存在 | 不得因代码可连接或“公开”而视为授权；不可用于 P3 |
| `sina` | `backend/app/data/sina_kline.py` 直连 `money.finance.sina.com.cn` K 线；`a-stock-data/service/providers.py` 还含股票列表/其他新浪路径 | K 线可能含分钟或日线；本轮未调用 | 无项目账户变量 | 未找到许可证据；当前项目决定禁止将新浪接口作为未批准实时来源 | 直接接口代码存在 | 禁止用于 P3 实时；可调用性、许可、自动化、存储/二次处理均未知 |
| `sohu` / `sohu_daily_kline` | `backend/app/data/sohu_daily_importer.py` 直连 `https://q.stock.sohu.com/hisHq`，日线 OHLCV | 历史日线导入，不是实时；本轮未调用 | 无项目账户变量 | 未找到底层许可、自动化、存储/二次处理授权文件 | `provider=sohu`、`source=sohu_daily_kline`、批次/Hash/质量路径明确；ADR-003 固定为历史小样本 | 不能升级为实时或 P3 实时 Provider |
| `tencent` / `tencent_fqkline_raw` | `backend/scripts/import_sprint13_dataset.py` 第 48 行的 `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get` | 历史日线交叉验证，不是实时运行；本轮未调用 | 无项目账户变量 | manifest 仅定义 `read_only_no_fallback`，不等于许可 | Sprint13 secondary Provider 结构存在：`config/datasets/sprint13_universe.yaml` | 许可未知；不得把历史 replay 标记为实时 |
| `cninfo` | 公告/财报原文观察：`a-stock-data/service/providers.py` 的 CNINFO 常量；`docs/adr/ADR-014-financial-report-evidence-observation.md` | observed 证据，不是行情 | 无项目账户变量 | `docs/adr/ADR-014-financial-report-evidence-observation.md`、`docs/adr/ADR-019-financial-report-snapshot-and-page-location.md` 明确自动化使用许可未批准，保持 `review_required/unverified` | 可记录原文、Hash、时间与证据 | 不可作为 P3 行情或输入授权 |
| `gdelt` | GAL RSS 新闻证据：`worker/services/data_client.py` 第 410-457 行；`docs/adr/ADR-018-research-source-usage-evidence-governance.md` | observed RSS 标题/链接证据，不是行情 | 无项目账户变量 | 有条款证据治理结构，但其授权不传播到链接目标内容，且研究证据仍被 `PROVIDER_USAGE_PERMISSION_UNAPPROVED` 阻塞 | 新闻证据路径可追溯 | 不可作为实时行情或直接交易事实 |
| `eastmoney` | `a-stock-data/service/providers.py`、`a-stock-data/README.md` 含东财 HTTP 路径 | 包含历史、分钟和资讯能力；本轮未调用 | 无项目账户变量 | 未找到 P3 所需许可/授权记录；当前决定禁止接入或抓取 | 代码存在 | 禁止用于 P3；不能以限流代码替代许可 |
| QMT / miniQMT | 仅环境变量模板：`.env.example` 第 82-87 行；交易探测路径：`backend/app/api/trade.py` 第 312 行起 | 未发现本轮可证实的已配置实时行情 Provider | 预留 `QMT_PATH`、账号、会话变量 | 没有账号已配置、行情许可或自动化权限的证据 | 配置槽位存在 | 不是已批准或可用的 P3 来源 |

结论：仓内存在实时技术链路和溯源结构，但不存在可证明为 P3 合格的真实实时行情许可。固定结论为 `realtime_data_approved=false`、`P3_REALTIME_DATA_NOT_APPROVED`；阶段 C 实时验证 blocked。

### 1.4 策略、版本与输入 Profile

| 实际策略类型 | `strategy_id` / `strategy_version` | 实现与参数来源 | 输入字段/Profile | 生命周期与验证证据 | PIT/未来函数风险 | 是否适合 P3-0 |
| --- | --- | --- | --- | --- | --- | --- |
| `dual_ma` | 未知。`strategy.strategies` 与不可变版本表结构存在，但本轮未查询运行数据库，迁移未写入固定策略行：`backend/alembic/versions/028_strategy_version_governance.py` | `backend/app/strategy/catalog.py`、`backend/app/strategy/signals.py`；参数校验在 `backend/app/strategy/config_store.py` | `OHLCV_RETURN_V1`，字段为交易日、OHLCV、复权、交易日历、公司行动状态 | 生命周期代码要求 approved enabled version：`backend/app/strategy/version_service.py`；ADR-007 有内部回测完整性与未来函数测试证据：`docs/adr/ADR-007-backtest-integrity-and-execution-model.md` 第 8、48-50 行 | 信号函数只取 `date <= trade_date`；ADR-007 明确验证未来 K 线改变不影响当期信号 | 仅可作为候选。缺少实际 approved 版本、P3 输入 Profile、固定样本和许可实时数据 |
| `bollinger` | 未知，同上 | 同上 | 同上 | 有目录与参数校验实现；未找到其独立回测、Walk Forward 或模拟运行证据 | 代码按截至交易日序列取窗口；缺少独立 PIT 验收证据 | 不适合当前冻结；仅候选代码类型 |
| `rsi` | 未知，同上 | 同上 | 同上 | 有目录与参数校验实现；未找到其独立回测、Walk Forward 或模拟运行证据 | 代码按截至交易日序列计算；缺少独立 PIT 验收证据 | 不适合当前冻结；仅候选代码类型 |
| `macd` | 未知，同上 | 同上 | 同上 | 有目录与参数校验实现；未找到其独立回测、Walk Forward 或模拟运行证据 | 代码按截至交易日序列计算；缺少独立 PIT 验收证据 | 不适合当前冻结；仅候选代码类型 |

`OHLCV_RETURN_V1` 的允许范围是 `raw_price_analysis` 与 `return_backtest`：`backend/app/data/research_profiles.py` 第 30-36 行。它不是已批准的实时 shadow input Profile。当前仓库没有可确认的 Walk Forward 证据，也没有可确认的 P3 模拟运行证据；测试 fixture 中的 `builtin:dual_ma:v1`、`strategy_id=7`、`version_id=11` 仅用于测试，不能当作真实版本：`backend/tests/test_l4_async_job_contracts.py` 第 34-52 行。

### 1.5 安全隔离事实

- 六个锁的默认值均为 `false`：`backend/app/core/config.py` 第 53-60 行；完整键集合受 `backend/tests/test_core_readonly_contracts.py` 第 19-34 行覆盖。
- 执行门禁会拒绝定时来源、AI、未开交易锁、未开纸面/实盘、未认证数据或缺少人工审批的请求：`backend/app/trade/execution_gate.py` 第 28-49 行。
- 现有实时 observed 行情不自动取得历史认证、Research Readiness、Execution Reference、选股或下单权限：`docs/adr/ADR-012-realtime-quote-provenance.md` 第 16-25 行。

## 2. 冲突项

1. 固定样本冲突：10 股 Sprint13、3 股 Sprint06、1 股 Sprint07、两套 2 股证据样本和动态活跃池互不等价；没有任何一套被标记为 P3 固定样本。
2. 数据来源冲突：现有腾讯 L1 被旧 ADR 固定为技术 Provider，但该 ADR 同时明确不构成商业许可或执行准入；本轮项目决定又明确其不得作为已批准实时来源。
3. 时态冲突：Sprint13/Sprint06/Sprint07 都是历史日线；不得称为实时。动态活跃池没有快照版本，不能满足固定样本。
4. 策略冲突：目录中有 4 个策略类型，但无可确认的实际 `strategy_id + approved version`；测试中的版本值不是运行事实。
5. Profile 冲突：现有 `OHLCV_RETURN_V1` 已定义，但只允许历史分析/回测范围；没有已批准的 P3 shadow input Profile。
6. 旧 worker 扫描冲突：`worker/services/signal_scan.py` 依赖动态策略池和 AI 推荐，不能包装或重命名为 P3 规则影子运行。

## 3. 候选决策表

### 3.1 固定样本

| 方案 | 证据 | 优点 | 风险 | 缺失条件 | 推荐顺序 |
| --- | --- | --- | --- | --- | --- |
| A：以 Sprint13 的 10 股历史 manifest 作为未来 P3 样本决策的起点 | `config/datasets/sprint13_universe.yaml`；`backend/scripts/import_sprint13_dataset.py` | 已有冻结文件、明确名单、选择规则、日期和 Hash 校验；覆盖多个板块 | 明确为历史工程验证，不是投资或实时样本；Provider 许可未确认；没有 P3 版本 | 用户确认是否复用名单、P3 样本版本号、适用生效时点、实时数据对应关系 | 1（仅建议，未批准） |
| B：以 ADR-007 已验证的两股 `300308.SZ, 603986.SH` 为最小 replay 对照集 | `docs/adr/ADR-007-backtest-integrity-and-execution-model.md` 第 8、50 行 | 有 dual_ma 回测完整性和未来函数证据，范围最小 | 非 P3 固定样本；历史 2026-06 数据；覆盖极窄 | 用户确认是否采用；正式样本版本、实时映射与稳定周期 | 2（仅限 replay 对照，未批准） |

### 3.2 Provider

| 方案 | 证据 | 优点 | 风险 | 缺失条件 | 推荐顺序 |
| --- | --- | --- | --- | --- | --- |
| A：仅定义 replay/test Provider 契约，使用明确标记的历史数据 | `config/datasets/sprint13_universe.yaml`；`docs/adr/ADR-003-certified-historical-data-ingestion.md`；`docs/adr/ADR-007-backtest-integrity-and-execution-model.md` | 不接入新外部来源；可验证输入血缘、可复现和零订单隔离 | 不能称为实时，不能完成阶段 C 实时验收 | 用户确认 replay 数据集/样本、策略版本、时点和稳定周期 | 1（当前唯一可提出的 Provider 契约） |
| B：等待合格真实实时 Provider 的许可和授权证据后再进入实时契约 | `docs/adr/ADR-012-realtime-quote-provenance.md` 第 25 行；本包 1.3 | 保持语义和许可边界正确 | 当前 blocked，不能实施或验收实时运行 | Provider、下游源、条款版本、自动化/存储/二次处理许可、账户范围、时效阈值 | 2（实时阶段的前置，不是当前可选实现） |

### 3.3 策略与输入组合

| 方案 | 证据 | 优点 | 风险 | 缺失条件 | 推荐顺序 |
| --- | --- | --- | --- | --- | --- |
| A：实际已批准的 `dual_ma` 版本 + 现有 `OHLCV_RETURN_V1` 作为历史 replay 候选 | `backend/app/strategy/catalog.py`；`backend/app/strategy/signals.py`；`docs/adr/ADR-007-backtest-integrity-and-execution-model.md` | 是唯一有明确未来函数防护与内部回测完整性文档的目录策略 | `OHLCV_RETURN_V1` 不允许 P3 shadow 用途；真实策略 ID/版本未知；没有 Walk Forward 或模拟运行证据 | 用户确认实际 approved 版本；单独批准 P3 input Profile/用途；样本和 replay 时点 | 1（仅建议，未批准） |
| B：实际已批准的 `macd` 版本 + `OHLCV_RETURN_V1` 的历史 replay 候选 | `backend/app/strategy/catalog.py`；`backend/app/strategy/signals.py` | 输入相同、代码简单 | 无独立回测/未来函数验收证据；Profile 用途同样不匹配 P3 | 同 A，另需 MACD 的定向 PIT/回放证据 | 2（仅建议，未批准） |

## 4. 推荐结论

推荐顺序为：固定样本候选 A（Sprint13 10 股）→ Provider 候选 A（严格 replay/test）→ 策略候选 A（已批准的 `dual_ma` 版本）。理由是它们的名单、历史输入和未来函数防护证据最完整。

这不是批准结论。当前没有任何候选同时满足固定样本、合格实时许可、实际 approved 策略版本、P3 input Profile、运行时间、时效阈值和稳定周期，因此不得冻结任何实际 P3-0 决策。

## 5. P3-0 契约草案

### 5.1 阶段边界

1. P3-0 仅记录规则策略对批准输入的影子决策及其证据。
2. P3-0 不创建订单、不调用订单执行接口、不写资金、不写持仓、不产生可交易状态。
3. 每个 run 和 decision 必须恒有：`tradable=false`、`order_created=false`、`order_count=0`、`capital_changed=false`、`position_changed=false`。
4. P3-0 是独立阶段，不得描述为完整 P3 或阶段 C 实时验收通过。

### 5.2 固定样本版本契约

1. 实施前必须由用户明确提供或确认 `sample_version`、股票完整有序列表或可复现规则、`effective_from`、`selection_basis`、创建者和批准记录。
2. `sample_version` 必须绑定规范化名单 Hash；同一版本不可修改。名单、顺序、规则、有效期任一变化都必须产生新版本，不能覆盖旧 run。
3. 每次 shadow run 必须记录 `sample_version`、`sample_hash`、成员数和实际扫描成员；不得从 `fundamental.stocks.is_active`、前端选择或当前 watchlist 隐式补全。
4. 未确认样本版本时必须 blocked，错误码 `P3_SAMPLE_UNCONFIRMED`。

### 5.3 Provider、来源和许可契约

1. 每个输入批次必须记录 `provider`、`source`、`fetch_endpoint`、`dataset_version`、`provider_time`、`fetched_at`、`received_at`、`raw_hash`、`collector_version`、`normalizer_version`、批次状态与 `fallback_used`。
2. 另必须记录可审计的 `license_evidence_ref`、`terms_version_or_effective_at`、`automation_allowed`、`storage_allowed`、`secondary_processing_allowed` 与授权主体。任一字段未知或未批准，不能标记为 approved realtime。
3. “公开、免费、无需 token、代码可调用、聚合库可调用”均不是许可事实。
4. Provider 失败、部分批次、未知来源、未知许可或 fallback 均不得静默替换；应保留原状态并返回 unavailable/degraded。

### 5.4 replay 与 realtime 强制区分

1. `data_mode` 必须为 `replay`、`test` 或 `realtime` 之一；不得省略。
2. `replay/test` 必须保存历史数据集/fixture 标识、范围、Hash、业务时间和重放时间；响应必须带 `realtime_data_approved=false` 与 `not_realtime=true`。
3. 仅当已登记合格许可、实际来源为实时、`realtime_data_approved=true` 且时效阈值满足时，才能写 `data_mode=realtime`。
4. 当前强制：`realtime_data_approved=false`，实时请求返回 blocked：`P3_REALTIME_DATA_NOT_APPROVED`。不得用缓存、历史 K 线、测试 fixture 或上次行情替代。

### 5.5 策略版本与 input Profile 契约

1. 每个 run 必须绑定实际 `strategy_id`、`strategy_type`、`version_id`、`version`、`revision`、`params`、`config_hash`、`catalog_hash` 和审批状态；不可用、待审批、过期或 Hash 不匹配即 blocked。
2. 每个 run 必须绑定已确认的 input Profile 名称、policy version、用途、完整 required fields、数据 adjustment、交易日历和公司行动状态。不得以目录默认值推断。
3. 当前 `OHLCV_RETURN_V1` 只能作为历史 replay 候选的证据引用；在未获单独确认前，不得声称它是 P3 shadow input Profile。
4. 无实际 approved 版本返回 `P3_STRATEGY_VERSION_UNCONFIRMED`；无已确认 input Profile 返回 `P3_INPUT_PROFILE_UNCONFIRMED`。

### 5.6 shadow run、decision 与证据契约

1. shadow run 至少保存：不可变 `run_id`、运行目的、`data_mode`、开始/结束时间、请求运行时点、样本版本、策略快照、input Profile 快照、输入批次引用、数据截止时间、时效计算、结果 Hash、状态、阻塞/降级原因。
2. shadow decision 至少保存：`decision_id`、`run_id`、股票、`information_cutoff`、规则结论/原因、输入 evidence 引用、`would_action`（若有）、策略快照 Hash 和决策状态。`would_action` 仅表示规则观察，不是订单意图、候选发布或交易资格。
3. 决策证据必须能回指到每个数据批次、行级 Hash/证据 ID、业务时间、接收时间、许可状态和所用算法/规则版本。缺少证据时只能 recorded blocked/unavailable，不能补全分数或行动。
4. 去重键必须至少覆盖 `sample_version + stock_code + strategy_id + version_id + input_profile + input_snapshot_hash + information_cutoff + decision_rule_hash`。完全相同键返回原 decision；任一项变化生成新决策并保留旧记录。

### 5.7 数据时效与降级契约

1. 每个输入记录必须有 `provider_time`、`fetched_at`、`received_at`、`age_seconds`、`freshness_threshold_seconds`、`freshness_status`。
2. 时效阈值、决策运行时间和稳定周期均须用户确认；确认前不得以 `DATA_CACHE_TTL_QUOTE` 或其他配置默认值替代，错误码分别为 `P3_FRESHNESS_THRESHOLD_UNCONFIRMED`、`P3_SCHEDULE_UNCONFIRMED`、`P3_STABILITY_PERIOD_UNCONFIRMED`。
3. 数据缺失、批次 `running/partial/fetch_failed/validation_failed/write_failed`、许可不合格或超时必须将 run/decision 标记为 `unavailable` 或 `degraded`，并带精确错误码；不得生成虚假行情、旧值或可交易结论。

### 5.8 订单、资金、持仓与锁隔离

1. P3-0 代码边界不得导入或调用订单创建、执行、模拟成交、资金变动、持仓变动或交易准入服务。
2. 每次 run 完成时必须执行零订单安全断言：`order_count == 0`、不存在 `order_id`、`order_created is false`、无执行接口调用记录、资金与持仓写入计数均为 0。
3. 下列六锁必须持续为 false，P3-0 不得写入或覆盖：`CERTIFIED_BACKTEST_EXECUTION_ENABLED`、`CERTIFIED_SCREENER_OUTPUT_ENABLED`、`TRADING_EXECUTION_ENABLED`、`LIVE_TRADING_ENABLED`、`AI_ORDER_ENABLED`、`ALLOW_SCHEDULED_ORDER`。
4. 任何零订单断言失败即 fail closed，错误码 `P3_ZERO_ORDER_ASSERTION_FAILED`；该 run 不得标记成功。

### 5.9 错误码与阻塞状态

最低错误码集合：

- `P3_SAMPLE_UNCONFIRMED`
- `P3_REALTIME_DATA_NOT_APPROVED`
- `P3_PROVIDER_LICENSE_UNCONFIRMED`
- `P3_REPLAY_NOT_REALTIME`
- `P3_STRATEGY_VERSION_UNCONFIRMED`
- `P3_INPUT_PROFILE_UNCONFIRMED`
- `P3_SCHEDULE_UNCONFIRMED`
- `P3_FRESHNESS_THRESHOLD_UNCONFIRMED`
- `P3_STABILITY_PERIOD_UNCONFIRMED`
- `P3_DATA_UNAVAILABLE`
- `P3_DATA_STALE`
- `P3_INPUT_LINEAGE_INCOMPLETE`
- `P3_ZERO_ORDER_ASSERTION_FAILED`

`blocked` 表示准入条件未满足；`unavailable` 表示来源未提供合格输入；`degraded` 表示可记录降级事实但不得形成可交易或实时验收结论。三者不得转换为成功或实时。

### 5.10 验收契约

1. replay/test 验收只能使用显式 `data_mode=replay/test` 的已批准输入；相同 run 输入须产生相同结果 Hash 与去重结果。
2. 定向测试必须证明：未来数据变动不改变截止时点前的决策；缺失/过期/许可未知输入被阻断；replay 不会被标为 realtime；无任何订单、资金或持仓写入；六锁不变。
3. 完整测试、验收脚本和审计输出必须基于真实命令结果；replay 通过仅代表 P3-0 replay 契约通过，不代表阶段 C。
4. 真实实时验收准入前，必须同时具备：用户批准的固定样本、真实 Provider 及底层来源、书面许可与自动化/存储/二次处理证据、实际 approved 策略版本、P3 input Profile、运行时间、时效阈值、稳定周期、实时输入批次与零订单隔离测试。缺一不可。

## 6. 当前阻塞项

必须由用户确认：

1. 固定股票样本及正式版本/生效范围。
2. 采用的实际策略 ID、已审批版本与参数快照。
3. P3 input Profile；现有 Profile 不自动适用。
4. 决策运行时间、数据时效阈值和稳定运行验收周期。
5. 是否批准仅开展严格标记的 replay/test 契约验收。

必须补充外部许可或数据证据：

1. 真实实时 Provider、实际底层数据源和账户范围。
2. 许可/条款有效版本，以及自动化调用、本地存储、二次处理的明确依据。
3. Provider 可用性与实时数据时效的实测证据。

在以上实时证据缺失时，`P3_REALTIME_DATA_NOT_APPROVED` 保持 blocked，阶段 C 实时验证不能开始或通过。

## 7. 下一阶段建议

在用户确认所有决策并单独授权实施后，第一批开发应仅包含：

1. 将已确认的样本、策略版本、input Profile、Provider/replay 标识和运行参数写成不可变引用；不复用动态股票池。
2. 建立只记录 shadow run、decision 与 evidence 的最小存储/API 契约，并把零订单、资金/持仓零写入和六锁不变做成定向测试。
3. 先执行 replay/test 验收；实时 Provider 仍保持 `P3_REALTIME_DATA_NOT_APPROVED`，不接入新来源、不进行阶段 C 验收。

本包至此停止，不包含迁移、模型、接口、任务或影子运行业务实现。
