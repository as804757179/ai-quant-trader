import type { CSSProperties, ReactNode } from "react";
import type { TableProps } from "antd";
import type { DataProvenance, StatusTone } from "../../presentation/contracts";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable, { type RemotePagination } from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

export interface SectionMetric {
  label: string;
  value: ReactNode;
  detail: string;
  tone?: StatusTone;
}

export interface SectionPageProps<T extends object> {
  title: string;
  subtitle: string;
  relatedId: string;
  provenance: DataProvenance;
  metadataStatusText?: string;
  statusLabel?: string;
  statusTone?: StatusTone;
  metrics: readonly SectionMetric[];
  tableTitle: string;
  columns: TableProps<T>["columns"];
  tableData?: readonly T[];
  tablePagination?: RemotePagination;
  tableSearchEnabled?: boolean;
  rowKey: TableProps<T>["rowKey"];
  emptyDescription: string;
  auditTitle: string;
  auditItems: readonly { label: string; value: string; tone?: StatusTone; detail: string }[];
  note: string;
}

export default function SectionPage<T extends object>({
  title,
  subtitle,
  relatedId,
  provenance,
  metadataStatusText,
  statusLabel = "待接入",
  statusTone = "review",
  metrics,
  tableTitle,
  columns,
  tableData = [],
  tablePagination,
  tableSearchEnabled,
  rowKey,
  emptyDescription,
  auditTitle,
  auditItems,
  note,
}: SectionPageProps<T>) {
  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header">
        <div><h1>{title}</h1><p>{subtitle}</p></div>
        <StatusBadge label={statusLabel} tone={statusTone} />
      </header>
      <DataMetaBar provenance={provenance} relatedId={relatedId} statusText={metadataStatusText} />
      <div className="metric-grid" style={{ "--metric-columns": Math.min(metrics.length, 5) } as CSSProperties}>
        {metrics.map((metric) => <MetricCard key={metric.label} {...metric} />)}
      </div>
      <div className="section-page-grid">
        <section className="panel table-panel"><div className="panel__title">{tableTitle}</div><div className="panel__body"><ReadOnlyTable columns={columns} data={tableData} remotePagination={tablePagination} showSearch={tableSearchEnabled} rowKey={rowKey} emptyDescription={emptyDescription} /></div></section>
        <section className="panel"><div className="panel__title">{auditTitle}</div><div className="panel__body gate-list">{auditItems.map((item) => <div key={item.label}><StatusBadge label={item.value} tone={item.tone ?? "review"} /><span>{item.label}</span><small>{item.detail}</small></div>)}</div></section>
      </div>
      <section className="panel"><div className="panel__title">页面说明</div><div className="panel__body"><p className="soft-note">{note}</p></div></section>
    </section>
  );
}
