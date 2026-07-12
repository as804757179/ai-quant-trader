# ADR-011：受控认证数据扩展

状态：Accepted（流程设计）；数据集发布状态：Blocked

## 决策

以冻结清单驱动数据扩展，主 Provider 固定为 Sohu raw，第二 Provider 固定为腾讯 raw 且只读。导入按股票×月份记录 checkpoint；Provider 请求失败、质量失败和不完整月份均保留明确终态，不 fallback。Certified Store 只插入新业务键，已有行只校验、不覆盖；legacy 不参与冲突。

目标区间使用沪深交易所年度休市安排版本化生成认证日历，禁止可信链路使用 weekday fallback。逐日缺失必须区分正常交易、休市、停牌、Provider 缺失或 unresolved；无法证明时保持 unresolved。

第二 Provider 每股每月至少抽查一个共同交易日。OHLC 容差为绝对差不超过 0.01 CNY；amount 未获得可靠独立证据时只阻止 `AMOUNT_FACTOR_V1`。腾讯数据禁止写 Certified Store。

企业行动必须来自官方公告并归档原件及 SHA-256。只做搜索发现而未完成事件级证据解析时状态必须为 unresolved，return_backtest 不得 ready。净税后与 Execution Reference 继续 blocked，权限不能跨 Profile 传播。

## 恢复与回滚

同一 run_id 可重跑。完整已有月份记 certified；Provider 与已有行一致但日历覆盖不完整的月份记 review_required，不重复写入。新写入按 batch 审计；错误批次不得覆盖旧行。发现污染时按 run/batch 隔离，不修改 legacy 或旧 Certified。

## 当前结果

工程导入和幂等机制已运行，但企业行动官方事件级审核尚未完成，且 688981.SH 有 6 个交易日缺失原因 unresolved。因此数据集不能发布为 return_backtest ready，Sprint14 不准入。
