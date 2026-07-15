import type { CSSProperties } from "react";
import { RELEASE_LOCKS } from "../../presentation/contracts";
import { formatCurrency, formatPercent, useTradeControlModel } from "../../presentation/coreModels";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import StatusBadge from "../../ui/StatusBadge";

function booleanStatus(value: boolean | undefined, positive = "已验证") {
  if (value === true) return { label: positive, tone: "pass" as const };
  if (value === false) return { label: "未满足", tone: "reject" as const };
  return { label: "待接入", tone: "review" as const };
}

export default function TradeControlPage() {
  const { mode, broker, exposure } = useTradeControlModel();
  const currentMode = mode.data?.mode?.toUpperCase() ?? mode.message;
  const brokerConnection = booleanStatus(broker.data?.connection_ready, "已连接");

  return (
    <section className="page-frame">
      <header className="page-header"><div><h1>交易控制台 / Trade Execution</h1><p>交易模式、范围化授权和执行安全门禁</p></div><StatusBadge label="自动执行：关闭" tone="reject" /></header>
      <DataMetaBar provenance={mode.provenance} relatedId="execution:simulation" statusText="基础设施 待读取 · 数据资格 待审核 · 业务发布 关闭" />
      <div className="trade-control-grid">
        <section className="panel"><div className="panel__title">运行模式</div><div className="panel__body mode-grid">
          {[
            ["仿真交易", "SIMULATION", mode.data?.available_modes?.includes("simulation")],
            ["模拟盘", "PAPER", mode.data?.available_modes?.includes("paper")],
            ["实盘交易", "LIVE", mode.data?.available_modes?.includes("live")],
          ].map(([label, value, available]) => <div className={`mode-card${value === currentMode ? " is-selected" : ""}`} key={String(value)}><strong>{label}</strong><span>{value}</span><StatusBadge label={available ? "模式可见" : "待接入"} tone={available ? "info" : "review"} /></div>)}
        </div></section>
        <section className="panel"><div className="panel__title">全局发布锁</div><div className="panel__body gate-list">{RELEASE_LOCKS.map((lock) => <div key={lock.key}><StatusBadge label="关闭" tone="reject" /><span>{lock.label}</span><small>{lock.reason}</small></div>)}</div></section>
      </div>
      <div className="metric-grid" style={{ "--metric-columns": 4 } as CSSProperties}>
        <MetricCard label="当前模式" value={currentMode} detail="只读 /trade/mode" tone={mode.kind === "live" ? "info" : "review"} />
        <MetricCard label="可用资金" value={formatCurrency(exposure.data?.cash)} detail="仅读取风险敞口快照" />
        <MetricCard label="当前仓位" value={formatPercent(exposure.data?.position_ratio)} detail="不触发下单" />
        <MetricCard label="券商连接" value={brokerConnection.label} detail={broker.data?.selected_adapter ?? broker.message} tone={brokerConnection.tone} />
      </div>
      <div className="trade-control-grid">
        <section className="panel"><div className="panel__title">执行门禁（Execution Gate）</div><div className="panel__body gate-list">
          <div><StatusBadge label="关闭" tone="reject" /><span>自动交易执行</span><small>TRADING_EXECUTION_ENABLED=false</small></div>
          <div><StatusBadge label="关闭" tone="reject" /><span>AI 订单权限</span><small>AI_ORDER_ENABLED=false</small></div>
          <div><StatusBadge label="关闭" tone="reject" /><span>定时任务订单</span><small>ALLOW_SCHEDULED_ORDER=false</small></div>
          <div><StatusBadge label="待审批" tone="review" /><span>范围化授权</span><small>未提供明确人工授权</small></div>
        </div></section>
        <section className="panel"><div className="panel__title">连接状态</div><div className="panel__body gate-list">
          {[
            ["券商适配器", broker.data?.selected_adapter ?? "待接入", broker.kind === "live" ? "pass" : "review"],
            ["xtquant 环境", booleanStatus(broker.data?.xtquant_available).label, booleanStatus(broker.data?.xtquant_available).tone],
            ["QMT 路径", booleanStatus(broker.data?.qmt_path_exists).label, booleanStatus(broker.data?.qmt_path_exists).tone],
            ["账户配置", booleanStatus(broker.data?.account_configured).label, booleanStatus(broker.data?.account_configured).tone],
          ].map(([label, value, tone]) => <div key={String(label)}><StatusBadge label={String(value)} tone={tone as "pass" | "review" | "reject"} /><span>{label}</span><small>读取 /trade/broker-status</small></div>)}
        </div></section>
      </div>
      <section className="panel"><div className="panel__title">最近执行记录</div><div className="panel__body"><p className="soft-note">订单写入、撤单和人工授权接口不会由本页面调用。订单审计请查看“订单与成交”与“交易与盈亏日志”。</p></div></section>
    </section>
  );
}
