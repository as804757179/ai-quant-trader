import type { TableProps } from "antd";
import { useState } from "react";
import { type DataBlockerItem, useDataBlockers } from "../../presentation/coreModels";
import SectionPage from "../shared/SectionPage";

interface BlockerRow { key: string; stockCode: string; date: string; classification: string; evidence: string; status: string; }

function toRow(item: DataBlockerItem, index: number): BlockerRow {
  return {
    key: item.blocker_id ?? String(index),
    stockCode: item.stock_code ?? "未记录",
    date: item.trading_date ?? "未记录",
    classification: item.classification ?? "unresolved",
    evidence: item.evidence_source ?? "未记录",
    status: item.readiness_linkage_status === "not_recorded" ? "Readiness 关联未记录" : item.status ?? "未记录",
  };
}

export default function DataBlockersPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const state = useDataBlockers(page, pageSize);
  const rows = (state.data?.items ?? []).map(toRow);
  const total = state.data?.total;
  const known = (state.kind === "live" || state.kind === "empty") && typeof total === "number";
  const columns: TableProps<BlockerRow>["columns"] = [{ title: "股票代码", dataIndex: "stockCode", width: 140 }, { title: "交易日期", dataIndex: "date", width: 160 }, { title: "归因分类", dataIndex: "classification", width: 210 }, { title: "证据来源", dataIndex: "evidence", width: 310 }, { title: "Readiness 关联", dataIndex: "status", width: 190 }];
  return <SectionPage title="阻塞归因" subtitle="已审核的缺失日期、证券状态与企业行动归因" relatedId="data:blockers" provenance={{ ...state.provenance, sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion }} metadataStatusText="只读归因观察 · 服务端分页 · 不推断 Readiness 因果" statusLabel={known ? "已接入（只读）" : state.message} statusTone={known ? "info" : "review"} metrics={[{ label: "归因记录", value: known ? total : "状态未知", detail: "当前服务端筛选范围", tone: known ? "info" : "review" }, { label: "unresolved", value: known ? state.data?.summary?.unresolved ?? "未记录" : "状态未知", detail: "保持 fail closed", tone: "review" }, { label: "Provider 缺失", value: known ? state.data?.summary?.provider_missing ?? "未记录" : "状态未知", detail: "不与停牌混淆", tone: "review" }, { label: "自动补齐", value: "禁止", detail: "不得补假 K 线", tone: "reject" }]} tableTitle="缺失与阻塞明细（服务端分页）" columns={columns} tableData={rows} tablePagination={known ? { current: state.data?.page ?? page, pageSize: state.data?.page_size ?? pageSize, total, onChange: (nextPage, nextPageSize) => { setPage(nextPageSize === pageSize ? nextPage : 1); setPageSize(nextPageSize); } } : undefined} tableSearchEnabled={false} rowKey="key" emptyDescription={state.message} auditTitle="归因标准" auditItems={[{ label: "无法证明", value: "unresolved", detail: "保持 fail closed", tone: "reject" }, { label: "停牌证据", value: "保留", detail: "记录来源与审核版本", tone: "info" }, { label: "Readiness 关联", value: "未记录", detail: "不从区间重叠推断因果", tone: "review" }]} note="没有直接绑定到 Readiness 审核的归因记录，会明确显示为未记录；页面不创建补齐、认证或交易副作用。" />;
}
