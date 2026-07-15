import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { RELEASE_LOCKS } from "../../presentation/contracts";
import { formatChinaDateTime } from "../../presentation/time";
import { useBacktestTasks, type BacktestTaskData } from "../../presentation/coreModels";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

export default function BacktestValidationPage() {
  const tasks = useBacktestTasks();
  const rows = (tasks.data?.items ?? []).map((task, index) => ({ ...task, key: String(task.id ?? index) }));
  const columns: TableProps<BacktestTaskData & { key: string }>["columns"] = [
    { title: "任务 ID", dataIndex: "id", width: 120 },
    { title: "策略", dataIndex: "strategy_type", width: 180, render: (value) => value ?? "待接入" },
    { title: "创建时间", dataIndex: "created_at", width: 200, render: (value) => formatChinaDateTime(value) },
    { title: "状态", dataIndex: "status", width: 130, render: (value) => <StatusBadge label={value ?? "待接入"} tone="review" /> },
    { title: "结果 Hash", dataIndex: "result_hash", width: 260, render: (value) => value ?? "待接入" },
  ];

  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header"><div><h1>回测验证 / Backtest Validation</h1><p>数据读取、时序、会计、Reference 对账和发布门禁</p></div><StatusBadge label="未发布" tone="reject" /></header>
      <DataMetaBar provenance={tasks.provenance} relatedId="backtest:validation-only" statusText="基础设施 待接入 · 数据资格 按任务验证 · 业务发布 关闭" />
      <div className="metric-grid" style={{ "--metric-columns": 5 } as CSSProperties}>
        <MetricCard label="验证状态" value="未发布" detail="公共回测入口关闭" tone="reject" />
        <MetricCard label="验证任务" value={tasks.data?.total ?? "待接入"} detail="只读任务列表" />
        <MetricCard label="数据集 Hash" value="待接入" detail="必须稳定排序" tone="review" />
        <MetricCard label="策略版本" value="待接入" detail="不展示策略盈利结论" tone="review" />
        <MetricCard label="引擎版本" value="待接入" detail="Engine/Reference 需逐项对账" tone="review" />
      </div>
      <div className="backtest-grid">
        <section className="panel table-panel"><div className="panel__title">验证任务（只读）</div><div className="panel__body"><ReadOnlyTable columns={columns} data={rows} rowKey="key" emptyDescription={tasks.message} /></div></section>
        <section className="panel"><div className="panel__title">发布门槛值</div><div className="panel__body gate-list">{RELEASE_LOCKS.slice(0, 2).map((lock) => <div key={lock.key}><StatusBadge label="关闭" tone="reject" /><span>{lock.label}</span><small>{lock.reason}</small></div>)}</div></section>
      </div>
      <section className="panel"><div className="panel__title">验证边界</div><div className="panel__body"><p className="soft-note">本页只呈现回测完整性和可复现性证据。任何小样本指标均不能解释为策略盈利能力或投资建议。</p></div></section>
    </section>
  );
}
