import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import type { SectionMetric } from "../shared/SectionPage";
import SectionPage from "../shared/SectionPage";

interface ReviewRow { key: string; primary: string; asOf: string; hindsight: string; evidence: string; approval: string; status: string; }

interface ReviewPageDefinition {
  title: string;
  subtitle: string;
  relatedId: string;
  tableTitle: string;
  emptyDescription: string;
  metrics: readonly SectionMetric[];
  columns: TableProps<ReviewRow>["columns"];
  auditItems: readonly { label: string; value: string; detail: string; tone: "pass" | "idle" | "review" | "reject" | "info" }[];
  note: string;
}

function ReviewStaticPage(definition: ReviewPageDefinition) {
  const state = pendingState(definition.emptyDescription, `${definition.relatedId}-ui-v1`);
  return <SectionPage title={definition.title} subtitle={definition.subtitle} relatedId={definition.relatedId} provenance={state.provenance} metrics={definition.metrics} tableTitle={definition.tableTitle} columns={definition.columns} rowKey="key" emptyDescription={state.message} auditTitle="复盘安全边界" auditItems={definition.auditItems} note={definition.note} />;
}

const reviewColumns: TableProps<ReviewRow>["columns"] = [
  { title: "复盘对象 ID", dataIndex: "primary", width: 210 }, { title: "当时可得信息", dataIndex: "asOf", width: 240 }, { title: "事后结果", dataIndex: "hindsight", width: 220 }, { title: "证据/血缘", dataIndex: "evidence", width: 240 }, { title: "审批编号", dataIndex: "approval", width: 180 }, { title: "状态", dataIndex: "status", width: 150 },
];

export function DailyReviewPage() {
  return <ReviewStaticPage title="每日复盘" subtitle="当时可得信息、事后结果、异常与改进事项的明确分层" relatedId="review:daily" tableTitle="每日复盘记录" emptyDescription="每日复盘接口待接入" columns={reviewColumns} metrics={[{ label: "复盘业务日", value: "待接入", detail: "必须有业务日期", tone: "review" }, { label: "当时信息", value: "待接入", detail: "与事后结果严格分离", tone: "review" }, { label: "异常事项", value: "待接入", detail: "需关联风险和系统事件", tone: "review" }, { label: "自动上线", value: "禁止", detail: "复盘不会改变策略发布状态", tone: "reject" }]} auditItems={[{ label: "信息边界", value: "必须", detail: "复盘不能回写当时决策输入", tone: "info" }, { label: "策略变更", value: "需审批", detail: "不得自动上线", tone: "review" }, { label: "交易执行", value: "关闭", detail: "复盘页面无下单能力", tone: "reject" }]} note="每日复盘用于改进流程，不把后验结果当作当时已知信息，也不自动修改策略或交易权限。" />;
}

export function TradeReviewPage() {
  return <ReviewStaticPage title="交易复盘" subtitle="订单、成交、费用、T+1、微观规则和账务对账的逐笔复核" relatedId="review:trades" tableTitle="交易复盘明细" emptyDescription="交易复盘接口待接入" columns={reviewColumns} metrics={[{ label: "待复核交易", value: "待接入", detail: "订单与成交必须关联", tone: "review" }, { label: "费用一致性", value: "待接入", detail: "对照费用规则版本", tone: "review" }, { label: "会计差异", value: "待接入", detail: "Engine 与 Reference 需对账", tone: "review" }, { label: "自动修复", value: "禁止", detail: "复核不得改写历史账务", tone: "reject" }]} auditItems={[{ label: "执行时序", value: "必须", detail: "信号与成交至少隔至下一交易日", tone: "info" }, { label: "交易规则", value: "按日解析", detail: "T+1、整手、零股、涨跌停可追踪", tone: "info" }, { label: "订单重放", value: "禁止", detail: "复盘不重新发单", tone: "reject" }]} note="交易复盘只读呈现既有审计轨迹；它不执行交易，也不以复盘结论自动调参。" />;
}

export function MissedOpportunitiesPage() {
  return <ReviewStaticPage title="错失机会" subtitle="事后观察的机会记录、排除理由与误差归因，非实时交易信号" relatedId="review:missed" tableTitle="事后机会复核" emptyDescription="错失机会复核接口待接入" columns={reviewColumns} metrics={[{ label: "事后记录", value: "待接入", detail: "必须显著标识 hindsight", tone: "review" }, { label: "原始排除", value: "待接入", detail: "保留当时规则与数据状态", tone: "review" }, { label: "研究结论", value: "待审核", detail: "不可直接更改阈值", tone: "review" }, { label: "自动交易", value: "禁止", detail: "事后机会不能触发订单", tone: "reject" }]} auditItems={[{ label: "后验标签", value: "必须", detail: "不可混入实时候选", tone: "info" }, { label: "排除依据", value: "保留", detail: "包含数据、风险与资格状态", tone: "info" }, { label: "策略上线", value: "禁止", detail: "需独立版本、测试与审批", tone: "reject" }]} note="错失机会页只用于审计和研究改进，永不作为实时交易触发器或盈利证明。" />;
}

export function ReviewCandidatesPage() {
  return <ReviewStaticPage title="候选复核" subtitle="研究候选的进入、排除、失效与人工复核轨迹" relatedId="review:candidates" tableTitle="候选复核生命周期" emptyDescription="候选复核接口待接入" columns={reviewColumns} metrics={[{ label: "候选记录", value: "待接入", detail: "研究候选不等于投资建议", tone: "review" }, { label: "排除原因", value: "待接入", detail: "数据、风险和资格原因必须保留", tone: "review" }, { label: "人工复核", value: "待接入", detail: "需要审批 ID 与时间", tone: "review" }, { label: "Screener 发布", value: "关闭", detail: "不输出真实候选", tone: "reject" }]} auditItems={[{ label: "Readiness", value: "必须", detail: "Profile 权限不可传播", tone: "info" }, { label: "数据来源", value: "必须", detail: "unknown/synthetic 不能进入可信候选", tone: "info" }, { label: "订单创建", value: "禁止", detail: "候选不调用下单接口", tone: "reject" }]} note="候选复核页将候选、排除、待复核和不可交易状态分开显示；不会发布选股结果。" />;
}

export function ShadowRunPage() {
  return <ReviewStaticPage title="影子运行" subtitle="不发布、不下单的策略观察结果、输入版本和对账状态" relatedId="review:shadow" tableTitle="影子运行记录" emptyDescription="影子运行接口待接入" columns={reviewColumns} metrics={[{ label: "影子批次", value: "待接入", detail: "需有独立 run_id", tone: "review" }, { label: "输入血缘", value: "待接入", detail: "数据、规则与参数可追踪", tone: "review" }, { label: "结果 Hash", value: "待接入", detail: "相同输入可复现", tone: "review" }, { label: "交易执行", value: "关闭", detail: "影子运行永不下单", tone: "reject" }]} auditItems={[{ label: "发布隔离", value: "必须", detail: "不能进入公共 Backtest 或 Screener 输出", tone: "info" }, { label: "执行隔离", value: "必须", detail: "不能创建 paper 或 live order", tone: "info" }, { label: "结果解释", value: "非盈利结论", detail: "样本与状态必须披露", tone: "review" }]} note="影子运行是隔离验证，不会开放回测发布、选股、模拟自动交易或实盘权限。" />;
}

export function ReviewApprovalPage() {
  return <ReviewStaticPage title="策略变更审批" subtitle="策略、参数、规则或模型修改的审批、回滚和生效边界" relatedId="review:approval" tableTitle="变更审批与回滚" emptyDescription="策略变更审批接口待接入" columns={reviewColumns} metrics={[{ label: "待审批变更", value: "待接入", detail: "必须记录变更原因", tone: "review" }, { label: "回滚方案", value: "待接入", detail: "长期安全变更需明确回滚", tone: "review" }, { label: "测试证据", value: "待接入", detail: "不以手工结论替代", tone: "review" }, { label: "自动生效", value: "禁止", detail: "策略变更不得自动上线", tone: "reject" }]} auditItems={[{ label: "版本关联", value: "必须", detail: "记录 strategy、parameter 与 rule Hash", tone: "info" }, { label: "验证范围", value: "必须", detail: "说明数据、样本与已知限制", tone: "info" }, { label: "发布权限", value: "关闭", detail: "变更审批不解锁交易或回测", tone: "reject" }]} note="变更审批页记录准入过程；任何策略、模型或规则变更均不得因复盘记录而自动上线。" />;
}
