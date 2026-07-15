import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface SectorRow { key: string; sectorId: string; sectorName: string; classificationSource: string; effectiveRange: string; coverage: string; validation: string; }

export default function MarketSectorPage() {
  const state = pendingState("行业与板块接口待接入", "market-sector-ui-v1");
  const columns: TableProps<SectorRow>["columns"] = [
    { title: "板块 ID", dataIndex: "sectorId", width: 160 }, { title: "行业/板块", dataIndex: "sectorName", width: 200 }, { title: "分类来源", dataIndex: "classificationSource", width: 220 }, { title: "有效区间", dataIndex: "effectiveRange", width: 220 }, { title: "覆盖范围", dataIndex: "coverage", width: 160 }, { title: "验证状态", dataIndex: "validation", width: 170 },
  ];
  return <SectionPage title="行业与板块" subtitle="行业分类来源、有效区间、覆盖范围与集中度研究边界" relatedId="market:sector" provenance={state.provenance} metrics={[{ label: "分类版本", value: "待接入", detail: "行业归属需有来源与有效期", tone: "review" }, { label: "板块覆盖", value: "待接入", detail: "不能由代码名猜测归属", tone: "review" }, { label: "集中度研究", value: "待审核", detail: "风控输入需独立认证", tone: "review" }, { label: "策略发布", value: "关闭", detail: "行业观察不输出候选股", tone: "idle" }]} tableTitle="分类与有效区间" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="分类控制" auditItems={[{ label: "分类来源", value: "必须", detail: "记录 source 与版本", tone: "info" }, { label: "历史归属", value: "时点化", detail: "不使用今天分类回写历史", tone: "info" }, { label: "集中度下单", value: "禁止", detail: "仍需 Risk Engine 审核", tone: "reject" }]} note="行业和板块页面仅提供只读观察；分类数据没有明确来源或版本时，不得进入风险或选股链路。" />;
}
