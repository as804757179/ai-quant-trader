import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface MarketSourceRow { key: string; provider: string; endpoint: string; dataTime: string; delay: string; fallback: string; status: string; }

export default function MarketLivePage() {
  const state = pendingState("全市场行情运行明细接口待接入", "market-live-ui-v1");
  const columns: TableProps<MarketSourceRow>["columns"] = [
    { title: "Provider", dataIndex: "provider", width: 180 }, { title: "Endpoint", dataIndex: "endpoint", width: 220 }, { title: "数据时间", dataIndex: "dataTime", width: 210 }, { title: "延迟", dataIndex: "delay", width: 120 }, { title: "降级状态", dataIndex: "fallback", width: 170 }, { title: "状态", dataIndex: "status", width: 130 },
  ];
  return <SectionPage title="全市场行情" subtitle="主备行情来源、数据时间、延迟、端点与降级状态" relatedId="market:live" provenance={state.provenance} metrics={[{ label: "主行情源", value: "待接入", detail: "必须记录 Provider 与 Endpoint", tone: "review" }, { label: "最新延迟", value: "待接入", detail: "超阈值应产生数据告警", tone: "review" }, { label: "降级链路", value: "禁止静默", detail: "Provider 变更必须可审计", tone: "reject" }, { label: "业务发布", value: "关闭", detail: "行情可见不等于可交易", tone: "idle" }]} tableTitle="行情源运行明细" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="数据时效门禁" auditItems={[{ label: "行情来源", value: "待接入", detail: "provider/source/version 必须明确", tone: "review" }, { label: "数据截止", value: "待接入", detail: "统一显示 Asia/Shanghai", tone: "review" }, { label: "自动 fallback", value: "禁止", detail: "不允许悄然切换未知来源", tone: "reject" }]} note="行情页面只展示来源、时效与审计信息；任何未认证、未知或合成数据都不能被当作研究或执行价格使用。" />;
}
