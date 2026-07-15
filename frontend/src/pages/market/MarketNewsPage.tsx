import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface NewsRow { key: string; eventId: string; source: string; publishedAt: string; receivedAt: string; verification: string; useStatus: string; }

export default function MarketNewsPage() {
  const state = pendingState("新闻事件接口待接入", "market-news-ui-v1");
  const columns: TableProps<NewsRow>["columns"] = [
    { title: "事件 ID", dataIndex: "eventId", width: 210 }, { title: "来源", dataIndex: "source", width: 210 }, { title: "发布时间", dataIndex: "publishedAt", width: 210 }, { title: "接收时间", dataIndex: "receivedAt", width: 210 }, { title: "验证状态", dataIndex: "verification", width: 160 }, { title: "用途状态", dataIndex: "useStatus", width: 170 },
  ];
  return <SectionPage title="新闻与事件" subtitle="新闻来源、发布与接收时点、核验状态和研究用途" relatedId="market:news" provenance={state.provenance} metrics={[{ label: "已接收事件", value: "待接入", detail: "不显示虚构新闻", tone: "review" }, { label: "时点完整性", value: "待接入", detail: "需区分 published_at 与 received_at", tone: "review" }, { label: "研究可用", value: "待审核", detail: "不能把文本直接转为订单", tone: "review" }, { label: "AI 下单", value: "关闭", detail: "AI 仅用于说明与审核", tone: "reject" }]} tableTitle="新闻事件审计" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="时点与安全" auditItems={[{ label: "未来信息", value: "禁止", detail: "只使用当时已公开且已接收的内容", tone: "reject" }, { label: "来源质量", value: "待审核", detail: "必须记录 Provider 和版本", tone: "review" }, { label: "订单创建", value: "禁止", detail: "新闻分析不调用 TradeSubmitter", tone: "reject" }]} note="新闻信息可被研究层引用，但必须保留来源和可得时点；当前页面不将新闻或情绪包装为可交易信号。" />;
}
