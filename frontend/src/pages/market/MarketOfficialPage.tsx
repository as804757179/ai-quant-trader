import type { TableProps } from "antd";
import { useState } from "react";
import { type ResearchEvidence, useResearchEvidence } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import SectionPage from "../shared/SectionPage";

interface NoticeRow { key: string; noticeId: string; stockCode: string; publishedAt: string; source: string; evidenceHash: string; availability: string; }

export default function MarketOfficialPage() {
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(50); const state = useResearchEvidence("announcement", page, pageSize); const total = state.data?.total;
  const known = (state.kind === "live" || state.kind === "empty") && typeof total === "number";
  const rows: NoticeRow[] = (state.data?.items ?? []).map((item: ResearchEvidence, index) => ({
    key: item.evidence_id ?? `announcement-${index}`,
    noticeId: item.evidence_id ?? "未记录",
    stockCode: item.stock_code ?? "未记录",
    publishedAt: formatChinaDateTime(item.source_published_at ?? item.source_published_date ?? undefined),
    source: [item.publisher_name, item.provider, item.source].filter(Boolean).join(" · ") || "未记录",
    evidenceHash: item.raw_hash ?? "未记录",
    availability: item.available_at ? `${formatChinaDateTime(item.available_at)} · ${item.availability_basis ?? "依据未记录"}` : "未记录",
  }));
  const columns: TableProps<NoticeRow>["columns"] = [
    { title: "公告 ID", dataIndex: "noticeId", width: 180 }, { title: "证券代码", dataIndex: "stockCode", width: 150 }, { title: "公告时间", dataIndex: "publishedAt", width: 210 }, { title: "官方来源", dataIndex: "source", width: 200 }, { title: "证据 Hash", dataIndex: "evidenceHash", width: 250 }, { title: "时点状态", dataIndex: "availability", width: 160 },
  ];
  return <SectionPage title="官方公告" subtitle="公告证据、来源记录与可得时间" relatedId="market:official" provenance={{ ...state.provenance, sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion }} metadataStatusText="只读公告证据 · 服务端分页 · 不将公告显示为研究就绪或交易授权" statusLabel={known ? "已接入（只读）" : state.message} statusTone={known ? "info" : "review"} metrics={[{ label: "公告证据", value: known ? total : "状态未知", detail: known ? `本页 ${rows.length} 条 · 仅 evidence_type=announcement` : "接口不可用时不将其视为 0", tone: known ? "info" : "review" }, { label: "已观察", value: known ? state.data?.summary?.observed ?? "未记录" : "状态未知", detail: "质量状态由服务端记录", tone: "review" }, { label: "最近可得时间", value: known ? formatChinaDateTime(state.data?.summary?.latest_available_at ?? undefined) : "状态未知", detail: "不以公告日期替代可得时间", tone: "review" }, { label: "研究与交易", value: "未授予", detail: "证据展示不授予 Readiness 或订单权限", tone: "reject" }]} tableTitle="公告证据与时点（服务端分页）" columns={columns} tableData={rows} tablePagination={known ? { current: state.data?.page ?? page, pageSize: state.data?.page_size ?? pageSize, total, onChange: (nextPage, nextPageSize) => { setPage(nextPageSize === pageSize ? nextPage : 1); setPageSize(nextPageSize); } } : undefined} tableSearchEnabled={false} rowKey="key" emptyDescription={state.message} auditTitle="证据约束" auditItems={[{ label: "来源", value: "按记录展示", detail: "不从空缺字段推断官方来源", tone: "info" }, { label: "文件哈希", value: "保留原值", detail: "Hash 缺失时明确显示未记录", tone: "review" }, { label: "未来可见", value: "禁止", detail: "不能用后来修订改写过去信号", tone: "reject" }]} note="公告页面仅作证据索引；它不自动形成研究结论、企业行动结论或交易指令。" />;
}
