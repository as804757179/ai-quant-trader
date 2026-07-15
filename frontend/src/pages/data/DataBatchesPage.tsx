import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface BatchRow { key: string; batchId: string; provider: string; range: string; accepted: string; status: string; }

export default function DataBatchesPage() {
  const state = pendingState("数据批次查询接口待接入", "data-batches-ui-v1");
  const columns: TableProps<BatchRow>["columns"] = [{ title: "批次 ID", dataIndex: "batchId", width: 220 }, { title: "Provider", dataIndex: "provider", width: 170 }, { title: "日期范围", dataIndex: "range", width: 220 }, { title: "接收/拒绝", dataIndex: "accepted", width: 150 }, { title: "终态", dataIndex: "status", width: 130 }];
  return <SectionPage title="数据批次" subtitle="导入、校验、认证、重试和可恢复检查点" relatedId="data:batches" provenance={state.provenance} metrics={[{ label: "批次总数", value: "待接入", detail: "数据集级运行记录", tone: "review" }, { label: "认证终态", value: "待接入", detail: "certified/rejected/fetch_failed", tone: "review" }, { label: "受控重试", value: "待接入", detail: "必须记录次数与退避", tone: "review" }, { label: "覆盖写入", value: "禁止", detail: "不得覆盖 Certified 原始记录", tone: "reject" }]} tableTitle="批次血缘" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="批次约束" auditItems={[{ label: "幂等执行", value: "必需", detail: "稳定业务键去重", tone: "info" }, { label: "失败记录", value: "必需", detail: "不能静默 fallback", tone: "info" }, { label: "事务回滚", value: "必需", detail: "单批失败不得污染数据", tone: "info" }]} note="每次导入必须可回答 provider、source、period、区间、质量结果和 reject_reason；任何未知来源批次不得被认证。" />;
}
