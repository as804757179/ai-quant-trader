import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface LogLineage { correlationId: string; eventId: string; businessDate: string; eventTime: string; receivedAt: string; version: string; integrityHash: string; }

interface LogRow extends LogLineage { key: string; source: string; }

interface LogDefinition {
  title: string;
  subtitle: string;
  relatedId: string;
  tableTitle: string;
  emptyDescription: string;
  eventLabel: string;
  sourceLabel: string;
  lineageNote: string;
  restriction: string;
}

function LogStaticPage(definition: LogDefinition) {
  const state = pendingState(definition.emptyDescription, `${definition.relatedId}-ui-v1`);
  const columns: TableProps<LogRow>["columns"] = [
    { title: definition.eventLabel, dataIndex: "eventId", width: 220 }, { title: "correlation_id", dataIndex: "correlationId", width: 240 }, { title: "业务日期", dataIndex: "businessDate", width: 170 }, { title: "事件时间", dataIndex: "eventTime", width: 210 }, { title: "接收时间", dataIndex: "receivedAt", width: 210 }, { title: definition.sourceLabel, dataIndex: "source", width: 190 }, { title: "版本", dataIndex: "version", width: 150 }, { title: "完整性 Hash", dataIndex: "integrityHash", width: 260 },
  ];
  return <SectionPage title={definition.title} subtitle={definition.subtitle} relatedId={definition.relatedId} provenance={state.provenance} metrics={[{ label: "日志事件", value: "待接入", detail: "不展示虚构日志", tone: "review" }, { label: "业务日期", value: "待接入", detail: "与接收时间分离", tone: "review" }, { label: "完整性校验", value: "待接入", detail: "事件需有稳定 Hash", tone: "review" }, { label: "写入行为", value: "只读", detail: "页面不生成业务事件", tone: "idle" }]} tableTitle={definition.tableTitle} columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="日志血缘" auditItems={[{ label: "关联 ID", value: "必须", detail: definition.lineageNote, tone: "info" }, { label: "时间语义", value: "必须", detail: "使用 Asia/Shanghai yyyy-MM-dd HH:mm:ss", tone: "info" }, { label: "业务限制", value: "保持", detail: definition.restriction, tone: "reject" }]} note="日志页提供可检索、可筛选、可分页的只读审计结构；每条事件必须保留 event_id、correlation_id、业务时间、接收时间、版本和完整性哈希。" />;
}

export function ScanLogPage() { return <LogStaticPage title="扫描日志" subtitle="全市场扫描任务、数据批次、时点和运行结论" relatedId="logs:scan" tableTitle="扫描任务事件" emptyDescription="扫描日志接口待接入" eventLabel="scan_run_id" sourceLabel="数据批次" lineageNote="关联 scan_run_id、dataset_hash 与 provider batch" restriction="扫描不产生订单" />; }
export function SelectionLogPage() { return <LogStaticPage title="选股日志" subtitle="研究筛选、候选进入、排除和待复核的证据" relatedId="logs:selection" tableTitle="研究筛选事件" emptyDescription="选股日志接口待接入" eventLabel="selection_run_id" sourceLabel="研究 Profile" lineageNote="关联 selection_run_id、Readiness review 与排除原因" restriction="候选不发布、不下单" />; }
export function DecisionLogPage() { return <LogStaticPage title="决策日志" subtitle="决策输入、风险检查、审批和最终动作的完整轨迹" relatedId="logs:decisions" tableTitle="决策审计事件" emptyDescription="决策日志接口待接入" eventLabel="decision_id" sourceLabel="调用者" lineageNote="关联 decision_id、risk_check_id 与 approval_id" restriction="AI 不得创建订单" />; }
export function OrderLogPage() { return <LogStaticPage title="订单日志" subtitle="订单来源、幂等键、Execution Gate 和审批状态" relatedId="logs:orders" tableTitle="订单生命周期事件" emptyDescription="订单日志接口待接入" eventLabel="order_id" sourceLabel="order_source" lineageNote="关联 order_id、caller、approval_id 与 idempotency_key" restriction="自动下单保持关闭" />; }
export function FillLogPage() { return <LogStaticPage title="成交日志" subtitle="成交回报、费用明细、订单关联与回报时效" relatedId="logs:fills" tableTitle="成交审计事件" emptyDescription="成交日志接口待接入" eventLabel="fill_id" sourceLabel="订单 ID" lineageNote="关联 fill_id、order_id、费用规则与执行价格来源" restriction="无回报不得伪造成交" />; }
export function RejectionLogPage() { return <LogStaticPage title="拒绝日志" subtitle="数据、Readiness、Risk Engine 与 Execution Gate 的拒绝证据" relatedId="logs:rejections" tableTitle="拒绝事件" emptyDescription="拒绝日志接口待接入" eventLabel="rejection_id" sourceLabel="拒绝来源" lineageNote="关联 rejection_reason、caller、risk_check_id 与数据状态" restriction="拒绝不能被静默绕过" />; }
export function PositionLogPage() { return <LogStaticPage title="持仓日志" subtitle="持仓、可用数量、成本、T+1 与零股变化的账务轨迹" relatedId="logs:positions" tableTitle="持仓状态事件" emptyDescription="持仓日志接口待接入" eventLabel="position_event_id" sourceLabel="账务来源" lineageNote="关联订单、成交、企业行动与账本版本" restriction="不得用 K 线修改持仓" />; }
export function CashLogPage() { return <LogStaticPage title="现金日志" subtitle="可用现金、冻结资金、费用和资金流的账务轨迹" relatedId="logs:cash" tableTitle="现金账务事件" emptyDescription="现金日志接口待接入" eventLabel="cash_event_id" sourceLabel="账务来源" lineageNote="关联订单、成交、费用与对账批次" restriction="不连接真实账户资金" />; }
export function DailyPnlLogPage() { return <LogStaticPage title="每日盈亏日志" subtitle="当日已实现、未实现、费用、现金事件和差异拆分" relatedId="logs:pnl-daily" tableTitle="每日盈亏事件" emptyDescription="每日盈亏日志接口待接入" eventLabel="pnl_event_id" sourceLabel="估值/账务版本" lineageNote="关联业务日期、估值来源、费用与对账结果" restriction="不输出策略盈利结论" />; }
export function HistoryPnlLogPage() { return <LogStaticPage title="历史盈亏日志" subtitle="按业务日归档的盈亏、版本、重算与结果 Hash 轨迹" relatedId="logs:pnl-history" tableTitle="历史盈亏归档" emptyDescription="历史盈亏日志接口待接入" eventLabel="pnl_snapshot_id" sourceLabel="结果版本" lineageNote="关联资产快照、dataset_hash 和规则版本" restriction="历史数据不可悄然改写" />; }
export function CashEventLogPage() { return <LogStaticPage title="现金事件日志" subtitle="企业行动现金、支付日期、证据和账务入账轨迹" relatedId="logs:cash-events" tableTitle="现金事件审计" emptyDescription="现金事件日志接口待接入" eventLabel="corporate_action_id" sourceLabel="官方证据" lineageNote="关联公告、evidence_hash、payment_date 与账务事件" restriction="不得提前入账或伪装为交易盈亏" />; }
export function SettlementLogPage() { return <LogStaticPage title="清算日志" subtitle="日终清算阶段、异常、回滚与对账状态" relatedId="logs:settlement" tableTitle="清算运行事件" emptyDescription="清算日志接口待接入" eventLabel="settlement_run_id" sourceLabel="清算批次" lineageNote="关联业务日期、账务版本、异常与回滚记录" restriction="清算不解锁交易" />; }
export function RiskLogPage() { return <LogStaticPage title="风险日志" subtitle="风险规则命中、阈值、处置和拒绝的可追踪记录" relatedId="logs:risk" tableTitle="风险控制事件" emptyDescription="风险日志接口待接入" eventLabel="risk_event_id" sourceLabel="规则版本" lineageNote="关联 risk_check_id、规则版本和相关订单/决策" restriction="风险门禁不得绕过" />; }
export function ReviewLogPage() { return <LogStaticPage title="复盘日志" subtitle="复盘输入、当时信息、后验结果和审批轨迹" relatedId="logs:review" tableTitle="复盘审计事件" emptyDescription="复盘日志接口待接入" eventLabel="review_id" sourceLabel="复盘版本" lineageNote="关联业务日期、证据版本和审批记录" restriction="复盘不自动改变策略" />; }
export function StrategyChangeLogPage() { return <LogStaticPage title="策略变更日志" subtitle="策略、参数、规则变更、测试证据、审批和回滚轨迹" relatedId="logs:strategy-changes" tableTitle="策略变更事件" emptyDescription="策略变更日志接口待接入" eventLabel="change_id" sourceLabel="策略版本" lineageNote="关联 strategy_id、parameter_hash、测试与 approval_id" restriction="变更不得自动上线" />; }
