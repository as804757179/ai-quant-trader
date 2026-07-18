import type { TableProps } from "antd";
import { useState } from "react";
import { type CertificationBatchItem, useCertificationBatches } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import SectionPage from "../shared/SectionPage";

interface BatchRow {
  key: string;
  batchId: string;
  provider: string;
  range: string;
  accepted: string;
  status: string;
  fetchedAt: string;
}

function toRow(item: CertificationBatchItem, index: number): BatchRow {
  return {
    key: item.batch_id ?? String(index),
    batchId: item.batch_id ?? "未记录",
    provider: item.provider ?? "未记录",
    range: `${item.start_date ?? "未记录"} 至 ${item.end_date ?? "未记录"}`,
    accepted: `${item.accepted_rows ?? "未记录"}/${item.rejected_rows ?? "未记录"}`,
    status: item.status ?? "未记录",
    fetchedAt: formatChinaDateTime(item.fetch_time ?? undefined),
  };
}

export default function DataBatchesPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const state = useCertificationBatches(page, pageSize);
  const rows = (state.data?.items ?? []).map(toRow);
  const total = state.data?.total;
  const known = (state.kind === "live" || state.kind === "empty") && typeof total === "number";
  const columns: TableProps<BatchRow>["columns"] = [
    { title: "批次 ID", dataIndex: "batchId", width: 220 },
    { title: "Provider", dataIndex: "provider", width: 170 },
    { title: "日期范围", dataIndex: "range", width: 220 },
    { title: "接收/拒绝", dataIndex: "accepted", width: 150 },
    { title: "终态", dataIndex: "status", width: 150 },
    { title: "采集时间", dataIndex: "fetchedAt", width: 210 },
  ];

  return (
    <SectionPage
      title="数据批次"
      subtitle="导入、校验与认证批次的只读审计记录"
      relatedId="data:batches"
      provenance={{ ...state.provenance, sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion }}
      metadataStatusText="只读批次观察 · 服务端分页 · 不授予 Research Readiness"
      statusLabel={known ? "已接入（只读）" : state.message}
      statusTone={known ? "info" : "review"}
      metrics={[
        { label: "批次总数", value: known ? total : "状态未知", detail: "当前服务端筛选范围", tone: known ? "info" : "review" },
        { label: "已认证", value: known ? state.data?.summary?.certified ?? "未记录" : "状态未知", detail: "仅为批次认证终态", tone: known ? "info" : "review" },
        { label: "拒绝/失败", value: known ? `${state.data?.summary?.rejected ?? 0}/${state.data?.summary?.failed ?? 0}` : "状态未知", detail: "失败不会被旧成功状态覆盖", tone: "review" },
        { label: "研究权限", value: "未授予", detail: "Certification 不传播为 Research Readiness", tone: "reject" },
      ]}
      tableTitle="批次血缘（服务端分页）"
      columns={columns}
      tableData={rows}
      tablePagination={known ? {
        current: state.data?.page ?? page,
        pageSize: state.data?.page_size ?? pageSize,
        total,
        onChange: (nextPage, nextPageSize) => {
          setPage(nextPageSize === pageSize ? nextPage : 1);
          setPageSize(nextPageSize);
        },
      } : undefined}
      tableSearchEnabled={false}
      rowKey="key"
      emptyDescription={state.message}
      auditTitle="批次约束"
      auditItems={[
        { label: "失败记录", value: "保留", detail: "不能静默 fallback", tone: "info" },
        { label: "覆盖写入", value: "禁止", detail: "不覆盖 Certified 原始记录", tone: "reject" },
        { label: "订单创建", value: "禁止", detail: "页面没有写入或交易副作用", tone: "reject" },
      ]}
      note="本页仅观察批次事实，不触发采集、重试或认证；完整血缘和拒绝原因由服务端批次记录保留。"
    />
  );
}
