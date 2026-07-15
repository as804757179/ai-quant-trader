import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface ProviderRow { key: string; stockCode: string; tradingDate: string; field: string; difference: string; conclusion: string; }

export default function ProviderValidationPage() {
  const state = pendingState("Provider 验证接口待接入", "provider-validation-ui-v1");
  const columns: TableProps<ProviderRow>["columns"] = [{ title: "股票代码", dataIndex: "stockCode", width: 140 }, { title: "交易日期", dataIndex: "tradingDate", width: 160 }, { title: "差异字段", dataIndex: "field", width: 180 }, { title: "绝对/相对差", dataIndex: "difference", width: 210 }, { title: "审核结论", dataIndex: "conclusion", width: 160 }];
  return <SectionPage title="Provider 验证" subtitle="主 Provider 与第二 Provider 的只读交叉验证" relatedId="data:provider-validation" provenance={state.provenance} metrics={[{ label: "主 Provider", value: "待接入", detail: "导入批次必须固定", tone: "review" }, { label: "第二 Provider", value: "待接入", detail: "只读验证，不写 Certified Store", tone: "review" }, { label: "抽查日期", value: "待接入", detail: "跨完整区间分布", tone: "review" }, { label: "Certified 写入", value: "0", detail: "第二 Provider 不得写入", tone: "pass" }]} tableTitle="字段差异报告" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="验证结论" auditItems={[{ label: "OHLCV", value: "必需", detail: "差异超容差需 review", tone: "info" }, { label: "amount", value: "独立", detail: "证据不足只阻断 Amount Profile", tone: "review" }, { label: "静默 fallback", value: "禁止", detail: "Provider 失败必须记录", tone: "reject" }]} note="第二 Provider 仅用于交叉验证，不能在运行中静默替换主 Provider，也不能写入 Certified Store 或伪造认证结论。" />;
}
