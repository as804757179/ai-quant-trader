import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface NoticeRow { key: string; noticeId: string; stockCode: string; publishedAt: string; source: string; evidenceHash: string; availability: string; }

export default function MarketOfficialPage() {
  const state = pendingState("官方公告证据接口待接入", "market-official-ui-v1");
  const columns: TableProps<NoticeRow>["columns"] = [
    { title: "公告 ID", dataIndex: "noticeId", width: 180 }, { title: "证券代码", dataIndex: "stockCode", width: 150 }, { title: "公告时间", dataIndex: "publishedAt", width: 210 }, { title: "官方来源", dataIndex: "source", width: 200 }, { title: "证据 Hash", dataIndex: "evidenceHash", width: 250 }, { title: "时点状态", dataIndex: "availability", width: 160 },
  ];
  return <SectionPage title="官方公告" subtitle="官方公告、归档证据、可得时间与企业行动关联" relatedId="market:official" provenance={state.provenance} metrics={[{ label: "已归档证据", value: "待接入", detail: "原件与 SHA-256 必须可复算", tone: "review" }, { label: "PIT 可得性", value: "待接入", detail: "公告日前事件不可见", tone: "review" }, { label: "未知来源", value: "拒绝", detail: "不可用作企业行动证据", tone: "reject" }, { label: "修订版本", value: "待接入", detail: "旧版本必须保留", tone: "review" }]} tableTitle="公告证据与时点" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="证据约束" auditItems={[{ label: "来源", value: "官方优先", detail: "使用 CNINFO 或交易所公告", tone: "info" }, { label: "文件哈希", value: "必须校验", detail: "数据库记录必须与原件一致", tone: "info" }, { label: "未来可见", value: "禁止", detail: "不能用后来修订改写过去信号", tone: "reject" }]} note="公告页面是证据索引，不自动产生交易或研究结论；事件日期或比例无法证明时必须保持阻断。" />;
}
