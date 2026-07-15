import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface StrategyVersionRow { key: string; strategyId: string; version: string; parameterHash: string; approval: string; releaseStatus: string; effectiveRange: string; }

export default function StrategyVersionsPage() {
  const state = pendingState("策略版本审计接口待接入", "strategy-versions-ui-v1");
  const columns: TableProps<StrategyVersionRow>["columns"] = [
    { title: "策略 ID", dataIndex: "strategyId", width: 180 }, { title: "版本", dataIndex: "version", width: 130 }, { title: "参数 Hash", dataIndex: "parameterHash", width: 240 }, { title: "审批状态", dataIndex: "approval", width: 160 }, { title: "发布状态", dataIndex: "releaseStatus", width: 170 }, { title: "生效范围", dataIndex: "effectiveRange", width: 210 },
  ];
  return <SectionPage title="策略版本" subtitle="策略版本、参数、审核、发布锁与可追踪范围" relatedId="strategy:versions" provenance={state.provenance} metrics={[{ label: "已登记版本", value: "待接入", detail: "版本与参数必须有 Hash", tone: "review" }, { label: "人工审批", value: "待接入", detail: "策略变更不得自动上线", tone: "review" }, { label: "公共回测", value: "关闭", detail: "回测发布锁保持关闭", tone: "idle" }, { label: "自动交易", value: "关闭", detail: "策略存在不授予执行权限", tone: "reject" }]} tableTitle="策略版本与审批" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="发布纪律" auditItems={[{ label: "参数变更", value: "需审核", detail: "输入变化必须生成新 Hash", tone: "review" }, { label: "发布权限", value: "关闭", detail: "不得由复盘自动变为线上策略", tone: "reject" }, { label: "可复现性", value: "必须", detail: "同输入应得到同结果", tone: "info" }]} note="此页只记录策略版本与审批状态；不输出收益结论，也不提供策略调参或自动上线操作。" />;
}
