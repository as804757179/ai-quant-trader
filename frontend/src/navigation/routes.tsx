import { lazy, type ComponentType, type CSSProperties, type ReactNode } from "react";

function lazyNamed<TModule extends Record<string, unknown>>(
  loader: () => Promise<TModule>,
  exportName: keyof TModule,
) {
  return lazy(async () => {
    const module = await loader();
    return { default: module[exportName] as ComponentType };
  });
}

const AiEvidencePage = lazy(() => import("../pages/ai/AiEvidencePage"));
const AiSummaryPage = lazy(() => import("../pages/ai/AiSummaryPage"));
const AiAuditPage = lazy(() => import("../pages/core/AiAuditPage"));
const BacktestValidationPage = lazy(() => import("../pages/core/BacktestValidationPage"));
const OverviewPage = lazy(() => import("../pages/core/OverviewPage"));
const ReadinessPage = lazy(() => import("../pages/core/ReadinessPage"));
const TradeControlPage = lazy(() => import("../pages/core/TradeControlPage"));
const CertifiedStorePage = lazy(() => import("../pages/data/CertifiedStorePage"));
const DataBatchesPage = lazy(() => import("../pages/data/DataBatchesPage"));
const DataBlockersPage = lazy(() => import("../pages/data/DataBlockersPage"));
const DataQualityPage = lazy(() => import("../pages/data/DataQualityPage"));
const ProviderValidationPage = lazy(() => import("../pages/data/ProviderValidationPage"));
const MarketLimitPage = lazy(() => import("../pages/market/MarketLimitPage"));
const MarketLivePage = lazy(() => import("../pages/market/MarketLivePage"));
const MarketNewsPage = lazy(() => import("../pages/market/MarketNewsPage"));
const MarketOfficialPage = lazy(() => import("../pages/market/MarketOfficialPage"));
const MarketPricePage = lazy(() => import("../pages/market/MarketPricePage"));
const MarketSectorPage = lazy(() => import("../pages/market/MarketSectorPage"));
const MarketSentimentPage = lazy(() => import("../pages/market/MarketSentimentPage"));
const MarketVolumePage = lazy(() => import("../pages/market/MarketVolumePage"));
const ResearchCandidatesPage = lazy(() => import("../pages/research/ResearchCandidatesPage"));
const ResearchDeepPage = lazy(() => import("../pages/research/ResearchDeepPage"));
const ResearchExcludedPage = lazy(() => import("../pages/research/ResearchExcludedPage"));
const ResearchHoldingsPage = lazy(() => import("../pages/research/ResearchHoldingsPage"));
const NewsEvidenceReviewPage = lazy(() => import("../pages/research/NewsEvidenceReviewPage"));
const CalendarRulesPage = lazy(() => import("../pages/strategy/CalendarRulesPage"));
const FeeRulesPage = lazy(() => import("../pages/strategy/FeeRulesPage"));
const StrategyVersionsPage = lazy(() => import("../pages/strategy/StrategyVersionsPage"));
const TradingRulesPage = lazy(() => import("../pages/strategy/TradingRulesPage"));

const logPages = () => import("../pages/logs/LogPages");
const CashEventLogPage = lazyNamed(logPages, "CashEventLogPage");
const CashLogPage = lazyNamed(logPages, "CashLogPage");
const DailyPnlLogPage = lazyNamed(logPages, "DailyPnlLogPage");
const DecisionLogPage = lazyNamed(logPages, "DecisionLogPage");
const FillLogPage = lazyNamed(logPages, "FillLogPage");
const HistoryPnlLogPage = lazyNamed(logPages, "HistoryPnlLogPage");
const OrderLogPage = lazyNamed(logPages, "OrderLogPage");
const PositionLogPage = lazyNamed(logPages, "PositionLogPage");
const RejectionLogPage = lazyNamed(logPages, "RejectionLogPage");
const ReviewLogPage = lazyNamed(logPages, "ReviewLogPage");
const RiskLogPage = lazyNamed(logPages, "RiskLogPage");
const ScanLogPage = lazyNamed(logPages, "ScanLogPage");
const SelectionLogPage = lazyNamed(logPages, "SelectionLogPage");
const SettlementLogPage = lazyNamed(logPages, "SettlementLogPage");
const StrategyChangeLogPage = lazyNamed(logPages, "StrategyChangeLogPage");

const portfolioPages = () => import("../pages/portfolio/PortfolioPages");
const AccountPage = lazyNamed(portfolioPages, "AccountPage");
const AttributionPage = lazyNamed(portfolioPages, "AttributionPage");
const EquityPage = lazyNamed(portfolioPages, "EquityPage");
const PositionsPage = lazyNamed(portfolioPages, "PositionsPage");
const ReconciliationPage = lazyNamed(portfolioPages, "ReconciliationPage");
const SettlementPage = lazyNamed(portfolioPages, "SettlementPage");
const TodayPnlPage = lazyNamed(portfolioPages, "TodayPnlPage");

const reviewPages = () => import("../pages/review/ReviewPages");
const DailyReviewPage = lazyNamed(reviewPages, "DailyReviewPage");
const MissedOpportunitiesPage = lazyNamed(reviewPages, "MissedOpportunitiesPage");
const ReviewApprovalPage = lazyNamed(reviewPages, "ReviewApprovalPage");
const ReviewCandidatesPage = lazyNamed(reviewPages, "ReviewCandidatesPage");
const ShadowRunPage = lazyNamed(reviewPages, "ShadowRunPage");
const TradeReviewPage = lazyNamed(reviewPages, "TradeReviewPage");

const riskPages = () => import("../pages/risk/RiskPages");
const RiskEventsPage = lazyNamed(riskPages, "RiskEventsPage");
const RiskOverviewPage = lazyNamed(riskPages, "RiskOverviewPage");

const systemPages = () => import("../pages/system/SystemPages");
const SchedulePage = lazyNamed(systemPages, "SchedulePage");
const SystemAlertsPage = lazyNamed(systemPages, "SystemAlertsPage");
const SystemAuditPage = lazyNamed(systemPages, "SystemAuditPage");
const SystemHealthPage = lazyNamed(systemPages, "SystemHealthPage");

const tradePages = () => import("../pages/trading/TradePages");
const AllOrdersPage = lazyNamed(tradePages, "AllOrdersPage");
const AuthorizationPage = lazyNamed(tradePages, "AuthorizationPage");
const DecisionQueuePage = lazyNamed(tradePages, "DecisionQueuePage");
const FillsPage = lazyNamed(tradePages, "FillsPage");
const OpenOrdersPage = lazyNamed(tradePages, "OpenOrdersPage");
const RejectedOrdersPage = lazyNamed(tradePages, "RejectedOrdersPage");

export interface AppRoute {
  id: string;
  path: string;
  title: string;
  description: string;
  element: ReactNode;
}

interface RouteDefinition extends Omit<AppRoute, "element"> {}

const routeDefinitions: readonly RouteDefinition[] = [
  { id: "overview", path: "/", title: "运行总览", description: "系统运行状态与关键指标总览" },
  { id: "market-live", path: "/market/live", title: "全市场行情", description: "主备行情源、时效和降级状态" },
  { id: "market-price", path: "/market/price", title: "价格与盘口", description: "价格、盘口与报价来源审计" },
  { id: "market-volume", path: "/market/volume", title: "成交量与流动性", description: "成交量、流动性与数据适用性" },
  { id: "market-limit", path: "/market/limit", title: "涨跌停与状态", description: "按日期规则解析的证券状态与价格限制" },
  { id: "market-official", path: "/market/official", title: "官方公告", description: "公告来源、证据和时点可得性" },
  { id: "market-news", path: "/market/news", title: "新闻与事件", description: "新闻事件的来源、时效和审核状态" },
  { id: "market-sentiment", path: "/market/sentiment", title: "市场情绪", description: "情绪数据质量与研究用途边界" },
  { id: "market-sector", path: "/market/sector", title: "行业与板块", description: "行业与板块状态的只读观察" },
  { id: "research-candidates", path: "/research/candidates", title: "研究候选", description: "候选、排除、待复核和不可交易状态" },
  { id: "research-deep", path: "/research/deep", title: "深度分析", description: "多维研究证据、数据截止和风险说明" },
  { id: "research-news-review", path: "/research/news-review", title: "新闻人工复核", description: "标题链接关联的追加式人工审计" },
  { id: "research-excluded", path: "/research/excluded", title: "排除与阻断", description: "未满足研究和交易门禁的原因" },
  { id: "research-holdings", path: "/research/holdings", title: "持仓再评估", description: "已有持仓的只读研究复核" },
  { id: "trade-control", path: "/trade/control", title: "交易运行控制", description: "模式、授权和执行门禁的只读状态" },
  { id: "trade-decisions", path: "/trade/decisions", title: "决策队列", description: "风险前后的候选决策与阻断原因" },
  { id: "orders-all", path: "/orders/all", title: "全部订单", description: "订单来源、审批、认证和风控审计" },
  { id: "orders-open", path: "/orders/open", title: "开放订单", description: "未完成订单的只读生命周期状态" },
  { id: "orders-rejected", path: "/orders/rejected", title: "拒绝记录", description: "Execution Gate 与 Risk Engine 拒绝原因" },
  { id: "orders-fills", path: "/orders/fills", title: "成交回报", description: "成交价格、费用和回报时效审计" },
  { id: "trade-authorization", path: "/trade/authorization", title: "范围化授权", description: "人工审批边界与有效期" },
  { id: "portfolio-account", path: "/portfolio/account", title: "账户总览", description: "账户资产、现金和数据对账状态" },
  { id: "portfolio-positions", path: "/portfolio/positions", title: "持仓与可用", description: "总持仓、可用持仓与 T+1 状态" },
  { id: "portfolio-pnl", path: "/portfolio/pnl-today", title: "当日盈亏", description: "已实现、未实现、费用与现金事件分离" },
  { id: "portfolio-attribution", path: "/portfolio/attribution", title: "盈亏归因", description: "收益归因的证据和适用范围" },
  { id: "portfolio-equity", path: "/portfolio/equity", title: "资产曲线", description: "资产净值与计算血缘" },
  { id: "portfolio-settlement", path: "/portfolio/settlement", title: "日终清算", description: "清算阶段、账务和异常审计" },
  { id: "portfolio-reconciliation", path: "/portfolio/reconciliation", title: "资金对账", description: "现金、持仓和对账差异" },
  { id: "review-daily", path: "/review/daily", title: "每日复盘", description: "当时可得信息与事后结果分离" },
  { id: "review-trades", path: "/review/trades", title: "交易复盘", description: "交易决策、回报和费用复核" },
  { id: "review-missed", path: "/review/missed", title: "错失机会", description: "仅记录事后复核，不自动改变策略" },
  { id: "review-candidates", path: "/review/candidates", title: "候选复核", description: "候选生命周期与准入状态" },
  { id: "review-shadow", path: "/review/shadow", title: "影子运行", description: "不发布、不交易的策略观察" },
  { id: "review-approval", path: "/review/approval", title: "策略变更审批", description: "策略修改不得自动上线" },
  { id: "logs-scan", path: "/logs/scan", title: "扫描日志", description: "扫描任务的时点与数据血缘" },
  { id: "logs-selection", path: "/logs/selection", title: "选股日志", description: "研究筛选的原因和排除结论" },
  { id: "logs-decisions", path: "/logs/decisions", title: "决策日志", description: "决策输入、风险检查和最终动作" },
  { id: "logs-orders", path: "/logs/orders", title: "订单日志", description: "订单来源、审批与幂等键" },
  { id: "logs-fills", path: "/logs/fills", title: "成交日志", description: "成交、费用和回报时间" },
  { id: "logs-rejections", path: "/logs/rejections", title: "拒绝日志", description: "数据、风险和执行门禁拒绝记录" },
  { id: "logs-positions", path: "/logs/positions", title: "持仓日志", description: "持仓、可用数量和成本变化" },
  { id: "logs-cash", path: "/logs/cash", title: "现金日志", description: "资金流、冻结资金和可用现金" },
  { id: "logs-pnl-daily", path: "/logs/pnl-daily", title: "每日盈亏日志", description: "日内盈亏、费用和对账结果" },
  { id: "logs-pnl-history", path: "/logs/pnl-history", title: "历史盈亏日志", description: "按日归档的盈亏记录" },
  { id: "logs-cash-events", path: "/logs/cash-events", title: "现金事件日志", description: "分红等现金事件与交易盈亏分离" },
  { id: "logs-settlement", path: "/logs/settlement", title: "清算日志", description: "清算步骤与异常说明" },
  { id: "logs-risk", path: "/logs/risk", title: "风险日志", description: "风险规则命中与拒绝记录" },
  { id: "logs-review", path: "/logs/review", title: "复盘日志", description: "复盘输入、结果和审批轨迹" },
  { id: "logs-strategy-changes", path: "/logs/strategy-changes", title: "策略变更日志", description: "策略版本、审批与生效范围" },
  { id: "risk-overview", path: "/risk/overview", title: "风险总览", description: "风险事件、敞口和门禁状态" },
  { id: "risk-events", path: "/risk/events", title: "风险事件", description: "按优先级归档的风险事件" },
  { id: "system-schedule", path: "/system/schedule", title: "任务时序", description: "采集、研究、审批和执行窗口" },
  { id: "system-alerts", path: "/system/alerts", title: "系统告警", description: "基础设施、数据资格和业务发布告警" },
  { id: "system-health", path: "/system/health", title: "服务健康", description: "服务连通、延迟和版本状态" },
  { id: "system-audit", path: "/system/audit", title: "审计日志", description: "平台级操作和关联 ID 审计" },
  { id: "data-certified", path: "/data/certified", title: "Certified Store", description: "已认证 K 线的来源和版本血缘" },
  { id: "data-batches", path: "/data/batches", title: "数据批次", description: "导入批次、重试和认证终态" },
  { id: "data-quality", path: "/data/quality", title: "数据质量", description: "字段、价格、单位和交易日期校验" },
  { id: "readiness", path: "/readiness", title: "Research Readiness", description: "用途级数据授权和阻断原因" },
  { id: "data-blockers", path: "/data/blockers", title: "阻塞归因", description: "缺失、状态和企业行动归因" },
  { id: "data-provider", path: "/data/provider", title: "Provider 验证", description: "主次 Provider 差异、证据和审核结论" },
  { id: "strategy-versions", path: "/strategy/versions", title: "策略版本", description: "策略版本、参数与审批状态" },
  { id: "backtest-validation", path: "/backtest-validation", title: "回测验证", description: "引擎、Reference、Hash 与发布门禁" },
  { id: "rules-trading", path: "/rules/trading", title: "交易规则", description: "A 股 T+1、整手、零股和涨跌停规则" },
  { id: "rules-fees", path: "/rules/fees", title: "费用规则", description: "按日期版本化的佣金、印花税和过户费" },
  { id: "rules-calendar", path: "/rules/calendar", title: "认证交易日历", description: "可信回测的交易日历来源和版本" },
  { id: "ai-summary", path: "/ai/summary", title: "AI 摘要", description: "AI 仅生成展示性摘要和建议" },
  { id: "ai-evidence", path: "/ai/evidence", title: "证据复核", description: "AI 上下文、数据资格和证据状态" },
  { id: "ai-audit", path: "/ai-audit", title: "AI 审计", description: "AI 调用与 order_created=false 审计" },
];

const routeElements: Readonly<Record<string, ReactNode>> = {
  "/": <OverviewPage />,
  "/readiness": <ReadinessPage />,
  "/backtest-validation": <BacktestValidationPage />,
  "/trade/control": <TradeControlPage />,
  "/ai/summary": <AiSummaryPage />,
  "/ai/evidence": <AiEvidencePage />,
  "/ai-audit": <AiAuditPage />,
  "/market/live": <MarketLivePage />,
  "/market/price": <MarketPricePage />,
  "/market/volume": <MarketVolumePage />,
  "/market/limit": <MarketLimitPage />,
  "/market/official": <MarketOfficialPage />,
  "/market/news": <MarketNewsPage />,
  "/market/sentiment": <MarketSentimentPage />,
  "/market/sector": <MarketSectorPage />,
  "/research/candidates": <ResearchCandidatesPage />,
  "/research/deep": <ResearchDeepPage />,
  "/research/news-review": <NewsEvidenceReviewPage />,
  "/research/excluded": <ResearchExcludedPage />,
  "/research/holdings": <ResearchHoldingsPage />,
  "/data/certified": <CertifiedStorePage />,
  "/data/batches": <DataBatchesPage />,
  "/data/quality": <DataQualityPage />,
  "/data/blockers": <DataBlockersPage />,
  "/data/provider": <ProviderValidationPage />,
  "/strategy/versions": <StrategyVersionsPage />,
  "/rules/trading": <TradingRulesPage />,
  "/rules/fees": <FeeRulesPage />,
  "/rules/calendar": <CalendarRulesPage />,
  "/trade/decisions": <DecisionQueuePage />,
  "/trade/authorization": <AuthorizationPage />,
  "/orders/all": <AllOrdersPage />,
  "/orders/open": <OpenOrdersPage />,
  "/orders/rejected": <RejectedOrdersPage />,
  "/orders/fills": <FillsPage />,
  "/portfolio/account": <AccountPage />,
  "/portfolio/positions": <PositionsPage />,
  "/portfolio/pnl-today": <TodayPnlPage />,
  "/portfolio/attribution": <AttributionPage />,
  "/portfolio/equity": <EquityPage />,
  "/portfolio/settlement": <SettlementPage />,
  "/portfolio/reconciliation": <ReconciliationPage />,
  "/review/daily": <DailyReviewPage />,
  "/review/trades": <TradeReviewPage />,
  "/review/missed": <MissedOpportunitiesPage />,
  "/review/candidates": <ReviewCandidatesPage />,
  "/review/shadow": <ShadowRunPage />,
  "/review/approval": <ReviewApprovalPage />,
  "/logs/scan": <ScanLogPage />,
  "/logs/selection": <SelectionLogPage />,
  "/logs/decisions": <DecisionLogPage />,
  "/logs/orders": <OrderLogPage />,
  "/logs/fills": <FillLogPage />,
  "/logs/rejections": <RejectionLogPage />,
  "/logs/positions": <PositionLogPage />,
  "/logs/cash": <CashLogPage />,
  "/logs/pnl-daily": <DailyPnlLogPage />,
  "/logs/pnl-history": <HistoryPnlLogPage />,
  "/logs/cash-events": <CashEventLogPage />,
  "/logs/settlement": <SettlementLogPage />,
  "/logs/risk": <RiskLogPage />,
  "/logs/review": <ReviewLogPage />,
  "/logs/strategy-changes": <StrategyChangeLogPage />,
  "/risk/overview": <RiskOverviewPage />,
  "/risk/events": <RiskEventsPage />,
  "/system/schedule": <SchedulePage />,
  "/system/alerts": <SystemAlertsPage />,
  "/system/health": <SystemHealthPage />,
  "/system/audit": <SystemAuditPage />,
};

export const APP_ROUTES: readonly AppRoute[] = routeDefinitions.map((definition) => ({
  ...definition,
  element: routeElements[definition.path],
}));

export function getRouteMeta(pathname: string): RouteDefinition | undefined {
  return routeDefinitions.find((route) => route.path === pathname);
}

export const METRIC_GRID_STYLE: CSSProperties = { "--metric-columns": 4 } as CSSProperties;
