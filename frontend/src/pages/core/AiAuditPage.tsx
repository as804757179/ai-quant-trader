import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { formatChinaDateTime } from "../../presentation/time";
import { useAiSignals, type AiSignalData } from "../../presentation/coreModels";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

export default function AiAuditPage() {
  const signals = useAiSignals();
  const rows = (signals.data?.items ?? []).map((signal, index) => ({ ...signal, key: signal.id ?? `signal-${index}` }));
  const columns: TableProps<AiSignalData & { key: string }>["columns"] = [
    { title: "调用 ID", dataIndex: "id", width: 150, render: (value) => value ?? "待接入" },
    { title: "标的", dataIndex: "stock_code", width: 120, render: (value) => value ?? "待接入" },
    { title: "输出类型", dataIndex: "action", width: 120, render: (value) => <StatusBadge label={value ?? "待接入"} tone="idle" /> },
    { title: "风险等级", dataIndex: "risk_level", width: 120, render: (value) => <StatusBadge label={value ?? "待接入"} tone="review" /> },
    { title: "生成时间", dataIndex: "signal_time", width: 200, render: (value) => formatChinaDateTime(value) },
    { title: "审计摘要", dataIndex: "reason", width: 360, render: (value) => value ?? "待接入" },
  ];

  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header"><div><h1>AI 审计 / AI Audit</h1><p>AI 调用、证据、摘要和订单边界审计</p></div><StatusBadge label="AI 不具备下单权限" tone="reject" /></header>
      <DataMetaBar provenance={signals.provenance} relatedId="ai:audit" statusText="基础设施 待读取 · 数据资格 按上下文标记 · 业务发布 关闭" />
      <div className="metric-grid" style={{ "--metric-columns": 5 } as CSSProperties}>
        <MetricCard label="AI 调用总数" value={signals.data?.total ?? "待接入"} detail="仅读取信号审计列表" />
        <MetricCard label="摘要生成" value="待接入" detail="摘要接口待接入" tone="review" />
        <MetricCard label="订单创建" value="false" detail="AI 不得直接或间接创建订单" tone="reject" />
        <MetricCard label="越权尝试" value="待接入" detail="需接入审计事件" tone="review" />
        <MetricCard label="可用模型" value="待接入" detail="模型目录接口待接入" tone="review" />
      </div>
      <div className="ai-audit-grid">
        <section className="panel table-panel"><div className="panel__title">调用日志</div><div className="panel__body"><ReadOnlyTable columns={columns} data={rows} rowKey="key" emptyDescription={signals.message} /></div></section>
        <section className="panel"><div className="panel__title">AI 状态</div><div className="panel__body gate-list">
          <div><StatusBadge label="禁止" tone="reject" /><span>AI 直接下单</span><small>order_created=false</small></div>
          <div><StatusBadge label="待接入" tone="review" /><span>数据资格标记</span><small>未认证数据仅可展示</small></div>
          <div><StatusBadge label="禁止" tone="reject" /><span>定时任务自动下单</span><small>Celery 不得产生订单</small></div>
          <div><StatusBadge label="关闭" tone="reject" /><span>公共交易执行</span><small>Execution Gate 关闭</small></div>
        </div></section>
      </div>
      <section className="panel"><div className="panel__title">审计说明</div><div className="panel__body"><p className="soft-note">AI 可提供分析、解释、评分和 recommendation；任何推荐都不能绕过 Data Certification、Research Readiness、Risk Engine、人工授权或 Execution Gate。</p></div></section>
    </section>
  );
}
