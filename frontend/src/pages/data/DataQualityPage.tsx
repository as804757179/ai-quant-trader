import type { TableProps } from "antd";
import { useState } from "react";
import { type QualityResultItem, useQualityResults } from "../../presentation/coreModels";
import SectionPage from "../shared/SectionPage";

interface QualityRow {
  key: string;
  batchId: string;
  rule: string;
  scope: string;
  result: string;
  inputHash: string;
  rejectReason: string;
}

function toRow(item: QualityResultItem, index: number): QualityRow {
  return {
    key: item.quality_result_id ?? String(index),
    batchId: item.batch_id ?? "未记录",
    rule: `${item.rule_code ?? "未记录"} (${item.rule_version ?? "未记录"})`,
    scope: item.audit_scope ?? "未记录",
    result: item.result ?? "未记录",
    inputHash: item.input_hash ?? "未记录",
    rejectReason: item.reject_reason ?? "无",
  };
}

export default function DataQualityPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const state = useQualityResults(page, pageSize);
  const rows = (state.data?.items ?? []).map(toRow);
  const total = state.data?.total;
  const known = (state.kind === "live" || state.kind === "empty") && typeof total === "number";
  const columns: TableProps<QualityRow>["columns"] = [
    { title: "批次 ID", dataIndex: "batchId", width: 210 },
    { title: "质量规则", dataIndex: "rule", width: 260 },
    { title: "审核范围", dataIndex: "scope", width: 140 },
    { title: "结果", dataIndex: "result", width: 150 },
    { title: "输入 Hash", dataIndex: "inputHash", width: 220 },
    { title: "拒绝原因", dataIndex: "rejectReason", width: 360 },
  ];

  return (
    <SectionPage
      title="数据质量"
      subtitle="认证校验器已持久化的规则级结果"
      relatedId="data:quality"
      provenance={{ ...state.provenance, sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion }}
      metadataStatusText="只读质量审计 · 服务端分页 · 历史未记录批次不会伪造明细"
      statusLabel={known ? "已接入（只读）" : state.message}
      statusTone={known ? "info" : "review"}
      metrics={[
        { label: "规则结果", value: known ? total : "状态未知", detail: "当前服务端筛选范围", tone: known ? "info" : "review" },
        { label: "通过", value: known ? state.data?.summary?.passed ?? "未记录" : "状态未知", detail: "规则级审计事实", tone: known ? "info" : "review" },
        { label: "失败", value: known ? state.data?.summary?.failed ?? "未记录" : "状态未知", detail: "失败结果保留拒绝原因", tone: "review" },
        { label: "未评估", value: known ? state.data?.summary?.not_evaluated ?? "未记录" : "状态未知", detail: "输入不足时不伪装为通过", tone: "review" },
      ]}
      tableTitle="质量规则结果（服务端分页）"
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
      auditTitle="强制拒绝项"
      auditItems={[
        { label: "Synthetic", value: "拒绝", detail: "不能认证为真实数据", tone: "reject" },
        { label: "Unknown source", value: "拒绝", detail: "来源缺失不得认证", tone: "reject" },
        { label: "同日重复", value: "拒绝", detail: "对应数据不得 certified", tone: "reject" },
      ]}
      note="质量结果关联批次、规则版本和输入 Hash。页面不生成、补写或修复质量结论，也不授予 Research Readiness、回测或交易权限。"
    />
  );
}
