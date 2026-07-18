import { useState } from "react";
import type { TableProps } from "antd";
import type { DataProvenance, StatusTone } from "../../presentation/contracts";
import {
  type MarketQuoteBatchData,
  useMarketQuoteBatches,
  useMarketStatus,
} from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import SectionPage from "../shared/SectionPage";

interface MarketSourceRow {
  key: string;
  provider: string;
  endpoint: string;
  dataTime: string;
  delay: string;
  fallback: string;
  status: string;
}

function batchTone(status: string | undefined): StatusTone {
  if (status === "success") return "pass";
  if (status === "partial") return "review";
  if (status === "running") return "info";
  if (status === "fetch_failed" || status === "validation_failed" || status === "write_failed") return "reject";
  return "review";
}

function formatDelay(seconds: number | null | undefined): string {
  if (typeof seconds !== "number") return "无行情记录";
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分钟`;
}

function fallbackLabel(value: boolean | null | undefined): string {
  if (value === false) return "未使用";
  if (value === true) return "已使用";
  return "未记录";
}

function toRow(batch: MarketQuoteBatchData, lagSeconds: number | null | undefined): MarketSourceRow {
  return {
    key: batch.batch_id ?? `${batch.provider}-${batch.received_at}`,
    provider: batch.provider ?? "未记录",
    endpoint: batch.fetch_endpoint ?? "未记录",
    dataTime: formatChinaDateTime(batch.received_at),
    delay: formatDelay(lagSeconds),
    fallback: fallbackLabel(batch.fallback_used),
    status: batch.status ?? "未记录",
  };
}

export default function MarketLivePage() {
  const [batchPage, setBatchPage] = useState(1);
  const [batchPageSize, setBatchPageSize] = useState(20);
  const market = useMarketStatus();
  const batches = useMarketQuoteBatches(batchPage, batchPageSize);
  const marketKnown = market.kind === "live" && Boolean(market.data);
  const batchesKnown = (batches.kind === "live" || batches.kind === "empty") && Boolean(batches.data);
  const latestBatch = marketKnown ? market.data?.latest_batch : undefined;
  const latestDisplayedBatch = batches.data?.items?.[0];
  const observedLatestBatch = latestBatch ?? latestDisplayedBatch;
  const rows = (batches.data?.items ?? []).map((batch) => toRow(batch, marketKnown ? market.data?.lag_seconds : undefined));
  const batchTotal = batchesKnown && typeof batches.data?.total === "number" ? batches.data.total : undefined;
  const returnedPage = batches.data?.page ?? batchPage;
  const returnedPageSize = batches.data?.page_size ?? batchPageSize;
  const batchWindow = batchTotal === undefined ? "状态未知" : `${rows.length}/${batchTotal}`;
  const batchWindowDetail = !batchesKnown
    ? "批次接口状态未知"
    : `第 ${returnedPage} 页，每页 ${returnedPageSize} 条${batches.data?.has_more ? "；可继续翻页" : "；已到末页"}`;
  const marketCoverage = marketKnown
    && typeof market.data?.recent_symbol_count === "number"
    && typeof market.data?.active_stock_count === "number"
    ? `${market.data.recent_symbol_count}/${market.data.active_stock_count}`
    : "状态未知";
  const latestBatchStatus = observedLatestBatch?.status;
  const latestBatchDetail = observedLatestBatch
    ? `接收 ${observedLatestBatch.accepted_symbols ?? "未记录"}，拒绝 ${observedLatestBatch.rejected_symbols ?? "未记录"}`
    : batchesKnown
      ? "尚未产生批次"
      : "批次接口状态未知";
  const handleBatchPageChange = (nextPage: number, nextPageSize: number) => {
    setBatchPage(nextPageSize === batchPageSize ? nextPage : 1);
    setBatchPageSize(nextPageSize);
  };
  const provenance: DataProvenance = {
    ...market.provenance,
    dataCutoff: formatChinaDateTime(market.data?.latest_quote_at ?? observedLatestBatch?.received_at),
    sourceVersion: batches.data?.source_version ?? market.data?.source_version ?? market.provenance.sourceVersion,
    traceId: observedLatestBatch?.batch_id ?? market.provenance.traceId,
  };
  const sourceStatus = !marketKnown ? "状态未知" : market.data?.provider_metadata_status === "recorded" ? "已记录" : "未记录";
  const pageTone = marketKnown ? batchTone(latestBatchStatus) : "review";
  const columns: TableProps<MarketSourceRow>["columns"] = [
    { title: "Provider", dataIndex: "provider", width: 150 },
    { title: "Endpoint", dataIndex: "endpoint", width: 260 },
    { title: "数据时间", dataIndex: "dataTime", width: 210 },
    { title: "延迟", dataIndex: "delay", width: 120 },
    { title: "Fallback 记录", dataIndex: "fallback", width: 150 },
    { title: "批次状态", dataIndex: "status", width: 150 },
  ];

  return (
    <SectionPage
      title="全市场行情"
      subtitle="当前配置股票池的固定 Provider 行情批次、时效与血缘状态"
      relatedId={observedLatestBatch?.batch_id ? `quote_batch:${observedLatestBatch.batch_id}` : "market:live"}
      provenance={provenance}
      statusLabel={market.kind === "live" ? `行情 ${market.data?.status ?? "已接入"}` : market.message}
      statusTone={pageTone}
      metrics={[
        {
          label: "主行情源",
          value: marketKnown ? market.data?.provider ?? "未记录" : "状态未知",
          detail: `元数据：${sourceStatus}`,
          tone: marketKnown && market.data?.provider ? "pass" : "review",
        },
        {
          label: "最新延迟",
          value: marketKnown ? formatDelay(market.data?.lag_seconds) : "状态未知",
          detail: `阈值 ${marketKnown ? market.data?.freshness_threshold_seconds ?? "未记录" : "状态未知"} 秒`,
          tone: marketKnown && market.data?.status === "fresh" ? "pass" : "review",
        },
        {
          label: "当前覆盖",
          value: marketCoverage,
          detail: "仅为当前配置同步范围，不等于全市场覆盖",
          tone: market.kind === "live" ? "info" : "review",
        },
        {
          label: "最近批次",
          value: batchesKnown ? latestBatchStatus ?? "暂无" : "状态未知",
          detail: latestBatchDetail,
          tone: batchTone(latestBatchStatus),
        },
        {
          label: "批次窗口",
          value: batchWindow,
          detail: batchWindowDetail,
          tone: batchesKnown ? "info" : "review",
        },
      ]}
      tableTitle={`行情源运行明细（最近 ${batchWindow}）`}
      columns={columns}
      tableData={rows}
      tablePagination={batchTotal === undefined ? undefined : {
        current: returnedPage,
        pageSize: returnedPageSize,
        total: batchTotal,
        onChange: handleBatchPageChange,
      }}
      tableSearchEnabled={false}
      rowKey="key"
      emptyDescription={batches.message}
      auditTitle="数据时效门禁"
      auditItems={[
        {
          label: "行情来源",
          value: sourceStatus,
          detail: observedLatestBatch ? `${observedLatestBatch.provider}/${observedLatestBatch.source}` : "尚未产生可追溯批次",
          tone: marketKnown && market.data?.provider_metadata_status === "recorded" ? "pass" : "review",
        },
        {
          label: "自动 fallback",
          value: fallbackLabel(observedLatestBatch?.fallback_used),
          detail: "逐批读取 fallback 记录；缺少 provenance 时保持未记录。",
          tone: observedLatestBatch?.fallback_used === false ? "pass" : observedLatestBatch?.fallback_used === true ? "reject" : "review",
        },
        {
          label: "数据用途",
          value: "观察数据",
          detail: "实时行情写入不授予 Certification、Readiness 或执行权限",
          tone: "idle",
        },
      ]}
      note="本页面仅展示当前配置股票池的实时行情血缘。未知、合成或未认证历史数据仍不能被当作可信研究或执行价格。"
    />
  );
}
