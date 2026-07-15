import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface CertifiedRow { key: string; stockCode: string; tradingDate: string; adjustment: string; batchId: string; certification: string; }

export default function CertifiedStorePage() {
  const state = pendingState("Certified Store 查询接口待接入", "certified-store-ui-v1");
  const columns: TableProps<CertifiedRow>["columns"] = [
    { title: "股票代码", dataIndex: "stockCode", width: 150 }, { title: "交易日期", dataIndex: "tradingDate", width: 150 }, { title: "复权口径", dataIndex: "adjustment", width: 130 }, { title: "批次 ID", dataIndex: "batchId", width: 220 }, { title: "认证状态", dataIndex: "certification", width: 140 },
  ];
  return <SectionPage title="Certified Store" subtitle="认证历史 K 线、来源、批次和版本血缘" relatedId="data:certified" provenance={state.provenance} metrics={[{ label: "认证行数", value: "待接入", detail: "只读 Certified Store", tone: "review" }, { label: "unknown 写入", value: "0", detail: "必须永久阻断", tone: "pass" }, { label: "synthetic 写入", value: "0", detail: "必须永久阻断", tone: "pass" }, { label: "复权口径", value: "待接入", detail: "raw/qfq/hfq 不得混用", tone: "review" }]} tableTitle="认证 K 线清单" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="准入规则" auditItems={[{ label: "来源明确", value: "必需", detail: "provider/source/batch_id 必须完整", tone: "info" }, { label: "质量状态", value: "必需", detail: "quality_status=pass", tone: "info" }, { label: "认证状态", value: "必需", detail: "certification_status=certified", tone: "info" }]} note="本页仅面向 market.certified_klines。legacy、unknown、synthetic 和 uncertified 数据不得作为可信数据集展示或读取。" />;
}
