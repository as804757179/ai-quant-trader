import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { type AiSignalData, useAiAuditSummary, useAiSignals } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

interface SummaryRow extends AiSignalData { key: string; }

export default function AiSummaryPage() {
  const signals = useAiSignals(); const audit = useAiAuditSummary(); const total = signals.data?.total;
  const known = (signals.kind === "live" || signals.kind === "empty") && typeof total === "number";
  const rows: SummaryRow[] = (signals.data?.items ?? []).map((item, index) => ({ ...item, key: item.id ?? `ai-signal-${index}` }));
  const columns: TableProps<SummaryRow>["columns"] = [
    { title: "信号记录", dataIndex: "id", width: 180, render: (value) => value ?? "未记录" }, { title: "标的", dataIndex: "stock_code", width: 120, render: (value) => value ?? "未记录" }, { title: "AI 分析标签（非订单）", dataIndex: "action", width: 190, render: (value) => <StatusBadge label={value ? `AI 标签：${value}` : "未记录"} tone="idle" /> }, { title: "历史数据状态", dataIndex: "historical_data_status", width: 150, render: (value) => <StatusBadge label={value ?? "unknown"} tone={value === "certified" ? "pass" : "review"} /> }, { title: "当前有效性", dataIndex: "current_validity_status", width: 150, render: (value) => value ?? "未记录" }, { title: "信号时间", dataIndex: "signal_time", width: 210, render: (value) => formatChinaDateTime(value) },
  ];
  const modelUsage = audit.data?.agent_usage?.map((item) => `${item.agent_name ?? "未记录"}:${item.model_used ?? "未记录"}`).join(" / ") || "未记录";
  return <section className="page-frame page-frame--fill">
    <header className="page-header"><div><h1>AI 摘要</h1><p>已记录 AI 信号与调用审计；不生成订单或交易指令</p></div><StatusBadge label={known ? "已接入（只读）" : signals.message} tone="review" /></header>
    <DataMetaBar provenance={{ ...audit.provenance, sourceVersion: audit.data?.source_version ?? audit.provenance.sourceVersion }} relatedId="ai:summary" statusText="只读审计 · 证据关联未记录 · recommendation-only · 不授予研究或交易资格" />
    <div className="metric-grid" style={{ "--metric-columns": 5 } as CSSProperties}>
      <MetricCard label="已记录信号" value={known ? total : "状态未知"} detail="AI 标签，不是订单或交易指令" tone="review" />
      <MetricCard label="调用模型" value={audit.data?.agent_usage?.length ?? "状态未知"} detail={modelUsage} tone="review" />
      <MetricCard label="调用版本" value="未记录" detail="现有审计未持久化逐调用版本" tone="review" />
      <MetricCard label="证据截止时间" value="未记录" detail="信号与研究证据尚无可追溯关联，不用信号时间替代" tone="reject" />
      <MetricCard label="AI 来源订单" value={audit.data?.ai_order_count ?? "状态未知"} detail="仅历史审计；本页不创建或修改订单" tone={audit.data?.order_created === false ? "pass" : "reject"} />
    </div>
    <section className="panel table-panel"><div className="panel__title">AI 信号审计记录</div><div className="panel__body"><ReadOnlyTable columns={columns} data={rows} rowKey="key" emptyDescription={signals.message} showSearch={false} /></div></section>
    <section className="panel"><div className="panel__title">使用边界</div><div className="panel__body gate-list">
      <div><StatusBadge label="未记录" tone="review" /><span>信号—证据关联</span><small>不推断信号与任何新闻、公告或财报证据存在关联</small></div>
      <div><StatusBadge label="仅建议" tone="reject" /><span>研究与回测</span><small>recommendation_only 不等于 Research Readiness、回测资格或策略结论</small></div>
      <div><StatusBadge label="禁止" tone="reject" /><span>直接下单</span><small>AI 输出不能绕过 Risk Engine、人工授权或 Execution Gate</small></div>
    </div></section>
    <section className="panel"><div className="panel__title">页面说明</div><div className="panel__body"><p className="soft-note">模型使用记录来自 AI 调用审计。调用版本、逐信号证据引用和证据截止时间当前均未记录；页面明确展示缺失，不生成 BUY/SELL 建议，不把未知、未认证或过期信息包装为可交易事实。</p></div></section>
  </section>;
}
