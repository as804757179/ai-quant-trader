import { useEffect, useRef, useState } from "react";
import { get, type APIResponse } from "../api/client";
import type { DisplayState, ReleaseLock } from "./contracts";
import { loadingState, pendingState, readOptional } from "./readOnlyApi";

export interface PortfolioSnapshot {
  mode?: string;
  account_record_id?: number | string | null;
  snapshot_time?: string | null;
  account_snapshot_time?: string | null;
  account_snapshot_age_seconds?: number | null;
  account_snapshot_freshness?: string;
  total_assets?: number;
  cash?: number;
  market_value?: number;
  daily_pnl?: number;
  daily_pnl_pct?: number;
  drawdown_from_peak?: number;
  position_count?: number;
  position_ratio?: number;
  is_fused?: boolean;
  valuation_status?: string;
  valuation_stale?: boolean;
  valuation_freshness?: string;
  valuation_as_of?: string | null;
  valuation_age_seconds?: number | null;
  valuation_unavailable_positions?: string[];
  valuation_source?: Record<string, unknown> | null;
  source?: string;
  source_version?: string;
}

export interface PortfolioPosition {
  stock_code?: string;
  name?: string;
  total_qty?: number;
  available_qty?: number;
  frozen_qty?: number;
  avg_cost?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  valuation_freshness?: string;
  price_source?: string;
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
  type?: string;
  message?: string;
  created_at?: string;
  ts?: string;
  action_taken?: string;
  trigger_value?: number | null;
  threshold?: number | null;
  is_resolved?: boolean;
  resolved_at?: string | null;
  resolved_by?: string | null;
}

export interface RiskAlertListData {
  items?: RiskAlert[];
  total?: number;
  page?: number;
  page_size?: number;
  source?: string;
  source_version?: string;
}

export interface RiskAlertSummaryData {
  available_total?: number;
  critical?: number;
  error?: number;
  warning?: number;
  info?: number;
  source?: string;
  source_version?: string;
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

export interface TradeOrderData {
  id?: string;
  stock_code?: string;
  side?: string;
  quantity?: number;
  status?: string;
  created_at?: string;
  order_source?: string;
  caller?: string;
  approval_status?: string;
  approval_id?: string;
  risk_check_id?: string;
  data_certification_status?: string;
}

export interface TradeOrderListData {
  items?: TradeOrderData[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
}

export interface ExecutionStatusData {
  mode?: string;
  release_locks?: ReleaseLock[];
  all_release_locks_closed?: boolean;
  paper_trading_enabled?: boolean;
  require_human_approval?: boolean;
  ai_direct_order_allowed?: boolean;
  source_version?: string;
  snapshot_version?: string;
  snapshot_at?: string | null;
  identity?: {
    authenticated?: boolean;
    principal_type?: string;
    role?: string;
    scopes?: string[];
  };
  window_days?: number;
  order_audit?: {
    total?: number;
    failed?: number;
    cancelled?: number;
    open?: number;
    unknown_caller?: number;
    ai_source?: number;
    scheduled_source?: number;
    unapproved?: number;
    latest_order_at?: string | null;
    rejection_reasons?: Array<{ reason?: string; count?: number }>;
  };
  risk_rules?: {
    enabled_count?: number;
    rule_set_hash?: string;
    rule_version?: string;
    effective_at?: string | null;
    source?: string;
    source_version?: string;
  };
  approval_policy?: {
    required?: boolean;
    policy_version?: string;
    independent_approver_required?: boolean;
  };
  approval_audit?: {
    total?: number;
    requested?: number;
    approved?: number;
    consumed?: number;
    expired?: number;
    rejected?: number;
    expired_unconsumed?: number;
    policy_version_mismatch?: number;
    latest_approval_at?: string | null;
  };
  data_authorization_policy?: {
    required_for_order_approval?: boolean;
    server_review_reference_required?: boolean;
    profile?: string;
    scope?: string;
    freshness_seconds?: number;
  };
  data_authorization_audit?: {
    latest_review_count?: number;
    ready_fresh_count?: number;
    stale_ready_count?: number;
    review_required_count?: number;
    rejected_count?: number;
    invalid_field_count?: number;
    latest_reviewed_at?: string | null;
  };
}

export interface HealthStatusData {
  status?: string;
  version?: string;
  checks?: Record<string, string>;
}

export interface SystemHealthData {
  infrastructure?: { status?: string; components?: Array<{ component?: string; status?: string; detail?: string; observed_at?: string }> };
  data_qualification?: { status?: string; summary?: { total?: number; ready?: number; review_required?: number; rejected?: number; latest_reviewed_at?: string | null } | null; research_readiness?: string };
  business_release?: { status?: string; all_release_locks_closed?: boolean; release_locks?: ReleaseLock[]; tradable?: boolean; order_created?: boolean };
  observed_only?: boolean;
  source?: string;
  source_version?: string;
}

export interface SystemAlertListData {
  items?: Array<{ category?: string; alert_id?: string; severity?: string; alert_type?: string; owner?: string; event_time?: string | null; related_id?: string; detail_code?: string | null; source?: string; source_version?: string }>;
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  summary?: { system_operation?: number; data_qualification?: number; latest_event_at?: string | null };
  business_release?: { status?: string; release_locks?: ReleaseLock[]; all_release_locks_closed?: boolean };
  risk_alerts_included?: boolean;
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
  source?: string;
  source_version?: string;
}

export interface SystemJobListData {
  items?: Array<{ job_id?: string; job_type?: string; status?: string; progress?: number; error_code?: string | null; retry_count?: number; max_retries?: number; next_retry_at?: string | null; created_at?: string; started_at?: string | null; finished_at?: string | null; updated_at?: string; last_stage?: string | null; operation_approval_id?: string | null }>;
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  summary?: { pending?: number; running?: number; failed_or_blocked?: number; latest_updated_at?: string | null };
  scheduler?: { registration_status?: string; registration_source?: string; runtime_status?: string; timezone?: string };
  business_release?: { status?: string; release_locks?: ReleaseLock[]; all_release_locks_closed?: boolean };
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
  source?: string;
  source_version?: string;
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
  task_id?: number | string;
  name?: string;
  status?: string;
  progress?: number;
  start_date?: string;
  end_date?: string;
  universe?: string;
  created_at?: string;
  finished_at?: string;
  error_msg?: string;
}

export interface BacktestTaskListData {
  items?: BacktestTaskData[];
  total?: number;
}

export interface BacktestValidationSummaryData {
  summary?: {
    total?: number;
    done?: number;
    failed?: number;
    active?: number;
    latest_task_at?: string | null;
  };
  latest_persisted_result?: {
    task_id?: number;
    result_id?: number;
    name?: string;
    date_from?: string;
    date_to?: string;
    universe?: string;
    lookahead_checked?: boolean;
    strategy_type?: string | null;
    parameter_hash?: string;
    persisted_result_hash?: string;
    result_hash_status?: string;
    dataset_hash?: string | null;
    dataset_hash_status?: string;
    strategy_version?: string | null;
    strategy_version_status?: string;
    engine_version?: string | null;
    engine_version_status?: string;
    cost_hash?: string | null;
    cost_hash_status?: string;
    reference_comparison_status?: string;
    validation_status?: string;
    blocking_reasons?: string[];
    readiness_reviews?: ReadinessReviewData[];
  } | null;
  current_runtime_versions?: {
    engine?: string;
    market_rules?: string;
    trading_calendar?: string;
  };
  validation_only?: boolean;
  not_for_investment?: boolean;
  public_execution_enabled?: boolean;
  source_version?: string;
}

export interface AiSignalData {
  id?: string;
  record_type?: string;
  stock_code?: string;
  action?: string;
  confidence?: number;
  risk_level?: string;
  reason?: string;
  signal_time?: string;
  valid_until?: string;
  status?: string;
  historical_data_status?: string;
  current_validity_status?: string;
  recorded_context_status?: string;
  data_authorization_status?: string;
  recommendation_only?: boolean;
  tradable?: boolean;
  research_eligible?: boolean;
  order_created?: boolean;
}

export interface AiSignalListData {
  items?: AiSignalData[];
  total?: number;
}

export interface AiAuditSummaryData {
  window_days?: number;
  signal_count?: number;
  hold_count?: number;
  agent_call_count?: number;
  agent_failure_count?: number;
  ai_order_count?: number;
  order_created?: boolean;
  unauthorized_attempt_count?: number | null;
  unauthorized_attempt_status?: string;
  configured_models?: string[];
  latest_call_at?: string | null;
  ai_order_enabled?: boolean;
  ai_direct_order_allowed?: boolean;
  scheduled_order_enabled?: boolean;
  source_version?: string;
  latest_signal_at?: string | null;
  data_status_counts?: {
    certified?: number;
    blocked?: number;
    unknown?: number;
  };
  agent_usage?: Array<{
    agent_name?: string;
    model_used?: string;
    status?: string;
    count?: number;
    average_latency_ms?: number;
  }>;
}

export interface ReadinessReviewData {
  review_id?: string;
  stock_code?: string;
  period?: string;
  date_from?: string;
  date_to?: string;
  adjustment?: string;
  readiness_status?: string;
  research_use_scope?: string;
  requirement_profile?: string;
  required_fields?: string[];
  validated_fields?: string[];
  unresolved_fields?: string[];
  rejected_fields?: string[];
  corporate_action_status?: string;
  missingness_status?: string;
  provider_validation_status?: string;
  review_reason?: string;
  policy_version?: string;
  reviewer_version?: string;
  reviewed_at?: string;
}

export interface ReadinessListData {
  items?: ReadinessReviewData[];
  total?: number;
  summary?: {
    ready?: number;
    review_required?: number;
    rejected?: number;
    stock_count?: number;
    unresolved_field_count?: number;
    rejected_field_count?: number;
    latest_reviewed_at?: string | null;
    policy_versions?: string[];
  };
  dimensions?: Record<string, Record<string, number>>;
  blockers?: Array<{ reason?: string; count?: number }>;
  page?: number;
  page_size?: number;
  source_version?: string;
}

export interface MarketDataStatusData {
  status?: string;
  market_session?: string;
  latest_quote_at?: string | null;
  lag_seconds?: number | null;
  freshness_threshold_seconds?: number;
  recent_symbol_count?: number;
  active_stock_count?: number;
  calendar_sources?: string[];
  source?: string;
  provider?: string | null;
  provider_metadata_status?: string;
  fallback_status?: string;
  source_version?: string;
  latest_batch?: MarketQuoteBatchData | null;
}

export interface MarketQuoteBatchData {
  batch_id?: string;
  provider?: string;
  source?: string;
  fetch_endpoint?: string;
  requested_symbols?: number;
  returned_symbols?: number;
  accepted_symbols?: number;
  rejected_symbols?: number;
  status?: string;
  failure_reason?: string | null;
  raw_response_hash?: string | null;
  collector_version?: string;
  normalizer_version?: string;
  started_at?: string;
  fetched_at?: string | null;
  received_at?: string;
  fallback_used?: boolean | null;
}

export interface MarketQuoteBatchListData {
  items?: MarketQuoteBatchData[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  source?: string;
  source_version?: string;
}

export interface ObservedQuoteListData {
  items?: Array<{ stock_code?: string; market?: string | null; board?: string | null; quote_time?: string; price?: number | null; bid1_price?: number | null; ask1_price?: number | null; provider?: string; source?: string; fetch_endpoint?: string; provider_time?: string | null; received_at?: string; batch_id?: string; raw_hash?: string; fallback_used?: boolean; quality_status?: string; batch_status?: string; lag_seconds?: number; freshness_status?: string; order_book_status?: string }>;
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  observed_only?: boolean;
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
  source?: string;
  source_version?: string;
}

export interface ObservedLiquidityListData {
  items?: Array<{ stock_code?: string; market?: string | null; board?: string | null; quote_time?: string; period?: string; volume?: number | null; volume_unit?: string; volume_status?: string; amount?: number | null; amount_unit?: string; amount_status?: string; provider?: string; source?: string; fetch_endpoint?: string; received_at?: string; batch_id?: string; raw_hash?: string; quality_status?: string; freshness_status?: string }>;
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  observed_only?: boolean;
  research_readiness?: string;
  amount_research_eligible?: boolean;
  liquidity_conclusion?: string;
  tradable?: boolean;
  order_created?: boolean;
  source?: string;
  source_version?: string;
}

export interface EquityCurvePoint {
  id?: number;
  record_time?: string;
  total_assets?: number;
  cash?: number;
  market_value?: number;
  daily_pnl?: number;
  total_pnl?: number;
  total_pnl_pct?: number;
  position_count?: number;
  position_ratio?: number;
  data_type?: string;
  valuation_status?: string;
  valuation_stale?: boolean;
  valuation_freshness?: string;
  valuation_as_of?: string | null;
  valuation_age_seconds?: number | null;
  valuation_source?: Record<string, unknown> | null;
}

export interface EquityCurveData {
  mode?: string;
  days?: number;
  items?: EquityCurvePoint[];
  total?: number;
  latest_at?: string | null;
  source?: string;
  source_version?: string;
  valuation_status?: string;
  valuation_stale?: boolean;
  valuation_freshness?: string;
  valuation_as_of?: string | null;
  valuation_age_seconds?: number | null;
  valuation_source?: Record<string, unknown> | null;
}

export interface ResearchCandidateStatusData {
  items?: ReadinessReviewData[];
  counts?: Record<string, number>;
  snapshot_hash?: string;
  candidate_count?: number | null;
  candidate_status?: string;
  tradable?: boolean;
  order_created?: boolean;
  release_lock?: ReleaseLock;
  source_version?: string;
}

export interface ResearchEvidence {
  evidence_id?: string;
  evidence_type?: "announcement" | "news" | "financial_report";
  stock_code?: string;
  provider?: string;
  source?: string;
  publisher_name?: string;
  title?: string;
  document_url?: string;
  source_published_at?: string | null;
  source_published_date?: string | null;
  received_at?: string | null;
  available_at?: string | null;
  availability_basis?: string;
  raw_hash?: string;
  quality_status?: string;
  usage_status?: string;
}

export interface ResearchEvidenceDetail extends ResearchEvidence {
  financial_report_detail?: {
    report_period_end?: string;
    currency_code?: string;
    currency_unit?: string;
    audit_opinion?: string;
    revision_status?: string;
    detail_parse_status?: string;
  } | null;
  financial_report_snapshot_location?: {
    snapshot_status?: string;
    parse_run?: { status?: string; page_count?: number; locations?: Array<{ field_name?: string; status?: string }> } | null;
  } | null;
}

export interface FinancialLocationReviewListData {
  items?: Array<{ review_id?: string; location_id?: string; conclusion?: string; reason?: string; reviewed_at?: string; reviewer_label?: string; field_name?: string; location_status?: string; page_number?: number }>;
  total?: number;
  page?: number;
  page_size?: number;
  review_scope?: string;
  source_version?: string;
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
}

export interface ResearchEvidenceListData {
  items?: ResearchEvidence[];
  total?: number;
  summary?: { observed?: number; rejected?: number; stock_count?: number; latest_available_at?: string | null };
  page?: number;
  page_size?: number;
  source?: string;
  source_version?: string;
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
}

export interface StrategyRuntimeStatusItem {
  type?: string;
  name?: string;
  strategy_id?: number;
  revision?: number;
  version?: number | null;
  version_id?: number | null;
  enabled?: boolean;
  requested_enabled?: boolean;
  config_status?: string;
  params_source?: string;
  approval_status?: string | null;
  config_hash?: string | null;
  catalog_hash?: string | null;
  requirement_profile?: string;
  error_code?: string;
}

export interface StrategyRuntimeStatusData {
  items?: StrategyRuntimeStatusItem[];
  total?: number;
  enabled_count?: number;
  catalog_version?: string;
  config_hash?: string;
  source?: string;
  source_version?: string;
}

export interface CertifiedKlineLineageItem {
  stock_code?: string;
  trading_date?: string;
  period?: string;
  adjustment?: string;
  provider?: string;
  source?: string;
  batch_id?: string;
  raw_hash?: string;
  quality_status?: string;
  certification_status?: string;
  certification_time?: string;
  importer_version?: string;
  normalizer_version?: string;
  schema_version?: string;
  research_readiness_status?: string;
  review_reason?: string | null;
}

export interface CertifiedKlineLineageData {
  items?: CertifiedKlineLineageItem[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  summary?: {
    stock_count?: number;
    date_from?: string | null;
    date_to?: string | null;
    providers?: string[];
  };
  certification_scope?: string;
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
  source_version?: string;
}

export interface CertificationBatchItem {
  batch_id?: string;
  stock_code?: string | null;
  provider?: string;
  source?: string;
  period?: string;
  start_date?: string | null;
  end_date?: string | null;
  fetch_time?: string | null;
  total_rows?: number;
  accepted_rows?: number;
  rejected_rows?: number;
  quality_score?: number | null;
  status?: string;
  reject_reason?: string | null;
  importer_version?: string;
}

export interface CertificationBatchListData {
  items?: CertificationBatchItem[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  summary?: {
    certified?: number;
    rejected?: number;
    failed?: number;
    latest_fetch_time?: string | null;
  };
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
  source_version?: string;
}

export interface QualityResultItem {
  quality_result_id?: string;
  batch_id?: string;
  rule_code?: string;
  rule_version?: string;
  audit_scope?: string;
  result?: string;
  reject_reason?: string | null;
  input_hash?: string;
  created_at?: string | null;
  stock_code?: string | null;
  provider?: string;
  source?: string;
  period?: string;
  fetch_time?: string | null;
  importer_version?: string;
}

export interface QualityResultListData {
  items?: QualityResultItem[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  summary?: {
    passed?: number;
    failed?: number;
    not_evaluated?: number;
    latest_evaluated_at?: string | null;
  };
  research_readiness?: string;
  tradable?: boolean;
  order_created?: boolean;
  source_version?: string;
}

export interface DataBlockerItem {
  blocker_id?: string;
  stock_code?: string;
  trading_date?: string | null;
  classification?: string;
  status?: string;
  evidence_source?: string;
  evidence_version?: string;
  reviewed_at?: string | null;
  reason?: string | null;
  readiness_blocking?: boolean | null;
  readiness_linkage_status?: string;
}

export interface DataBlockerListData {
  items?: DataBlockerItem[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  summary?: { unresolved?: number; provider_missing?: number; latest_reviewed_at?: string | null };
  readiness_linkage?: string;
  tradable?: boolean;
  order_created?: boolean;
  source_version?: string;
}

export interface ProviderValidationItem {
  stock_code?: string;
  trading_date?: string;
  field?: string;
  absolute_difference?: string | null;
  relative_difference?: string | null;
  conclusion?: string;
}

export interface ProviderValidationListData {
  items?: ProviderValidationItem[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
  summary?: { passed?: number; review?: number; failed?: number };
  tradable?: boolean;
  source_version?: string;
}

export interface TradingCalendarListData {
  items?: Array<{ exchange?: string; trading_date?: string; is_trading_day?: boolean; source?: string; status?: string }>;
  total?: number; page?: number; page_size?: number; has_more?: boolean;
  summary?: { confirmed?: number; unresolved?: number; coverage_from?: string | null; coverage_to?: string | null };
  tradable?: boolean; source_version?: string;
}

export interface TradingRuleListData {
  items?: Array<{ rule_type?: string; exchange?: string; board?: string; security_status?: string; effective_from?: string; effective_to?: string | null; value?: string | number | boolean; direction?: string; source_name?: string; source_reference?: string; rule_version?: string; source_hash?: string | null; source_hash_status?: string; parse_status?: string }>;
  total?: number; page?: number; page_size?: number; has_more?: boolean;
  registry_version?: string; tradable?: boolean;
}

export interface SecurityStatusListData {
  items?: Array<{ run_id?: string; stock_code?: string; effective_from?: string; effective_to?: string; status?: string; evidence_source?: string; evidence_version?: string; resolution_status?: string; price_limit_rule?: string | null; price_tick?: string | null; source_hash?: string | null; source_hash_status?: string }>;
  total?: number; page?: number; page_size?: number; has_more?: boolean;
  summary?: { unresolved?: number; provider_missing?: number; latest_reviewed_at?: string | null };
  tradable?: boolean; source_version?: string;
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

export function useStrategyRuntimeStatus() {
  return useReadOnlyDisplay<StrategyRuntimeStatusData>(
    () => get<StrategyRuntimeStatusData>("/strategy/runtime-status"),
    "strategy-runtime-status-v2",
  );
}

export function useCertifiedKlineLineage(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<CertifiedKlineLineageData>(
    () => get<CertifiedKlineLineageData>("/data/certified-klines", {
      period: "1d",
      adjustment: "raw",
      page,
      page_size: pageSize,
    }),
    `certified-kline-lineage-v1:raw:p${page}:s${pageSize}`,
  );
}

export function useCertificationBatches(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<CertificationBatchListData>(
    () => get<CertificationBatchListData>("/data/certification-batches", { page, page_size: pageSize }),
    `certification-batches-v1:p${page}:s${pageSize}`,
  );
}

export function useQualityResults(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<QualityResultListData>(
    () => get<QualityResultListData>("/data/quality-results", { page, page_size: pageSize }),
    `quality-results-v1:p${page}:s${pageSize}`,
  );
}

export function useDataBlockers(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<DataBlockerListData>(
    () => get<DataBlockerListData>("/data/blockers", { page, page_size: pageSize }),
    `data-blockers-v1:p${page}:s${pageSize}`,
  );
}

export function useProviderValidations(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<ProviderValidationListData>(
    () => get<ProviderValidationListData>("/data/provider-validations", { page, page_size: pageSize }),
    `provider-validations-v1:p${page}:s${pageSize}`,
  );
}

export function useTradingCalendar(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<TradingCalendarListData>(() => get<TradingCalendarListData>("/rules/trading-calendar", { page, page_size: pageSize }), `trading-calendar-v1:p${page}:s${pageSize}`);
}

export function useTradingRules(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<TradingRuleListData>(() => get<TradingRuleListData>("/rules/trading", { page, page_size: pageSize }), `trading-rules-v1:p${page}:s${pageSize}`);
}

export function useFeeRules(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<TradingRuleListData>(() => get<TradingRuleListData>("/rules/fees", { page, page_size: pageSize }), `fee-rules-v1:p${page}:s${pageSize}`);
}

export function useSecurityStatus(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<SecurityStatusListData>(() => get<SecurityStatusListData>("/market/security-status", { page, page_size: pageSize }), `security-status-v1:p${page}:s${pageSize}`);
}

export function useResearchEvidence(evidenceType: "announcement" | "news" | "financial_report", page = 1, pageSize = 50) {
  return useReadOnlyDisplay<ResearchEvidenceListData>(() => get<ResearchEvidenceListData>("/research/evidence", { evidence_type: evidenceType, page, page_size: pageSize }), `research-evidence-v2:${evidenceType}:p${page}:s${pageSize}`);
}

export function useResearchEvidenceDetail(evidenceId?: string) {
  return useReadOnlyDisplay<ResearchEvidenceDetail>(evidenceId ? () => get<ResearchEvidenceDetail>(`/research/evidence/${encodeURIComponent(evidenceId)}`) : undefined, `research-evidence-detail-v1:${evidenceId ?? "unselected"}`);
}

export function useFinancialLocationReviews(evidenceId?: string) {
  return useReadOnlyDisplay<FinancialLocationReviewListData>(evidenceId ? () => get<FinancialLocationReviewListData>(`/research/evidence/${encodeURIComponent(evidenceId)}/financial-location-reviews`, { page: 1, page_size: 50 }) : undefined, `financial-location-review-v1:${evidenceId ?? "unselected"}`);
}

export function usePortfolioSummary() {
  return useReadOnlyDisplay<PortfolioSnapshot>(() => get<PortfolioSnapshot>("/portfolio/summary", { mode: "simulation" }), "portfolio-summary-v1");
}

export function usePortfolioPositions() {
  return useReadOnlyDisplay<PortfolioPosition[]>(() => get<PortfolioPosition[]>("/portfolio/positions", { mode: "simulation" }), "portfolio-positions-v1");
}

export function useEquityCurve() {
  return useReadOnlyDisplay<EquityCurveData>(() => get<EquityCurveData>("/portfolio/equity-curve", { mode: "simulation", days: 30 }), "account-equity-curve-v1");
}

export function useRiskDashboard() {
  return useReadOnlyDisplay<RiskDashboardData>(() => get<RiskDashboardData>("/risk/dashboard", { mode: "simulation" }), "risk-dashboard-v1");
}

export function useRiskAlerts(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<RiskAlertListData>(() => get<RiskAlertListData>("/risk/alerts", { page, page_size: pageSize }), `risk-alerts-v1:p${page}:s${pageSize}`);
}

export function useRiskAlertsSummary() {
  return useReadOnlyDisplay<RiskAlertSummaryData>(() => get<RiskAlertSummaryData>("/risk/alerts/summary", { limit: 100 }), "risk-alerts-summary-v1");
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
  const health = useReadOnlyDisplay<HealthStatusData>(() => get<HealthStatusData>("/health"), "health-v1");
  const execution = useExecutionStatus();
  const market = useReadOnlyDisplay<MarketDataStatusData>(
    () => get<MarketDataStatusData>("/stock/market/status"),
    "market-quote-status-v1",
  );
  const equity = useReadOnlyDisplay<EquityCurveData>(
    () => get<EquityCurveData>("/portfolio/equity-curve", { mode: "simulation", days: 30 }),
    "account-equity-curve-v1",
  );
  const candidates = useReadOnlyDisplay<ResearchCandidateStatusData>(
    () => get<ResearchCandidateStatusData>("/research/candidate-status", { limit: 5 }),
    "research-candidate-status-v1",
  );
  const strategy = useStrategyRuntimeStatus();

  return { dashboard, summary, alerts, health, execution, market, equity, candidates, strategy };
}

export function useMarketStatus() {
  return useReadOnlyDisplay<MarketDataStatusData>(
    () => get<MarketDataStatusData>("/stock/market/status"),
    "market-quote-status-v2",
  );
}

export function useMarketQuoteBatches(page = 1, pageSize = 20) {
  return useReadOnlyDisplay<MarketQuoteBatchListData>(
    () => get<MarketQuoteBatchListData>("/stock/market/batches", { page, page_size: pageSize }),
    `market-quote-batches-v2:p${page}:s${pageSize}`,
  );
}

export function useObservedQuotes(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<ObservedQuoteListData>(() => get<ObservedQuoteListData>("/stock/quotes", { page, page_size: pageSize }), `market-observed-quotes-v1:p${page}:s${pageSize}`);
}

export function useObservedLiquidity(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<ObservedLiquidityListData>(() => get<ObservedLiquidityListData>("/stock/liquidity", { page, page_size: pageSize }), `market-observed-liquidity-v1:p${page}:s${pageSize}`);
}

export function useSystemHealth() {
  return useReadOnlyDisplay<SystemHealthData>(() => get<SystemHealthData>("/system/health"), "system-health-v1");
}

export function useSystemAlerts(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<SystemAlertListData>(() => get<SystemAlertListData>("/system/alerts", { page, page_size: pageSize }), `system-alerts-v1:p${page}:s${pageSize}`);
}

export function useSystemJobs(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<SystemJobListData>(() => get<SystemJobListData>("/system/jobs", { page, page_size: pageSize }), `system-jobs-v1:p${page}:s${pageSize}`);
}

export function useExecutionStatus() {
  return useReadOnlyDisplay<ExecutionStatusData>(
    () => get<ExecutionStatusData>("/trade/execution-status"),
    "execution-safety-v4",
  );
}

export function useTradeOrders(page = 1, pageSize = 50) {
  return useReadOnlyDisplay<TradeOrderListData>(
    () => get<TradeOrderListData>("/trade/orders", {
      mode: "simulation",
      days: 7,
      page,
      page_size: pageSize,
    }),
    `trade-orders-v2:simulation:7:p${page}:s${pageSize}`,
  );
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
  const execution = useExecutionStatus();

  return { mode, broker, exposure, execution };
}

export function useReadinessReviews() {
  return useReadOnlyDisplay<ReadinessListData>(
    () => get<ReadinessListData>("/research/readiness", { page: 1, page_size: 100 }),
    "field-readiness-v2",
  );
}

export function useResearchCandidateStatus(limit = 50) {
  return useReadOnlyDisplay<ResearchCandidateStatusData>(
    () => get<ResearchCandidateStatusData>("/research/candidate-status", { limit }),
    "research-candidate-status-v1",
  );
}

export function useBacktestTasks() {
  return useReadOnlyDisplay<BacktestTaskListData>(
    () => get<BacktestTaskListData>("/backtest/tasks", { limit: 20 }),
    "backtest-tasks-v1",
  );
}

export function useBacktestValidationSummary() {
  return useReadOnlyDisplay<BacktestValidationSummaryData>(
    () => get<BacktestValidationSummaryData>("/backtest/validation-summary"),
    "backtest-validation-summary-v1",
  );
}

export function useAiSignals() {
  return useReadOnlyDisplay<AiSignalListData>(
    () => get<AiSignalListData>("/ai/signals", { page: 1, page_size: 50 }),
    "ai-signals-v1",
  );
}

export function useAiAuditSummary() {
  return useReadOnlyDisplay<AiAuditSummaryData>(
    () => get<AiAuditSummaryData>("/ai/audit-summary", { days: 30 }),
    "ai-audit-v2",
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
