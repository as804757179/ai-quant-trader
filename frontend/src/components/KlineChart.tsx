/**
 * 同花顺 / 支付宝风格 A 股 K 线面板
 * - 默认「分时」（当日 1 分钟）
 * - 周期：分时 / 5分 / 15分 / 30分 / 60分 / 日K / 周K / 月K
 * - 红涨绿跌、成交量、日K 均线
 */
import { Alert, Button, Segmented, Space, Spin, Typography } from "antd";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get, post } from "../api/client";

const { Text } = Typography;

export type ChartPeriod =
  | "timeline" // 分时
  | "5min"
  | "15min"
  | "30min"
  | "60min"
  | "1d"
  | "1w"
  | "1M";

const PERIOD_TABS: { value: ChartPeriod; label: string }[] = [
  { value: "timeline", label: "分时" },
  { value: "5min", label: "5分" },
  { value: "15min", label: "15分" },
  { value: "30min", label: "30分" },
  { value: "60min", label: "60分" },
  { value: "1d", label: "日K" },
  { value: "1w", label: "周K" },
  { value: "1M", label: "月K" },
];

const PERIOD_API: Record<ChartPeriod, string> = {
  timeline: "1min",
  "5min": "5min",
  "15min": "15min",
  "30min": "30min",
  "60min": "60min",
  "1d": "1d",
  "1w": "1w",
  "1M": "1M",
};

const PERIOD_LIMIT: Record<ChartPeriod, number> = {
  timeline: 241, // 约一个交易日 1 分钟
  "5min": 200,
  "15min": 200,
  "30min": 200,
  "60min": 200,
  "1d": 250,
  "1w": 200,
  "1M": 120,
};

interface KlineRaw {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface QuoteSnap {
  price?: number;
  open?: number;
  high?: number;
  low?: number;
  prev_close?: number;
  change?: number;
  change_pct?: number;
  volume?: number;
  volume_shares?: number;
  amount?: number;
  turnover_rate?: number;
  volume_ratio?: number;
  amplitude?: number;
  avg_price?: number;
  pe_ratio?: number;
  pb_ratio?: number;
  float_mv?: number;
  total_mv?: number;
  outer_vol?: number;
  inner_vol?: number;
  limit_up?: number;
  limit_down?: number;
  commission_ratio?: number;
  trade_time?: string;
  name?: string;
  bid1_price?: number;
  bid1_vol?: number;
  bid2_price?: number;
  bid2_vol?: number;
  bid3_price?: number;
  bid3_vol?: number;
  bid4_price?: number;
  bid4_vol?: number;
  bid5_price?: number;
  bid5_vol?: number;
  ask1_price?: number;
  ask1_vol?: number;
  ask2_price?: number;
  ask2_vol?: number;
  ask3_price?: number;
  ask3_vol?: number;
  ask4_price?: number;
  ask4_vol?: number;
  ask5_price?: number;
  ask5_vol?: number;
}

export interface KlineChartProps {
  code: string;
  name?: string;
  quote?: QuoteSnap | null;
  height?: number;
}

/** 十字光标当前 K 线详情 */
interface HoverBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change?: number;
  change_pct?: number;
}

function toCnDate(d: Date): string {
  return d.toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
}

function parseTs(raw: string): number {
  const t = new Date(raw).getTime();
  return Number.isFinite(t) ? t : 0;
}

function toUtcSec(raw: string): UTCTimestamp {
  return Math.floor(parseTs(raw) / 1000) as UTCTimestamp;
}

function toDayStr(raw: string): string {
  try {
    return toCnDate(new Date(raw));
  } catch {
    return String(raw).slice(0, 10);
  }
}

function calcMA(closes: number[], n: number): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i + 1 < n) {
      out.push(null);
      continue;
    }
    let s = 0;
    for (let j = i - n + 1; j <= i; j++) s += closes[j];
    out.push(s / n);
  }
  return out;
}

function fmt(n: number | undefined | null, d = 2): string {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toFixed(d);
}

function fmtSigned(n: number | undefined | null, d = 2): string {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const s = v > 0 ? "+" : "";
  return `${s}${v.toFixed(d)}`;
}

/** 成交量：手 → 万手/手 */
function fmtVolHands(hands: number | undefined | null): string {
  if (hands == null || Number.isNaN(Number(hands))) return "—";
  const v = Number(hands);
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(2)}万手`;
  return `${v.toFixed(0)}手`;
}

/** 成交额：元 → 亿/万 */
function fmtAmount(yuan: number | undefined | null): string {
  if (yuan == null || Number.isNaN(Number(yuan))) return "—";
  const v = Number(yuan);
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toFixed(0);
}

/** 市值：腾讯为亿 */
function fmtYi(yi: number | undefined | null): string {
  if (yi == null || Number.isNaN(Number(yi)) || Number(yi) === 0) return "—";
  const v = Number(yi);
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(2)}万亿`;
  return `${v.toFixed(2)}亿`;
}

function pnlColor(v: number | undefined | null): string {
  if (v == null || Number(v) === 0) return "rgba(0,0,0,0.85)";
  return Number(v) > 0 ? "#cf1322" : "#389e0d";
}

function StatCell({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 12, color: "rgba(0,0,0,0.45)", lineHeight: 1.3 }}>{label}</div>
      <div
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: color || "rgba(0,0,0,0.88)",
          lineHeight: 1.35,
          fontVariantNumeric: "tabular-nums",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </div>
    </div>
  );
}

export default function KlineChart({ code, name, quote, height = 420 }: KlineChartProps) {
  const [period, setPeriod] = useState<ChartPeriod>("timeline");
  const [loading, setLoading] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [tick, setTick] = useState(0);
  const [barCount, setBarCount] = useState(0);
  const [chartReady, setChartReady] = useState(0);
  const [hover, setHover] = useState<HoverBar | null>(null);
  const [liveQuote, setLiveQuote] = useState<QuoteSnap | null>(null);

  const wrapRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const volRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const volChartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lineRef = useRef<ISeriesApi<"Area"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma5Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma10Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const rawRef = useRef<KlineRaw[]>([]);
  const barsIndexRef = useRef<Map<string | number, HoverBar>>(new Map());

  const isTimeline = period === "timeline";
  const isDayLike = period === "1d" || period === "1w" || period === "1M";

  const destroyCharts = useCallback(() => {
    chartRef.current?.remove();
    volChartRef.current?.remove();
    chartRef.current = null;
    volChartRef.current = null;
    candleRef.current = null;
    lineRef.current = null;
    volSeriesRef.current = null;
    ma5Ref.current = null;
    ma10Ref.current = null;
    ma20Ref.current = null;
  }, []);

  // 创建图表（白底同花顺/支付宝风格）
  useEffect(() => {
    if (!mainRef.current || !volRef.current) return;
    destroyCharts();

    const w = Math.max(mainRef.current.clientWidth || 400, 200);
    const mainH = Math.max(Math.floor(height * 0.72), 240);
    const volH = Math.max(Math.floor(height * 0.28), 90);

    const common = {
      width: w,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "rgba(0,0,0,0.65)",
      },
      grid: {
        vertLines: { color: "rgba(0,0,0,0.06)" },
        horzLines: { color: "rgba(0,0,0,0.06)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(0,0,0,0.08)" },
      timeScale: {
        borderColor: "rgba(0,0,0,0.08)",
        timeVisible: !isDayLike,
        secondsVisible: false,
      },
    };

    const main = createChart(mainRef.current, { ...common, height: mainH });
    const vol = createChart(volRef.current, {
      ...common,
      height: volH,
      timeScale: { ...common.timeScale, visible: true },
    });

    chartRef.current = main;
    volChartRef.current = vol;

    if (isTimeline) {
      lineRef.current = main.addAreaSeries({
        lineColor: "#1677ff",
        topColor: "rgba(22,119,255,0.25)",
        bottomColor: "rgba(22,119,255,0.02)",
        lineWidth: 2,
        priceLineVisible: true,
      });
    } else {
      candleRef.current = main.addCandlestickSeries({
        upColor: "#cf1322",
        downColor: "#389e0d",
        borderUpColor: "#cf1322",
        borderDownColor: "#389e0d",
        wickUpColor: "#cf1322",
        wickDownColor: "#389e0d",
      });
      if (isDayLike) {
        ma5Ref.current = main.addLineSeries({ color: "#fa8c16", lineWidth: 1, priceLineVisible: false });
        ma10Ref.current = main.addLineSeries({ color: "#1677ff", lineWidth: 1, priceLineVisible: false });
        ma20Ref.current = main.addLineSeries({ color: "#722ed1", lineWidth: 1, priceLineVisible: false });
      }
    }

    volSeriesRef.current = vol.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    vol.priceScale("").applyOptions({ scaleMargins: { top: 0.15, bottom: 0 } });

    main.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) vol.timeScale().setVisibleLogicalRange(range);
    });
    vol.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) main.timeScale().setVisibleLogicalRange(range);
    });

    // 十字光标：显示当前 K 线 开高低收量
    main.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point) {
        setHover(null);
        return;
      }
      const key = param.time as string | number;
      const hit = barsIndexRef.current.get(key);
      if (hit) setHover(hit);
      else setHover(null);
    });

    const ro = new ResizeObserver(() => {
      if (!mainRef.current || !volRef.current) return;
      const nw = Math.max(mainRef.current.clientWidth, 200);
      main.applyOptions({ width: nw });
      vol.applyOptions({ width: nw });
    });
    ro.observe(mainRef.current);

    setChartReady((n) => n + 1);

    return () => {
      ro.disconnect();
      destroyCharts();
    };
  }, [code, period, height, isTimeline, isDayLike, destroyCharts]);

  const paintRaw = useCallback(
    (rawIn: KlineRaw[]) => {
      let raw = rawIn;
      if (period === "timeline" && raw.length) {
        const lastDay = toDayStr(raw[raw.length - 1].time);
        raw = raw.filter((k) => toDayStr(k.time) === lastDay);
      }
      if (!raw.length) {
        setEmpty(true);
        setBarCount(0);
        return;
      }

      const useUnix = !isDayLike || period === "timeline";

      try {
        if (isTimeline && lineRef.current) {
          const map = new Map<number, number>();
          raw.forEach((k) => {
            const t = toUtcSec(k.time) as number;
            const v = Number(k.close);
            if (t > 0 && Number.isFinite(v)) map.set(t, v);
          });
          const pts = Array.from(map.entries())
            .map(([time, value]) => ({ time: time as UTCTimestamp, value }))
            .sort((a, b) => (a.time as number) - (b.time as number));
          lineRef.current.setData(pts);
          const idx = new Map<string | number, HoverBar>();
          raw.forEach((k) => {
            const t = toUtcSec(k.time) as number;
            if (t <= 0) return;
            const open = Number(k.open);
            const close = Number(k.close);
            idx.set(t, {
              time: String(k.time),
              open,
              high: Number(k.high),
              low: Number(k.low),
              close,
              volume: Number(k.volume || 0),
              change: close - open,
              change_pct: open ? ((close - open) / open) * 100 : 0,
            });
          });
          barsIndexRef.current = idx;
          if (volSeriesRef.current) {
            const vmap = new Map<number, { time: UTCTimestamp; value: number; color: string }>();
            raw.forEach((k) => {
              const t = toUtcSec(k.time) as number;
              if (t <= 0) return;
              vmap.set(t, {
                time: t as UTCTimestamp,
                value: Number(k.volume || 0),
                color:
                  Number(k.close) >= Number(k.open)
                    ? "rgba(207,19,34,0.45)"
                    : "rgba(56,158,13,0.45)",
              });
            });
            volSeriesRef.current.setData(
              Array.from(vmap.values()).sort(
                (a, b) => (a.time as number) - (b.time as number)
              ) as never
            );
          }
          setBarCount(pts.length);
          setEmpty(pts.length === 0);
        } else if (candleRef.current) {

          type CBar = {
            time: string | UTCTimestamp;
            open: number;
            high: number;
            low: number;
            close: number;
            volume: number;
          };
          const map = new Map<string | number, CBar>();
          for (const k of raw) {
            const time = (useUnix ? toUtcSec(k.time) : toDayStr(k.time)) as
              | string
              | UTCTimestamp;
            const open = Number(k.open);
            const high = Number(k.high);
            const low = Number(k.low);
            const close = Number(k.close);
            if (
              !Number.isFinite(open) ||
              !Number.isFinite(high) ||
              !Number.isFinite(low) ||
              !Number.isFinite(close) ||
              high < low
            ) {
              continue;
            }
            map.set(time as string | number, {
              time,
              open,
              high,
              low,
              close,
              volume: Number(k.volume || 0),
            });
          }
          const unique = Array.from(map.values()).sort((a, b) => {
            if (typeof a.time === "number" && typeof b.time === "number") return a.time - b.time;
            return String(a.time) < String(b.time) ? -1 : 1;
          });
          candleRef.current.setData(
            unique.map((b) => ({
              time: b.time as never,
              open: b.open,
              high: b.high,
              low: b.low,
              close: b.close,
            }))
          );
          const idx = new Map<string | number, HoverBar>();
          unique.forEach((b, i) => {
            const prev = i > 0 ? unique[i - 1].close : b.open;
            idx.set(b.time as string | number, {
              time: String(b.time),
              open: b.open,
              high: b.high,
              low: b.low,
              close: b.close,
              volume: b.volume,
              change: b.close - prev,
              change_pct: prev ? ((b.close - prev) / prev) * 100 : 0,
            });
          });
          barsIndexRef.current = idx;
          if (isDayLike && ma5Ref.current && ma10Ref.current && ma20Ref.current) {
            const closes = unique.map((b) => b.close);
            const ma5 = calcMA(closes, 5);
            const ma10 = calcMA(closes, 10);
            const ma20 = calcMA(closes, 20);
            const mk = (arr: (number | null)[]) =>
              unique
                .map((b, i) =>
                  arr[i] == null ? null : { time: b.time as never, value: arr[i] as number }
                )
                .filter(Boolean) as { time: never; value: number }[];
            ma5Ref.current.setData(mk(ma5));
            ma10Ref.current.setData(mk(ma10));
            ma20Ref.current.setData(mk(ma20));
          }
          if (volSeriesRef.current) {
            volSeriesRef.current.setData(
              unique.map((b) => ({
                time: b.time as never,
                value: b.volume,
                color:
                  b.close >= b.open ? "rgba(207,19,34,0.55)" : "rgba(56,158,13,0.55)",
              }))
            );
          }
          setBarCount(unique.length);
          setEmpty(unique.length === 0);
        } else {
          // 图表尚未就绪，等待 chartReady 再绘
          return;
        }
        chartRef.current?.timeScale().fitContent();
        volChartRef.current?.timeScale().fitContent();
      } catch (e) {
        console.warn("paint kline failed", e);
        setEmpty(true);
      }
    },
    [period, isTimeline, isDayLike]
  );

  // 图表就绪后补绘
  useEffect(() => {
    if (chartReady > 0 && rawRef.current.length) {
      paintRaw(rawRef.current);
    }
  }, [chartReady, paintRaw]);

  // 拉数（空数据时自动回填一次再拉）
  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    setLoading(true);
    setEmpty(false);
    setLoadError(null);

    (async () => {
      const apiPeriod = PERIOD_API[period];
      const limit = PERIOD_LIMIT[period];

      const loadOnce = async (): Promise<KlineRaw[]> => {
        const res = await get<KlineRaw[]>(`/stock/${code}/kline`, {
          period: apiPeriod,
          limit,
        });
        return Array.isArray(res.data) ? res.data : [];
      };

      try {
        let raw = await loadOnce();
        // 空数据：自动回填再拉（解决 8080 挂掉 / 库内无分钟线）
        if (!raw.length) {
          try {
            await post("/stock/backfill-kline", {
              codes: [code],
              period: apiPeriod,
              limit: Math.min(limit, 250),
              allow_synthetic: true,
            });
            raw = await loadOnce();
          } catch {
            /* 回填失败仍走空态 */
          }
        }
        // 分时仍空：再试 5 分钟线
        if (!raw.length && period === "timeline") {
          try {
            const res5 = await get<KlineRaw[]>(`/stock/${code}/kline`, {
              period: "5min",
              limit: 120,
            });
            raw = Array.isArray(res5.data) ? res5.data : [];
          } catch {
            /* ignore */
          }
        }

        if (cancelled) return;
        rawRef.current = raw;
        if (!raw.length) {
          setEmpty(true);
          setBarCount(0);
          setLoadError(
            "未拉到 K 线。请确认：①后端 8000 ②行情 8080 ③网络可访问新浪；然后点「刷新/回填」。"
          );
          return;
        }
        setLoadError(null);
        paintRaw(raw);
      } catch (e) {
        if (!cancelled) {
          rawRef.current = [];
          setEmpty(true);
          setBarCount(0);
          setLoadError(
            e instanceof Error
              ? `加载失败：${e.message}。请先启动后端(8000)与行情(8080)。`
              : "加载失败，请启动后端与行情服务"
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, period, tick, paintRaw]);

  const onBackfill = async () => {
    setBackfilling(true);
    try {
      const apiPeriod = PERIOD_API[period];
      await post("/stock/backfill-kline", {
        codes: [code],
        period: apiPeriod === "1min" ? "1min" : apiPeriod,
        limit: PERIOD_LIMIT[period],
        allow_synthetic: true,
      });
      setTick((t) => t + 1);
    } catch {
      /* ignore */
    } finally {
      setBackfilling(false);
    }
  };

  // 定时刷新实时行情（与父组件 quote 合并）
  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    const pull = async () => {
      try {
        const res = await get<QuoteSnap>(`/stock/${code}/quote`);
        if (!cancelled && res?.data) setLiveQuote(res.data);
      } catch {
        /* ignore */
      }
    };
    void pull();
    const t = window.setInterval(pull, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [code, tick]);

  const q: QuoteSnap = { ...(quote || {}), ...(liveQuote || {}) };
  const chg = q.change_pct;
  const color = pnlColor(chg);
  const openColor = pnlColor(
    q.open != null && q.prev_close != null ? q.open - q.prev_close : 0
  );
  const highColor = pnlColor(
    q.high != null && q.prev_close != null ? q.high - q.prev_close : 0
  );
  const lowColor = pnlColor(
    q.low != null && q.prev_close != null ? q.low - q.prev_close : 0
  );

  // 支付宝式指标网格：两行多列
  const metrics = useMemo(
    () => [
      { label: "今开", value: fmt(q.open), color: openColor },
      { label: "最高", value: fmt(q.high), color: highColor },
      { label: "最低", value: fmt(q.low), color: lowColor },
      { label: "昨收", value: fmt(q.prev_close) },
      { label: "成交量", value: fmtVolHands(q.volume) },
      { label: "成交额", value: fmtAmount(q.amount) },
      {
        label: "换手率",
        value: q.turnover_rate != null ? `${fmt(q.turnover_rate)}%` : "—",
      },
      { label: "量比", value: fmt(q.volume_ratio, 2) },
      {
        label: "振幅",
        value: q.amplitude != null ? `${fmt(q.amplitude)}%` : "—",
      },
      { label: "均价", value: fmt(q.avg_price, 3) },
      { label: "涨停", value: fmt(q.limit_up), color: "#cf1322" },
      { label: "跌停", value: fmt(q.limit_down), color: "#389e0d" },
      {
        label: "市盈率",
        value: q.pe_ratio ? fmt(q.pe_ratio, 2) : "—",
      },
      {
        label: "市净率",
        value: q.pb_ratio ? fmt(q.pb_ratio, 2) : "—",
      },
      { label: "总市值", value: fmtYi(q.total_mv) },
      { label: "流通值", value: fmtYi(q.float_mv) },
      { label: "外盘", value: fmtVolHands(q.outer_vol), color: "#cf1322" },
      { label: "内盘", value: fmtVolHands(q.inner_vol), color: "#389e0d" },
      {
        label: "委比",
        value: q.commission_ratio != null ? `${fmtSigned(q.commission_ratio)}%` : "—",
        color: pnlColor(q.commission_ratio),
      },
      {
        label: "涨跌额",
        value: fmtSigned(q.change),
        color,
      },
    ],
    [q, openColor, highColor, lowColor, color]
  );

  const levels = useMemo(() => {
    const rows: { side: "买" | "卖"; i: number; price?: number; vol?: number }[] = [];
    for (let i = 5; i >= 1; i--) {
      rows.push({
        side: "卖",
        i,
        price: q[`ask${i}_price` as keyof QuoteSnap] as number | undefined,
        vol: q[`ask${i}_vol` as keyof QuoteSnap] as number | undefined,
      });
    }
    for (let i = 1; i <= 5; i++) {
      rows.push({
        side: "买",
        i,
        price: q[`bid${i}_price` as keyof QuoteSnap] as number | undefined,
        vol: q[`bid${i}_vol` as keyof QuoteSnap] as number | undefined,
      });
    }
    return rows;
  }, [q]);

  return (
    <div ref={wrapRef} style={{ width: "100%" }}>
      {/* 报价头 + 指标 + 五档：支付宝/同花顺风格 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(160px, 220px) 1fr minmax(140px, 180px)",
          gap: 12,
          marginBottom: 12,
          paddingBottom: 10,
          borderBottom: "1px solid rgba(0,0,0,0.06)",
        }}
        className="quote-head-grid"
      >
        <style>{`
          @media (max-width: 900px) {
            .quote-head-grid { grid-template-columns: 1fr !important; }
          }
        `}</style>

        {/* 左侧大字报价 */}
        <div>
          <div style={{ fontSize: 12, color: "rgba(0,0,0,0.45)" }}>
            {code} {name || q.name || ""}
            {q.trade_time ? (
              <span style={{ marginLeft: 8 }}>更新 {q.trade_time}</span>
            ) : null}
          </div>
          <div style={{ fontSize: 36, fontWeight: 700, color, lineHeight: 1.05, marginTop: 2 }}>
            {fmt(q.price)}
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 4, fontSize: 15, fontWeight: 600, color }}>
            <span>{fmtSigned(q.change)}</span>
            <span>{chg != null ? `${fmtSigned(chg)}%` : "—"}</span>
          </div>
          {/* 十字光标 K 线明细 */}
          {hover && (
            <div
              style={{
                marginTop: 8,
                fontSize: 12,
                lineHeight: 1.6,
                color: "rgba(0,0,0,0.65)",
                background: "rgba(0,0,0,0.03)",
                borderRadius: 6,
                padding: "6px 8px",
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 2 }}>K线 {hover.time}</div>
              <div>
                开 <b style={{ color: pnlColor(hover.open - (q.prev_close || hover.open)) }}>{fmt(hover.open)}</b>
                {"  "}高 <b style={{ color: "#cf1322" }}>{fmt(hover.high)}</b>
              </div>
              <div>
                低 <b style={{ color: "#389e0d" }}>{fmt(hover.low)}</b>
                {"  "}收 <b style={{ color: pnlColor(hover.change) }}>{fmt(hover.close)}</b>
              </div>
              <div>
                量 <b>{fmtVolHands(hover.volume)}</b>
                {"  "}涨跌 <b style={{ color: pnlColor(hover.change) }}>{fmtSigned(hover.change_pct)}%</b>
              </div>
            </div>
          )}
        </div>

        {/* 中间指标网格 */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(88px, 1fr))",
            gap: "8px 12px",
            alignContent: "start",
          }}
        >
          {metrics.map((m) => (
            <StatCell key={m.label} label={m.label} value={m.value} color={m.color} />
          ))}
        </div>

        {/* 右侧五档盘口 */}
        <div
          style={{
            border: "1px solid rgba(0,0,0,0.06)",
            borderRadius: 8,
            padding: "6px 8px",
            fontSize: 12,
            background: "#fafafa",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4, color: "rgba(0,0,0,0.65)" }}>五档盘口</div>
          {levels.map((lv) => (
            <div
              key={`${lv.side}${lv.i}`}
              style={{
                display: "grid",
                gridTemplateColumns: "36px 1fr 48px",
                gap: 4,
                lineHeight: 1.55,
                color: lv.side === "卖" ? "#389e0d" : "#cf1322",
              }}
            >
              <span style={{ color: "rgba(0,0,0,0.45)" }}>
                {lv.side}
                {lv.i}
              </span>
              <span style={{ fontVariantNumeric: "tabular-nums", textAlign: "right" }}>
                {lv.price ? fmt(lv.price) : "—"}
              </span>
              <span
                style={{
                  color: "rgba(0,0,0,0.55)",
                  textAlign: "right",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {lv.vol != null ? lv.vol : "—"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 周期切换 */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "space-between",
          gap: 8,
          marginBottom: 10,
          alignItems: "center",
        }}
      >
        <Segmented
          size="small"
          value={period}
          onChange={(v) => setPeriod(v as ChartPeriod)}
          options={PERIOD_TABS.map((p) => ({ value: p.value, label: p.label }))}
        />
        <Space size={8} wrap>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {isTimeline ? "当日分时" : PERIOD_TABS.find((p) => p.value === period)?.label}
            {barCount > 0 ? ` · ${barCount} 根` : ""}
            {isDayLike ? " · MA5/10/20" : ""}
          </Text>
          <Button size="small" loading={backfilling} onClick={() => void onBackfill()}>
            刷新/回填
          </Button>
        </Space>
      </div>

      <Spin spinning={loading || backfilling}>
        {(empty || loadError) && !loading && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 8 }}
            message={loadError ? "K 线加载失败" : "暂无该周期 K 线"}
            description={
              loadError ||
              "接口无数据。常见原因：后端 8000 / 行情 8080 未启动。请点击「刷新/回填」重试。"
            }
          />
        )}
        <div
          style={{
            border: "1px solid rgba(0,0,0,0.06)",
            borderRadius: 8,
            overflow: "hidden",
            background: "#fff",
          }}
        >
          <div ref={mainRef} style={{ width: "100%", height: Math.floor(height * 0.72) }} />
          <div
            ref={volRef}
            style={{
              width: "100%",
              height: Math.floor(height * 0.28),
              borderTop: "1px solid rgba(0,0,0,0.06)",
            }}
          />
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginTop: 6,
            fontSize: 11,
            color: "rgba(0,0,0,0.35)",
          }}
        >
          <span>红涨绿跌 · 参考同花顺/支付宝</span>
          <span>
            {isDayLike && (
              <>
                <span style={{ color: "#fa8c16" }}>MA5</span>{" "}
                <span style={{ color: "#1677ff" }}>MA10</span>{" "}
                <span style={{ color: "#722ed1" }}>MA20</span>
              </>
            )}
          </span>
        </div>
      </Spin>
    </div>
  );
}
