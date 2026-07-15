import type { TableProps } from "antd";
import { RELEASE_LOCKS } from "../../presentation/contracts";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface SystemRow { key: string; primary: string; eventTime: string; owner: string; version: string; relatedId: string; status: string; }

const systemColumns: TableProps<SystemRow>["columns"] = [
  { title: "事件/任务 ID", dataIndex: "primary", width: 230 }, { title: "时间", dataIndex: "eventTime", width: 210 }, { title: "责任组件", dataIndex: "owner", width: 190 }, { title: "版本", dataIndex: "version", width: 180 }, { title: "关联 ID", dataIndex: "relatedId", width: 230 }, { title: "状态", dataIndex: "status", width: 150 },
];

export function SchedulePage() {
  const state = pendingState("任务时序接口待接入", "system-schedule-ui-v1");
  return <SectionPage title="任务时序" subtitle="采集、研究、审批、清算与审计任务的只读运行计划" relatedId="system:schedule" provenance={state.provenance} metrics={[{ label: "已登记任务", value: "待接入", detail: "从调度器只读查询", tone: "review" }, { label: "执行窗口", value: "待接入", detail: "必须有生效区间和时区", tone: "review" }, { label: "定时下单", value: "关闭", detail: "ALLOW_SCHEDULED_ORDER=false", tone: "reject" }, { label: "任务失败", value: "待接入", detail: "应产生系统告警", tone: "review" }]} tableTitle="调度与运行窗口" columns={systemColumns} rowKey="key" emptyDescription={state.message} auditTitle="调度安全" auditItems={[{ label: "任务时区", value: "UTC+8", detail: "展示 yyyy-MM-dd HH:mm:ss", tone: "info" }, { label: "自动订单", value: "禁止", detail: "任务只能产生信号或审计记录", tone: "reject" }, { label: "失败重试", value: "受控", detail: "重试次数与退避应可追踪", tone: "review" }]} note="任务时序页仅展示调度信息，不能通过前端页面启动策略、下单或修改定时任务。" />;
}

export function SystemAlertsPage() {
  const state = pendingState("系统告警接口待接入", "system-alerts-ui-v1");
  return <SectionPage title="系统告警" subtitle="基础设施、数据资格和业务发布三类告警的独立归档" relatedId="system:alerts" provenance={state.provenance} metrics={[{ label: "基础设施告警", value: "待接入", detail: "服务、网络、队列与数据库", tone: "review" }, { label: "数据资格告警", value: "待接入", detail: "认证、Readiness 与时效", tone: "review" }, { label: "发布状态告警", value: "关闭", detail: "发布锁不可被告警页解除", tone: "idle" }, { label: "风险事件", value: "独立页面", detail: "不与系统告警混淆", tone: "info" }]} tableTitle="系统告警事件" columns={systemColumns} rowKey="key" emptyDescription={state.message} auditTitle="告警职责" auditItems={[{ label: "基础设施", value: "独立", detail: "健康与连接失败进入系统告警", tone: "info" }, { label: "数据资格", value: "独立", detail: "数据认证与 Readiness 问题明确标识", tone: "info" }, { label: "业务发布", value: "独立", detail: "发布锁状态不等同服务正常", tone: "info" }]} note="告警页不使用单一“正常”掩盖不同状态；基础设施可用、数据可研究和业务已发布必须分别判断。" />;
}

export function SystemHealthPage() {
  const state = pendingState("服务健康接口待接入", "system-health-ui-v1");
  return <SectionPage title="服务健康" subtitle="基础设施连通、数据资格和业务发布三种状态的分离展示" relatedId="system:health" provenance={state.provenance} metrics={[{ label: "基础设施", value: "待接入", detail: "API、Worker、Redis、数据库与数据服务", tone: "review" }, { label: "数据资格", value: "待审核", detail: "Certification 与 Readiness 独立判断", tone: "review" }, { label: "业务发布", value: "关闭", detail: "安全发布锁保持关闭", tone: "idle" }, { label: "实时连接", value: "待接入", detail: "显示延迟、版本与最后成功时间", tone: "review" }]} tableTitle="服务连通与版本" columns={systemColumns} rowKey="key" emptyDescription={state.message} auditTitle="发布锁状态" auditItems={RELEASE_LOCKS.map((lock) => ({ label: lock.label, value: "关闭", detail: lock.reason, tone: "reject" as const }))} note="绿色只表示某项已通过，不能代替数据资格或业务发布状态；当前所有发布与交易锁均保持关闭。" />;
}

export function SystemAuditPage() {
  const state = pendingState("平台审计接口待接入", "system-audit-ui-v1");
  return <SectionPage title="平台审计" subtitle="平台级只读操作、配置版本、关联 ID 与完整性 Hash 审计" relatedId="system:audit" provenance={state.provenance} metrics={[{ label: "审计事件", value: "待接入", detail: "需有稳定 event_id", tone: "review" }, { label: "关联链路", value: "待接入", detail: "trace_id、run_id 与版本可追踪", tone: "review" }, { label: "配置变更", value: "待接入", detail: "变更需有审批和回滚", tone: "review" }, { label: "删除审计", value: "禁止", detail: "审计记录不可静默删除", tone: "reject" }]} tableTitle="平台审计事件" columns={systemColumns} rowKey="key" emptyDescription={state.message} auditTitle="审计边界" auditItems={[{ label: "风险事件", value: "独立", detail: "风险命中在风险模块归档", tone: "info" }, { label: "系统告警", value: "独立", detail: "服务失败在系统告警归档", tone: "info" }, { label: "完整性 Hash", value: "必须", detail: "审计数据需要可验证", tone: "info" }]} note="平台审计页用于关联和追踪系统行为，不提供修改安全开关、订单或业务数据的能力。" />;
}
