import type { TableProps } from "antd";
import { useState } from "react";
import { useRiskAlerts, useRiskAlertsSummary, useRiskDashboard } from "../../presentation/coreModels";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface RiskRow { key: string; riskId: string; detectedAt: string; scope: string; ruleVersion: string; action: string; status: string; }

const columns: TableProps<RiskRow>["columns"] = [
  { title: "风险事件 ID", dataIndex: "riskId", width: 220 }, { title: "发现时间", dataIndex: "detectedAt", width: 210 }, { title: "风险范围", dataIndex: "scope", width: 210 }, { title: "规则版本", dataIndex: "ruleVersion", width: 190 }, { title: "处置动作", dataIndex: "action", width: 210 }, { title: "状态", dataIndex: "status", width: 160 },
];

export function RiskOverviewPage() {
  const state = useRiskDashboard(); const data = state.data; const alerts = data?.alerts?.items ?? []; const known = state.kind === "live" || state.kind === "empty";
  const rows: RiskRow[] = alerts.map((item, index) => ({ key: item.id ?? String(index), riskId: item.id ?? "未记录", detectedAt: item.created_at ?? item.ts ?? "未记录", scope: item.alert_type ?? item.type ?? "未记录", ruleVersion: "未记录", action: "未记录", status: item.level ?? "未记录" }));
  return <SectionPage title="风险总览" subtitle="风险暴露、熔断状态与持久化风险告警" relatedId="risk:overview" provenance={state.provenance} metadataStatusText="只读风险聚合 · unknown/stale 不显示为通过" statusLabel={known ? "已接入（只读）" : state.message} statusTone={known ? "info" : "review"} metrics={[{ label: "持仓暴露", value: known ? data?.portfolio?.position_ratio ?? "未记录" : "状态未知", detail: "风险快照原始值", tone: known ? "info" : "review" }, { label: "活动告警", value: known ? data?.alerts?.total ?? "未记录" : "状态未知", detail: "持久化风险告警汇总", tone: known ? "info" : "review" }, { label: "熔断状态", value: data?.fuse?.is_active === true ? "已触发" : data?.fuse?.is_active === false ? "未触发（当前快照）" : "未记录", detail: "不从缺失状态推断通过", tone: data?.fuse?.is_active === true ? "reject" : "review" }, { label: "风控绕过", value: "禁止", detail: "页面不修改阈值、不解除熔断或创建订单", tone: "reject" }]} tableTitle="持久化风险告警" columns={columns} tableData={rows} tableSearchEnabled={false} rowKey="key" emptyDescription={state.message} auditTitle="风险门禁" auditItems={[{ label: "估值新鲜度", value: data?.portfolio?.valuation_freshness ?? "未记录", detail: "stale 或 unknown 不显示为通过", tone: "review" }, { label: "规则版本", value: "未记录", detail: "Dashboard 未提供时不补造", tone: "review" }, { label: "交易权限", value: "未授予", detail: "风险展示不创建订单", tone: "reject" }]} note="风险总览只读呈现可审计风险状态；它不调整风控规则、不解除熔断，也不创建订单。" />;
}

export function RiskEventsPage() {
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(50); const state = useRiskAlerts(page, pageSize); const summary = useRiskAlertsSummary(); const total = state.data?.total;
  const known = (state.kind === "live" || state.kind === "empty") && typeof total === "number";
  const rows: RiskRow[] = (state.data?.items ?? []).map((item, index) => ({ key: item.id ?? String(index), riskId: item.id ?? "未记录", detectedAt: item.created_at ?? "未记录", scope: item.alert_type ?? item.type ?? "未记录", ruleVersion: "未记录", action: item.action_taken ?? "未记录", status: item.is_resolved === true ? "已解决" : item.is_resolved === false ? "未解决" : "未记录" }));
  return <SectionPage title="风险事件" subtitle="持久化风险规则命中与处置记录" relatedId="risk:events" provenance={{ ...state.provenance, sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion }} metadataStatusText="只读风险事件 · 服务端分页 · 不与系统告警混用" statusLabel={known ? "已接入（只读）" : state.message} statusTone={known ? "info" : "review"} metrics={[{ label: "风险事件", value: known ? total : "状态未知", detail: "risk.risk_events 持久化记录", tone: known ? "info" : "review" }, { label: "严重", value: summary.data?.critical ?? "未记录", detail: "当前汇总窗口", tone: "review" }, { label: "错误", value: summary.data?.error ?? "未记录", detail: "当前汇总窗口", tone: "review" }, { label: "风险自动下单", value: "禁止", detail: "页面不创建或修改订单", tone: "reject" }]} tableTitle="风险事件归档（服务端分页）" columns={columns} tableData={rows} tablePagination={known ? { current: state.data?.page ?? page, pageSize: state.data?.page_size ?? pageSize, total, onChange: (nextPage, nextPageSize) => { setPage(nextPageSize === pageSize ? nextPage : 1); setPageSize(nextPageSize); } } : undefined} tableSearchEnabled={false} rowKey="key" emptyDescription={state.message} auditTitle="事件责任" auditItems={[{ label: "风险事件", value: "独立归档", detail: "不与系统告警或平台审计混用", tone: "info" }, { label: "规则版本", value: "未记录", detail: "告警接口未提供时不补造", tone: "review" }, { label: "人工处置", value: "只读记录", detail: "页面不改变解决状态", tone: "reject" }]} note="风险事件页只读展示持久化风险告警；它不创建、删除或解决风险事件，也不创建订单。" />;
}
