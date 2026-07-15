import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface ExcludedRow { key: string; stockCode: string; reason: string; gate: string; evidence: string; reviewStatus: string; }

export default function ResearchExcludedPage() {
  const state = pendingState("研究排除接口待接入", "research-excluded-ui-v1");
  const columns: TableProps<ExcludedRow>["columns"] = [{ title: "股票代码", dataIndex: "stockCode", width: 150 }, { title: "排除原因", dataIndex: "reason", width: 300 }, { title: "阻断门禁", dataIndex: "gate", width: 190 }, { title: "证据", dataIndex: "evidence", width: 260 }, { title: "复核状态", dataIndex: "reviewStatus", width: 150 }];
  return <SectionPage title="排除与阻断" subtitle="无法进入研究或交易链路的标的与明确原因" relatedId="research:excluded" provenance={state.provenance} metrics={[{ label: "数据未认证", value: "待接入", detail: "必须拒绝真实研究", tone: "review" }, { label: "Readiness 阻断", value: "待接入", detail: "授权范围不完整", tone: "review" }, { label: "风控阻断", value: "待接入", detail: "不放宽规则", tone: "review" }, { label: "人工覆盖", value: "禁止", detail: "不得强制放行", tone: "reject" }]} tableTitle="排除明细" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="排除策略" auditItems={[{ label: "unknown 数据", value: "拒绝", detail: "不能因页面展示而放行", tone: "reject" }, { label: "Synthetic 数据", value: "拒绝", detail: "仅 smoke test", tone: "reject" }, { label: "证据缺失", value: "待复核", detail: "无法证明则 fail closed", tone: "review" }]} note="排除不是页面异常：它是研究和交易安全门禁的正常输出。任何排除原因都应可定位到数据、规则、风险或审批证据。" />;
}
