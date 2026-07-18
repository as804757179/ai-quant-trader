# Sprint14.3：多维研究证据观察试点

状态：已批准实施  
日期：2026-07-15

## 成功标准

- 当前日期的沪深交易日历具有两所官方来源、完整覆盖和 `confirmed` 状态。
- 对固定小样本公告，系统记录 Provider、source、发布者、原文 URL、外部文档 ID、原文 SHA-256、日期精度、首次观测时间、可得时间、版本和批次状态。
- 来源或原文失败时保留 `fetch_failed`、`validation_failed`、`write_failed` 或 rejected 审计；不使用 fallback。
- 只读 API 能返回证据和批次，并明确 `observed_only`、`tradable=false`、`order_created=false`。
- 验收真实读取固定 Provider，确认原文 Hash、日历覆盖和六个发布/交易锁均关闭。

## 最小方案

1. 复用 `market.trading_calendar`，仅追加 2026 年沪深官方休市安排覆盖。
2. 新增 `market.research_evidence_batches` 与 `market.research_evidence` sidecar，复用实时行情的批次、Hash、失败和只读查询模式。
3. 复用 `a-stock-data` 服务，新增巨潮公告单 Provider 查询与 PDF Hash；不使用现有空新闻/财报端点。
4. 新增显式人工运行的公告采集脚本和只读研究证据 API；不加入 Celery Beat。
5. 新增定向契约、单位与真实接口验收脚本。

## 时间语义

巨潮公告列表返回的是披露日期，不是可证明的精确公开时刻。因此：

- `source_published_date` 保存来源日期，`publication_time_precision=date`；
- `source_published_at` 保持为空；
- `first_observed_at` 是系统首次成功接收该原文的时刻；
- `available_at=first_observed_at`，`availability_basis=system_first_observed`；
- 任一数据均不因此获得 Research Readiness、回测、选股或执行资格。

## 明确不做

- 不接入新闻或财报抓取，不扩大为全市场常驻采集。
- 不修改 Data Certification、Research Readiness、Backtest、Screener、Risk Engine、Execution Gate 或 AI 下单边界。
- 不开启 `CERTIFIED_BACKTEST_EXECUTION_ENABLED`、`CERTIFIED_SCREENER_OUTPUT_ENABLED`、`TRADING_EXECUTION_ENABLED`、`LIVE_TRADING_ENABLED`、`AI_ORDER_ENABLED` 或 `ALLOW_SCHEDULED_ORDER`。
- 不新增第三方依赖，不把巨潮网页数据的许可状态误报为已批准。
