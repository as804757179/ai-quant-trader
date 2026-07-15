import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { Link } from "react-router-dom";
import {
  formatCurrency,
  formatPercent,
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

function stateTone(kind: DisplayKind): StatusTone {
  if (kind === "live") return "pass";
  if (kind === "empty") return "idle";
  if (kind === "loading") return "info";
  return kind === "pending" ? "review" : "reject";
}

export default function OverviewPage() {
  const { dashboard, summary, alerts } = useOverviewModel();
  const portfolio = summary.data ?? dashboard.data?.portfolio;
  const alertRows: AlertRow[] = (alerts.data?.items ?? dashboard.data?.alerts?.items ?? []).map(
    (alert: RiskAlert, index) => ({
      key: alert.id ?? `${alert.created_at ?? "pending"}-${index}`,
      time: formatChinaDateTime(alert.created_at),
      level: alert.level ?? "待接入",
      message: alert.message ?? "待接入",
      type: alert.alert_type ?? "待接入",
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
          value={dashboard.data?.fuse?.is_active ? "风险熔断" : dashboard.kind === "live" ? "运行中" : "待接入"}
          detail="交易时段与证券状态待接入"
          tone={dashboard.data?.fuse?.is_active ? "reject" : dashboard.kind === "live" ? "pass" : "review"}
        />
        <MetricCard label="当前仓位" value={formatPercent(portfolio?.position_ratio)} detail={`持仓数：${portfolio?.position_count ?? "待接入"}`} />
        <MetricCard label="数据延迟" value="待接入" detail="行情延迟接口待接入" tone="review" />
      </div>
      <div className="overview-grid overview-grid--top">
        <section className="panel">
          <div className="panel__title">自动闭环状态</div>
          <div className="panel__body">
            <div className="pipeline">
              <div><span className="pipeline__node pipeline__node--info" />数据采集<small>待接入</small></div>
              <div><span className="pipeline__arrow" />证券资格校验<small>待审核</small></div>
              <div><span className="pipeline__arrow" />研究候选分析<small>待接入</small></div>
              <div><span className="pipeline__arrow" />人工审批<small>未授权</small></div>
              <div><span className="pipeline__arrow" />执行门禁<small>关闭</small></div>
            </div>
            <p className="soft-note">自动执行已关闭。任何订单都必须经过数据资格、风险检查、明确授权和执行门禁。</p>
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
          <div className="panel__body"><EmptyState description="研究候选接口待接入" /></div>
        </section>
        <section className="panel">
          <div className="panel__title">资产曲线（近30天）</div>
          <div className="panel__body"><EmptyState description="资产曲线接口待接入" /></div>
        </section>
      </div>
      <section className="panel">
        <div className="panel__title">系统服务状态</div>
        <div className="panel__body service-grid">
          {[
            ["数据服务", "数据时效与降级状态待接入"],
            ["交易服务", "执行门禁：关闭"],
            ["风控引擎", "规则版本待接入"],
            ["策略引擎", "策略版本待接入"],
            ["AI 分析服务", "仅分析，不创建订单"],
          ].map(([label, detail]) => (
            <div className="service-card" key={label}>
              <strong>{label}</strong>
              <StatusBadge label="待接入" tone="review" />
              <span>{detail}</span>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
