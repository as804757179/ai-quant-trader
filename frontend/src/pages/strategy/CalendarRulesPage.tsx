import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import SectionPage from "../shared/SectionPage";

interface CalendarRow { key: string; tradeDate: string; exchange: string; calendarStatus: string; source: string; version: string; coverage: string; }

export default function CalendarRulesPage() {
  const state = pendingState("认证交易日历接口待接入", "rules-calendar-ui-v1");
  const columns: TableProps<CalendarRow>["columns"] = [
    { title: "日期", dataIndex: "tradeDate", width: 170 }, { title: "交易所", dataIndex: "exchange", width: 140 }, { title: "日历状态", dataIndex: "calendarStatus", width: 180 }, { title: "来源", dataIndex: "source", width: 240 }, { title: "版本", dataIndex: "version", width: 170 }, { title: "覆盖范围", dataIndex: "coverage", width: 190 },
  ];
  return <SectionPage title="认证交易日历" subtitle="沪深交易日历来源、版本、覆盖区间与失败关闭状态" relatedId="rules:calendar" provenance={state.provenance} metrics={[{ label: "认证日历", value: "待接入", detail: "可信回测只读取认证日历", tone: "review" }, { label: "weekday fallback", value: "禁止", detail: "周末、节假日与临时休市不能猜测", tone: "reject" }, { label: "覆盖区间", value: "待接入", detail: "无覆盖时必须拒绝", tone: "review" }, { label: "Fixture 日历", value: "仅测试", detail: "不得进入可信回测入口", tone: "idle" }]} tableTitle="日历覆盖与版本" columns={columns} rowKey="key" emptyDescription={state.message} auditTitle="日历门禁" auditItems={[{ label: "非交易日", value: "拒绝数据", detail: "不补假 K 线", tone: "reject" }, { label: "日历缺失", value: "失败关闭", detail: "不能由 weekday 推断", tone: "reject" }, { label: "来源版本", value: "必须", detail: "需进入数据和结果血缘", tone: "info" }]} note="日历规则为回测、研究和状态审核提供时点边界；此页只读，不解锁任何业务发布能力。" />;
}
