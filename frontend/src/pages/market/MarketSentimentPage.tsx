import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface SentimentRow { key: string; indicator: string; provider: string; cutoff: string; methodology: string; readiness: string; restriction: string; }

export default function MarketSentimentPage() {
  const state = pendingState("市场情绪接口待接入", "market-sentiment-ui-v1");
  const columns: TableProps<SentimentRow>["columns"] = [
    { title: "情绪指标", dataIndex: "indicator", width: 190 }, { title: "Provider", dataIndex: "provider", width: 190 }, { title: "数据截止", dataIndex: "cutoff", width: 210 }, { title: "方法说明", dataIndex: "methodology", width: 240 }, { title: "研究资格", dataIndex: "readiness", width: 160 }, { title: "限制", dataIndex: "restriction", width: 220 },
  ];
  return <SectionPage title="市场情绪" subtitle="情绪指标来源、方法、数据时点与研究使用限制" relatedId="market:sentiment" provenance={state.provenance} metrics={[{ label: "情绪数据源", value: "待接入", detail: "Provider 与方法必须披露", tone: "review" }, { label: "可用时点", value: "待接入", detail: "禁止后验情绪回填", tone: "review" }, { label: "研究权限", value: "待审核", detail: "用途级 Readiness 独立判断", tone: "review" }, { label: "交易指令", value: "禁止", detail: "情绪评分不是订单", tone: "reject" }]} tableTitle="情绪指标资格" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="使用边界" auditItems={[{ label: "方法可解释", value: "必须", detail: "不可把黑箱分数伪装为 Alpha", tone: "info" }, { label: "数据资格", value: "必须", detail: "未认证数据不得进入可信研究", tone: "info" }, { label: "自动执行", value: "关闭", detail: "任何情绪输出都不能直接下单", tone: "reject" }]} note="市场情绪仅作为需要单独验证的研究输入；当前未接入数据时必须显示待接入，而非展示示例信号。" />;
}
