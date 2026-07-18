# Sprint14.2：受控实时行情血缘闭环

状态：已批准实施  
日期：2026-07-15

## 成功标准

- 当前配置范围的批量行情由固定腾讯 Provider 真实获取并写入 `market.quotes`。
- 每批与每行都具备 Provider、source、端点、时间、Hash、版本和状态。
- Provider 失败无 fallback；失败或部分批次可查询、可解释。
- 市场监控展示实际 Provider、覆盖数、延迟、批次状态和降级状态。
- 实时行情不改变任何历史数据认证、研究资格、选股、订单或发布锁。

## 最小方案

1. 复用现有 `a-stock-data` 腾讯批量行情能力，增加批量元数据返回与 `fresh=true` 无缓存采集路径。
2. 复用现有 worker 定时任务，将单票 Redis 同步改为受控分批采集、数据库行情写入和 Redis 发布。
3. 使用 sidecar `market.quote_batches`、`market.quote_provenance`，不改写 `market.quotes` 的既有主键和保留策略。
4. 新增市场批次只读接口、前端行情监控页面、契约测试和验收脚本。

## 明确不做

- 不扩大到全市场默认采集。
- 不增加 Provider fallback 或商业数据依赖。
- 不将 observed 行情当作 Research Ready 或 Execution Reference。
- 不运行策略、不发布候选、不创建订单、不改变六个发布锁。
