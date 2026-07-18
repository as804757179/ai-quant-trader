# ADR-012：实时行情固定 Provider 与可追踪血缘

日期：2026-07-15  
状态：Accepted

## 背景

现有实时行情任务仅将单票结果写入 Redis；`market.quotes` 没有数据，也没有 Provider、端点、接收时间、原始响应 Hash 或 fallback 记录。单票查询还可能降级到其他来源，无法作为可审计的实时行情链路。

## 决策

1. Sprint14.2 固定使用现有腾讯批量行情端点 `https://qt.gtimg.cn/q` 作为唯一主 Provider。
2. 采集任务只调用批量行情路径，禁止 Provider fallback。请求失败只记录 `fetch_failed`，不得改用通达信、Mock、Synthetic、unknown 或上一笔行情。
3. 新增 `market.quote_batches` 和 `market.quote_provenance`，与既有 `market.quotes` 保持 sidecar 关系。
4. 每批记录 Provider、source、endpoint、请求/返回/接受数量、状态、失败原因、原始响应 Hash、采集与规范化版本、获取和接收时间。
5. 每条写入行情记录 Provider、source、批次、Provider 时间、接收时间、行级原始 Hash、质量状态和 fallback=false。
6. 实时行情在本阶段仅是 `observed` 数据：可用于市场监控和质量审计，不自动获得历史 Data Certification、Research Readiness、Execution Reference、选股或下单权限。
7. 当前默认范围仍由 `QUOTE_SYNC_STOCK_LIMIT` 控制。页面必须展示实际覆盖数，不能将受控范围称为全市场覆盖。
8. 批次在行情和行级血缘事务写入期间必须是 `running`；只有写入完成后才能成为 `success` 或 `partial`。读取方不得把创建中批次当作成功数据。

## 后果

- 市场监控可以回答每条行情从哪里来、何时获得、是否发生降级、批次是否完整。
- Provider 出错或部分返回会留下可审计批次；数据缺口不会伪装为停牌或正常行情。
- 这不构成行情商业授权、全市场吞吐保证或交易执行数据准入。扩大范围前必须完成 Provider 负载与许可验证。

## 回滚

撤销本 ADR 对应的采集代码和只读展示；迁移回滚会删除仅由本 ADR 创建的行情批次与 provenance 表，不修改既有行情、历史 K 线、认证数据或交易记录。
