# Sprint13 Corporate Actions

10 只股票均建立 CNINFO 官方公告检索审核记录，但尚未逐事件解析并归档目标区间全部官方原件、公告日、登记日、除权日、支付/到账日、比例和 Hash。当前 10 股状态均为 `unresolved`。

因此所有 `return_backtest + OHLCV_RETURN_V1` 保持 `review_required`；未创建 Gross Profile 授权，净税后继续 blocked。raw K 线没有平滑或改写。该项是 Sprint13 的 P0 阻塞，禁止强制 ready 或进入 Sprint14。
