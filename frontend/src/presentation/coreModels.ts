import { useEffect, useRef, useState } from "react";
import { get, type APIResponse } from "../api/client";
import type { DisplayState } from "./contracts";
import { loadingState, pendingState, readOptional } from "./readOnlyApi";

export interface PortfolioSnapshot {
  total_assets?: number;
  cash?: number;
  market_value?: number;
  daily_pnl?: number;
  daily_pnl_pct?: number;
  drawdown_from_peak?: number;
  position_count?: number;
  position_ratio?: number;
  is_fused?: boolean;
}

export interface RiskDashboardData {
  mode?: string;
  portfolio?: PortfolioSnapshot;
  fuse?: { is_active?: boolean };
  alerts?: { items?: RiskAlert[]; total?: number };
}

export interface RiskAlert {
  id?: string;
  level?: string;
  alert_type?: string;
  message?: string;
  created_at?: string;
}

export interface TradeModeData {
  mode?: string;
  available_modes?: string[];
  live_confirm_required?: boolean;
  live_max_order_value?: number;
  adapters?: Record<string, string>;
}

export interface BrokerStatusData {
  selected_adapter?: string;
  xtquant_available?: boolean;
  qmt_path_exists?: boolean;
  account_configured?: boolean;
  connection_ready?: boolean;
}

export interface RiskExposureData extends PortfolioSnapshot {
  mode?: string;
  positions?: Array<{
    stock_code?: string;
    name?: string;
    sector?: string;
    market_value?: number;
    ratio?: number;
    total_qty?: number;
    unrealized_pnl?: number;
  }>;
}

export interface BacktestTaskData {
  id?: number | string;
  name?: string;
  strategy_type?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  result_hash?: string;
}

export interface BacktestTaskListData {
  items?: BacktestTaskData[];
  total?: number;
}

export interface AiSignalData {
  id?: string;
  stock_code?: string;
  action?: string;
  confidence?: number;
  risk_level?: string;
  reason?: string;
  signal_time?: string;
  valid_until?: string;
  status?: string;
}

export interface AiSignalListData {
  items?: AiSignalData[];
  total?: number;
}

type ApiLoader<T> = () => Promise<APIResponse<T>>;

export function useReadOnlyDisplay<T>(
  loader: ApiLoader<T> | undefined,
  sourceVersion: string,
): DisplayState<T> {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const [state, setState] = useState<DisplayState<T>>(
    () => (loader ? loadingState("加载中", sourceVersion) : pendingState("待接入", sourceVersion)) as DisplayState<T>,
  );

  useEffect(() => {
    if (!loaderRef.current) {
      setState(pendingState("待接入", sourceVersion) as DisplayState<T>);
      return;
    }

    let active = true;
    setState(loadingState("加载中", sourceVersion) as DisplayState<T>);
    void readOptional(loaderRef.current, sourceVersion).then((nextState) => {
      if (active) {
        setState(nextState);
      }
    });

    return () => {
      active = false;
    };
  }, [sourceVersion]);

  return state;
}

export function useOverviewModel() {
  const dashboard = useReadOnlyDisplay<RiskDashboardData>(
    () => get<RiskDashboardData>("/risk/dashboard", { mode: "simulation" }),
    "risk-dashboard-v1",
  );
  const summary = useReadOnlyDisplay<PortfolioSnapshot>(
    () => get<PortfolioSnapshot>("/portfolio/summary", { mode: "simulation" }),
    "portfolio-summary-v1",
  );
  const alerts = useReadOnlyDisplay<{ items?: RiskAlert[]; total?: number }>(
    () => get<{ items?: RiskAlert[]; total?: number }>("/risk/alerts", { limit: 10 }),
    "risk-alerts-v1",
  );

  return { dashboard, summary, alerts };
}

export function useTradeControlModel() {
  const mode = useReadOnlyDisplay<TradeModeData>(() => get<TradeModeData>("/trade/mode"), "trade-mode-v1");
  const broker = useReadOnlyDisplay<BrokerStatusData>(
    () => get<BrokerStatusData>("/trade/broker-status"),
    "broker-status-v1",
  );
  const exposure = useReadOnlyDisplay<RiskExposureData>(
    () => get<RiskExposureData>("/risk/exposure", { mode: "simulation" }),
    "risk-exposure-v1",
  );

  return { mode, broker, exposure };
}

export function useBacktestTasks() {
  return useReadOnlyDisplay<BacktestTaskListData>(
    () => get<BacktestTaskListData>("/backtest/tasks", { limit: 20 }),
    "backtest-tasks-v1",
  );
}

export function useAiSignals() {
  return useReadOnlyDisplay<AiSignalListData>(
    () => get<AiSignalListData>("/ai/signals", { page: 1, page_size: 50 }),
    "ai-signals-v1",
  );
}

export function formatCurrency(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "待接入";
  }

  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "待接入";
  }

  return `${(value * 100).toFixed(2)}%`;
}
