import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface CandidateRow { key: string; runId: string; stockCode: string; enteredAt: string; expiresAt: string; rank: string; dataStatus: string; tradingStatus: string; }

export default function ResearchCandidatesPage() {
  const state = pendingState("研究候选接口待接入", "research-candidates-ui-v1");
  const columns: TableProps<CandidateRow>["columns"] = [{ title: "selection_run_id", dataIndex: "runId", width: 210 }, { title: "股票代码", dataIndex: "stockCode", width: 140 }, { title: "进入时间", dataIndex: "enteredAt", width: 190 }, { title: "失效时间", dataIndex: "expiresAt", width: 190 }, { title: "综合排名", dataIndex: "rank", width: 120 }, { title: "数据状态", dataIndex: "dataStatus", width: 140 }, { title: "交易权限", dataIndex: "tradingStatus", width: 150 }];
  return <SectionPage title="研究候选" subtitle="候选、排除、待复核和不可交易的研究状态" relatedId="research:candidates" provenance={state.provenance} metrics={[{ label: "候选数量", value: "待接入", detail: "不得展示伪候选", tone: "review" }, { label: "待复核", value: "待接入", detail: "研究资格与交易资格分离", tone: "review" }, { label: "不可交易", value: "待接入", detail: "必须保留阻断原因", tone: "review" }, { label: "自动下单", value: "关闭", detail: "候选不能直接产生订单", tone: "reject" }]} tableTitle="候选生命周期" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="候选准入" auditItems={[{ label: "数据认证", value: "必需", detail: "unknown/synthetic 不得进入", tone: "info" }, { label: "Readiness", value: "必需", detail: "按用途与 Profile 授权", tone: "info" }, { label: "投资候选发布", value: "关闭", detail: "Screener 发布锁关闭", tone: "reject" }]} note="本页只展示研究候选的可追踪状态。候选分数不是交易指令，不得因 AI 或策略建议直接创建订单。" />;
}
