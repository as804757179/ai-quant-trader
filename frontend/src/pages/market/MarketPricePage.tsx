import type { TableProps } from "antd";
import { useState } from "react";
import { formatCurrency, type ObservedQuoteListData, useObservedQuotes } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import SectionPage from "../shared/SectionPage";

interface PriceRow { key: string; stockCode: string; quoteTime: string; price: string; priceSource: string; bidAskStatus: string; dataStatus: string; batchHash: string; }

export default function MarketPricePage() {
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(50); const state = useObservedQuotes(page, pageSize); const total = state.data?.total;
  const known = (state.kind === "live" || state.kind === "empty") && typeof total === "number";
  const rows: PriceRow[] = (state.data?.items ?? []).map((item: NonNullable<ObservedQuoteListData["items"]>[number], index) => ({ key: `${item.stock_code ?? index}-${item.quote_time ?? index}`, stockCode: item.stock_code ?? "未记录", quoteTime: formatChinaDateTime(item.quote_time), price: formatCurrency(item.price ?? undefined), priceSource: [item.provider, item.source, item.fetch_endpoint].filter(Boolean).join(" · ") || "未记录", bidAskStatus: item.order_book_status ?? "未记录", dataStatus: `${item.quality_status ?? "未记录"} · ${item.freshness_status ?? "未记录"}`, batchHash: `${item.batch_id ?? "未记录"} · ${item.raw_hash ?? "未记录"}` }));
  const bookCount = rows.filter((item) => item.bidAskStatus === "level_1_recorded").length;
  const columns: TableProps<PriceRow>["columns"] = [
    { title: "证券代码", dataIndex: "stockCode", width: 150 }, { title: "报价时间", dataIndex: "quoteTime", width: 210 }, { title: "最新价", dataIndex: "price", width: 140 }, { title: "价格来源", dataIndex: "priceSource", width: 260 }, { title: "盘口状态", dataIndex: "bidAskStatus", width: 180 }, { title: "数据资格", dataIndex: "dataStatus", width: 170 }, { title: "批次 / Hash", dataIndex: "batchHash", width: 330 },
  ];
  return <SectionPage title="价格与盘口" subtitle="已观察报价、已记录盘口层级与完整 provenance" relatedId="market:price" provenance={{ ...state.provenance, sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion }} metadataStatusText="只读观察 · 服务端分页 · 每证券最新已观察报价 · 不作全市场覆盖声明" statusLabel={known ? "已接入（只读）" : state.message} statusTone={known ? "info" : "review"} metrics={[{ label: "已观察报价", value: known ? total : "状态未知", detail: known ? `本页 ${rows.length} 条；仅 provenance 质量通过记录` : "接口不可用时不将其视为 0", tone: known ? "info" : "review" }, { label: "已记录一级盘口", value: known ? bookCount : "状态未知", detail: "仅统计本页 bid1/ask1 同时存在记录", tone: "review" }, { label: "执行参考", value: "未授权", detail: "报价展示不授予 Execution Reference", tone: "reject" }, { label: "回退数据", value: "不纳入", detail: "仅返回 fallback_used=false 的观测记录", tone: "info" }]} tableTitle="报价与盘口审计（服务端分页）" columns={columns} tableData={rows} tablePagination={known ? { current: state.data?.page ?? page, pageSize: state.data?.page_size ?? pageSize, total, onChange: (nextPage, nextPageSize) => { setPage(nextPageSize === pageSize ? nextPage : 1); setPageSize(nextPageSize); } } : undefined} tableSearchEnabled={false} rowKey="key" emptyDescription={state.message} auditTitle="执行边界" auditItems={[{ label: "价格适用性", value: "未授权", detail: "研究观察不能自动成为执行价格", tone: "reject" }, { label: "盘口层级", value: "按记录展示", detail: "缺少层级不推断为五档盘口", tone: "review" }, { label: "无有效价格", value: "拒绝成交", detail: "不得以上一日或合成价格替代", tone: "reject" }]} note="本页只展示每证券最新的已观察报价；它不产生价格指令，也不为 Simulation 或 Live 交易授予执行参考数据权限。" />;
}
