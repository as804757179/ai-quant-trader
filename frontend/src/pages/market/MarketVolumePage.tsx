import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface LiquidityRow { key: string; stockCode: string; period: string; volumeUnit: string; amountUnit: string; validation: string; useScope: string; }

export default function MarketVolumePage() {
  const state = pendingState("成交量与流动性接口待接入", "market-volume-ui-v1");
  const columns: TableProps<LiquidityRow>["columns"] = [
    { title: "证券代码", dataIndex: "stockCode", width: 150 }, { title: "周期", dataIndex: "period", width: 120 }, { title: "成交量单位", dataIndex: "volumeUnit", width: 150 }, { title: "成交额单位", dataIndex: "amountUnit", width: 150 }, { title: "验证状态", dataIndex: "validation", width: 170 }, { title: "研究用途", dataIndex: "useScope", width: 190 },
  ];
  return <SectionPage title="成交量与流动性" subtitle="成交量、成交额、单位语义与因子适用性" relatedId="market:volume" provenance={state.provenance} metrics={[{ label: "成交量数据", value: "待接入", detail: "统一以 share 记录", tone: "review" }, { label: "成交额数据", value: "待接入", detail: "统一以 CNY 记录", tone: "review" }, { label: "Amount 因子", value: "未授权", detail: "必须通过独立字段验证", tone: "reject" }, { label: "流动性结论", value: "待审核", detail: "不能由空数据推导", tone: "review" }]} tableTitle="流动性字段验证" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="字段级授权" auditItems={[{ label: "OHLCV", value: "独立审核", detail: "不自动传播 amount 权限", tone: "info" }, { label: "amount", value: "待验证", detail: "无 Provider 证据时不能放行", tone: "review" }, { label: "单位换算", value: "可追踪", detail: "禁止重复换算", tone: "info" }]} note="流动性与成交额指标必须展示单位、来源和验证状态；未验证的 amount 不得用于研究因子或交易判断。" />;
}
