import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface BlockerRow { key: string; stockCode: string; date: string; classification: string; evidence: string; status: string; }

export default function DataBlockersPage() {
  const state = pendingState("阻塞归因接口待接入", "data-blockers-ui-v1");
  const columns: TableProps<BlockerRow>["columns"] = [{ title: "股票代码", dataIndex: "stockCode", width: 140 }, { title: "交易日期", dataIndex: "date", width: 160 }, { title: "归因分类", dataIndex: "classification", width: 180 }, { title: "证据来源", dataIndex: "evidence", width: 270 }, { title: "处理状态", dataIndex: "status", width: 150 }];
  return <SectionPage title="阻塞归因" subtitle="缺失日期、证券状态、Provider 缺失和未决项" relatedId="data:blockers" provenance={state.provenance} metrics={[{ label: "unresolved", value: "待接入", detail: "必须阻止 readiness", tone: "review" }, { label: "停牌", value: "待接入", detail: "不得伪装为 Provider 缺失", tone: "review" }, { label: "非交易日", value: "待接入", detail: "不得 weekday 推测", tone: "review" }, { label: "自动补齐", value: "禁止", detail: "不得补假 K 线", tone: "reject" }]} tableTitle="缺失与阻塞明细" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="归因标准" auditItems={[{ label: "无法证明", value: "unresolved", detail: "保持 fail closed", tone: "reject" }, { label: "停牌证据", value: "必需", detail: "记录来源与有效区间", tone: "info" }, { label: "Provider 缺失", value: "独立", detail: "不与停牌混淆", tone: "info" }]} note="缺失日期必须逐日分类并附带证据、审核版本和时间；不能用上一日价格、零成交量 K 线或主观猜测替代真实归因。" />;
}
