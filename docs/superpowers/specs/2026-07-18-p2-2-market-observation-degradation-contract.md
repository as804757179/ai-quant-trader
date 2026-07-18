# P2-2 行业、板块与情绪观察 V1 降级契约

## 范围与语义

P2-2 V1 仅新增四个只读接口：`GET /market/industry-classifications`、`GET /market/concept-boards`、`GET /market/exchange-boards` 和 `GET /market/sentiment`。本阶段完成的是契约与降级语义，不是正式 PIT 数据源接入。

`fundamental.stocks.sector` 与 `fundamental.stocks.board` 只能返回 `data_semantics=current_snapshot`、`provider=legacy_internal`、`quality_status=unverified`、`pit_capable=false`。它们仅用于当前页面展示、查询与非历史辅助筛选；不得进入历史回测、Walk Forward、模型训练、历史因子计算或任何声称 PIT 的研究结果。不得补造 `fetched_at`、`effective_from`、`effective_to` 或 `dataset_version`。

`observed`、`current_snapshot`、`derived`、`derived_from_observed` 与 `unavailable` 为互不替代的语义。AI/LLM 输出不是 observed；没有已获许可的原始证据时，情绪接口必须返回 `unavailable`，不返回分数、证据引用或伪造 lineage。

所有接口保持 `research_readiness=not_granted`、`tradable=false`、`order_created=false`，不触发回测、训练、选股、风险调整或订单。

## 接口

### 行业当前快照

`GET /market/industry-classifications` 从 `fundamental.stocks.sector` 按行业聚合。支持 `sector`、`page`、`page_size`，按 `snapshot_updated_at DESC NULLS LAST, classification_name` 稳定分页。返回 `provider=legacy_internal`、`source=fundamental.stocks.sector`、`dataset_version=null`、`fetched_at=null`、`effective_from=null`、`effective_to=null`、`pit_capable=false`、`historical_research_usable=false`、`backtest_usable=false`。

### 概念板块

`GET /market/concept-boards` 在 V1 返回 `availability_status=unavailable`、空列表与 `data_semantics=unavailable`。`market.concept_board_memberships` 仅为未来已获许可来源的独立模型，不写入合成或推断结果。

### 交易所板块当前快照

`GET /market/exchange-boards` 从 `fundamental.stocks.board` 按板块聚合，字段与行业当前快照同义，但 `source=fundamental.stocks.board`。`market.exchange_board_observations` 为未来正式来源的独立模型；当前快照不能替代其中的 PIT 记录。

### 市场情绪

`GET /market/sentiment` 在 V1 返回 `availability_status=unavailable`、空列表、`data_semantics=unavailable` 与 `derived_from_observed=false`。`market.sentiment_derivations` 预留原始证据引用、Provider、原始发布时间、抓取时间、算法版本、计算规则和 lineage 字段。未来只有在合格原始证据存在时，才允许产生 `derived_from_observed` 或 `derived` 分数；分数永不标记为 observed。

## 数据模型与技术债

迁移 `041_p2_2_market_observation_semantics.py` 追加四个独立表：`market.industry_classification_observations`、`market.concept_board_memberships`、`market.exchange_board_observations` 与 `market.sentiment_derivations`。它们均保存正式来源所需的 Provider、source、dataset_version、fetched_at、有效期、质量与 PIT 字段；V1 不从 `fundamental.stocks` 回填这些表。

- `P2-2-PIT-INDUSTRY-DATA-SOURCE`：V2 或获得书面数据许可后，接入可追溯的行业、概念板块和交易所板块 PIT 来源。
- `P2-2-OBSERVED-SENTIMENT-EVIDENCE-SOURCE`：V2 或获得书面数据许可后，接入可观察的原始新闻/公告证据来源，再开启可追溯的派生情绪。

以上技术债不阻塞 V1 其他核心功能，也不构成 Research、Backtest 或 Execution 准入。

## 验收与回滚

每项接口必须有路由、权限、零写入、语义隔离和前端契约测试；前端必须展示“当前快照、非历史还原数据”或“正式情绪数据源尚未接入”。回滚时移除对应读取路由和页面绑定；不删除已记录的未来正式来源事实。
