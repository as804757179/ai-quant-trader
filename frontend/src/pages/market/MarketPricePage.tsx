import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface PriceRow { key: string; stockCode: string; quoteTime: string; priceSource: string; bidAskStatus: string; dataStatus: string; }

export default function MarketPricePage() {
  const state = pendingState("价格与盘口审计接口待接入", "market-price-ui-v1");
  const columns: TableProps<PriceRow>["columns"] = [
    { title: "证券代码", dataIndex: "stockCode", width: 150 }, { title: "报价时间", dataIndex: "quoteTime", width: 210 }, { title: "价格来源", dataIndex: "priceSource", width: 220 }, { title: "盘口状态", dataIndex: "bidAskStatus", width: 180 }, { title: "数据资格", dataIndex: "dataStatus", width: 170 },
  ];
  return <SectionPage title="价格与盘口" subtitle="价格、五档盘口、报价来源与执行适用性审计" relatedId="market:price" provenance={state.provenance} metrics={[{ label: "有效报价", value: "待接入", detail: "不展示伪实时价格", tone: "review" }, { label: "盘口完整性", value: "待接入", detail: "买卖盘字段需单独验证", tone: "review" }, { label: "执行参考", value: "未授权", detail: "Execution Reference 独立审核", tone: "reject" }, { label: "报价降级", value: "待接入", detail: "不可用时不得虚构价格", tone: "review" }]} tableTitle="报价与盘口审计" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="执行边界" auditItems={[{ label: "价格适用性", value: "未授权", detail: "研究数据不能自动成为执行价格", tone: "reject" }, { label: "报价时效", value: "待接入", detail: "必须输出精确数据时间", tone: "review" }, { label: "无有效价格", value: "拒绝成交", detail: "不得以上一日或合成价格替代", tone: "reject" }]} note="本页不产生价格指令，也不为 Simulation 或 Live 交易授予执行参考数据权限。" />;
}
