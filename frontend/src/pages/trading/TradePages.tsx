import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import type { SectionMetric } from "../shared/SectionPage";
import SectionPage from "../shared/SectionPage";

interface TradeRow { key: string; primary: string; source: string; approval: string; dataStatus: string; riskResult: string; gateResult: string; idempotencyKey: string; }

interface TradePageDefinition {
  title: string;
  subtitle: string;
  relatedId: string;
  tableTitle: string;
  emptyDescription: string;
  metrics: readonly SectionMetric[];
  auditItems: readonly { label: string; value: string; detail: string; tone: "pass" | "idle" | "review" | "reject" | "info" }[];
  note: string;
  columns: TableProps<TradeRow>["columns"];
}

const orderColumns: TableProps<TradeRow>["columns"] = [
  { title: "订单/决策 ID", dataIndex: "primary", width: 210 }, { title: "来源/调用者", dataIndex: "source", width: 180 }, { title: "审批编号", dataIndex: "approval", width: 180 }, { title: "数据认证", dataIndex: "dataStatus", width: 160 }, { title: "Risk Engine", dataIndex: "riskResult", width: 170 }, { title: "Execution Gate", dataIndex: "gateResult", width: 180 }, { title: "幂等键", dataIndex: "idempotencyKey", width: 260 },
];

function TradeStaticPage(definition: TradePageDefinition) {
  const state = pendingState(definition.emptyDescription, `${definition.relatedId}-ui-v1`);
  return <SectionPage title={definition.title} subtitle={definition.subtitle} relatedId={definition.relatedId} provenance={state.provenance} metrics={definition.metrics} tableTitle={definition.tableTitle} columns={definition.columns} rowKey="key" emptyDescription={state.message} auditTitle="执行安全审计" auditItems={definition.auditItems} note={definition.note} />;
}

export function DecisionQueuePage() {
  return <TradeStaticPage title="决策队列" subtitle="风险预检前后、人工审批前后的决策候选与阻断原因" relatedId="trade:decisions" tableTitle="决策候选队列" emptyDescription="决策队列接口待接入" columns={orderColumns} metrics={[{ label: "待审批决策", value: "待接入", detail: "不等于可创建订单", tone: "review" }, { label: "风险拒绝", value: "待接入", detail: "保留命中规则与原因", tone: "review" }, { label: "执行许可", value: "关闭", detail: "TRADING_EXECUTION_ENABLED=false", tone: "reject" }, { label: "AI 决策", value: "不可下单", detail: "仅能形成 recommendation", tone: "reject" }]} auditItems={[{ label: "数据资格", value: "必须", detail: "认证与用途级 Readiness 不可跳过", tone: "info" }, { label: "人工审批", value: "必须", detail: "未审批决策不能进入下单", tone: "reject" }, { label: "未知调用者", value: "拒绝", detail: "必须明确 caller 与 order_source", tone: "reject" }]} note="决策队列是审计视图，不会提交、模拟或创建任何订单。" />;
}

export function AuthorizationPage() {
  return <TradeStaticPage title="范围化授权" subtitle="人工审批、有效期、适用账户与撤销状态" relatedId="trade:authorization" tableTitle="审批与授权记录" emptyDescription="范围化授权接口待接入" columns={orderColumns} metrics={[{ label: "有效授权", value: "待接入", detail: "需有 approval_id 与范围", tone: "review" }, { label: "人工审批", value: "必须", detail: "默认 REQUIRE_HUMAN_APPROVAL=true", tone: "info" }, { label: "定时订单", value: "关闭", detail: "ALLOW_SCHEDULED_ORDER=false", tone: "reject" }, { label: "Live 授权", value: "关闭", detail: "LIVE_TRADING_ENABLED=false", tone: "reject" }]} auditItems={[{ label: "授权范围", value: "明确", detail: "标的、数量、模式与有效期必须受限", tone: "info" }, { label: "审批关联", value: "必须", detail: "订单必须可回溯 approval_id", tone: "info" }, { label: "过期授权", value: "拒绝", detail: "不得继续用于下单", tone: "reject" }]} note="授权页面不提供授权创建或撤销操作；其职责是展示已有审批的可审计状态。" />;
}

export function AllOrdersPage() {
  return <TradeStaticPage title="全部订单" subtitle="订单来源、审批、数据认证、风控、执行门禁与幂等审计" relatedId="orders:all" tableTitle="订单全量审计" emptyDescription="订单查询接口待接入" columns={orderColumns} metrics={[{ label: "订单总数", value: "待接入", detail: "只读审计数据", tone: "review" }, { label: "Execution Gate", value: "强制", detail: "所有提交前必须检查", tone: "info" }, { label: "Risk Engine", value: "强制", detail: "Gate 通过后仍需风控", tone: "info" }, { label: "自动订单", value: "关闭", detail: "默认拒绝", tone: "reject" }]} auditItems={[{ label: "order_source", value: "必须", detail: "区分 manual、AI recommendation 与 scheduled", tone: "info" }, { label: "数据状态", value: "必须", detail: "记录 certification 与 readiness", tone: "info" }, { label: "幂等键", value: "必须", detail: "防止重复提交", tone: "info" }]} note="当前页面仅展示订单审计字段；不会以展示数据生成订单、成交或资金变动。" />;
}

export function OpenOrdersPage() {
  return <TradeStaticPage title="开放订单" subtitle="未完成订单的状态、有效期、回报时效与撤销原因" relatedId="orders:open" tableTitle="订单生命周期" emptyDescription="开放订单查询接口待接入" columns={[{ title: "订单 ID", dataIndex: "primary", width: 210 }, { title: "订单来源", dataIndex: "source", width: 180 }, { title: "审批编号", dataIndex: "approval", width: 180 }, { title: "风控结果", dataIndex: "riskResult", width: 170 }, { title: "Gate 状态", dataIndex: "gateResult", width: 180 }, { title: "幂等键", dataIndex: "idempotencyKey", width: 260 }]} metrics={[{ label: "未完成订单", value: "待接入", detail: "状态必须来自订单回报", tone: "review" }, { label: "超时订单", value: "待接入", detail: "需记录撤销或失效原因", tone: "review" }, { label: "模拟成交", value: "不可伪造", detail: "没有回报不得显示成交", tone: "reject" }, { label: "Live 执行", value: "关闭", detail: "不可因页面存在而开放", tone: "reject" }]} auditItems={[{ label: "回报时间", value: "必须", detail: "显示 UTC+8 精确时间", tone: "info" }, { label: "重复提交", value: "阻断", detail: "同一幂等键不得重复创建", tone: "info" }, { label: "撤单行为", value: "待接入", detail: "必须记录实际订单回报", tone: "review" }]} note="开放订单必须来自真实订单状态接口；未接入时页面保持空状态，不产生模拟回报。" />;
}

export function RejectedOrdersPage() {
  return <TradeStaticPage title="拒绝记录" subtitle="Data Certification、Readiness、Risk Engine 与 Execution Gate 的拒绝证据" relatedId="orders:rejected" tableTitle="订单拒绝与原因" emptyDescription="订单拒绝记录接口待接入" columns={[{ title: "拒绝 ID", dataIndex: "primary", width: 210 }, { title: "来源/调用者", dataIndex: "source", width: 190 }, { title: "数据认证", dataIndex: "dataStatus", width: 170 }, { title: "Risk 结果", dataIndex: "riskResult", width: 180 }, { title: "Gate 拒绝", dataIndex: "gateResult", width: 210 }, { title: "幂等键", dataIndex: "idempotencyKey", width: 260 }]} metrics={[{ label: "拒绝记录", value: "待接入", detail: "拒绝不应静默丢失", tone: "review" }, { label: "未知数据", value: "拒绝", detail: "unknown/synthetic 不进入交易链路", tone: "reject" }, { label: "AI 来源", value: "拒绝", detail: "AI 无直接下单权限", tone: "reject" }, { label: "人工审批缺失", value: "拒绝", detail: "审批是默认前置条件", tone: "reject" }]} auditItems={[{ label: "拒绝原因", value: "必须", detail: "返回明确 rejection_reason", tone: "info" }, { label: "调用者", value: "必须", detail: "UNKNOWN_CALLER 必须阻断", tone: "info" }, { label: "重试", value: "受控", detail: "不得绕过安全门禁", tone: "review" }]} note="拒绝记录用于证明安全边界有效，不应被视为可绕过或可自动重试的失败。" />;
}

export function FillsPage() {
  return <TradeStaticPage title="成交回报" subtitle="成交价格、数量、费用、回报时点和订单关联的只读审计" relatedId="orders:fills" tableTitle="成交与费用明细" emptyDescription="成交回报查询接口待接入" columns={[{ title: "成交/订单 ID", dataIndex: "primary", width: 210 }, { title: "订单来源", dataIndex: "source", width: 180 }, { title: "审批编号", dataIndex: "approval", width: 180 }, { title: "数据资格", dataIndex: "dataStatus", width: 170 }, { title: "风控结果", dataIndex: "riskResult", width: 170 }, { title: "Gate 状态", dataIndex: "gateResult", width: 180 }, { title: "幂等键", dataIndex: "idempotencyKey", width: 250 }]} metrics={[{ label: "成交回报", value: "待接入", detail: "不得伪造 simulated fill", tone: "review" }, { label: "佣金", value: "待接入", detail: "每笔单独记录", tone: "review" }, { label: "印花税/过户费", value: "待接入", detail: "依日期规则版本解析", tone: "review" }, { label: "回报完整性", value: "待审核", detail: "需对账订单与成交", tone: "review" }]} auditItems={[{ label: "成交价来源", value: "必须", detail: "无合法价格不得成交", tone: "info" }, { label: "费用明细", value: "必须", detail: "不允许隐含费率", tone: "info" }, { label: "订单关联", value: "必须", detail: "成交必须回溯至订单与审批", tone: "info" }]} note="成交页面不计算或宣称收益；成交、费用和资金变动均需由实际回报与后续对账证实。" />;
}
