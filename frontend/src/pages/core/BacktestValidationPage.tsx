import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { formatChinaDateTime } from "../../presentation/time";
import { useBacktestTasks, type BacktestTaskData, useBacktestValidationSummary, useExecutionStatus } from "../../presentation/coreModels";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

export default function BacktestValidationPage() {
  const tasks = useBacktestTasks();
  const validation = useBacktestValidationSummary();
  const execution = useExecutionStatus();
  const rows = (tasks.data?.items ?? []).map((task, index) => ({ ...task, key: String(task.task_id ?? index) }));
  const backtestLocks = (execution.data?.release_locks ?? []).filter((lock) =>
    ["CERTIFIED_BACKTEST_EXECUTION_ENABLED", "CERTIFIED_SCREENER_OUTPUT_ENABLED"].includes(lock.key),
  );
  const backtestLock = backtestLocks.find(
    (lock) => lock.key === "CERTIFIED_BACKTEST_EXECUTION_ENABLED",
  );
  const persisted = validation.data?.latest_persisted_result;
  const shortHash = (value: string | null | undefined) => value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "未记录";
  const columns: TableProps<BacktestTaskData & { key: string }>["columns"] = [
    { title: "任务 ID", dataIndex: "task_id", width: 120 },
    { title: "任务名称", dataIndex: "name", width: 200, render: (value) => value ?? "待接入" },
    { title: "数据区间", width: 220, render: (_, row) => `${row.start_date ?? "待接入"} — ${row.end_date ?? "待接入"}` },
    { title: "股票范围", dataIndex: "universe", width: 180, render: (value) => value ?? "待接入" },
    { title: "创建时间", dataIndex: "created_at", width: 200, render: (value) => formatChinaDateTime(value) },
    { title: "状态", dataIndex: "status", width: 130, render: (value) => <StatusBadge label={value ?? "待接入"} tone="review" /> },
    { title: "失败原因", dataIndex: "error_msg", width: 260, render: (value) => value ?? "—" },
  ];

  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header"><div><h1>回测验证 / Backtest Validation</h1><p>数据读取、时序、会计、Reference 对账和发布门禁</p></div><StatusBadge label={backtestLock?.enabled ? "已开启" : backtestLock ? "未发布" : "待接入"} tone={backtestLock?.enabled ? "review" : "reject"} /></header>
      <DataMetaBar provenance={validation.provenance} relatedId={persisted?.task_id ? `backtest:task:${persisted.task_id}` : "backtest:validation-only"} statusText={`基础设施 已读取 · 数据资格 ${persisted?.readiness_reviews?.length ? "有审核记录" : "未记录"} · 业务发布 ${backtestLock?.enabled ? "已开启" : backtestLock ? "关闭" : "待接入"}`} />
      <div className="metric-grid" style={{ "--metric-columns": 5 } as CSSProperties}>
        <MetricCard label="验证状态" value={persisted?.validation_status ?? "无持久化结果"} detail={persisted?.blocking_reasons?.[0] ?? backtestLock?.reason ?? execution.message} tone={persisted?.validation_status === "validated" ? "pass" : "reject"} />
        <MetricCard label="验证任务" value={validation.data?.summary?.total ?? tasks.data?.total ?? "待接入"} detail={`完成 ${validation.data?.summary?.done ?? 0} · 失败 ${validation.data?.summary?.failed ?? 0}`} />
        <MetricCard label="数据集 Hash" value={shortHash(persisted?.dataset_hash)} detail={persisted?.dataset_hash_status ?? "无持久化结果"} tone="review" />
        <MetricCard label="策略版本" value={persisted?.strategy_type ?? "未记录"} detail={persisted?.strategy_version_status ?? "无持久化结果"} tone="review" />
        <MetricCard label="引擎版本" value={validation.data?.current_runtime_versions?.engine ?? "待接入"} detail="当前运行版本；历史任务版本单独标记" tone="review" />
      </div>
      <section className="panel"><div className="panel__title">最新持久化结果血缘</div><div className="panel__body gate-list">
        <div><StatusBadge label={persisted?.lookahead_checked ? "已检查" : "未记录"} tone={persisted?.lookahead_checked ? "pass" : "review"} /><span>未来函数检查</span><small>任务 {persisted?.task_id ?? "无"}</small></div>
        <div><StatusBadge label={persisted?.persisted_result_hash ? "已重建" : "未记录"} tone={persisted?.persisted_result_hash ? "info" : "review"} /><span>持久化结果 Hash</span><small>{shortHash(persisted?.persisted_result_hash)} · {persisted?.result_hash_status ?? "无结果"}</small></div>
        <div><StatusBadge label={persisted?.reference_comparison_status === "not_recorded_at_run_time" ? "未记录" : "待接入"} tone="review" /><span>Engine / Reference</span><small>{persisted?.reference_comparison_status ?? "无持久化结果"}</small></div>
        <div><StatusBadge label={persisted?.readiness_reviews?.length ? "有记录" : "未记录"} tone={persisted?.readiness_reviews?.length ? "info" : "review"} /><span>Scoped Readiness</span><small>{persisted?.readiness_reviews?.map((item) => `${item.stock_code}:${item.readiness_status}`).join(" / ") || "历史任务未保存完整授权键"}</small></div>
        <div><StatusBadge label={String(persisted?.blocking_reasons?.length ?? 0)} tone={persisted?.blocking_reasons?.length ? "reject" : "pass"} /><span>验证阻塞</span><small>{persisted?.blocking_reasons?.join(" / ") || "无阻塞"}</small></div>
        <div><StatusBadge label="验证用途" tone="idle" /><span>发布语义</span><small>validation_only=true · not_for_investment=true</small></div>
      </div></section>
      <div className="backtest-grid">
        <section className="panel table-panel"><div className="panel__title">验证任务（只读）</div><div className="panel__body"><ReadOnlyTable columns={columns} data={rows} rowKey="key" emptyDescription={tasks.message} /></div></section>
        <section className="panel"><div className="panel__title">发布门槛值</div><div className="panel__body gate-list">{backtestLocks.length ? backtestLocks.map((lock) => <div key={lock.key}><StatusBadge label={lock.enabled ? "已开启" : "关闭"} tone="reject" /><span>{lock.label}</span><small>{lock.reason}</small></div>) : <p className="soft-note">{execution.message}</p>}</div></section>
      </div>
      <section className="panel"><div className="panel__title">验证边界</div><div className="panel__body"><p className="soft-note">本页只呈现回测完整性和可复现性证据。任何小样本指标均不能解释为策略盈利能力或投资建议。</p></div></section>
    </section>
  );
}
