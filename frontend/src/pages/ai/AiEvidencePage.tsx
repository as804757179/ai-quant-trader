import { Button, Input, Select } from "antd";
import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { useEffect, useMemo, useState } from "react";
import { appendFinancialLocationReview, type FinancialLocationCandidateListData, type FinancialLocationReviewListData, type FinancialLocationReviewRequest, type ResearchEvidence, useAiAuditSummary, useAiSignals, useFinancialLocationCandidates, useFinancialLocationReviews, useResearchEvidence, useResearchEvidenceDetail } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

interface EvidenceRow { key: string; evidenceId: string; stockCode: string; title: string; usageStatus: string; qualityStatus: string; }
type CandidateRow = NonNullable<FinancialLocationCandidateListData["items"]>[number] & { key: string; };
type FinancialLocationConclusion = FinancialLocationReviewRequest["conclusion"];
interface PendingSubmission extends FinancialLocationReviewRequest { evidenceId: string; idempotencyKey: string; }

const conclusionLabels: Record<FinancialLocationConclusion, string> = {
  confirmed: "确认定位",
  rejected: "拒绝定位",
  ambiguous: "定位存在歧义",
  needs_more_evidence: "需要更多证据",
};

export default function AiEvidencePage() {
  const [evidencePage, setEvidencePage] = useState(1); const [evidencePageSize, setEvidencePageSize] = useState(50); const [selectedEvidenceId, setSelectedEvidenceId] = useState<string>(); const [candidatePage, setCandidatePage] = useState(1); const [candidatePageSize, setCandidatePageSize] = useState(50); const [refreshVersion, setRefreshVersion] = useState(0);
  const [selectedLocationId, setSelectedLocationId] = useState<string>(); const [conclusion, setConclusion] = useState<FinancialLocationConclusion>("needs_more_evidence"); const [reason, setReason] = useState(""); const [submitMessage, setSubmitMessage] = useState(""); const [submitting, setSubmitting] = useState(false); const [pendingSubmission, setPendingSubmission] = useState<PendingSubmission>();
  const evidence = useResearchEvidence("financial_report", evidencePage, evidencePageSize); const detail = useResearchEvidenceDetail(selectedEvidenceId); const candidates = useFinancialLocationCandidates(selectedEvidenceId, candidatePage, candidatePageSize, refreshVersion); const reviews = useFinancialLocationReviews(selectedEvidenceId, refreshVersion); const signals = useAiSignals(); const audit = useAiAuditSummary(); const total = evidence.data?.total;
  const evidenceKnown = (evidence.kind === "live" || evidence.kind === "empty") && typeof total === "number";
  const reviewable = (evidence.data?.items ?? []).filter((item) => item.quality_status === "observed" && item.usage_status === "review_required");
  const rows: EvidenceRow[] = reviewable.map((item: ResearchEvidence, index) => ({ key: item.evidence_id ?? `financial-report-${index}`, evidenceId: item.evidence_id ?? "未记录", stockCode: item.stock_code ?? "未记录", title: item.title ?? "未记录", usageStatus: item.usage_status ?? "未记录", qualityStatus: item.quality_status ?? "未记录" }));
  const candidateRows: CandidateRow[] = (candidates.data?.items ?? []).map((item, index) => ({ ...item, key: item.location_id ?? `financial-location-${index}` }));
  const selectedCandidate = useMemo(() => candidateRows.find((item) => item.location_id === selectedLocationId), [candidateRows, selectedLocationId]);
  const reviewRows = (reviews.data?.items ?? []).map((item, index) => ({ ...item, key: item.review_id ?? `financial-location-review-${index}` }));

  useEffect(() => {
    setSelectedLocationId(undefined);
    setCandidatePage(1);
    setPendingSubmission(undefined);
    setSubmitMessage("");
  }, [selectedEvidenceId]);

  const submitReview = async () => {
    if (!selectedEvidenceId || !selectedCandidate?.location_id) {
      setSubmitMessage("请先选择一条当前有效的页级定位候选");
      return;
    }
    const normalizedReason = reason.trim();
    if (!normalizedReason) {
      setSubmitMessage("复核理由不能为空");
      return;
    }
    const sameRequest = pendingSubmission
      && pendingSubmission.evidenceId === selectedEvidenceId
      && pendingSubmission.location_id === selectedCandidate.location_id
      && pendingSubmission.conclusion === conclusion
      && pendingSubmission.reason === normalizedReason;
    const submission: PendingSubmission = sameRequest
      ? pendingSubmission
      : { evidenceId: selectedEvidenceId, location_id: selectedCandidate.location_id, conclusion, reason: normalizedReason, idempotencyKey: crypto.randomUUID() };
    if (!sameRequest) setPendingSubmission(submission);
    setSubmitting(true);
    setSubmitMessage("");
    try {
      const response = await appendFinancialLocationReview(
        selectedEvidenceId,
        {
          location_id: submission.location_id,
          conclusion: submission.conclusion,
          reason: submission.reason,
        },
        submission.idempotencyKey,
      );
      setSubmitMessage(response.message || "页级定位复核已追加");
      setReason("");
      setPendingSubmission(undefined);
      setRefreshVersion((value) => value + 1);
    } catch (error) {
      setSubmitMessage(error instanceof Error ? error.message : "页级定位复核提交失败，可使用相同请求重试");
    } finally {
      setSubmitting(false);
    }
  };
  const columns: TableProps<EvidenceRow>["columns"] = [
    { title: "证据 ID", dataIndex: "evidenceId", width: 220 }, { title: "证券代码", dataIndex: "stockCode", width: 130 }, { title: "财报标题", dataIndex: "title", width: 360 }, { title: "质量状态", dataIndex: "qualityStatus", width: 140 }, { title: "用途状态", dataIndex: "usageStatus", width: 160 },
  ];
  const reviewColumns: TableProps<NonNullable<FinancialLocationReviewListData["items"]>[number] & { key: string }>['columns'] = [
    { title: "字段", dataIndex: "field_name", width: 180, render: (value) => value ?? "未记录" }, { title: "页码", dataIndex: "page_number", width: 100, render: (value) => value ?? "未记录" }, { title: "复核结论", dataIndex: "conclusion", width: 160, render: (value) => value ?? "未记录" }, { title: "定位状态", dataIndex: "location_status", width: 150, render: (value) => value ?? "未记录" }, { title: "复核时间", dataIndex: "reviewed_at", width: 210, render: (value) => formatChinaDateTime(value) }, { title: "复核理由", dataIndex: "reason", width: 360, render: (value) => value ?? "未记录" },
  ];
  const candidateColumns: TableProps<CandidateRow>["columns"] = [
    { title: "字段", dataIndex: "field_name", width: 180, render: (value) => value ?? "未记录" }, { title: "页码", dataIndex: "page_number", width: 100, render: (value) => value ?? "未记录" }, { title: "候选状态", dataIndex: "status", width: 150, render: (value) => value ?? "未记录" }, { title: "原始值", dataIndex: "raw_value", width: 220, render: (value) => value ?? "未记录" }, { title: "规范化值", dataIndex: "normalized_value", width: 180, render: (value) => value ?? "未记录" }, { title: "定位版本", dataIndex: "locator_version", width: 150, render: (value) => value ?? "未记录" }, { title: "页文本 Hash", dataIndex: "text_hash", width: 220, render: (value) => value ?? "未记录" }, { title: "操作", key: "action", width: 120, render: (_value, row) => <Button size="small" type={row.location_id === selectedLocationId ? "primary" : "default"} disabled={!row.location_id || row.extraction_status !== "text_observed"} onClick={() => setSelectedLocationId(row.location_id)}>选择复核</Button> },
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
      <section className="panel table-panel"><div className="panel__title">当前页级定位候选</div><div className="panel__body"><ReadOnlyTable columns={candidateColumns} data={candidateRows} rowKey="key" emptyDescription={selectedEvidenceId ? candidates.message : "请选择财报证据查看当前候选"} showSearch={false} remotePagination={(candidates.kind === "live" || candidates.kind === "empty") && typeof candidates.data?.total === "number" ? { current: candidates.data?.page ?? candidatePage, pageSize: candidates.data?.page_size ?? candidatePageSize, total: candidates.data.total, onChange: (nextPage, nextPageSize) => { setCandidatePage(nextPageSize === candidatePageSize ? nextPage : 1); setCandidatePageSize(nextPageSize); setSelectedLocationId(undefined); } } : undefined} /></div></section>
      <section className="panel"><div className="panel__title">追加页级定位人工复核</div><div className="panel__body news-review-editor"><p className="soft-note">{selectedCandidate ? `当前候选：${selectedCandidate.field_name ?? "未记录"} · 第 ${selectedCandidate.page_number ?? "未记录"} 页 · parse run ${selectedCandidate.parse_run_id ?? "未记录"} · locator ${selectedCandidate.locator_version ?? "未记录"}` : "请选择当前解析运行中具有 text_observed 页证据的候选；候选已失效、无权限或服务拒绝时不会显示为成功。"}</p><div className="news-review-editor__fields"><label htmlFor="financial-location-conclusion">复核结论<Select id="financial-location-conclusion" value={conclusion} onChange={setConclusion} disabled={!selectedCandidate} options={Object.entries(conclusionLabels).map(([value, label]) => ({ value, label }))} /></label></div><label htmlFor="financial-location-reason">复核理由<Input.TextArea id="financial-location-reason" value={reason} maxLength={2000} rows={3} onChange={(event) => setReason(event.target.value)} placeholder="说明为何确认、拒绝、存在歧义或仍需更多证据" disabled={!selectedCandidate} /></label><div className="news-review-editor__actions"><Button type="primary" onClick={() => void submitReview()} loading={submitting} disabled={!selectedCandidate || !reason.trim()}> {pendingSubmission ? "重试同一复核请求" : "追加复核记录"}</Button><span>{submitMessage || "后端以已认证会话主体记录复核人，并依据候选的原始 Hash 与定位版本计算请求 Hash；提交不会授予 Research Readiness、候选发布或交易权限。"}</span></div></div></section>
      <section className="panel table-panel"><div className="panel__title">页级定位复核历史</div><div className="panel__body"><ReadOnlyTable columns={reviewColumns} data={reviewRows} rowKey="key" emptyDescription={selectedEvidenceId ? reviews.message : "请选择财报证据查看复核历史"} showSearch={false} /></div></section>
      <section className="panel"><div className="panel__title">审核边界</div><div className="panel__body"><p className="soft-note">AI 上下文必须记录来源、截止时间、版本和认证状态。unknown、synthetic 或 uncertified 数据不得被包装成可用于交易判断的证据；本页不创建 AI 私有证据副本，不生成研究准入或订单。</p></div></section>
    </section>
  );
}
