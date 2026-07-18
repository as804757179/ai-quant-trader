export type DisplayKind = "loading" | "live" | "empty" | "pending" | "forbidden" | "unavailable";

export interface DataProvenance {
  dataCutoff: string;
  sourceVersion: string;
  traceId: string;
}

export interface DisplayState<T> {
  kind: DisplayKind;
  data?: T;
  message: string;
  provenance: DataProvenance;
}

export type StatusTone = "pass" | "idle" | "review" | "reject" | "info";

export const DISPLAY_KIND_LABELS: Record<DisplayKind, string> = {
  loading: "加载中",
  live: "已接入",
  empty: "暂无数据",
  pending: "待接入",
  forbidden: "无权限",
  unavailable: "接口暂不可用",
};

export interface ReleaseLock {
  key:
    | "CERTIFIED_BACKTEST_EXECUTION_ENABLED"
    | "CERTIFIED_SCREENER_OUTPUT_ENABLED"
    | "TRADING_EXECUTION_ENABLED"
    | "LIVE_TRADING_ENABLED"
    | "AI_ORDER_ENABLED"
    | "ALLOW_SCHEDULED_ORDER";
  label: string;
  enabled: boolean;
  reason: string;
}

export const RELEASE_LOCKS: readonly ReleaseLock[] = [
  {
    key: "CERTIFIED_BACKTEST_EXECUTION_ENABLED",
    label: "可信回测发布",
    enabled: false,
    reason: "未开放公共回测执行",
  },
  {
    key: "CERTIFIED_SCREENER_OUTPUT_ENABLED",
    label: "真实选股输出",
    enabled: false,
    reason: "未开放候选发布",
  },
  {
    key: "TRADING_EXECUTION_ENABLED",
    label: "交易执行",
    enabled: false,
    reason: "执行门禁关闭",
  },
  {
    key: "LIVE_TRADING_ENABLED",
    label: "实盘交易",
    enabled: false,
    reason: "Live 安全锁关闭",
  },
  {
    key: "AI_ORDER_ENABLED",
    label: "AI 下单",
    enabled: false,
    reason: "AI 仅可分析和推荐",
  },
  {
    key: "ALLOW_SCHEDULED_ORDER",
    label: "定时任务下单",
    enabled: false,
    reason: "定时任务不得自动产生订单",
  },
];
