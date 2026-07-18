import type { TableProps } from "antd";
import { useMarketSentiment } from "../../presentation/coreModels";
import SectionPage from "../shared/SectionPage";

interface SentimentRow { key: string; indicator: string; provider: string; cutoff: string; methodology: string; readiness: string; restriction: string; }

export default function MarketSentimentPage() {
  const state = useMarketSentiment(); const unavailable = state.data?.availability_status === "unavailable";
  const columns: TableProps<SentimentRow>["columns"] = [
    { title: "情绪指标", dataIndex: "indicator", width: 190 }, { title: "Provider", dataIndex: "provider", width: 190 }, { title: "数据截止", dataIndex: "cutoff", width: 210 }, { title: "方法说明", dataIndex: "methodology", width: 240 }, { title: "研究资格", dataIndex: "readiness", width: 160 }, { title: "限制", dataIndex: "restriction", width: 220 },
  ];
  return <SectionPage title="市场情绪" subtitle="情绪指标来源、方法、数据时点与研究使用限制" relatedId="market:sentiment" provenance={{ ...state.provenance, sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion }} metadataStatusText="正式情绪数据源尚未接入 · 不生成虚假分数" statusLabel={unavailable ? "正式数据源未接入" : state.message} statusTone="review" metrics={[{ label: "情绪数据源", value: unavailable ? "未接入" : "状态未知", detail: "正式情绪数据源尚未接入", tone: "review" }, { label: "原始观察证据", value: unavailable ? "不可用" : "状态未知", detail: "没有合格新闻或公告证据时不生成 observed-only", tone: "review" }, { label: "情绪分数", value: unavailable ? "不生成" : "状态未知", detail: "AI/LLM 分数只能是 derived，不是 observed", tone: "reject" }, { label: "交易指令", value: "禁止", detail: "情绪输出不是订单，当前不授予研究或回测资格", tone: "reject" }]} tableTitle="情绪指标资格" columns={columns} tableData={[]} tableSearchEnabled={false} rowKey="key" emptyDescription={unavailable ? "正式情绪数据源尚未接入" : state.message} auditTitle="使用边界" auditItems={[{ label: "observed-only 情绪", value: "禁止", detail: "无合格原始证据时接口返回 unavailable", tone: "reject" }, { label: "未来派生结果", value: "需血缘", detail: "必须保留证据引用、提供方、发布时间、抓取时间、算法版本和计算规则", tone: "review" }, { label: "自动执行", value: "关闭", detail: "任何情绪输出都不能直接下单", tone: "reject" }]} note="当前正式情绪数据源尚未接入，因此本页不生成分数，也不把 AI/LLM 输出标记为 observed。未来仅允许带有原始证据与完整 lineage 的 derived 或 derived_from_observed 特征作为可追溯辅助过滤条件。" />;
}
