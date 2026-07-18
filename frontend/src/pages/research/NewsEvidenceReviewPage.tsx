import { Button, Input, Select } from "antd";
import type { TableProps } from "antd";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { get, post } from "../../api/client";
import { useReadOnlyDisplay } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

type ManualConclusion = "title_link_relevant" | "title_link_irrelevant" | "needs_more_evidence";

interface NewsManualReview {
  review_id?: string;
  evidence_id?: string;
  reviewer_label?: string;
  conclusion?: ManualConclusion;
  reason?: string;
  reviewed_at?: string;
}

interface NewsEvidence {
  evidence_id?: string;
  stock_code?: string;
  title?: string;
  document_url?: string;
  publisher_name?: string;
  quality_status?: string;
  usage_status?: string;
  available_at?: string;
  provider_reported_at?: string;
  manual_review?: NewsManualReview | null;
}

interface NewsEvidenceListData {
  items?: NewsEvidence[];
  total?: number;
  page?: number;
  page_size?: number;
  observed_only?: boolean;
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
}

interface NewsReviewHistoryData {
  items?: NewsManualReview[];
  total?: number;
}

interface ReviewRow extends NewsEvidence {
  key: string;
}

const conclusionLabels: Record<ManualConclusion, string> = {
  title_link_relevant: "标题/链接相关",
  title_link_irrelevant: "标题/链接不相关",
  needs_more_evidence: "需要更多证据",
};

function conclusionLabel(value?: ManualConclusion): string {
  return value ? conclusionLabels[value] : "待人工复核";
}

export default function NewsEvidenceReviewPage() {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [evidencePage, setEvidencePage] = useState(1);
  const [evidencePageSize, setEvidencePageSize] = useState(50);
  const evidenceState = useReadOnlyDisplay<NewsEvidenceListData>(
    () => get<NewsEvidenceListData>("/research/evidence", {
      evidence_type: "news",
      quality_status: "observed",
      page: evidencePage,
      page_size: evidencePageSize,
    }),
    `research-news-evidence-review-v2:p${evidencePage}:s${evidencePageSize}:r${refreshVersion}`,
  );
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string>();
  const [conclusion, setConclusion] = useState<ManualConclusion>("needs_more_evidence");
  const [reason, setReason] = useState("");
  const [history, setHistory] = useState<NewsManualReview[]>([]);
  const [historyMessage, setHistoryMessage] = useState("请选择一条已观察新闻查看复核历史");
  const [submitMessage, setSubmitMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const rows: ReviewRow[] = (evidenceState.data?.items ?? []).map((item, index) => ({
    ...item,
    key: item.evidence_id ?? `news-evidence-${index}`,
  }));
  const selectedEvidence = useMemo(
    () => rows.find((item) => item.evidence_id === selectedEvidenceId),
    [rows, selectedEvidenceId],
  );
  const reviewedCount = rows.filter((item) => item.manual_review).length;
  const evidenceTotal = evidenceState.data?.total;
  const evidenceKnown = (evidenceState.kind === "live" || evidenceState.kind === "empty")
    && typeof evidenceTotal === "number";

  const handleEvidencePageChange = (nextPage: number, nextPageSize: number) => {
    setEvidencePageSize(nextPageSize);
    setEvidencePage(nextPageSize === evidencePageSize ? nextPage : 1);
    setSelectedEvidenceId(undefined);
  };

  useEffect(() => {
    let active = true;
    if (!selectedEvidenceId) {
      setHistory([]);
      setHistoryMessage("请选择一条已观察新闻查看复核历史");
      return () => {
        active = false;
      };
    }
    setHistoryMessage("加载复核历史中");
    void get<NewsReviewHistoryData>(`/research/evidence/${encodeURIComponent(selectedEvidenceId)}/reviews`)
      .then((response) => {
        if (active) {
          setHistory(response.data.items ?? []);
          setHistoryMessage(response.data.total ? "" : "该新闻尚无人工复核记录");
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setHistory([]);
          setHistoryMessage(error instanceof Error ? error.message : "复核历史加载失败");
        }
      });
    return () => {
      active = false;
    };
  }, [refreshVersion, selectedEvidenceId]);

  const submitReview = async () => {
    if (!selectedEvidenceId) {
      setSubmitMessage("请先选择一条已观察新闻");
      return;
    }
    setSubmitting(true);
    setSubmitMessage("");
    try {
      const response = await post<{ item?: NewsManualReview }>(
        `/research/evidence/${encodeURIComponent(selectedEvidenceId)}/reviews`,
        {
          conclusion,
          reason,
        },
        { headers: { "Idempotency-Key": crypto.randomUUID() } },
      );
      setSubmitMessage(response.message || "人工复核已追加");
      setReason("");
      setRefreshVersion((value) => value + 1);
    } catch (error) {
      setSubmitMessage(error instanceof Error ? error.message : "人工复核提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  const evidenceColumns: TableProps<ReviewRow>["columns"] = [
    { title: "证券代码", dataIndex: "stock_code", width: 120, render: (value) => value ?? "未记录" },
    {
      title: "标题 / 外链",
      dataIndex: "title",
      width: 360,
      render: (value, row) => (
        <div>
          <div>{value ?? "未记录标题"}</div>
          {row.document_url ? <a href={row.document_url} target="_blank" rel="noreferrer">由用户打开原文链接</a> : "未记录链接"}
        </div>
      ),
    },
    { title: "发布域名", dataIndex: "publisher_name", width: 170, render: (value) => value ?? "未记录" },
    {
      title: "Provider 时间",
      dataIndex: "provider_reported_at",
      width: 190,
      render: (value) => formatChinaDateTime(value),
    },
    {
      title: "最新结论",
      dataIndex: "manual_review",
      width: 170,
      render: (review?: NewsManualReview | null) => (
        <StatusBadge label={conclusionLabel(review?.conclusion)} tone={review ? "review" : "idle"} />
      ),
    },
    {
      title: "最新复核",
      dataIndex: "manual_review",
      width: 200,
      render: (review?: NewsManualReview | null) => review ? `${review.reviewer_label ?? "未记录"} · ${formatChinaDateTime(review.reviewed_at)}` : "待复核",
    },
    {
      title: "操作",
      key: "action",
      width: 120,
      render: (_value, row) => (
        <Button size="small" type={row.evidence_id === selectedEvidenceId ? "primary" : "default"} onClick={() => setSelectedEvidenceId(row.evidence_id)} disabled={!row.evidence_id}>
          选择复核
        </Button>
      ),
    },
  ];

  const historyColumns: TableProps<NewsManualReview & { key: string }>["columns"] = [
    { title: "复核时间", dataIndex: "reviewed_at", width: 190, render: (value) => formatChinaDateTime(value) },
    { title: "复核人标识", dataIndex: "reviewer_label", width: 180, render: (value) => value ?? "未记录" },
    {
      title: "结论",
      dataIndex: "conclusion",
      width: 190,
      render: (value) => <StatusBadge label={conclusionLabel(value)} tone="review" />,
    },
    { title: "复核理由", dataIndex: "reason", width: 500, render: (value) => value ?? "未记录" },
  ];
  const historyRows = history.map((item, index) => ({ ...item, key: item.review_id ?? `news-review-${index}` }));

  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header">
        <div><h1>新闻人工复核</h1><p>仅复核已观察新闻的标题/链接关联；不抓取正文，不改变研究或交易权限</p></div>
        <StatusBadge label="仅标题/链接复核" tone="review" />
      </header>
      <DataMetaBar provenance={evidenceState.provenance} relatedId="research:news-review" statusText="原始证据不可变 · 复核记录追加 · 研究与交易锁关闭" />
      <div className="metric-grid" style={{ "--metric-columns": 4 } as CSSProperties}>
        <MetricCard label="已观察新闻（总数）" value={evidenceKnown ? evidenceTotal : "状态未知"} detail={evidenceKnown ? `仅显示 quality_status=observed · 本页 ${rows.length} 条` : "证据列表不可用，未将其视为 0"} tone={evidenceKnown ? "info" : "review"} />
        <MetricCard label="本页已有最新复核" value={reviewedCount} detail="历史记录不会被覆盖" tone="review" />
        <MetricCard label="本页待人工复核" value={Math.max(rows.length - reviewedCount, 0)} detail="标题别名匹配仍需人工判断" tone="review" />
        <MetricCard label="交易权限" value="关闭" detail="复核不会授予 Readiness 或订单权限" tone="reject" />
      </div>
      <section className="panel table-panel">
        <div className="panel__title">已观察新闻证据（服务器分页）</div>
        <div className="panel__body"><ReadOnlyTable columns={evidenceColumns} data={rows} rowKey="key" emptyDescription={evidenceState.message} remotePagination={evidenceKnown && typeof evidenceTotal === "number" ? { current: evidenceState.data?.page ?? evidencePage, pageSize: evidenceState.data?.page_size ?? evidencePageSize, total: evidenceTotal, onChange: handleEvidencePageChange } : undefined} showSearch={false} /></div>
      </section>
      <section className="panel">
        <div className="panel__title">追加人工复核</div>
        <div className="panel__body news-review-editor">
          <p className="soft-note">{selectedEvidence ? `当前证据：${selectedEvidence.stock_code ?? "未记录"} · ${selectedEvidence.title ?? "未记录标题"}` : "请先在上表选择一条已观察新闻"}</p>
          <div className="news-review-editor__fields">
            <label htmlFor="news-review-conclusion">标题/链接结论<Select id="news-review-conclusion" value={conclusion} onChange={setConclusion} disabled={!selectedEvidence} options={Object.entries(conclusionLabels).map(([value, label]) => ({ value, label }))} /></label>
          </div>
          <label htmlFor="news-review-reason">复核理由<Input.TextArea id="news-review-reason" value={reason} maxLength={2000} rows={3} onChange={(event) => setReason(event.target.value)} placeholder="说明标题/链接为何相关、无关或仍需更多证据" disabled={!selectedEvidence} /></label>
          <div className="news-review-editor__actions"><Button type="primary" onClick={() => void submitReview()} loading={submitting} disabled={!selectedEvidence || !reason.trim()}>追加复核记录</Button><span>{submitMessage || "复核人由已认证会话主体记录；提交后如需纠正，请追加新记录，不覆盖历史。"}</span></div>
        </div>
      </section>
      <section className="panel table-panel">
        <div className="panel__title">所选新闻的完整复核历史</div>
        <div className="panel__body"><ReadOnlyTable columns={historyColumns} data={historyRows} rowKey="key" emptyDescription={historyMessage} searchPlaceholder="筛选复核人、结论或理由" /></div>
      </section>
      <section className="panel"><div className="panel__title">边界说明</div><div className="panel__body"><p className="soft-note">`title_link_relevant` 仅表示人工认为标题/链接与该证券相关；它不验证正文事实、事件、情绪或投资价值，也不会改变原始 Hash、Provider 时间、Research Readiness、候选、回测、策略、风险或订单。</p></div></section>
    </section>
  );
}
