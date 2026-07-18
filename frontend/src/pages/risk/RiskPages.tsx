import type { TableProps } from "antd";
import { useRiskDashboard } from "../../presentation/coreModels";
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
  const state = pendingState("风险事件接口待接入", "risk-events-ui-v1");
  return <SectionPage title="风险事件" subtitle="风险规则命中、拒绝原因、处置、关联决策与订单的事件归档" relatedId="risk:events" provenance={state.provenance} metrics={[{ label: "风险事件", value: "待接入", detail: "需有 event_id 与关联 ID", tone: "review" }, { label: "已拒绝动作", value: "待接入", detail: "拒绝不得静默丢失", tone: "review" }, { label: "待复核事件", value: "待接入", detail: "不使用绿色表示未处理", tone: "review" }, { label: "风险自动下单", value: "禁止", detail: "风控只能审核与拒绝", tone: "reject" }]} tableTitle="风险事件归档" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="事件责任" auditItems={[{ label: "风险事件", value: "独立归档", detail: "不与系统告警或平台审计混用", tone: "info" }, { label: "拒绝原因", value: "必须", detail: "关联规则版本与输入快照", tone: "info" }, { label: "人工处置", value: "待接入", detail: "必须记录审批与完成时间", tone: "review" }]} note="风险事件页将业务风险与基础设施告警分开；风险记录不可被页面操作删除或修改。" />;
}
