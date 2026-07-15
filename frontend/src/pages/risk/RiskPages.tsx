import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface RiskRow { key: string; riskId: string; detectedAt: string; scope: string; ruleVersion: string; action: string; status: string; }

const columns: TableProps<RiskRow>["columns"] = [
  { title: "风险事件 ID", dataIndex: "riskId", width: 220 }, { title: "发现时间", dataIndex: "detectedAt", width: 210 }, { title: "风险范围", dataIndex: "scope", width: 210 }, { title: "规则版本", dataIndex: "ruleVersion", width: 190 }, { title: "处置动作", dataIndex: "action", width: 210 }, { title: "状态", dataIndex: "status", width: 160 },
];

export function RiskOverviewPage() {
  const state = pendingState("风险总览接口待接入", "risk-overview-ui-v1");
  return <SectionPage title="风险总览" subtitle="风险暴露、规则版本、拒绝结果与系统级熔断状态" relatedId="risk:overview" provenance={state.provenance} metrics={[{ label: "风险暴露", value: "待接入", detail: "不得由展示数据推断", tone: "review" }, { label: "活动告警", value: "待接入", detail: "来自 Risk Engine 审计", tone: "review" }, { label: "风控执行", value: "强制", detail: "订单必须经过 Risk Engine", tone: "info" }, { label: "风控绕过", value: "禁止", detail: "任何下单路径均不可绕过", tone: "reject" }]} tableTitle="风险态势与规则" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="风险门禁" auditItems={[{ label: "持仓限制", value: "待接入", detail: "需有规则版本与实际测量值", tone: "review" }, { label: "日亏/回撤", value: "待接入", detail: "触发后应记录明确处置", tone: "review" }, { label: "数据资格", value: "前置条件", detail: "风险评估不接受 unknown/synthetic", tone: "info" }]} note="风险总览仅展示可审计的风险状态；它不允许修改阈值、不解除交易锁，也不创建订单。" />;
}

export function RiskEventsPage() {
  const state = pendingState("风险事件接口待接入", "risk-events-ui-v1");
  return <SectionPage title="风险事件" subtitle="风险规则命中、拒绝原因、处置、关联决策与订单的事件归档" relatedId="risk:events" provenance={state.provenance} metrics={[{ label: "风险事件", value: "待接入", detail: "需有 event_id 与关联 ID", tone: "review" }, { label: "已拒绝动作", value: "待接入", detail: "拒绝不得静默丢失", tone: "review" }, { label: "待复核事件", value: "待接入", detail: "不使用绿色表示未处理", tone: "review" }, { label: "风险自动下单", value: "禁止", detail: "风控只能审核与拒绝", tone: "reject" }]} tableTitle="风险事件归档" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="事件责任" auditItems={[{ label: "风险事件", value: "独立归档", detail: "不与系统告警或平台审计混用", tone: "info" }, { label: "拒绝原因", value: "必须", detail: "关联规则版本与输入快照", tone: "info" }, { label: "人工处置", value: "待接入", detail: "必须记录审批与完成时间", tone: "review" }]} note="风险事件页将业务风险与基础设施告警分开；风险记录不可被页面操作删除或修改。" />;
}
