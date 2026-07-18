import { Select } from "antd";
import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { useState } from "react";
import { type FinancialLocationReviewListData, type ResearchEvidence, useAiAuditSummary, useAiSignals, useFinancialLocationReviews, useResearchEvidence, useResearchEvidenceDetail } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

interface EvidenceRow { key: string; evidenceId: string; stockCode: string; title: string; usageStatus: string; qualityStatus: string; }

export default function AiEvidencePage() {
  const [evidencePage, setEvidencePage] = useState(1); const [evidencePageSize, setEvidencePageSize] = useState(50); const [selectedEvidenceId, setSelectedEvidenceId] = useState<string>();
  const evidence = useResearchEvidence("financial_report", evidencePage, evidencePageSize); const detail = useResearchEvidenceDetail(selectedEvidenceId); const reviews = useFinancialLocationReviews(selectedEvidenceId); const signals = useAiSignals(); const audit = useAiAuditSummary(); const total = evidence.data?.total;
  const evidenceKnown = (evidence.kind === "live" || evidence.kind === "empty") && typeof total === "number";
  const reviewable = (evidence.data?.items ?? []).filter((item) => item.quality_status === "observed" && item.usage_status === "review_required");
  const rows: EvidenceRow[] = reviewable.map((item: ResearchEvidence, index) => ({ key: item.evidence_id ?? `financial-report-${index}`, evidenceId: item.evidence_id ?? "未记录", stockCode: item.stock_code ?? "未记录", title: item.title ?? "未记录", usageStatus: item.usage_status ?? "未记录", qualityStatus: item.quality_status ?? "未记录" }));
  const reviewRows = (reviews.data?.items ?? []).map((item, index) => ({ ...item, key: item.review_id ?? `financial-location-review-${index}` }));
  const columns: TableProps<EvidenceRow>["columns"] = [
    { title: "证据 ID", dataIndex: "evidenceId", width: 220 }, { title: "证券代码", dataIndex: "stockCode", width: 130 }, { title: "财报标题", dataIndex: "title", width: 360 }, { title: "质量状态", dataIndex: "qualityStatus", width: 140 }, { title: "用途状态", dataIndex: "usageStatus", width: 160 },
  ];
  const reviewColumns: TableProps<NonNullable<FinancialLocationReviewListData["items"]>[number] & { key: string }>['columns'] = [
    { title: "字段", dataIndex: "field_name", width: 180, render: (value) => value ?? "未记录" }, { title: "页码", dataIndex: "page_number", width: 100, render: (value) => value ?? "未记录" }, { title: "复核结论", dataIndex: "conclusion", width: 160, render: (value) => value ?? "未记录" }, { title: "定位状态", dataIndex: "location_status", width: 150, render: (value) => value ?? "未记录" }, { title: "复核时间", dataIndex: "reviewed_at", width: 210, render: (value) => formatChinaDateTime(value) }, { title: "复核理由", dataIndex: "reason", width: 360, render: (value) => value ?? "未记录" },
  ];

  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header"><div><h1>证据复核</h1><p>财报原始证据、页级复核历史与 AI 审计上下文</p></div><StatusBadge label={evidenceKnown ? "已接入（只读）" : evidence.message} tone={evidenceKnown ? "info" : "review"} /></header>
      <DataMetaBar provenance={{ ...evidence.provenance, sourceVersion: evidence.data?.source_version ?? evidence.provenance.sourceVersion }} relatedId={selectedEvidenceId ? `research:evidence:${selectedEvidenceId}` : "ai:evidence"} statusText="证据与 AI 审计独立展示 · 不创建 AI 私有证据副本 · 不授予交易权限" />
      <div className="metric-grid" style={{ "--metric-columns": 4 } as CSSProperties}>
        <MetricCard label="财报证据" value={evidenceKnown ? total : "状态未知"} detail={evidenceKnown ? `当前页可复核 ${rows.length} 条` : "接口不可用时不将其视为 0"} tone={evidenceKnown ? "info" : "review"} />
        <MetricCard label="页级复核历史" value={selectedEvidenceId && (reviews.kind === "live" || reviews.kind === "empty") ? reviews.data?.total ?? "未记录" : "未选择证据"} detail="仅已观察且待复核的财报可查询" tone="review" />
        <MetricCard label="AI 信号记录" value={signals.data?.total ?? "状态未知"} detail="仅作分析标签审计，不是订单" tone="review" />
        <MetricCard label="AI 来源订单" value={audit.data ? audit.data.ai_order_count ?? "未记录" : "状态未知"} detail="不由本页创建或改变" tone={audit.data?.order_created === false ? "pass" : "reject"} />
      </div>
      <section className="panel table-panel"><div className="panel__title">可复核财报证据（服务端分页）</div><div className="panel__body"><ReadOnlyTable columns={columns} data={rows} rowKey="key" emptyDescription={evidence.message} showSearch={false} remotePagination={evidenceKnown ? { current: evidence.data?.page ?? evidencePage, pageSize: evidence.data?.page_size ?? evidencePageSize, total, onChange: (nextPage, nextPageSize) => { setEvidencePage(nextPageSize === evidencePageSize ? nextPage : 1); setEvidencePageSize(nextPageSize); setSelectedEvidenceId(undefined); } } : undefined} /></div></section>
      <section className="panel"><div className="panel__title">所选财报证据详情</div><div className="panel__body"><Select aria-label="选择财报证据" value={selectedEvidenceId} onChange={setSelectedEvidenceId} placeholder="选择一条可复核财报证据" style={{ minWidth: 420, maxWidth: "100%" }} options={reviewable.filter((item) => item.evidence_id).map((item) => ({ value: item.evidence_id!, label: `${item.stock_code ?? "未记录"} · ${item.title ?? item.evidence_id}` }))} /><p className="soft-note">{selectedEvidenceId ? detail.kind === "live" ? `来源：${[detail.data?.publisher_name, detail.data?.provider, detail.data?.source].filter(Boolean).join(" · ") || "未记录"}；原始 Hash：${detail.data?.raw_hash ?? "未记录"}；解析状态：${detail.data?.financial_report_detail?.detail_parse_status ?? "未记录"}；页级定位：${detail.data?.financial_report_snapshot_location?.parse_run?.status ?? "未记录"}` : detail.message : "请选择一条已观察且待复核的财报证据；本页不会推断其与任何 AI 信号存在关联。"}</p></div></section>
      <section className="panel table-panel"><div className="panel__title">页级定位复核历史</div><div className="panel__body"><ReadOnlyTable columns={reviewColumns} data={reviewRows} rowKey="key" emptyDescription={selectedEvidenceId ? reviews.message : "请选择财报证据查看复核历史"} showSearch={false} /></div></section>
      <section className="panel"><div className="panel__title">审核边界</div><div className="panel__body"><p className="soft-note">AI 上下文必须记录来源、截止时间、版本和认证状态。unknown、synthetic 或 uncertified 数据不得被包装成可用于交易判断的证据；本页不创建 AI 私有证据副本，不生成研究准入或订单。</p></div></section>
    </section>
  );
}
