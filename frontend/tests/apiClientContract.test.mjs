import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("API client rejects false and non-envelope responses", async () => {
  const source = await readFile(new URL("../src/api/client.ts", import.meta.url), "utf8");
  assert.match(source, /API_CONTRACT_INVALID/);
  assert.match(source, /if \(!response\.success\)/);
  assert.match(source, /errorCode = response\.error_code/);
  assert.doesNotMatch(source, /success: true,\s*data: payload as T/);
});

test("策略版本页面仅使用受治理的只读状态接口", async () => {
  const [page, models] = await Promise.all([
    readFile(new URL("../src/pages/strategy/StrategyVersionsPage.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
  ]);

  assert.match(page, /useStrategyRuntimeStatus/);
  assert.doesNotMatch(page, /\/strategy\/(?:create|versions\/.*approve)/i);
  assert.doesNotMatch(page, /\bpost\b/i);
  assert.match(
    models,
    /export function useStrategyRuntimeStatus\(\) \{[\s\S]*?get<StrategyRuntimeStatusData>\("\/strategy\/runtime-status"\)/,
  );
});

test("行情批次使用服务端分页并保留每批 fallback 记录", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/market/MarketLivePage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /export function useMarketQuoteBatches\(page = 1, pageSize = 20\)/);
  assert.match(models, /get<MarketQuoteBatchListData>\("\/stock\/market\/batches", \{ page, page_size: pageSize \}\)/);
  assert.match(models, /market-quote-batches-v2:p\$\{page\}:s\$\{pageSize\}/);
  assert.match(page, /fallback_used/);
  assert.match(page, /tablePagination=/);
  assert.match(page, /tableSearchEnabled=\{false\}/);
  assert.doesNotMatch(page, /fallback: "未使用"/);
});

test("订单和新闻证据页面使用服务端分页且不夸大查询范围", async () => {
  const [models, ordersPage, newsPage] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/trading/TradePages.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/research/NewsEvidenceReviewPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /export function useTradeOrders\(page = 1, pageSize = 50\)/);
  assert.match(models, /get<TradeOrderListData>\("\/trade\/orders", \{[\s\S]*?mode: "simulation",[\s\S]*?days: 7,[\s\S]*?page,[\s\S]*?page_size: pageSize,/);
  assert.match(models, /trade-orders-v2:simulation:7:p\$\{page\}:s\$\{pageSize\}/);
  assert.match(ordersPage, /useTradeOrders\(orderPage, orderPageSize\)/);
  assert.match(ordersPage, /tablePagination=/);
  assert.match(ordersPage, /tableSearchEnabled=\{false\}/);
  assert.match(ordersPage, /client_intent_key/);
  assert.match(newsPage, /page: evidencePage,/);
  assert.match(newsPage, /page_size: evidencePageSize,/);
  assert.match(newsPage, /research-news-evidence-review-v2:p\$\{evidencePage\}:s\$\{evidencePageSize\}:r\$\{refreshVersion\}/);
  assert.match(newsPage, /remotePagination=/);
  assert.match(newsPage, /showSearch=\{false\}/);
  assert.doesNotMatch(newsPage, /page: 1,\s*page_size: 50,/);
});

test("Certified Store 只读取认证血缘且不把认证显示为研究准入", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/data/CertifiedStorePage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /export function useCertifiedKlineLineage\(page = 1, pageSize = 50\)/);
  assert.match(models, /get<CertifiedKlineLineageData>\("\/data\/certified-klines", \{[\s\S]*?period: "1d",[\s\S]*?adjustment: "raw",[\s\S]*?page,[\s\S]*?page_size: pageSize,/);
  assert.match(page, /useCertifiedKlineLineage\(page, pageSize\)/);
  assert.match(page, /tablePagination=/);
  assert.match(page, /Certification 不传播为 Research Readiness/);
  assert.doesNotMatch(page, /pendingState\(/);
});

test("数据批次和质量页面使用服务端分页的只读认证接口", async () => {
  const [models, batchesPage, qualityPage] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/data/DataBatchesPage.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/data/DataQualityPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /export function useCertificationBatches\(page = 1, pageSize = 50\)/);
  assert.match(models, /get<CertificationBatchListData>\("\/data\/certification-batches", \{ page, page_size: pageSize \}\)/);
  assert.match(models, /export function useQualityResults\(page = 1, pageSize = 50\)/);
  assert.match(models, /get<QualityResultListData>\("\/data\/quality-results", \{ page, page_size: pageSize \}\)/);
  assert.match(batchesPage, /useCertificationBatches\(page, pageSize\)/);
  assert.match(qualityPage, /useQualityResults\(page, pageSize\)/);
  assert.match(batchesPage, /tablePagination=/);
  assert.match(qualityPage, /tablePagination=/);
  assert.match(qualityPage, /历史未记录批次不会伪造明细/);
  assert.doesNotMatch(batchesPage, /pendingState\(/);
  assert.doesNotMatch(qualityPage, /pendingState\(/);
});

test("阻塞归因页面不推断 Readiness 因果", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/data/DataBlockersPage.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(models, /get<DataBlockerListData>\("\/data\/blockers", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useDataBlockers\(page, pageSize\)/);
  assert.match(page, /不推断 Readiness 因果/);
  assert.doesNotMatch(page, /pendingState\(/);
});
