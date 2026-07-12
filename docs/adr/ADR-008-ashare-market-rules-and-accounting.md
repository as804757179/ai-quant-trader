# ADR-008：A股市场规则与会计基线

日期：2026-07-12  
状态：已接受（内部验证）

## 背景

Sprint10 的固定样本验证尚未实现过户费，可信回测仍可能从 K 线日期或 weekday 推导交易日，涨跌停依赖代码前缀，独立参考实现也没有覆盖多次买入和部分卖出。扩大数据前必须把市场规则、证券状态、日历和会计口径变成可追踪且 fail closed 的输入。

## 决策

新增 `AshareMarketRuleRegistry`。每条规则保存 rule_type、exchange、board、security_status、生效区间、value、source_name、source_reference 和 rule_version。规则按交易日期及显式 `SecurityStatusSnapshot` 解析；缺少覆盖、状态 unknown、前收盘价无效或规则冲突时拒绝，不再以代码前缀永久推断可信成交规则。

## 官方依据

- 佣金、最低佣金、印花税、过户费：[上交所股票投资费用说明](https://one.sse.com.cn/onething/gptz/)。该页面说明佣金最高不超过成交金额 3‰、最低 5 元，印花税按成交金额 0.5‰ 向出让方单边征收，过户费按成交金额 0.01‰ 双向收取。
- 印花税生效：[财政部、税务总局公告 2023 年第 39 号](https://shanxi.chinatax.gov.cn/web/detail/sx-11400-545-1780448)，自 2023-08-28 起减半征收。
- 过户费：[中国结算上海市场收费及代收税费一览表](https://www.chinaclear.cn/zdjs/editor_file/20220701154723234.pdf)，A 股成交金额 0.01‰ 双向收取。注册表从 2022-04-29 起提供该规则；更早日期没有本项目已认证的官方版本，因此 fail closed。
- 深市整手与涨跌停：[深圳证券交易所交易规则（2023 年修订）](https://docs.static.szse.cn/www/lawrules/rule/trade/W020230217564423808793.pdf)。买入为 100 股或整数倍，主板 10%、创业板 20%，首次公开发行上市后前五个交易日等情形无涨跌幅限制。
- 沪市规则：[上海证券交易所交易规则（2023 年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20250519_10779396.shtml)。
- 沪市 2026 规则版本：[上海证券交易所交易规则（2026 年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)，自 2026-07-06 生效；主板风险警示股票限制由 5% 调整为 10%。固定 2026-06 样本仍解析旧版本。
- 交易日历：[上交所 2026 年休市安排](https://www.sse.com.cn/disclosure/dealinstruc/closed/)及[深交所 2026 年端午节休市通知](https://www.szse.cn/disclosure/notice/general/t20260611_620979.html)。2026-06-19 明确为休市日。

## 费用模型

内部可信验证使用官方披露的佣金上限 3‰及最低 5 元作为保守、可复现的会计基线。该数值不是对任一历史券商账户实际佣金的声明。若未来需要账户级真实回测，必须导入并认证具体券商费率版本。

固定样本适用：

- 买卖佣金：成交金额 × 3‰，最低 5 元。
- 卖出印花税：成交金额 × 0.5‰。
- 买卖过户费：成交金额 × 0.01‰。
- 滑点：0.2%，属于明确的内部执行模型，不是官方收费。

每笔成交分别记录 commission、stamp_duty、transfer_fee、slippage 和 realized_pnl。买入持仓成本包含成交金额、佣金与过户费；卖出净收入扣除佣金、印花税和过户费。持仓采用加权平均成本，部分卖出按卖出数量分摊成本。

## 可信交易日历

`TrustedTradingCalendar` 仅读取 `market.trading_calendar` 中 status=confirmed、source=sse/szse、带官方 source_reference 且 timezone=Asia/Shanghai 的完整自然日覆盖。沪深开放日期必须一致。可信模式缺少日历、覆盖不全或 K 线日期不在认证日历时立即失败。

普通单元测试仍可传入显式 fixture 日历；weekday fallback 不得进入可信内部验证。

## 证券状态与涨跌停

证券状态输入包含 exchange、board、NORMAL/ST、有效区间、停牌状态、是否免涨跌停、前收盘价有效性、官方证据和版本。固定样本明确声明：

- 300308.SZ：SZ/GEM/NORMAL，20%。
- 603986.SH：SH/MAIN/NORMAL，10%。

上市初期等无涨跌停情形必须显式设置 `price_limit_exempt=true`。unknown 状态、缺少日期覆盖或无有效前收盘价时 fail closed。

## 独立会计基线

独立参考实现使用 Decimal 和独立持仓状态，不调用 BacktestEngine 的成交、费用、资金、持仓或指标计算。覆盖 12 个场景：单买全卖、多买全卖、多买部分卖、部分卖后再买、最低佣金、资金不足、超可用持仓、同一执行日买卖的 T+1 拒绝、停牌、涨停买入拒绝、跌停卖出拒绝、过户费生效边界。

逐日比较现金、总持仓、可用持仓、总成本、已实现/未实现盈亏、市值、总资产及各项费用。所有场景差异必须为 0。

## Hash 标准化

dataset records 按 stock_code、trading_date、adjustment、raw_hash 排序；股票、raw hashes、batch IDs、review IDs、交易、净值、规则版本和证券状态版本均使用稳定业务键排序。generated_at 不进入 result_hash。

数据库返回顺序、股票输入顺序和重复运行不得改变哈希；费用、规则或状态版本变化必须产生新哈希。Sprint11 不复用 Sprint10 结果哈希。

## 发布决定

所有 Backtest、Screener、Trading、Live 和 AI Order 发布锁继续为 false。本 ADR 只证明固定样本下规则解析和会计计算可复现，不构成盈利验证、投资建议或交易授权。
