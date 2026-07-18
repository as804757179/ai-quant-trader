import type { CSSProperties } from "react";
import { formatCurrency, formatPercent, useTradeControlModel } from "../../presentation/coreModels";
import type { DataProvenance, ReleaseLock, StatusTone } from "../../presentation/contracts";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import StatusBadge from "../../ui/StatusBadge";

function booleanStatus(value: boolean | undefined, positive = "已验证", negative = "未满足") {
  if (value === true) return { label: positive, tone: "pass" as const };
  if (value === false) return { label: negative, tone: "reject" as const };
  return { label: "状态未知", tone: "review" as const };
}

function releaseLockStatus(lock: ReleaseLock | undefined, known: boolean) {
  if (!known) return { label: "状态未知", tone: "review" as const };
  if (!lock) return { label: "未记录", tone: "review" as const };
  return { label: lock.enabled ? "已开启" : "关闭", tone: "reject" as const };
}

function auditCountStatus(
  value: number | undefined,
  known: boolean,
  positiveTone: StatusTone,
  zeroTone: StatusTone,
) {
  if (!known || typeof value !== "number") return { label: "状态未知", tone: "review" as const };
  return { label: String(value), tone: value > 0 ? positiveTone : zeroTone };
}

function humanApprovalStatus(value: boolean | undefined) {
  if (value === true) return { label: "强制", tone: "pass" as const };
  if (value === false) return { label: "未强制", tone: "reject" as const };
  return { label: "状态未知", tone: "review" as const };
}

export default function TradeControlPage() {
  const { mode, broker, exposure, execution } = useTradeControlModel();
  const modeKnown = mode.kind === "live" && Boolean(mode.data);
  const brokerKnown = broker.kind === "live" && Boolean(broker.data);
  const executionKnown = execution.kind === "live" && Boolean(execution.data);
  const currentMode = modeKnown && mode.data?.mode ? mode.data.mode.toUpperCase() : "状态未知";
  const brokerConnection = booleanStatus(
    brokerKnown ? broker.data?.connection_ready : undefined,
    "已连接",
    "未连接",
  );
  const releaseLocks = executionKnown ? execution.data?.release_locks ?? [] : [];
  const tradingLock = releaseLocks.find((lock) => lock.key === "TRADING_EXECUTION_ENABLED");
  const aiLock = releaseLocks.find((lock) => lock.key === "AI_ORDER_ENABLED");
  const scheduledLock = releaseLocks.find((lock) => lock.key === "ALLOW_SCHEDULED_ORDER");
  const tradingLockStatus = releaseLockStatus(tradingLock, executionKnown);
  const aiLockStatus = releaseLockStatus(aiLock, executionKnown);
  const scheduledLockStatus = releaseLockStatus(scheduledLock, executionKnown);
  const humanApproval = humanApprovalStatus(
    executionKnown ? execution.data?.require_human_approval : undefined,
  );
  const orderAudit = executionKnown ? execution.data?.order_audit : undefined;
  const orderAuditKnown = Boolean(orderAudit);
  const totalOrders = auditCountStatus(orderAudit?.total, orderAuditKnown, "info", "info");
  const failedOrders = auditCountStatus(orderAudit?.failed, orderAuditKnown, "reject", "idle");
  const openOrders = auditCountStatus(orderAudit?.open, orderAuditKnown, "review", "idle");
  const unknownCallers = auditCountStatus(orderAudit?.unknown_caller, orderAuditKnown, "reject", "pass");
  const aiSourceOrders = auditCountStatus(orderAudit?.ai_source, orderAuditKnown, "reject", "pass");
  const scheduledSourceOrders = auditCountStatus(orderAudit?.scheduled_source, orderAuditKnown, "reject", "pass");
  const riskRules = executionKnown ? execution.data?.risk_rules : undefined;
  const riskRulesKnown = Boolean(riskRules);
  const provenance: DataProvenance = {
    ...execution.provenance,
    dataCutoff: "不适用（执行安全状态）",
    sourceVersion: execution.data?.source_version ?? execution.provenance.sourceVersion,
  };
  const releaseStatus = !executionKnown
    ? "状态未知"
    : execution.data?.all_release_locks_closed === true
      ? "全部关闭"
      : execution.data?.all_release_locks_closed === false
        ? "存在开启项"
        : "锁状态未记录";

  return (
    <section className="page-frame">
      <header className="page-header"><div><h1>交易控制台 / Trade Execution</h1><p>交易模式、范围化授权和执行安全门禁</p></div><StatusBadge label={`自动执行：${tradingLockStatus.label}`} tone={tradingLockStatus.tone} /></header>
      <DataMetaBar provenance={provenance} relatedId="execution:safety" statusText={`基础设施 ${executionKnown ? "已读取" : "状态未知"} · 数据资格 ${executionKnown ? "按订单记录" : "状态未知"} · 业务发布 ${releaseStatus}`} />
      <div className="trade-control-grid">
        <section className="panel"><div className="panel__title">运行模式</div><div className="panel__body mode-grid">
          {[
            ["仿真交易", "SIMULATION", modeKnown ? mode.data?.available_modes?.includes("simulation") : undefined],
            ["模拟盘", "PAPER", modeKnown ? mode.data?.available_modes?.includes("paper") : undefined],
            ["实盘交易", "LIVE", modeKnown ? mode.data?.available_modes?.includes("live") : undefined],
          ].map(([label, value, available]) => <div className={`mode-card${value === currentMode ? " is-selected" : ""}`} key={String(value)}><strong>{label}</strong><span>{value}</span><StatusBadge label={available === true ? "模式可见" : available === false ? "不可用" : "状态未知"} tone={available === true ? "info" : available === false ? "reject" : "review"} /></div>)}
        </div></section>
        <section className="panel"><div className="panel__title">全局发布锁</div><div className="panel__body gate-list">{releaseLocks.length ? releaseLocks.map((lock) => <div key={lock.key}><StatusBadge label={lock.enabled ? "已开启" : "关闭"} tone="reject" /><span>{lock.label}</span><small>{lock.reason}</small></div>) : <p className="soft-note">{executionKnown ? "未返回发布锁" : execution.message}</p>}</div></section>
      </div>
      <div className="metric-grid" style={{ "--metric-columns": 6 } as CSSProperties}>
        <MetricCard label="当前模式" value={currentMode} detail="只读 /trade/mode" tone={mode.kind === "live" ? "info" : "review"} />
        <MetricCard label="可用资金" value={formatCurrency(exposure.data?.cash)} detail="仅读取风险敞口快照" />
        <MetricCard label="当前仓位" value={formatPercent(exposure.data?.position_ratio)} detail="不触发下单" />
        <MetricCard label="券商连接" value={brokerConnection.label} detail={broker.data?.selected_adapter ?? broker.message} tone={brokerConnection.tone} />
        <MetricCard label="近期待处理订单" value={openOrders.label} detail={executionKnown && typeof execution.data?.window_days === "number" ? `审计窗口 ${execution.data.window_days} 天` : "审计窗口状态未知"} tone={openOrders.tone} />
        <MetricCard label="风险规则" value={riskRulesKnown ? String(riskRules?.enabled_count ?? "未记录") : "状态未知"} detail={`规则 Hash：${riskRules?.rule_set_hash?.slice(0, 12) ?? "未记录"}`} tone={riskRulesKnown ? "info" : "review"} />
      </div>
      <div className="trade-control-grid">
        <section className="panel"><div className="panel__title">执行门禁（Execution Gate）</div><div className="panel__body gate-list">
          <div><StatusBadge label={tradingLockStatus.label} tone={tradingLockStatus.tone} /><span>自动交易执行</span><small>{tradingLock ? `${tradingLock.key}=${tradingLock.enabled}` : executionKnown ? "发布锁未记录" : execution.message}</small></div>
          <div><StatusBadge label={aiLockStatus.label} tone={aiLockStatus.tone} /><span>AI 订单权限</span><small>{aiLock ? `${aiLock.key}=${aiLock.enabled}` : executionKnown ? "发布锁未记录" : execution.message}</small></div>
          <div><StatusBadge label={scheduledLockStatus.label} tone={scheduledLockStatus.tone} /><span>定时任务订单</span><small>{scheduledLock ? `${scheduledLock.key}=${scheduledLock.enabled}` : executionKnown ? "发布锁未记录" : execution.message}</small></div>
          <div><StatusBadge label={humanApproval.label} tone={humanApproval.tone} /><span>范围化授权</span><small>未提供明确人工授权时不得下单</small></div>
        </div></section>
        <section className="panel"><div className="panel__title">连接状态</div><div className="panel__body gate-list">
          {[
            ["券商适配器", brokerKnown ? broker.data?.selected_adapter ?? "未记录" : "状态未知", brokerKnown && broker.data?.selected_adapter ? "pass" : "review"],
            ["xtquant 环境", booleanStatus(brokerKnown ? broker.data?.xtquant_available : undefined).label, booleanStatus(brokerKnown ? broker.data?.xtquant_available : undefined).tone],
            ["QMT 路径", booleanStatus(brokerKnown ? broker.data?.qmt_path_exists : undefined).label, booleanStatus(brokerKnown ? broker.data?.qmt_path_exists : undefined).tone],
            ["账户配置", booleanStatus(brokerKnown ? broker.data?.account_configured : undefined).label, booleanStatus(brokerKnown ? broker.data?.account_configured : undefined).tone],
          ].map(([label, value, tone]) => <div key={String(label)}><StatusBadge label={String(value)} tone={tone as "pass" | "review" | "reject"} /><span>{label}</span><small>读取 /trade/broker-status</small></div>)}
        </div></section>
      </div>
      <section className="panel"><div className="panel__title">最近执行审计</div><div className="panel__body gate-list">
        <div><StatusBadge label={totalOrders.label} tone={totalOrders.tone} /><span>审计窗口订单总数</span><small>只读 trade.orders</small></div>
        <div><StatusBadge label={failedOrders.label} tone={failedOrders.tone} /><span>失败订单</span><small>{orderAuditKnown ? orderAudit?.rejection_reasons?.map((item) => `${item.reason}:${item.count}`).join(" / ") || "无失败原因记录" : "审计状态未知"}</small></div>
        <div><StatusBadge label={unknownCallers.label} tone={unknownCallers.tone} /><span>未知调用者</span><small>必须为 0</small></div>
        <div><StatusBadge label={aiSourceOrders.label} tone={aiSourceOrders.tone} /><span>AI 来源订单</span><small>必须为 0</small></div>
        <div><StatusBadge label={scheduledSourceOrders.label} tone={scheduledSourceOrders.tone} /><span>定时任务来源订单</span><small>默认必须为 0</small></div>
      </div></section>
    </section>
  );
}
