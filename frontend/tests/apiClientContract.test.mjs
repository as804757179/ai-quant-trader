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

test("价格盘口页面只读取每证券最新已观察报价且不授予执行参考", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/market/MarketPricePage.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<ObservedQuoteListData>\("\/stock\/quotes", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useObservedQuotes\(page, pageSize\)/); assert.match(page, /每证券最新已观察报价/); assert.match(page, /报价展示不授予 Execution Reference/); assert.doesNotMatch(page, /pendingState\(/);
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

test("Provider 验证页面只读展示交叉验证记录", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/data/ProviderValidationPage.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<ProviderValidationListData>\("\/data\/provider-validations", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useProviderValidations\(page, pageSize\)/);
  assert.match(page, /不作为运行时 fallback/);
  assert.doesNotMatch(page, /pendingState\(/);
});

test("认证交易日历页面使用服务端分页且禁止 weekday fallback", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/strategy/CalendarRulesPage.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<TradingCalendarListData>\("\/rules\/trading-calendar", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useTradingCalendar\(page, pageSize\)/); assert.match(page, /无 weekday fallback/); assert.doesNotMatch(page, /pendingState\(/);
});

test("交易规则页面读取版本化规则登记且不将滑点伪装为官方规则", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/strategy/TradingRulesPage.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<TradingRuleListData>\("\/rules\/trading", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useTradingRules\(page, pageSize\)/); assert.match(page, /Source Hash 未记录/); assert.match(page, /未展示为官方规则/); assert.doesNotMatch(page, /pendingState\(/);
});

test("费用规则页面只展示已登记费项并排除滑点模型", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/strategy/FeeRulesPage.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<TradingRuleListData>\("\/rules\/fees", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useFeeRules\(page, pageSize\)/); assert.match(page, /滑点模型/); assert.match(page, /没有官方费用规则登记/); assert.doesNotMatch(page, /pendingState\(/);
});

test("证券状态页面不把审核状态推断为涨跌停规则", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/market/MarketLimitPage.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<SecurityStatusListData>\("\/market\/security-status", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useSecurityStatus\(page, pageSize\)/); assert.match(page, /不按代码前缀推断规则/); assert.match(page, /状态审核不等于涨跌停规则解析/); assert.doesNotMatch(page, /pendingState\(/);
});

test("官方公告页面复用证据索引且不把公告显示为研究或交易授权", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/market/MarketOfficialPage.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<ResearchEvidenceListData>\("\/research\/evidence", \{ evidence_type: evidenceType, page, page_size: pageSize \}\)/);
  assert.match(page, /useResearchEvidence\("announcement", page, pageSize\)/); assert.match(page, /不将公告显示为研究就绪或交易授权/); assert.match(page, /不以公告日期替代可得时间/); assert.doesNotMatch(page, /pendingState\(/);
});

test("新闻事件页面复用证据索引且不把发布时间替代接收或可得时间", async () => {
  const page = await readFile(new URL("../src/pages/market/MarketNewsPage.tsx", import.meta.url), "utf8");
  assert.match(page, /useResearchEvidence\("news", page, pageSize\)/); assert.match(page, /发布时间与接收时间不相互替代/); assert.match(page, /仅新闻人工复核页面可写入复核记录/); assert.doesNotMatch(page, /pendingState\(/);
});

test("AI 证据复核复用财报证据详情和页级复核历史且不伪造 AI 关联", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/ai/AiEvidencePage.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<ResearchEvidenceDetail>\(`\/research\/evidence\/\$\{encodeURIComponent\(evidenceId\)\}`\)/); assert.match(models, /financial-location-reviews/);
  assert.match(page, /useResearchEvidence\("financial_report", evidencePage, evidencePageSize\)/); assert.match(page, /不创建 AI 私有证据副本/); assert.match(page, /不会推断其与任何 AI 信号存在关联/); assert.doesNotMatch(page, /pendingState\(/);
});

test("账户总览页面复用只读快照且不伪造资金或对账差异", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/portfolio/PortfolioPages.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<PortfolioSnapshot>\("\/portfolio\/summary", \{ mode: "simulation" \}\)/);
  assert.match(page, /usePortfolioSummary\(\)/); assert.match(page, /不伪造初始资金或对账差异/); assert.match(page, /接口未提供时不补造/);
});

test("持仓页面保留 T+1 可用数量与估值不可用状态", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/portfolio/PortfolioPages.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<PortfolioPosition\[]>\("\/portfolio\/positions", \{ mode: "simulation" \}\)/);
  assert.match(page, /usePortfolioPositions\(\)/); assert.match(page, /不释放 T\+1/); assert.match(page, /不以记录价回退估值/);
});

test("资产曲线页面仅展示历史快照且不绘制假曲线", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/portfolio/PortfolioPages.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<EquityCurveData>\("\/portfolio\/equity-curve", \{ mode: "simulation", days: 30 \}\)/);
  assert.match(page, /useEquityCurve\(\)/); assert.match(page, /不绘制假曲线/); assert.match(page, /历史快照不等于实时净值/);
});

test("风险总览页面使用只读聚合且不将未知状态显示为通过", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/risk/RiskPages.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<RiskDashboardData>\("\/risk\/dashboard", \{ mode: "simulation" \}\)/);
  assert.match(page, /useRiskDashboard\(\)/); assert.match(page, /unknown\/stale 不显示为通过/); assert.match(page, /不从缺失状态推断通过/); assert.doesNotMatch(page, /pendingState\("风险总览/);
});

test("风险事件页面读取持久化风险告警且不与系统告警混用", async () => {
  const [models, page] = await Promise.all([readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"), readFile(new URL("../src/pages/risk/RiskPages.tsx", import.meta.url), "utf8")]);
  assert.match(models, /get<RiskAlertListData>\("\/risk\/alerts", \{ page, page_size: pageSize \}\)/);
  assert.match(models, /get<RiskAlertSummaryData>\("\/risk\/alerts\/summary", \{ limit: 100 \}\)/);
  assert.match(page, /useRiskAlerts\(page, pageSize\)/); assert.match(page, /不与系统告警混用/); assert.match(page, /页面不改变解决状态/); assert.doesNotMatch(page, /pendingState\("风险事件/);
});
