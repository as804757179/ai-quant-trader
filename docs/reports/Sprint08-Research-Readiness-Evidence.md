# Sprint08 Research Readiness Evidence

日期：2026-07-11

## 日期完整性

- 主数据逐日审核：90 条（三只股票 × 30 个自然日）。
- normal_trade：63 条，对应每只股票 21 个确认交易日且均存在 certified bar。
- exchange_closed：27 条，对应周末及 2026-06-19 交易所休市。
- suspended / not_listed / delisted / unresolved：0。
- 未补价格、未生成零成交量 K 线。

## 新浪 2026-06-30 缺失归因

结论：`sina_klc_kl_archive` 端点特定的 `provider_missing`。

2026-06-30 是确认交易日。新浪 klc_kl 归档端点没有该日期，但新浪 CN_MarketData 日线端点和腾讯 raw 日线端点均有该日期。与 Sohu 比较：

| 股票 | OHLC 最大绝对差 | Volume 最大绝对差 | Amount 独立验证 | Readiness |
|---|---:|---:|---|---|
| 300308.SZ | 0.00 CNY | 9 股 | unresolved | review_required |
| 603986.SH | 0.00 CNY | 21 股 | unresolved | review_required |
| 300502.SZ | 0.00 CNY | 28 股 | unresolved | review_required |

因此可以证明新浪归档端点缺失和 Sohu OHLCV 的一致性，但不能证明该日 Sohu amount 与独立 Provider 一致。系统没有自动忽略差异，三个用途审核均未因该证据被标为 ready。

可复现脚本：`scripts/investigate_sina_20260630.py`。

## 企业行动审核

| 股票 | 区间内结论 | 事件日期 | 处理状态 | 来源 |
|---|---|---|---|---|
| 300308.SZ | verified_no_event | 最近一次除息为 2026-04-30，区间外 | 不阻断企业行动条件 | [巨潮公告](https://static.cninfo.com.cn/finalpage/2026-05-09/1225286790.PDF) |
| 603986.SH | verified_no_event | 最近一次除息为 2026-05-26，区间外 | 不阻断企业行动条件 | [巨潮检索](https://www.cninfo.com.cn/new/fulltextSearch?keyWord=603986) |
| 300502.SZ | 现金分红并资本公积转增 | 登记 2026-06-10；除权/生效 2026-06-11 | 未实现收益调整，return_backtest rejected | [巨潮检索](https://www.cninfo.com.cn/new/fulltextSearch?keyWord=300502) |

300502.SZ 的方案为每 10 股派现 10 元并转增 4 股。raw 价格未被平滑、删除或修改。

## 用途审核分布

- raw_price_analysis：3 review_required。
- return_backtest：2 review_required、1 rejected（300502.SZ）。
- execution_reference：3 rejected。
- Store 行状态：0 ready、63 review_required。

阻塞原因是独立 amount 证据未闭环、300502 企业行动尚未处理，以及 execution reference 没有时效授权。
