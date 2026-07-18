import type { TableProps } from "antd";
import { useState } from "react";
import { type ResearchEvidence, useResearchEvidence } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import SectionPage from "../shared/SectionPage";

interface NewsRow { key: string; eventId: string; source: string; publishedAt: string; receivedAt: string; verification: string; useStatus: string; }

export default function MarketNewsPage() {
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(50); const state = useResearchEvidence("news", page, pageSize); const total = state.data?.total;
  const known = (state.kind === "live" || state.kind === "empty") && typeof total === "number";
  const rows: NewsRow[] = (state.data?.items ?? []).map((item: ResearchEvidence, index) => ({
    key: item.evidence_id ?? `news-${index}`,
    eventId: item.evidence_id ?? "未记录",
    source: [item.publisher_name, item.provider, item.source].filter(Boolean).join(" · ") || "未记录",
    publishedAt: formatChinaDateTime(item.source_published_at ?? item.source_published_date ?? undefined),
    receivedAt: formatChinaDateTime(item.received_at ?? undefined),
    verification: item.quality_status ?? "未记录",
    useStatus: item.usage_status ?? "未记录",
  }));
  const columns: TableProps<NewsRow>["columns"] = [
    { title: "事件 ID", dataIndex: "eventId", width: 210 }, { title: "来源", dataIndex: "source", width: 210 }, { title: "发布时间", dataIndex: "publishedAt", width: 210 }, { title: "接收时间", dataIndex: "receivedAt", width: 210 }, { title: "验证状态", dataIndex: "verification", width: 160 }, { title: "用途状态", dataIndex: "useStatus", width: 170 },
  ];
  return <SectionPage title="新闻与事件" subtitle="新闻来源、发布与接收时点、质量状态和用途记录" relatedId="market:news" provenance={{ ...state.provenance, sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion }} metadataStatusText="只读新闻证据 · 服务端分页 · 不将新闻显示为研究就绪或交易授权" statusLabel={known ? "已接入（只读）" : state.message} statusTone={known ? "info" : "review"} metrics={[{ label: "新闻事件", value: known ? total : "状态未知", detail: known ? `本页 ${rows.length} 条 · 仅 evidence_type=news` : "接口不可用时不将其视为 0", tone: known ? "info" : "review" }, { label: "已观察", value: known ? state.data?.summary?.observed ?? "未记录" : "状态未知", detail: "质量状态由服务端记录", tone: "review" }, { label: "最近可得时间", value: known ? formatChinaDateTime(state.data?.summary?.latest_available_at ?? undefined) : "状态未知", detail: "发布时间与接收时间不相互替代", tone: "review" }, { label: "研究与交易", value: "未授予", detail: "新闻展示不授予 Readiness 或订单权限", tone: "reject" }]} tableTitle="新闻事件审计（服务端分页）" columns={columns} tableData={rows} tablePagination={known ? { current: state.data?.page ?? page, pageSize: state.data?.page_size ?? pageSize, total, onChange: (nextPage, nextPageSize) => { setPage(nextPageSize === pageSize ? nextPage : 1); setPageSize(nextPageSize); } } : undefined} tableSearchEnabled={false} rowKey="key" emptyDescription={state.message} auditTitle="时点与安全" auditItems={[{ label: "未来信息", value: "禁止", detail: "不以发布时间替代已接收和可得时间", tone: "reject" }, { label: "人工复核", value: "另页追加", detail: "仅新闻人工复核页面可写入复核记录", tone: "review" }, { label: "订单创建", value: "禁止", detail: "新闻展示不调用 TradeSubmitter", tone: "reject" }]} note="新闻信息可被研究层引用，但必须保留来源和可得时点；本页不将新闻或情绪包装为可交易信号。" />;
}
