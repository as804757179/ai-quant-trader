import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface HoldingReviewRow { key: string; stockCode: string; positionState: string; researchState: string; riskState: string; actionBoundary: string; }

export default function ResearchHoldingsPage() {
  const state = pendingState("持仓再评估接口待接入", "research-holdings-ui-v1");
  const columns: TableProps<HoldingReviewRow>["columns"] = [{ title: "股票代码", dataIndex: "stockCode", width: 160 }, { title: "持仓状态", dataIndex: "positionState", width: 180 }, { title: "研究状态", dataIndex: "researchState", width: 190 }, { title: "风险状态", dataIndex: "riskState", width: 180 }, { title: "动作边界", dataIndex: "actionBoundary", width: 300 }];
  return <SectionPage title="持仓再评估" subtitle="持有标的的研究、风险和换股边界复核" relatedId="research:holdings" provenance={state.provenance} metrics={[{ label: "在持标的", value: "待接入", detail: "只读组合接口待接入", tone: "review" }, { label: "再评估完成", value: "待接入", detail: "需记录 data cutoff", tone: "review" }, { label: "风险预警", value: "待接入", detail: "不自动卖出", tone: "review" }, { label: "强制换股", value: "禁止", detail: "比较优势不等于强制交易", tone: "reject" }]} tableTitle="持仓研究复核" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="操作边界" auditItems={[{ label: "加仓", value: "需授权", detail: "仍经 Risk/Execution Gate", tone: "review" }, { label: "卖出", value: "需授权", detail: "必须遵守 T+1 与可用数量", tone: "review" }, { label: "AI 下单", value: "禁止", detail: "AI 无订单创建权限", tone: "reject" }]} note="持仓优于新机会时可以维持不动；研究复核应解释持有、减仓、加仓或不操作的理由，但不得自动执行任何订单。" />;
}
