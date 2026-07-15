import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface QualityRow { key: string; rule: string; scope: string; result: string; rejectReason: string; }

export default function DataQualityPage() {
  const state = pendingState("数据质量报告接口待接入", "data-quality-ui-v1");
  const columns: TableProps<QualityRow>["columns"] = [{ title: "质量规则", dataIndex: "rule", width: 230 }, { title: "审核范围", dataIndex: "scope", width: 220 }, { title: "结果", dataIndex: "result", width: 130 }, { title: "拒绝原因", dataIndex: "rejectReason", width: 330 }];
  return <SectionPage title="数据质量" subtitle="字段、OHLC、单位、时间戳、重复与异常值验证" relatedId="data:quality" provenance={state.provenance} metrics={[{ label: "重复率", value: "待接入", detail: "同股票同日不得重复", tone: "review" }, { label: "缺失率", value: "待接入", detail: "必需字段不可缺失", tone: "review" }, { label: "异常价格", value: "待接入", detail: "OHLC 合法性", tone: "review" }, { label: "时间规范", value: "待接入", detail: "日线 15:00 Asia/Shanghai", tone: "review" }]} tableTitle="质量规则结果" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="强制拒绝项" auditItems={[{ label: "Synthetic", value: "拒绝", detail: "只能用于 smoke test", tone: "reject" }, { label: "Unknown source", value: "拒绝", detail: "来源缺失不得认证", tone: "reject" }, { label: "同日重复", value: "拒绝", detail: "对应数据不得 certified", tone: "reject" }]} note="质量结果必须与批次、raw_hash 和标准化版本关联。数据异常只能标记、隔离和拒绝，不能通过平滑或补值伪修复。" />;
}
