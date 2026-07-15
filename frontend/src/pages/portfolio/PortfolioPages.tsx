import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import type { SectionMetric } from "../shared/SectionPage";
import SectionPage from "../shared/SectionPage";

interface PortfolioRow { key: string; primary: string; total: string; available: string; realized: string; unrealized: string; fees: string; reconciliation: string; }

interface PortfolioPageDefinition {
  title: string;
  subtitle: string;
  relatedId: string;
  tableTitle: string;
  emptyDescription: string;
  metrics: readonly SectionMetric[];
  columns: TableProps<PortfolioRow>["columns"];
  auditItems: readonly { label: string; value: string; detail: string; tone: "pass" | "idle" | "review" | "reject" | "info" }[];
  note: string;
}

function PortfolioStaticPage(definition: PortfolioPageDefinition) {
  const state = pendingState(definition.emptyDescription, `${definition.relatedId}-ui-v1`);
  return <SectionPage title={definition.title} subtitle={definition.subtitle} relatedId={definition.relatedId} provenance={state.provenance} metrics={definition.metrics} tableTitle={definition.tableTitle} columns={definition.columns} rowKey="key" emptyDescription={state.message} auditTitle="账务与数据边界" auditItems={definition.auditItems} note={definition.note} />;
}

const accountColumns: TableProps<PortfolioRow>["columns"] = [
  { title: "账户/账本 ID", dataIndex: "primary", width: 210 }, { title: "总资产", dataIndex: "total", width: 180 }, { title: "可用现金", dataIndex: "available", width: 180 }, { title: "已实现盈亏", dataIndex: "realized", width: 180 }, { title: "未实现盈亏", dataIndex: "unrealized", width: 180 }, { title: "费用", dataIndex: "fees", width: 150 }, { title: "对账状态", dataIndex: "reconciliation", width: 180 },
];

export function AccountPage() {
  return <PortfolioStaticPage title="账户总览" subtitle="模拟账户资产、可用现金、已实现与未实现盈亏的分离展示" relatedId="portfolio:account" tableTitle="账户账务快照" emptyDescription="账户总览接口待接入" columns={accountColumns} metrics={[{ label: "总资产", value: "待接入", detail: "不可展示伪造资金", tone: "review" }, { label: "可用现金", value: "待接入", detail: "需与冻结资金分离", tone: "review" }, { label: "已实现盈亏", value: "待接入", detail: "仅由已完成交易产生", tone: "review" }, { label: "对账差异", value: "待接入", detail: "必须可追踪", tone: "review" }]} auditItems={[{ label: "资金模式", value: "Simulation", detail: "不连接真实账户资金", tone: "info" }, { label: "账务时间", value: "必须", detail: "显示 Asia/Shanghai 精确时间", tone: "info" }, { label: "执行权限", value: "关闭", detail: "账户可见不等于允许交易", tone: "reject" }]} note="账户页作为账务审计入口，交易、资金和收益字段未接入时必须保持待接入状态。" />;
}

export function PositionsPage() {
  return <PortfolioStaticPage title="持仓与可用" subtitle="总持仓、可用持仓、成本、T+1 与零股状态" relatedId="portfolio:positions" tableTitle="持仓可用性明细" emptyDescription="持仓查询接口待接入" columns={[{ title: "证券代码", dataIndex: "primary", width: 160 }, { title: "总持仓", dataIndex: "total", width: 150 }, { title: "可用持仓", dataIndex: "available", width: 160 }, { title: "已实现盈亏", dataIndex: "realized", width: 180 }, { title: "未实现盈亏", dataIndex: "unrealized", width: 180 }, { title: "费用", dataIndex: "fees", width: 150 }, { title: "对账状态", dataIndex: "reconciliation", width: 180 }]} metrics={[{ label: "持仓标的", value: "待接入", detail: "从订单回报和账务快照对账", tone: "review" }, { label: "可用持仓", value: "待接入", detail: "T+1 规则独立管理", tone: "review" }, { label: "零股余额", value: "待接入", detail: "只允许一次性卖出", tone: "review" }, { label: "超过持仓卖出", value: "拒绝", detail: "不得创建超卖订单", tone: "reject" }]} auditItems={[{ label: "总量与可用", value: "分离", detail: "买入当日可用数量需遵循 T+1", tone: "info" }, { label: "零股政策", value: "受控", detail: "禁止拆分零股卖出", tone: "info" }, { label: "成本口径", value: "待接入", detail: "需要多笔会计基线对账", tone: "review" }]} note="持仓页面不会用研究 K 线或页面演示数据替代实际订单、成交和账务记录。" />;
}

export function TodayPnlPage() {
  return <PortfolioStaticPage title="当日盈亏" subtitle="已实现、未实现、费用、现金事件和对账差异的当日拆分" relatedId="portfolio:pnl-today" tableTitle="当日盈亏构成" emptyDescription="当日盈亏接口待接入" columns={accountColumns} metrics={[{ label: "已实现盈亏", value: "待接入", detail: "与交易收益分离", tone: "review" }, { label: "未实现盈亏", value: "待接入", detail: "由有效估值产生", tone: "review" }, { label: "交易费用", value: "待接入", detail: "佣金、印花税、过户费分列", tone: "review" }, { label: "现金事件", value: "待接入", detail: "企业行动现金独立记录", tone: "review" }]} auditItems={[{ label: "企业行动收入", value: "独立科目", detail: "不伪装为交易 realized_pnl", tone: "info" }, { label: "估值价格", value: "待授权", detail: "Execution Reference 未授权", tone: "review" }, { label: "净税后收益", value: "阻断", detail: "当前不支持红利税处理", tone: "reject" }]} note="当日盈亏是账务拆分，不是策略评价；页面不会输出收益率、胜率或投资结论。" />;
}

export function AttributionPage() {
  return <PortfolioStaticPage title="盈亏归因" subtitle="交易、持仓、费用、现金事件与对账差异的证据链归因" relatedId="portfolio:attribution" tableTitle="盈亏归因证据" emptyDescription="盈亏归因接口待接入" columns={[{ title: "归因维度", dataIndex: "primary", width: 210 }, { title: "金额/数量", dataIndex: "total", width: 190 }, { title: "可用性", dataIndex: "available", width: 170 }, { title: "已实现", dataIndex: "realized", width: 170 }, { title: "未实现", dataIndex: "unrealized", width: 170 }, { title: "费用", dataIndex: "fees", width: 150 }, { title: "对账", dataIndex: "reconciliation", width: 170 }]} metrics={[{ label: "交易归因", value: "待接入", detail: "需关联订单与成交", tone: "review" }, { label: "费用归因", value: "待接入", detail: "需关联费用规则版本", tone: "review" }, { label: "现金事件", value: "待接入", detail: "企业行动按 PIT 入账", tone: "review" }, { label: "差异解释", value: "待接入", detail: "不得隐藏对账差异", tone: "review" }]} auditItems={[{ label: "数据血缘", value: "必须", detail: "关联 batch、规则、订单与账务事件", tone: "info" }, { label: "事后解释", value: "标识", detail: "不能混入当时可得决策信息", tone: "info" }, { label: "盈利结论", value: "不输出", detail: "归因不证明策略有效", tone: "reject" }]} note="归因页面只解释账务结构，所有归因均需有可回溯的订单、事件或规则证据。" />;
}

export function EquityPage() {
  return <PortfolioStaticPage title="资产曲线" subtitle="资产净值、数据截止时间、估值来源和计算版本的只读曲线审计" relatedId="portfolio:equity" tableTitle="资产快照与血缘" emptyDescription="资产曲线接口待接入" columns={[{ title: "估值时点", dataIndex: "primary", width: 210 }, { title: "总资产", dataIndex: "total", width: 180 }, { title: "可用现金", dataIndex: "available", width: 180 }, { title: "已实现", dataIndex: "realized", width: 170 }, { title: "未实现", dataIndex: "unrealized", width: 170 }, { title: "费用", dataIndex: "fees", width: 150 }, { title: "对账", dataIndex: "reconciliation", width: 170 }]} metrics={[{ label: "净值点", value: "待接入", detail: "需要稳定时序数据", tone: "review" }, { label: "估值来源", value: "待接入", detail: "显示来源、时点与适用性", tone: "review" }, { label: "曲线 Hash", value: "待接入", detail: "相同输入应可复现", tone: "review" }, { label: "策略评价", value: "不输出", detail: "曲线不是盈利承诺", tone: "reject" }]} auditItems={[{ label: "资产来源", value: "必须", detail: "账务、价格与现金事件可追踪", tone: "info" }, { label: "估值资格", value: "待授权", detail: "不可把未授权 K 线用作执行估值", tone: "review" }, { label: "时间语义", value: "必须", detail: "统一 UTC+8 格式", tone: "info" }]} note="资产曲线会在接入后展示真实账务快照；当前不显示原型或随机曲线。" />;
}

export function SettlementPage() {
  return <PortfolioStaticPage title="日终清算" subtitle="日终账务、费用、现金事件、持仓可用性与异常处理审计" relatedId="portfolio:settlement" tableTitle="日终清算阶段" emptyDescription="日终清算接口待接入" columns={accountColumns} metrics={[{ label: "清算批次", value: "待接入", detail: "需记录业务日期与批次 ID", tone: "review" }, { label: "费用入账", value: "待接入", detail: "按成交和规则版本核算", tone: "review" }, { label: "现金事件", value: "待接入", detail: "支付日期不可提前入账", tone: "review" }, { label: "清算异常", value: "待接入", detail: "失败不得静默忽略", tone: "review" }]} auditItems={[{ label: "日终顺序", value: "明确", detail: "订单、账务与审计需有确定顺序", tone: "info" }, { label: "回滚策略", value: "必须", detail: "异常不能污染正式账务", tone: "info" }, { label: "自动发布", value: "关闭", detail: "清算完成不等于开放交易", tone: "reject" }]} note="日终清算页不会执行清算命令；它仅展示已完成批次和异常的可审计状态。" />;
}

export function ReconciliationPage() {
  return <PortfolioStaticPage title="资金对账" subtitle="现金、持仓、成交、企业行动与账务差异的逐项对账" relatedId="portfolio:reconciliation" tableTitle="对账差异明细" emptyDescription="资金对账接口待接入" columns={[{ title: "对账项目", dataIndex: "primary", width: 240 }, { title: "账务值", dataIndex: "total", width: 170 }, { title: "外部/来源值", dataIndex: "available", width: 190 }, { title: "已实现", dataIndex: "realized", width: 160 }, { title: "未实现", dataIndex: "unrealized", width: 160 }, { title: "费用", dataIndex: "fees", width: 150 }, { title: "差异状态", dataIndex: "reconciliation", width: 180 }]} metrics={[{ label: "现金差异", value: "待接入", detail: "必须单独显示", tone: "review" }, { label: "持仓差异", value: "待接入", detail: "总量与可用量分别对账", tone: "review" }, { label: "成交差异", value: "待接入", detail: "关联订单与成交回报", tone: "review" }, { label: "未解释差异", value: "阻断", detail: "不应被隐藏或平滑", tone: "reject" }]} auditItems={[{ label: "对账时间", value: "必须", detail: "记录业务日期和完成时间", tone: "info" }, { label: "差异原因", value: "必须", detail: "保留调查与处理状态", tone: "info" }, { label: "自动纠正", value: "禁止", detail: "不得悄然修改账务记录", tone: "reject" }]} note="对账视图用于暴露差异；没有证据的差异必须保持未解决状态，而不是以演示数据填平。" />;
}
