import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { formatChinaDateTime } from "../../presentation/time";
import { useAiAuditSummary, useAiSignals, type AiSignalData } from "../../presentation/coreModels";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

function aiActionLabel(value: string | undefined): string {
  return value ? `AI 标签：${value}（非订单）` : "未记录";
}

export default function AiAuditPage() {
  const signals = useAiSignals();
  const audit = useAiAuditSummary();
  const rows = (signals.data?.items ?? []).map((signal, index) => ({ ...signal, key: signal.id ?? `signal-${index}` }));
  const columns: TableProps<AiSignalData & { key: string }>["columns"] = [
    { title: "调用 ID", dataIndex: "id", width: 150, render: (value) => value ?? "待接入" },
    { title: "标的", dataIndex: "stock_code", width: 120, render: (value) => value ?? "待接入" },
    { title: "AI 输出标签（非订单）", dataIndex: "action", width: 190, render: (value) => <StatusBadge label={aiActionLabel(value)} tone="idle" /> },
    { title: "风险等级", dataIndex: "risk_level", width: 120, render: (value) => <StatusBadge label={value ?? "待接入"} tone="review" /> },
    { title: "历史数据状态", dataIndex: "historical_data_status", width: 150, render: (value) => <StatusBadge label={value ?? "unknown"} tone={value === "certified" ? "pass" : "review"} /> },
    { title: "创建订单", dataIndex: "order_created", width: 110, render: (value) => <StatusBadge label={value ? "是" : "否"} tone={value ? "reject" : "pass"} /> },
    { title: "生成时间", dataIndex: "signal_time", width: 200, render: (value) => formatChinaDateTime(value) },
    { title: "审计摘要", dataIndex: "reason", width: 360, render: (value) => value ?? "待接入" },
  ];

  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header"><div><h1>AI 审计 / AI Audit</h1><p>AI 调用、证据、摘要和订单边界审计</p></div><StatusBadge label="AI 不具备下单权限" tone="reject" /></header>
      <DataMetaBar provenance={audit.provenance} relatedId="ai:audit" statusText="基础设施 待读取 · 数据资格 按上下文标记 · 业务发布 关闭" />
      <div className="metric-grid" style={{ "--metric-columns": 5 } as CSSProperties}>
        <MetricCard label="AI 调用总数" value={audit.data?.agent_call_count ?? "待接入"} detail={`近 ${audit.data?.window_days ?? 30} 天`} />
        <MetricCard label="信号记录" value={audit.data?.signal_count ?? signals.data?.total ?? "待接入"} detail={`HOLD：${audit.data?.hold_count ?? "待接入"}`} />
        <MetricCard label="订单创建" value={audit.data ? String(audit.data.order_created) : "待接入"} detail={`AI 来源订单：${audit.data?.ai_order_count ?? "待接入"}`} tone={audit.data?.order_created === false ? "pass" : "reject"} />
        <MetricCard label="越权尝试" value={audit.data?.unauthorized_attempt_count ?? "未记录"} detail="当前无独立拒绝事件计数器" tone="review" />
        <MetricCard label="数据资格" value={`C:${audit.data?.data_status_counts?.certified ?? 0} / B:${audit.data?.data_status_counts?.blocked ?? 0}`} detail={`unknown：${audit.data?.data_status_counts?.unknown ?? 0}`} tone={audit.data?.data_status_counts?.unknown ? "review" : "info"} />
      </div>
      <div className="ai-audit-grid">
        <section className="panel table-panel"><div className="panel__title">调用日志</div><div className="panel__body"><ReadOnlyTable columns={columns} data={rows} rowKey="key" emptyDescription={signals.message} /></div></section>
        <section className="panel"><div className="panel__title">AI 状态</div><div className="panel__body gate-list">
          <div><StatusBadge label={audit.data?.ai_direct_order_allowed === false ? "禁止" : "待接入"} tone="reject" /><span>AI 直接下单</span><small>order_created 必须为 false</small></div>
          <div><StatusBadge label={audit.data?.data_status_counts ? "已记录" : "待接入"} tone={audit.data?.data_status_counts ? "info" : "review"} /><span>数据资格标记</span><small>certified {audit.data?.data_status_counts?.certified ?? 0} · blocked {audit.data?.data_status_counts?.blocked ?? 0} · unknown {audit.data?.data_status_counts?.unknown ?? 0}</small></div>
          <div><StatusBadge label={audit.data?.scheduled_order_enabled ? "已开启" : audit.data ? "禁止" : "待接入"} tone="reject" /><span>定时任务自动下单</span><small>Celery 不得产生订单</small></div>
          <div><StatusBadge label={audit.data?.ai_order_enabled ? "已开启" : audit.data ? "关闭" : "待接入"} tone="reject" /><span>AI 订单配置</span><small>AI_ORDER_ENABLED</small></div>
          <div><StatusBadge label={String(audit.data?.agent_usage?.length ?? "待接入")} tone="info" /><span>Agent / 模型组合</span><small>{audit.data?.agent_usage?.map((item) => `${item.agent_name}:${item.model_used}(${item.count})`).join(" / ") || "暂无调用记录"}</small></div>
        </div></section>
      </div>
      <section className="panel"><div className="panel__title">审计说明</div><div className="panel__body"><p className="soft-note">AI 输出标签仅记录分析、解释、评分或 recommendation，不是订单意图；任何推荐都不能绕过 Data Certification、Research Readiness、Risk Engine、人工授权或 Execution Gate。</p></div></section>
    </section>
  );
}
