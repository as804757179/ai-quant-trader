import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface LimitRuleRow { key: string; stockCode: string; tradeDate: string; securityStatus: string; limitRule: string; tickRule: string; resolution: string; }

export default function MarketLimitPage() {
  const state = pendingState("涨跌停与证券状态接口待接入", "market-limit-ui-v1");
  const columns: TableProps<LimitRuleRow>["columns"] = [
    { title: "证券代码", dataIndex: "stockCode", width: 150 }, { title: "交易日期", dataIndex: "tradeDate", width: 160 }, { title: "证券状态", dataIndex: "securityStatus", width: 180 }, { title: "涨跌停规则", dataIndex: "limitRule", width: 210 }, { title: "最小变动单位", dataIndex: "tickRule", width: 180 }, { title: "解析结果", dataIndex: "resolution", width: 170 },
  ];
  return <SectionPage title="涨跌停与状态" subtitle="按交易日期、证券状态和最小价格变动单位解析市场微观规则" relatedId="market:limit" provenance={state.provenance} metrics={[{ label: "规则版本", value: "待接入", detail: "不得用代码前缀永久猜测", tone: "review" }, { label: "证券状态", value: "待接入", detail: "ST、停牌与无涨跌停需有证据", tone: "review" }, { label: "未知状态", value: "失败关闭", detail: "需要规则时必须拒绝", tone: "reject" }, { label: "价格 Tick", value: "0.01 CNY", detail: "规则模型要求 Decimal 取整", tone: "info" }]} tableTitle="交易日期规则解析" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="微观规则边界" auditItems={[{ label: "涨跌停价格", value: "精确取整", detail: "不使用比例模糊容差", tone: "info" }, { label: "无前收盘价", value: "失败关闭", detail: "不能推定限制价", tone: "reject" }, { label: "停牌", value: "拒绝成交", detail: "无合法成交价不得执行", tone: "reject" }]} note="本页只说明规则解析状态；交易执行仍由 Execution Gate、Risk Engine 和明确授权共同控制。" />;
}
