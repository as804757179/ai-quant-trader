# Sprint13.2：企业行动证据与缺失归因设计

状态：方案 A 已确认；等待本设计审核后实施。  
范围：冻结 10 只股票、`2025-07-01` 至 `2026-06-30`、`1d/raw`。

## 目标与非目标

目标是关闭两个可审计的数据治理缺口：

1. 对冻结股票完成目标区间内企业行动的官方事件级审核、证据归档与 Hash 校验。
2. 对 `688981.SH` 的 6 个缺失交易日（2025-09-01 至 05、08）完成真实归因。

不导入或修补 K 线，不修改 legacy/Certified raw 数据，不改变企业行动会计语义，不运行策略或回测，不开放 Backtest、Screener、Paper、Live 或 AI Order。全周期安全开关保持 `false`。

## 复用与数据流

复用 `market.corporate_action_reviews`、不可变的 `market.corporate_actions`、`market.research_date_reviews`、`ResearchReadinessService` 和现有 Sprint13 冻结清单。

```text
CNINFO / 交易所官方公告
  -> 本地原件归档 + SHA-256 + 来源元数据
  -> 事件级 review（verified / verified_no_event / unresolved）
  -> 已验证且处理器支持的事件写入 immutable corporate_actions
  -> 完整授权键重新计算 Readiness

Sohu + Tencent 只读核验 + 交易所停复牌公告
  -> 688981 六日逐日归因
  -> research_date_reviews
  -> 仅在证据完整时解除对应 missingness 阻塞
```

不使用搜索页空结果、代码身份或 weekday 推断作为 `verified_no_event`、`suspended` 或 `normal_trade` 的唯一证据。任何关键日期、比例、公告原件或停复牌事实缺失时保持 `unresolved`。

## 企业行动证据规则

- 官方来源优先 CNINFO；若 CNINFO 不足，以交易所公告为补充，不能以聚合站替代。
- 每个下载原件保存到 `evidence/corporate_actions/<source>/sprint13.2/`；同时保存来源 URL、下载时间、字节数、SHA-256、公告 ID、检索范围和解析版本。
- `verified` 事件必须有公告日、登记日、除权日、现金支付日、股份到账日、比例与原件 Hash。证据齐全后使用新的 `action_id` 与事件版本写入 `market.corporate_actions`；旧版本不更新或删除。
- 只有现金分红与转增/送股等已被当前 `CorporateActionProcessor` 明确支持、且 Point-in-Time 日期完整的事件，才可标记为 `event_verified_handled` 并用于 `OHLCV_TOTAL_RETURN_GROSS_V1`。
- 配股、分数股、未知到账日、复杂股本变动或未支持事件保持 `review_required` / `rejected`，不猜测、不平滑 raw K 线。
- `verified_no_event` 必须保存可复现的官方检索证据和覆盖区间；无法可靠证明“无事件”时保持 `unresolved`。

## 688981.SH 缺失归因规则

逐日比较 Sohu 主 Provider 与腾讯只读 Provider，并以沪交所停复牌/公告作为状态证据：

- 有官方停牌证据：`suspended`。
- Certified 缺失、另一 Provider 或官方端点存在对应行情：`provider_missing`，但本 Sprint 不回填 K 线。
- 交易所休市：`exchange_closed`。
- 证据不足或来源相互矛盾：`unresolved`。

即使发现可用行情，也不在 Sprint13.2 插入或覆盖 Certified raw K 线；需要单独、受认证的补数据 Sprint 才能处理。`provider_missing` 不自动授予 return-backtest ready。

## Readiness 与安全边界

所有更新使用完整授权键：股票、`1d`、`raw`、日期区间、用途、Requirement Profile 与 required_fields。

- `OHLCV_RETURN_V1` 仅在无企业行动或企业行动已按适用政策处理、逐日缺失已完整归因、Provider 校验通过且所有必需字段已验证时才可能 ready。
- 有完整可处理企业行动时仅评估 `OHLCV_TOTAL_RETURN_GROSS_V1`；不传播到净税后、amount 或 Execution Reference。
- `AMOUNT_FACTOR_V1` 与 `EXECUTION_REFERENCE_V1` 继续独立、fail closed。
- Sprint13 的年度证券状态仍是 `unresolved`，不在本 Sprint 推断或放行。因此本 Sprint 不承诺任何股票 ready，也不承诺 Sprint14 准入。

## 实现边界

新增一个显式的 Sprint13.2 审核入口和只读验收入口；不在导入器中增加隐藏 fallback。复用现有审核表的 `evidence` JSON 保存索引、Hash 与版本；除非实现时证明无法表达不可变审计关系，否则不新增数据库表或 migration。

验收前后对 legacy、既有 Certified raw、corporate action 原始事件和发布锁做稳定快照。失败时仅保留新 review/证据，Readiness 保持或回退为非 ready；不删除原始数据，不回滚为伪造结论。

## 测试与验收

定向测试至少覆盖：

1. 原件字节、数据库/审核记录 Hash 与预期 Hash 一致；缺原件或 Hash 不符不能 verified。
2. 关键日期/比例缺失、未知来源、未支持事件、公告日前可见性均 fail closed。
3. verified 事件新增版本不覆盖旧版本，且不改 raw K 线。
4. 六个缺失日按证据分别归因为 suspended、provider_missing、exchange_closed 或 unresolved；无证据不能变为 normal_trade。
5. Profile 权限不传播；年度证券状态 unresolved 时不得通过 Readiness。
6. 六个发布锁、AI/Celery 无下单、无订单/候选保持不变。

新增 `scripts/verify_sprint13_2_evidence_closure.ps1`：验证证据文件与 Hash、事件版本、六日归因、完整 Readiness 键、数据不可变快照、既有验收链和 Backend/Worker 全量测试。不得以 skip、xfail、xpass、Mock、Synthetic 或降低门禁获得 PASS。

## 回滚与完成条件

审核/证据写入使用新增 review ID 和事件版本，不覆盖旧审核或 immutable corporate action。若验证失败，保留审计痕迹、标记 unresolved，且不释放权限。

Sprint13.2 通过仅表示证据闭环与归因流程真实可验证；Sprint14 仍须另行满足至少 6 只 scoped-ready、至少 1,400 scoped-ready 行、无影响回测完整性的 P0/P1 和稳定 dataset hash 等门槛。
