import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import {
  type ReadinessReviewData,
  useExecutionStatus,
  useReadinessReviews,
} from "../../presentation/coreModels";
import type { StatusTone } from "../../presentation/contracts";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

interface ReadinessRow {
  key: string;
  stockCode: string;
  range: string;
  profile: string;
  contract: string;
  fields: string;
  status: string;
  blocker: string;
}

function readinessTone(status: string | undefined): StatusTone {
  if (status === "ready") return "pass";
  if (status === "rejected") return "reject";
  return "review";
}

function readinessLabel(status: string | undefined): string {
  if (status === "ready") return "已就绪";
  if (status === "rejected") return "已拒绝";
  if (status === "review_required") return "待审核";
  return "待接入";
}

export default function ReadinessPage() {
  const state = useReadinessReviews();
  const execution = useExecutionStatus();
  const backtestLock = execution.data?.release_locks?.find(
    (lock) => lock.key === "CERTIFIED_BACKTEST_EXECUTION_ENABLED",
  );
  const rows: ReadinessRow[] = (state.data?.items ?? []).map(
    (review: ReadinessReviewData, index) => ({
      key: review.review_id ?? `review-${index}`,
      stockCode: review.stock_code ?? "待接入",
      range: `${review.date_from ?? "待接入"} — ${review.date_to ?? "待接入"}`,
      profile: `${review.research_use_scope ?? "待接入"} / ${review.requirement_profile ?? "待接入"}`,
      contract: `${review.period ?? "待接入"} / ${review.adjustment ?? "待接入"}`,
      fields: `已验证 ${(review.validated_fields ?? []).length} · 未决 ${(review.unresolved_fields ?? []).length} · 拒绝 ${(review.rejected_fields ?? []).length}`,
      status: review.readiness_status ?? "待接入",
      blocker: review.review_reason ?? "待接入",
    }),
  );
  const columns: TableProps<ReadinessRow>["columns"] = [
    { title: "股票代码", dataIndex: "stockCode", width: 150 },
    { title: "审核区间", dataIndex: "range", width: 220 },
    { title: "Requirement Profile", dataIndex: "profile", width: 250 },
    { title: "周期 / 复权", dataIndex: "contract", width: 150 },
    { title: "字段审核", dataIndex: "fields", width: 210 },
    { title: "状态", dataIndex: "status", width: 120, render: (value: string) => <StatusBadge label={readinessLabel(value)} tone={readinessTone(value)} /> },
    { title: "阻塞归因", dataIndex: "blocker", width: 280 },
  ];

  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header"><div><h1>研究态势 / Research Readiness</h1><p>数据研究可用性、字段级授权与阻断原因</p></div><StatusBadge label={state.kind === "live" ? "用途级审核已接入" : state.message} tone={state.kind === "live" ? "pass" : "review"} /></header>
      <DataMetaBar provenance={state.provenance} relatedId={state.data?.items?.[0]?.review_id ?? "readiness:scoped-review"} />
      <div className="metric-grid" style={{ "--metric-columns": 5 } as CSSProperties}>
        <MetricCard label="审核记录" value={state.data?.total ?? "待接入"} detail={`覆盖股票：${state.data?.summary?.stock_count ?? "待接入"}`} tone={state.kind === "live" ? "info" : "review"} />
        <MetricCard label="Scoped Ready" value={state.data?.summary?.ready ?? "待接入"} detail="仅对完整授权键生效" tone={state.kind === "live" ? "pass" : "review"} />
        <MetricCard label="待审核" value={state.data?.summary?.review_required ?? "待接入"} detail={`未决字段：${state.data?.summary?.unresolved_field_count ?? "待接入"}`} tone="review" />
        <MetricCard label="已拒绝" value={state.data?.summary?.rejected ?? "待接入"} detail={`拒绝字段：${state.data?.summary?.rejected_field_count ?? "待接入"}`} tone={state.kind === "live" ? "reject" : "review"} />
        <MetricCard label="Return Backtest" value={backtestLock ? (backtestLock.enabled ? "已开启" : "关闭") : "待接入"} detail={backtestLock?.reason ?? execution.message} tone={backtestLock?.enabled ? "review" : backtestLock ? "idle" : "review"} />
      </div>
      <div className="readiness-grid">
        <section className="panel table-panel"><div className="panel__title">按股票与研究用途审核</div><div className="panel__body"><ReadOnlyTable columns={columns} data={rows} rowKey="key" getFilterValue={(record) => record.status} filterOptions={[{ label: "已就绪", value: "ready" }, { label: "待审核", value: "review_required" }, { label: "已拒绝", value: "rejected" }]} emptyDescription={state.message} /></div></section>
        <section className="panel"><div className="panel__title">阻塞原因分布</div><div className="panel__body gate-list">{state.data?.blockers?.length ? state.data.blockers.map((item, index) => <div key={item.reason ?? `blocker-${index}`}><StatusBadge label={String(item.count ?? 0)} tone="review" /><span>{item.reason ?? "未记录"}</span><small>真实审核记录聚合</small></div>) : <p className="soft-note">{state.message}</p>}</div></section>
      </div>
      <section className="panel"><div className="panel__title">授权规则与版本</div><div className="panel__body policy-list"><span>Certified 不等于所有用途 ready</span><span>权限键必须包含标的、区间、复权口径、用途和 Requirement Profile</span><span>一个 Profile 的 ready 不得传播到 Amount 或 Execution Reference</span><span>策略版本：{state.data?.summary?.policy_versions?.join(" / ") || "未记录"}</span></div></section>
    </section>
  );
}
