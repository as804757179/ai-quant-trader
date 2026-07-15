import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface AnalysisRow { key: string; dimension: string; source: string; cutoff: string; quality: string; conclusion: string; }

export default function ResearchDeepPage() {
  const state = pendingState("深度研究接口待接入", "research-deep-ui-v1");
  const columns: TableProps<AnalysisRow>["columns"] = [{ title: "研究维度", dataIndex: "dimension", width: 180 }, { title: "证据来源", dataIndex: "source", width: 250 }, { title: "数据截止", dataIndex: "cutoff", width: 200 }, { title: "质量状态", dataIndex: "quality", width: 150 }, { title: "展示结论", dataIndex: "conclusion", width: 300 }];
  return <SectionPage title="深度分析" subtitle="技术、财务、公告新闻、情绪、行业、流动性和风险证据" relatedId="research:deep" provenance={state.provenance} metrics={[{ label: "技术分析", value: "待接入", detail: "仅认证历史数据", tone: "review" }, { label: "财务信息", value: "待接入", detail: "必须 point-in-time", tone: "review" }, { label: "新闻公告", value: "待接入", detail: "需记录可得时间", tone: "review" }, { label: "AI 交易结论", value: "禁止", detail: "AI 仅展示与解释", tone: "reject" }]} tableTitle="研究证据维度" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="分析边界" auditItems={[{ label: "未来函数", value: "禁止", detail: "只使用当时可得信息", tone: "reject" }, { label: "数据质量", value: "必需", detail: "记录 provider、版本和 cutoff", tone: "info" }, { label: "交易结论", value: "待审批", detail: "不得绕过执行安全门禁", tone: "review" }]} note="深度分析必须将技术、财务、公告新闻、情绪、行业、流动性、风险和因子贡献分别标注来源、时间与质量，不能把展示性分析伪装为 Alpha。" />;
}
