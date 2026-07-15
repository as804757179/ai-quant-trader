import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface TradingRuleRow { key: string; ruleType: string; exchange: string; effectiveFrom: string; effectiveTo: string; ruleVersion: string; source: string; }

export default function TradingRulesPage() {
  const state = pendingState("A股交易规则注册表接口待接入", "rules-trading-ui-v1");
  const columns: TableProps<TradingRuleRow>["columns"] = [
    { title: "规则类型", dataIndex: "ruleType", width: 190 }, { title: "交易所", dataIndex: "exchange", width: 140 }, { title: "生效日期", dataIndex: "effectiveFrom", width: 160 }, { title: "失效日期", dataIndex: "effectiveTo", width: 160 }, { title: "规则版本", dataIndex: "ruleVersion", width: 180 }, { title: "官方依据", dataIndex: "source", width: 260 },
  ];
  return <SectionPage title="交易规则" subtitle="A股 T+1、买入整手、卖出零股、停牌与涨跌停的按日版本规则" relatedId="rules:trading" provenance={state.provenance} metrics={[{ label: "买入整手", value: "100 股", detail: "按证券及规则版本解析", tone: "info" }, { label: "卖出零股", value: "受规则约束", detail: "零股只能一次性清仓", tone: "info" }, { label: "T+1", value: "按日解析", detail: "可用持仓与总持仓分离", tone: "info" }, { label: "未知规则", value: "失败关闭", detail: "不可猜测为主板 10%", tone: "reject" }]} tableTitle="市场规则版本" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="规则安全" auditItems={[{ label: "官方依据", value: "必须", detail: "不得使用非官方来源猜测规则", tone: "info" }, { label: "按日期解析", value: "必须", detail: "不能只读取当前配置", tone: "info" }, { label: "未知状态", value: "拒绝", detail: "需要规则时 fail closed", tone: "reject" }]} note="规则注册表是只读审计视图；当前并不开放公共回测、选股或任何交易执行权限。" />;
}
