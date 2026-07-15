export interface NavigationNode {
  id: string;
  label: string;
  path?: string;
  children?: readonly NavigationNode[];
  section?: boolean;
}

export const NAVIGATION: readonly NavigationNode[] = [
  { id: "overview", label: "运行总览", path: "/" },
  {
    id: "market",
    label: "市场监控",
    children: [
      { id: "market-live", label: "全市场行情", path: "/market/live" },
      { id: "market-price", label: "价格与盘口", path: "/market/price" },
      { id: "market-volume", label: "成交量与流动性", path: "/market/volume" },
      { id: "market-limit", label: "涨跌停与状态", path: "/market/limit" },
      { id: "market-official", label: "官方公告", path: "/market/official" },
      { id: "market-news", label: "新闻与事件", path: "/market/news" },
      { id: "market-sentiment", label: "市场情绪", path: "/market/sentiment" },
      { id: "market-sector", label: "行业与板块", path: "/market/sector" },
    ],
  },
  {
    id: "research",
    label: "机会中心",
    children: [
      { id: "research-candidates", label: "研究候选", path: "/research/candidates" },
      { id: "research-deep", label: "深度分析", path: "/research/deep" },
      { id: "research-excluded", label: "排除与阻断", path: "/research/excluded" },
      { id: "research-holdings", label: "持仓再评估", path: "/research/holdings" },
    ],
  },
  {
    id: "trading",
    label: "自动交易",
    children: [
      { id: "trade-control", label: "交易运行控制", path: "/trade/control" },
      { id: "trade-decisions", label: "决策队列", path: "/trade/decisions" },
      {
        id: "orders",
        label: "订单与成交",
        children: [
          { id: "orders-all", label: "全部订单", path: "/orders/all" },
          { id: "orders-open", label: "开放订单", path: "/orders/open" },
          { id: "orders-rejected", label: "拒绝记录", path: "/orders/rejected" },
          { id: "orders-fills", label: "成交回报", path: "/orders/fills" },
        ],
      },
      { id: "trade-authorization", label: "范围化授权", path: "/trade/authorization" },
    ],
  },
  {
    id: "portfolio",
    label: "组合与盈亏",
    children: [
      { id: "portfolio-account", label: "账户总览", path: "/portfolio/account" },
      { id: "portfolio-positions", label: "持仓与可用", path: "/portfolio/positions" },
      { id: "portfolio-pnl", label: "当日盈亏", path: "/portfolio/pnl-today" },
      { id: "portfolio-attribution", label: "盈亏归因", path: "/portfolio/attribution" },
      { id: "portfolio-equity", label: "资产曲线", path: "/portfolio/equity" },
      { id: "portfolio-settlement", label: "日终清算", path: "/portfolio/settlement" },
      { id: "portfolio-reconciliation", label: "资金对账", path: "/portfolio/reconciliation" },
    ],
  },
  {
    id: "review",
    label: "盘后复盘",
    children: [
      { id: "review-daily", label: "每日复盘", path: "/review/daily" },
      { id: "review-trades", label: "交易复盘", path: "/review/trades" },
      { id: "review-missed", label: "错失机会", path: "/review/missed" },
      { id: "review-candidates", label: "候选复核", path: "/review/candidates" },
      { id: "review-shadow", label: "影子运行", path: "/review/shadow" },
      { id: "review-approval", label: "策略变更审批", path: "/review/approval" },
    ],
  },
  {
    id: "risk-system",
    label: "风险与系统",
    children: [
      {
        id: "risk",
        label: "风险控制",
        children: [
          { id: "risk-overview", label: "风险总览", path: "/risk/overview" },
          { id: "risk-events", label: "风险事件", path: "/risk/events" },
        ],
      },
      {
        id: "system",
        label: "系统运行",
        children: [
          { id: "system-schedule", label: "任务时序", path: "/system/schedule" },
          { id: "system-alerts", label: "系统告警", path: "/system/alerts" },
          { id: "system-health", label: "服务健康", path: "/system/health" },
          { id: "system-audit", label: "审计日志", path: "/system/audit" },
        ],
      },
    ],
  },
  { id: "tools", label: "研究工具", section: true },
  {
    id: "data",
    label: "数据与认证",
    children: [
      { id: "data-certified", label: "Certified Store", path: "/data/certified" },
      { id: "data-batches", label: "数据批次", path: "/data/batches" },
      { id: "data-quality", label: "数据质量", path: "/data/quality" },
      { id: "readiness", label: "Research Readiness", path: "/readiness" },
      { id: "data-blockers", label: "阻塞归因", path: "/data/blockers" },
      { id: "data-provider", label: "Provider 验证", path: "/data/provider" },
    ],
  },
  {
    id: "strategy",
    label: "策略与回测",
    children: [
      { id: "strategy-versions", label: "策略版本", path: "/strategy/versions" },
      { id: "backtest-validation", label: "回测验证", path: "/backtest-validation" },
      {
        id: "rules",
        label: "市场规则",
        children: [
          { id: "rules-trading", label: "交易规则", path: "/rules/trading" },
          { id: "rules-fees", label: "费用规则", path: "/rules/fees" },
          { id: "rules-calendar", label: "认证交易日历", path: "/rules/calendar" },
        ],
      },
    ],
  },
  {
    id: "ai",
    label: "AI 辅助",
    children: [
      { id: "ai-summary", label: "AI 摘要", path: "/ai/summary" },
      { id: "ai-evidence", label: "证据复核", path: "/ai/evidence" },
      { id: "ai-audit", label: "AI 审计", path: "/ai-audit" },
    ],
  },
  {
    id: "logs",
    label: "交易与盈亏日志",
    children: [
      { id: "logs-scan", label: "扫描日志", path: "/logs/scan" },
      { id: "logs-selection", label: "选股日志", path: "/logs/selection" },
      { id: "logs-decisions", label: "决策日志", path: "/logs/decisions" },
      { id: "logs-orders", label: "订单日志", path: "/logs/orders" },
      { id: "logs-fills", label: "成交日志", path: "/logs/fills" },
      { id: "logs-rejections", label: "拒绝日志", path: "/logs/rejections" },
      { id: "logs-positions", label: "持仓日志", path: "/logs/positions" },
      { id: "logs-cash", label: "现金日志", path: "/logs/cash" },
      { id: "logs-pnl-daily", label: "每日盈亏日志", path: "/logs/pnl-daily" },
      { id: "logs-pnl-history", label: "历史盈亏日志", path: "/logs/pnl-history" },
      { id: "logs-cash-events", label: "现金事件日志", path: "/logs/cash-events" },
      { id: "logs-settlement", label: "清算日志", path: "/logs/settlement" },
      { id: "logs-risk", label: "风险日志", path: "/logs/risk" },
      { id: "logs-review", label: "复盘日志", path: "/logs/review" },
      { id: "logs-strategy-changes", label: "策略变更日志", path: "/logs/strategy-changes" },
    ],
  },
];
