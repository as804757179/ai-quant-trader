import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { Link } from "react-router-dom";
import {
  formatCurrency,
  formatPercent,
  type EquityCurvePoint,
  type RiskAlert,
  useOverviewModel,
} from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import type { DisplayKind, StatusTone } from "../../presentation/contracts";
import DataMetaBar from "../../ui/DataMetaBar";
import EmptyState from "../../ui/EmptyState";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

interface AlertRow {
  key: string;
  time: string;
  level: string;
  message: string;
  type: string;
}

interface CandidateRow {
  key: string;
  stockCode: string;
  status: string;
  profile: string;
  reason: string;
}

function formatLag(seconds: number | null | undefined): string {
  if (typeof seconds !== "number") return "无行情记录";
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  return `${Math.floor(seconds / 3600)} 小时`;
}

function EquityCurve({ items }: { items: EquityCurvePoint[] }) {
  const points = items.filter((item) => typeof item.total_assets === "number");
  if (!points.length) return <EmptyState description="暂无真实账户资产快照" />;
  const values = points.map((item) => item.total_assets as number);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const line = values
    .map((value, index) => {
      const x = points.length === 1 ? 300 : (index / (points.length - 1)) * 600;
      const y = 160 - ((value - min) / span) * 130;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="equity-chart">
      <svg viewBox="0 0 600 180" role="img" aria-label="近30天账户资产曲线">
        <line x1="0" y1="160" x2="600" y2="160" className="equity-chart__axis" />
        <polyline points={line} className="equity-chart__line" />
      </svg>
      <div className="equity-chart__meta">
        <span>最低 {formatCurrency(min)}</span>
        <span>最新 {formatCurrency(values[values.length - 1])}</span>
        <span>最高 {formatCurrency(max)}</span>
      </div>
    </div>
  );
}

function stateTone(kind: DisplayKind): StatusTone {
  if (kind === "live") return "pass";
  if (kind === "empty") return "idle";
  if (kind === "loading") return "info";
  return kind === "pending" ? "review" : "reject";
}

export default function OverviewPage() {
  const { dashboard, summary, alerts, health, execution, market, equity, candidates, strategy } = useOverviewModel();
  const dashboardKnown = dashboard.kind === "live" && Boolean(dashboard.data);
  const executionKnown = execution.kind === "live" && Boolean(execution.data);
  const marketKnown = market.kind === "live" && Boolean(market.data);
  const candidateKnown = (candidates.kind === "live" || candidates.kind === "empty") && Boolean(candidates.data);
  const portfolio = { ...dashboard.data?.portfolio, ...summary.data };
  const executionLock = executionKnown ? execution.data?.release_locks?.find(
    (lock) => lock.key === "TRADING_EXECUTION_ENABLED",
  ) : undefined;
  const databaseReady = health.data?.checks?.database === "ok";
  const fuseActive = dashboardKnown ? dashboard.data?.fuse?.is_active : undefined;
  const marketSession = marketKnown ? market.data?.market_session ?? "市场状态未记录" : market.message;
  const marketCoverage = marketKnown
    && typeof market.data?.recent_symbol_count === "number"
    && typeof market.data?.active_stock_count === "number"
    ? `${market.data.recent_symbol_count}/${market.data.active_stock_count}`
    : "状态未知";
  const candidateReady = candidateKnown ? candidates.data?.counts?.ready : undefined;
  const candidateReadyStatus = typeof candidateReady === "number"
    ? `${candidateReady} 个标的 ready`
    : "状态未知";
  const humanApprovalStatus = !executionKnown
    ? "状态未知"
    : execution.data?.require_human_approval === true
      ? "强制要求"
      : execution.data?.require_human_approval === false
        ? "未强制"
        : "未记录";
  const executionGateStatus = !executionKnown
    ? "状态未知"
    : executionLock
      ? executionLock.enabled ? "已开启" : "关闭"
      : "未记录";
  const executionNote = !executionKnown
    ? `自动执行状态未知。${execution.message}`
    : executionLock
    ? `自动执行已${executionLock.enabled ? "开启" : "关闭"}。任何订单都必须经过数据资格、风险检查、明确授权和执行门禁。`
    : "自动执行发布锁未记录。";
  const alertRows: AlertRow[] = (alerts.data?.items ?? dashboard.data?.alerts?.items ?? []).map(
    (alert: RiskAlert, index) => ({
      key: alert.id ?? `${alert.created_at ?? alert.ts ?? "pending"}-${index}`,
      time: formatChinaDateTime(alert.created_at ?? alert.ts),
      level: alert.level ?? "待接入",
      message: alert.message ?? "待接入",
      type: alert.alert_type ?? alert.type ?? "待接入",
    }),
  );
  const alertColumns: TableProps<AlertRow>["columns"] = [
    { title: "时间", dataIndex: "time", width: 176 },
    {
      title: "级别",
      dataIndex: "level",
      width: 100,
      render: (value: string) => <StatusBadge label={value} tone={value === "INFO" ? "info" : "review"} />,
    },
    { title: "风险事件", dataIndex: "message", width: 360 },
    { title: "来源类型", dataIndex: "type", width: 160 },
  ];
  const candidateRows: CandidateRow[] = (candidates.data?.items ?? []).map((item, index) => ({
    key: item.review_id ?? `candidate-exclusion-${index}`,
    stockCode: item.stock_code ?? "待接入",
    status: item.readiness_status ?? "待接入",
    profile: item.requirement_profile ?? "待接入",
    reason: item.review_reason ?? "未记录排除原因",
  }));
  const candidateColumns: TableProps<CandidateRow>["columns"] = [
    { title: "股票代码", dataIndex: "stockCode", width: 130 },
    { title: "研究状态", dataIndex: "status", width: 130, render: (value: string) => <StatusBadge label={value} tone={value === "rejected" ? "reject" : "review"} /> },
    { title: "Profile", dataIndex: "profile", width: 210 },
    { title: "排除/待复核原因", dataIndex: "reason", width: 320 },
  ];
  const marketTone: StatusTone = market.data?.status === "fresh" ? "pass" : market.data?.status === "market_closed" ? "idle" : "review";

  return (
    <section className="page-frame">
      <header className="page-header">
        <div>
          <h1>运行总览</h1>
          <p>系统运行状态与关键指标总览</p>
        </div>
        <StatusBadge label={summary.kind === "live" ? "组合数据已接入" : summary.message} tone={stateTone(summary.kind)} />
      </header>
      <DataMetaBar provenance={summary.provenance} relatedId="dashboard:simulation" />
      <div className="metric-grid" style={{ "--metric-columns": 6 } as CSSProperties}>
        <MetricCard label="总资产" value={formatCurrency(portfolio?.total_assets)} detail="只读组合摘要" />
        <MetricCard label="今日盈亏" value={formatCurrency(portfolio?.daily_pnl)} detail={formatPercent(portfolio?.daily_pnl_pct)} />
        <MetricCard label="当前回撤" value={formatPercent(portfolio?.drawdown_from_peak)} detail="来自风险快照" />
        <MetricCard
          label="市场状态"
          value={fuseActive === true ? "风险熔断" : fuseActive === false ? marketSession : "熔断状态未知"}
          detail={`认证日历来源：${marketKnown ? market.data?.calendar_sources?.join(" / ") || "未记录" : "状态未知"}`}
          tone={fuseActive === true ? "reject" : fuseActive === false ? marketTone : "review"}
        />
        <MetricCard label="当前仓位" value={formatPercent(portfolio?.position_ratio)} detail={`持仓数：${portfolio?.position_count ?? "待接入"}`} />
        <MetricCard
          label="数据延迟"
          value={marketKnown ? formatLag(market.data?.lag_seconds) : "状态未知"}
          detail={`状态：${marketKnown ? market.data?.status ?? "未记录" : market.message}；覆盖 ${marketCoverage}`}
          tone={marketTone}
        />
      </div>
      <div className="overview-grid overview-grid--top">
        <section className="panel">
          <div className="panel__title">自动闭环状态</div>
          <div className="panel__body">
            <div className="pipeline">
              <div><span className="pipeline__node pipeline__node--info" />数据采集<small>{market.data?.status ?? market.message}</small></div>
              <div><span className="pipeline__arrow" />证券资格校验<small>{candidateReadyStatus}</small></div>
              <div><span className="pipeline__arrow" />研究候选分析<small>{candidates.data?.candidate_status ?? candidates.message}</small></div>
              <div><span className="pipeline__arrow" />人工审批<small>{humanApprovalStatus}</small></div>
              <div><span className="pipeline__arrow" />执行门禁<small>{executionGateStatus}</small></div>
            </div>
            <p className="soft-note">{executionNote}</p>
          </div>
        </section>
        <section className="panel table-panel">
          <div className="panel__title"><span>风险事件时间线</span><Link className="data-link" to="/risk/events">查看全部</Link></div>
          <div className="panel__body">
            <ReadOnlyTable<AlertRow>
              columns={alertColumns}
              data={alertRows}
              rowKey="key"
              getFilterValue={(record) => record.level}
              filterOptions={[
                { label: "INFO", value: "INFO" },
                { label: "WARNING", value: "WARNING" },
                { label: "ERROR", value: "ERROR" },
              ]}
              emptyDescription={alerts.message}
            />
          </div>
        </section>
      </div>
      <div className="overview-grid overview-grid--bottom">
        <section className="panel table-panel">
          <div className="panel__title"><span>研究机会与排除原因（Top 5）</span><Link className="data-link" to="/research/candidates">查看全部机会</Link></div>
          <div className="panel__body"><ReadOnlyTable columns={candidateColumns} data={candidateRows} rowKey="key" emptyDescription={candidates.message} /></div>
        </section>
        <section className="panel">
          <div className="panel__title">资产曲线（近30天）</div>
          <div className="panel__body"><EquityCurve items={equity.data?.items ?? []} /></div>
        </section>
      </div>
      <section className="panel">
        <div className="panel__title">系统服务状态</div>
        <div className="panel__body service-grid">
          {[
            ["数据服务", databaseReady ? `行情：${marketKnown ? market.data?.status ?? "未记录" : market.message}；Provider 元数据：${marketKnown ? market.data?.provider_metadata_status ?? "未记录" : "状态未知"}` : health.message, market.data?.status === "fresh" && market.data?.provider_metadata_status !== "not_recorded" ? "pass" : "review", market.data?.provider_metadata_status === "not_recorded" ? "待审核" : databaseReady ? "通过" : "待接入"],
            ["交易服务", executionLock ? `执行门禁：${executionLock.enabled ? "已开启" : "关闭"}` : execution.message, executionLock?.enabled ? "reject" : executionLock ? "pass" : "review", executionLock?.enabled ? "已开启" : executionLock ? "通过" : "待接入"],
            ["风控引擎", dashboardKnown && fuseActive !== undefined ? `风险快照已接入；熔断：${fuseActive ? "已触发" : "未触发"}` : dashboard.message, fuseActive === true ? "reject" : fuseActive === false ? "pass" : "review", fuseActive === true ? "熔断" : fuseActive === false ? "通过" : "待接入"],
            ["策略引擎", `${strategy.data?.catalog_version ?? strategy.message}；配置 ${strategy.data?.config_hash?.slice(0, 12) ?? "未记录"}`, strategy.kind === "live" ? "pass" : "review", strategy.kind === "live" ? "通过" : "待接入"],
            ["AI 分析服务", executionKnown && execution.data?.ai_direct_order_allowed === false ? "仅分析，不创建订单" : execution.message, executionKnown && execution.data?.ai_direct_order_allowed === false ? "pass" : "review", executionKnown && execution.data?.ai_direct_order_allowed === false ? "通过" : "待接入"],
          ].map(([label, detail, tone, status]) => (
            <div className="service-card" key={label}>
              <strong>{label}</strong>
              <StatusBadge label={status} tone={tone as StatusTone} />
              <span>{detail}</span>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
