import type { TableProps } from "antd";
import { useState } from "react";
import {
  type CertifiedKlineLineageItem,
  useCertifiedKlineLineage,
} from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import SectionPage from "../shared/SectionPage";

interface CertifiedRow {
  key: string;
  stockCode: string;
  tradingDate: string;
  adjustment: string;
  batchId: string;
  provider: string;
  certification: string;
  certifiedAt: string;
}

function toRow(item: CertifiedKlineLineageItem, index: number): CertifiedRow {
  return {
    key: `${item.stock_code ?? "unknown"}-${item.trading_date ?? index}-${item.adjustment ?? "unknown"}`,
    stockCode: item.stock_code ?? "未记录",
    tradingDate: item.trading_date ?? "未记录",
    adjustment: item.adjustment ?? "未记录",
    batchId: item.batch_id ?? "未记录",
    provider: item.provider ?? "未记录",
    certification: item.certification_status ?? "未记录",
    certifiedAt: formatChinaDateTime(item.certification_time),
  };
}

export default function CertifiedStorePage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const state = useCertifiedKlineLineage(page, pageSize);
  const rows = (state.data?.items ?? []).map(toRow);
  const total = state.data?.total;
  const known = (state.kind === "live" || state.kind === "empty") && typeof total === "number";
  const columns: TableProps<CertifiedRow>["columns"] = [
    { title: "股票代码", dataIndex: "stockCode", width: 150 },
    { title: "交易日期", dataIndex: "tradingDate", width: 150 },
    { title: "复权口径", dataIndex: "adjustment", width: 130 },
    { title: "批次 ID", dataIndex: "batchId", width: 220 },
    { title: "Provider", dataIndex: "provider", width: 170 },
    { title: "认证状态", dataIndex: "certification", width: 140 },
    { title: "认证时间", dataIndex: "certifiedAt", width: 210 },
  ];

  return (
    <SectionPage
      title="Certified Store"
      subtitle="认证历史 K 线、来源、批次和版本血缘；当前仅查询 raw 口径"
      relatedId="data:certified"
      provenance={{
        ...state.provenance,
        sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion,
      }}
      metadataStatusText="只读 Certified Store · 服务端分页 · 不授予 Research Readiness"
      statusLabel={state.kind === "live" || state.kind === "empty" ? "已接入（只读）" : state.message}
      statusTone={state.kind === "live" || state.kind === "empty" ? "info" : "review"}
      metrics={[
        {
          label: "认证行数",
          value: known ? total : "状态未知",
          detail: known ? `本页 ${rows.length} 条 · raw · 1d` : "接口不可用时不将其显示为 0",
          tone: known ? "info" : "review",
        },
        {
          label: "认证股票数",
          value: known ? state.data?.summary?.stock_count ?? "未记录" : "状态未知",
          detail: "仅当前筛选和口径范围",
          tone: known ? "info" : "review",
        },
        {
          label: "Provider",
          value: known ? state.data?.summary?.providers?.join("、") || "未记录" : "状态未知",
          detail: "每行保留来源和批次血缘",
          tone: known ? "info" : "review",
        },
        {
          label: "研究权限",
          value: "未授予",
          detail: "Certification 不传播为 Research Readiness",
          tone: "reject",
        },
      ]}
      tableTitle="认证 K 线血缘（服务器分页）"
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
      auditTitle="准入规则"
      auditItems={[
        { label: "来源明确", value: "必需", detail: "provider/source/batch_id 必须完整", tone: "info" },
        { label: "质量状态", value: "pass", detail: "查询层固定过滤质量不通过记录", tone: "info" },
        { label: "认证状态", value: "certified", detail: "查询层固定过滤未认证记录", tone: "info" },
      ]}
      note="本页只读取 market.certified_klines，且明确显示其仅为认证数据观察；不读取 legacy 数据、不自动授予 Research Readiness，也不开放回测或交易。"
    />
  );
}
