import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface FeeRuleRow { key: string; feeType: string; direction: string; effectiveFrom: string; rate: string; minimum: string; ruleVersion: string; }

export default function FeeRulesPage() {
  const state = pendingState("费用规则注册表接口待接入", "rules-fees-ui-v1");
  const columns: TableProps<FeeRuleRow>["columns"] = [
    { title: "费用类型", dataIndex: "feeType", width: 190 }, { title: "方向", dataIndex: "direction", width: 120 }, { title: "生效日期", dataIndex: "effectiveFrom", width: 170 }, { title: "费率", dataIndex: "rate", width: 150 }, { title: "最低费用", dataIndex: "minimum", width: 160 }, { title: "规则版本", dataIndex: "ruleVersion", width: 190 },
  ];
  return <SectionPage title="费用规则" subtitle="佣金、最低佣金、卖出印花税、过户费与滑点的日期版本化审计" relatedId="rules:fees" provenance={state.provenance} metrics={[{ label: "佣金", value: "待接入", detail: "买卖方向分别计算", tone: "review" }, { label: "印花税", value: "待接入", detail: "适用日期必须可追踪", tone: "review" }, { label: "过户费", value: "已建模", detail: "不得伪装为 0 或未实现", tone: "info" }, { label: "费用 Hash", value: "待接入", detail: "变更必须影响结果血缘", tone: "review" }]} tableTitle="费用版本清单" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="会计一致性" auditItems={[{ label: "买卖区分", value: "必须", detail: "每笔成交单独记录费用明细", tone: "info" }, { label: "最低佣金", value: "必须", detail: "边界情形需参考实现对账", tone: "info" }, { label: "隐含费率", value: "禁止", detail: "未声明配置不能参与计算", tone: "reject" }]} note="费用规则页仅展示版本化会计依据；不对策略收益、交易成本或盈利能力作任何结论。" />;
}
