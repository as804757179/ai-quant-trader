/**
 * 模拟交易台 — 参考常见券商/纸面交易终端布局：
 * 顶部账户资产条 + 模式切换 | 左侧下单票 | 右侧持仓/委托 Tab
 * A 股展示惯例：红涨绿跌
 */
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  Row,
  Segmented,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get, getLiveConfirmToken, post } from "../api/client";
import PageShell from "../components/PageShell";
import { useWebSocket } from "../hooks/useWebSocket";

const { Text } = Typography;

type TradeMode = "simulation" | "paper" | "live";

interface Summary {
  total_assets?: number;
  cash?: number;
  market_value?: number;
  daily_pnl?: number;
  daily_pnl_pct?: number;
  position_count?: number;
  is_fused?: boolean;
  mode?: string;
}

interface Position {
  stock_code: string;
  name?: string;
  total_qty?: number;
  available_qty?: number;
  avg_cost?: number;
  current_price?: number;
  market_value?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  price_source?: string;
}

interface OrderRow {
  id: string;
  stock_code: string;
  side: string;
  order_type?: string;
  quantity: number;
  limit_price?: number | string;
  filled_quantity?: number;
  avg_fill_price?: number | string;
  status: string;
  created_at?: string;
  broker_order_id?: string | null;
}

interface StockOpt {
  value: string;
  label: string;
  code: string;
  name: string;
}

interface QuoteSnap {
  price?: number;
  change_pct?: number;
  prev_close?: number;
}

const MODE_OPTS = [
  { value: "simulation", label: "模拟盘" },
  { value: "paper", label: "纸面交易" },
  { value: "live", label: "实盘" },
];

const MODE_HELP: Record<TradeMode, string> = {
  simulation:
    "真实行情本地撮合（非券商下单）：A股 T+1、涨跌停、100股/手、佣金/印花税；无真实资金。",
  paper: "纸面/Mock 券商通道，非真实资金，可演练对账与同步。",
  live: "真实券商通道。请确认令牌与 QMT；生产环境务必关闭 Mock 降级。",
};

/** A 股：红涨绿跌 */
function pnlColor(v: number | undefined | null): string {
  if (v == null || Number.isNaN(Number(v)) || Number(v) === 0) return "inherit";
  return Number(v) > 0 ? "#cf1322" : "#389e0d";
}

function fmtMoney(v: number | undefined | null, digits = 2): string {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtPct(v: number | undefined | null): string {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function statusTag(status: string) {
  const s = String(status || "").toUpperCase();
  const map: Record<string, { color: string; text: string }> = {
    FILLED: { color: "success", text: "已成交" },
    PARTIAL: { color: "processing", text: "部分成交" },
    PENDING: { color: "warning", text: "待报" },
    SUBMITTED: { color: "processing", text: "已报" },
    CANCELLED: { color: "default", text: "已撤" },
    REJECTED: { color: "error", text: "废单" },
    FAILED: { color: "error", text: "失败" },
  };
  const m = map[s] || { color: "default", text: s || "—" };
  return <Tag color={m.color}>{m.text}</Tag>;
}

function sideTag(side: string) {
  const buy = String(side).toUpperCase() === "BUY";
  return <Tag color={buy ? "red" : "green"}>{buy ? "买入" : "卖出"}</Tag>;
}

export default function Trade() {
  const [mode, setMode] = useState<TradeMode>("simulation");
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [riskMsg, setRiskMsg] = useState<string | null>(null);
  const [broker, setBroker] = useState<Record<string, unknown> | null>(null);
  const [modeInfo, setModeInfo] = useState<Record<string, unknown> | null>(null);
  const [wsHint, setWsHint] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [stockOptions, setStockOptions] = useState<StockOpt[]>([]);
  const [quote, setQuote] = useState<QuoteSnap | null>(null);
  const [stockName, setStockName] = useState("");
  const [form] = Form.useForm();
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const side = Form.useWatch("side", form) || "BUY";
  const orderType = Form.useWatch("order_type", form) || "LIMIT";
  const stockCode = Form.useWatch("stock_code", form) || "";
  const limitPrice = Form.useWatch("limit_price", form);
  const quantity = Form.useWatch("quantity", form);

  const { connected: wsConnected } = useWebSocket(
    `/ws/portfolio?mode=${encodeURIComponent(mode)}`,
    (msg) => {
      const m = msg as { type?: string; status?: string; stock_code?: string };
      if (
        m?.type === "order_filled" ||
        m?.type === "order_status" ||
        m?.type === "order_update"
      ) {
        setWsHint(
          m.type === "order_filled"
            ? `成交通知：${m.stock_code || ""} ${m.status || ""}`
            : `订单更新：${m.stock_code || ""} ${m.status || ""}`
        );
        void refreshAll(mode);
      }
    },
    { enabled: true }
  );

  const refreshAll = useCallback(async (m: TradeMode) => {
    try {
      const [posRes, sumRes, ordRes] = await Promise.all([
        get<Position[]>("/portfolio/positions", { mode: m }),
        get<Summary>("/portfolio/summary", { mode: m }),
        get<{ items: OrderRow[] }>("/trade/orders", { mode: m, page_size: 50 }),
      ]);
      setPositions(posRes.data || []);
      setSummary(sumRes.data || null);
      setOrders(ordRes.data?.items || []);
    } catch {
      message.warning("账户数据刷新失败，请确认后端已启动");
    }
  }, []);

  const loadMeta = useCallback(() => {
    get<Record<string, unknown>>("/trade/mode")
      .then((res) => setModeInfo(res.data || {}))
      .catch(() => setModeInfo(null));
    get<Record<string, unknown>>("/trade/broker-status")
      .then((res) => setBroker(res.data || {}))
      .catch(() => setBroker(null));
  }, []);

  useEffect(() => {
    form.setFieldsValue({
      side: "BUY",
      order_type: "LIMIT",
      quantity: 100,
      stock_code: "000001",
      limit_price: undefined,
    });
    void refreshAll(mode);
    loadMeta();
  }, [mode, form, refreshAll, loadMeta]);

  // 代码变化 → 拉名称与行情，限价默认填现价
  useEffect(() => {
    const code = String(stockCode || "").trim();
    if (!/^\d{6}$/.test(code)) {
      setQuote(null);
      setStockName("");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [qRes, listRes] = await Promise.all([
          get<QuoteSnap>(`/stock/${code}/quote`).catch(() => null),
          get<{ items: { code: string; name: string }[] }>("/stock/list", {
            keyword: code,
            page_size: 5,
          }).catch(() => null),
        ]);
        if (cancelled) return;
        const quoteData = qRes?.data ?? null;
        setQuote(quoteData);
        const items = listRes?.data?.items || [];
        const hit = items.find((x) => x.code === code);
        setStockName(hit?.name || "");
        const price = quoteData?.price;
        if (price && form.getFieldValue("order_type") === "LIMIT") {
          const cur = form.getFieldValue("limit_price");
          if (cur == null || cur === "" || cur === 0) {
            form.setFieldValue("limit_price", Number(Number(price).toFixed(2)));
          }
        }
      } catch {
        if (!cancelled) setQuote(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [stockCode, form]);

  const searchStocks = (text: string) => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(async () => {
      const kw = text.trim();
      if (!kw) {
        setStockOptions([]);
        return;
      }
      try {
        const res = await get<{ items: { code: string; name: string }[] }>("/stock/list", {
          keyword: kw,
          page_size: 20,
        });
        const opts: StockOpt[] = (res.data?.items || []).map((s) => ({
          value: s.code,
          code: s.code,
          name: s.name,
          label: `${s.code} ${s.name}`,
        }));
        setStockOptions(opts);
      } catch {
        setStockOptions([]);
      }
    }, 280);
  };

  const effectivePrice = useMemo(() => {
    if (orderType === "MARKET") return Number(quote?.price || 0);
    return Number(limitPrice || quote?.price || 0);
  }, [orderType, limitPrice, quote]);

  const estimateAmount = useMemo(() => {
    const qty = Number(quantity || 0);
    if (!qty || !effectivePrice) return 0;
    return qty * effectivePrice;
  }, [quantity, effectivePrice]);

  const cash = Number(summary?.cash || 0);

  const setQtyByFraction = (frac: number) => {
    const price = effectivePrice;
    if (side === "BUY") {
      if (!price || price <= 0) {
        message.info("请先填写价格或等待行情");
        return;
      }
      // A 股 100 股一手，向下取整
      let lots = Math.floor((cash * frac) / price / 100);
      if (lots < 1 && cash >= price * 100) lots = 1;
      form.setFieldValue("quantity", Math.max(lots * 100, 0));
    } else {
      const code = String(form.getFieldValue("stock_code") || "");
      const pos = positions.find((p) => p.stock_code === code);
      const avail = Number(pos?.available_qty ?? pos?.total_qty ?? 0);
      const qty = Math.floor((avail * frac) / 100) * 100;
      form.setFieldValue("quantity", Math.max(qty, 0));
    }
  };

  const fillFromPosition = (pos: Position, asSell = true) => {
    const price = pos.current_price != null ? Number(Number(pos.current_price).toFixed(2)) : undefined;
    const avail = Number(pos.available_qty || 0);
    const total = Number(pos.total_qty || 0);
    if (asSell) {
      if (avail <= 0) {
        message.warning(
          `${pos.stock_code} 可卖为 0（T+1：当日买入次日可卖）。持仓 ${total} 股，请点「释放T+1」或等下一交易日。`
        );
        form.setFieldsValue({
          stock_code: pos.stock_code,
          side: "SELL",
          order_type: "MARKET",
          limit_price: price,
          quantity: total >= 100 ? Math.floor(total / 100) * 100 : total,
        });
      } else {
        const qty = avail >= 100 ? Math.floor(avail / 100) * 100 : avail;
        form.setFieldsValue({
          stock_code: pos.stock_code,
          side: "SELL",
          order_type: "LIMIT",
          limit_price: price,
          quantity: Math.max(qty, 1),
        });
      }
    } else {
      form.setFieldsValue({
        stock_code: pos.stock_code,
        side: "BUY",
        order_type: "LIMIT",
        limit_price: price,
        quantity: 100,
      });
    }
    setStockName(pos.name || "");
    message.info(`已填入 ${pos.stock_code} ${pos.name || ""}`);
  };

  const onReleaseT1 = async () => {
    try {
      const res = await post<{ released_rows?: number }>("/trade/simulation/release-t1");
      message.success(res.message || `已释放可卖 ${res.data?.released_rows ?? 0} 条`);
      await refreshAll(mode);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "释放失败");
    }
  };

  const onSubmit = async (values: Record<string, unknown>) => {
    setRiskMsg(null);
    setSubmitting(true);
    const sideNow = String(values.side || "BUY");
    if (sideNow === "SELL") {
      const code = String(values.stock_code || "").padStart(6, "0");
      const pos = positions.find((p) => p.stock_code === code);
      const avail = Number(pos?.available_qty || 0);
      const qty = Number(values.quantity || 0);
      if (pos && avail < qty) {
        setRiskMsg(
          `可卖不足（T+1）：可卖 ${avail} 股，委托 ${qty} 股。当日买入的仓位次一交易日才能卖；可点击「释放T+1」对非当日买入仓位解锁。`
        );
        message.error("可卖数量不足（T+1）");
        setSubmitting(false);
        return;
      }
    }
    const payload: Record<string, unknown> = {
      ...values,
      mode,
      stock_code: String(values.stock_code || "").padStart(6, "0"),
      limit_price:
        values.limit_price != null && values.limit_price !== ""
          ? Math.round(Number(values.limit_price) * 100) / 100
          : values.limit_price,
    };
    if (mode === "live") {
      const token = getLiveConfirmToken() || String(values.live_confirm || "");
      if (!token) {
        message.error("实盘需要确认令牌");
        setSubmitting(false);
        return;
      }
      payload.live_confirm = token;
    }
    if (payload.order_type === "MARKET") {
      payload.limit_price = null;
    }
    try {
      const res = await post("/trade/order", payload);
      const data = res.data as {
        success?: boolean;
        message?: string;
        risk_report?: { checks?: { message: string }[] };
      };
      if (data && data.success === false) {
        let msg = data.message || "下单失败";
        if (data.risk_report?.checks?.length) {
          msg = data.risk_report.checks.map((c) => c.message).join("；");
        }
        setRiskMsg(msg);
        message.error("下单被拦截");
      } else {
        message.success(side === "BUY" ? "买入委托已提交" : "卖出委托已提交");
        await refreshAll(mode);
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "下单请求失败");
    } finally {
      setSubmitting(false);
    }
  };

  const onCancel = async (orderId: string) => {
    try {
      const res = await post("/trade/order/cancel", { order_id: orderId, mode });
      const data = res.data as { success?: boolean; message?: string };
      if (data?.success) message.success("撤单成功");
      else message.warning(data?.message || "撤单失败");
      await refreshAll(mode);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "撤单失败");
    }
  };

  const onReconcile = async () => {
    if (mode === "simulation") {
      message.info("模拟盘本地撮合，无需券商对账");
      return;
    }
    try {
      const res = await post(`/trade/reconcile?mode=${mode === "live" ? "live" : "paper"}`);
      const data = res.data as { status?: string; issues?: unknown[] };
      if (data?.status === "mismatch") {
        message.warning(`发现差异 ${(data.issues || []).length} 项`);
      } else {
        message.success("对账完成");
      }
    } catch {
      message.error("对账失败");
    }
  };

  const onSyncOrders = async () => {
    if (mode === "simulation") {
      message.info("模拟盘即时回报，无需同步挂单");
      return;
    }
    try {
      const res = await post(`/trade/orders/sync?mode=${mode === "live" ? "live" : "paper"}`);
      const data = res.data as { updated?: number; filled?: number; checked?: number };
      message.success(
        `同步完成：检查 ${data?.checked ?? 0}，更新 ${data?.updated ?? 0}，成交 ${data?.filled ?? 0}`
      );
      await refreshAll(mode);
    } catch {
      message.error("订单同步失败");
    }
  };

  const adapterLabel = useMemo(() => {
    const adapters = (modeInfo?.adapters || {}) as Record<string, string>;
    const name = String(broker?.selected_adapter || adapters.live || "-");
    if (name === "xtquant") return "迅投 QMT";
    if (name === "mock") return "模拟券商";
    if (mode === "simulation") return "本地撮合";
    return name;
  }, [broker, modeInfo, mode]);

  const buyColor = "#cf1322";
  const sellColor = "#389e0d";

  return (
    <PageShell
      title="模拟交易台"
      subtitle={MODE_HELP[mode]}
      extra={
        <Space wrap className="page-actions">
          <Segmented
            value={mode}
            options={MODE_OPTS}
            onChange={(v) => setMode(v as TradeMode)}
          />
          <Tag color={wsConnected ? "success" : "default"}>
            {wsConnected ? "推送已连接" : "推送未连接"}
          </Tag>
          <Tag>{adapterLabel}</Tag>
          <Button size="small" onClick={() => void refreshAll(mode)}>
            刷新
          </Button>
          {mode === "simulation" && (
            <Button size="small" onClick={() => void onReleaseT1()}>
              释放T+1可卖
            </Button>
          )}
          {mode !== "simulation" && (
            <>
              <Button size="small" onClick={() => void onReconcile()}>
                对账
              </Button>
              <Button size="small" onClick={() => void onSyncOrders()}>
                同步委托
              </Button>
            </>
          )}
        </Space>
      }
    >
      {mode === "live" && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="实盘模式 — 涉及真实资金"
          description="需配置实盘确认令牌与券商通道；无 QMT 时可能降级 Mock。"
        />
      )}
      {mode === "paper" && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="纸面模式使用模拟券商，非真实资金"
        />
      )}
      {wsHint && (
        <Alert
          type="info"
          showIcon
          closable
          style={{ marginBottom: 12 }}
          message={wsHint}
          onClose={() => setWsHint(null)}
        />
      )}
      {riskMsg && (
        <Alert
          type="error"
          showIcon
          closable
          style={{ marginBottom: 12 }}
          message="风控拦截"
          description={riskMsg}
          onClose={() => setRiskMsg(null)}
        />
      )}

      {/* 资产条 */}
      <Card size="small" styles={{ body: { padding: "16px 20px" } }}>
        <Row gutter={[16, 16]}>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="总资产"
              value={summary?.total_assets ?? 0}
              precision={2}
              prefix="¥"
              valueStyle={{ fontSize: 20, fontWeight: 600 }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="可用资金"
              value={summary?.cash ?? 0}
              precision={2}
              prefix="¥"
              valueStyle={{ fontSize: 20 }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="持仓市值"
              value={summary?.market_value ?? 0}
              precision={2}
              prefix="¥"
              valueStyle={{ fontSize: 20 }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="当日盈亏"
              value={summary?.daily_pnl ?? 0}
              precision={2}
              prefix="¥"
              valueStyle={{
                fontSize: 20,
                color: pnlColor(summary?.daily_pnl),
              }}
              suffix={
                <span style={{ fontSize: 13, marginLeft: 4 }}>
                  {fmtPct(summary?.daily_pnl_pct)}
                </span>
              }
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="持仓只数" value={summary?.position_count ?? 0} valueStyle={{ fontSize: 20 }} />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <div style={{ paddingTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                风控状态
              </Text>
              <div style={{ marginTop: 6 }}>
                {summary?.is_fused ? (
                  <Tag color="error" style={{ fontSize: 14, padding: "4px 10px" }}>
                    已熔断
                  </Tag>
                ) : (
                  <Tag color="success" style={{ fontSize: 14, padding: "4px 10px" }}>
                    正常
                  </Tag>
                )}
              </div>
            </div>
          </Col>
        </Row>
      </Card>

      <Row gutter={[16, 16]}>
        {/* 左侧：下单票 */}
        <Col xs={24} lg={8} xl={7}>
          <Card
            title="下单"
            size="small"
            extra={
              stockName ? (
                <Text type="secondary">
                  {stockCode} {stockName}
                </Text>
              ) : null
            }
          >
            <Form
              form={form}
              layout="vertical"
              onFinish={onSubmit}
              initialValues={{
                side: "BUY",
                order_type: "LIMIT",
                quantity: 100,
                stock_code: "000001",
              }}
            >
              <Form.Item
                name="stock_code"
                label="证券代码"
                rules={[
                  { required: true, message: "请输入代码" },
                  { pattern: /^\d{6}$/, message: "请输入 6 位代码" },
                ]}
              >
                <AutoComplete
                  options={stockOptions}
                  onSearch={searchStocks}
                  onSelect={(v, opt) => {
                    const o = opt as StockOpt;
                    form.setFieldValue("stock_code", o.code || v);
                    setStockName(o.name || "");
                    // 选中后清价格让 effect 填现价
                    form.setFieldValue("limit_price", undefined);
                  }}
                  placeholder="输入代码或名称模糊搜索"
                >
                  <Input maxLength={6} allowClear />
                </AutoComplete>
              </Form.Item>

              {/* 迷你行情 */}
              <div
                style={{
                  background: "rgba(0,0,0,0.04)",
                  borderRadius: 8,
                  padding: "10px 12px",
                  marginBottom: 16,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    参考现价
                  </Text>
                  <div
                    style={{
                      fontSize: 22,
                      fontWeight: 600,
                      color: pnlColor(quote?.change_pct),
                      lineHeight: 1.2,
                    }}
                  >
                    {quote?.price != null ? fmtMoney(quote.price) : "—"}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    涨跌幅
                  </Text>
                  <div style={{ fontSize: 16, color: pnlColor(quote?.change_pct), fontWeight: 500 }}>
                    {fmtPct(quote?.change_pct)}
                  </div>
                </div>
                {quote?.price != null && (
                  <Button
                    size="small"
                    type="link"
                    onClick={() =>
                      form.setFieldValue("limit_price", Number(Number(quote.price).toFixed(2)))
                    }
                  >
                    填入限价
                  </Button>
                )}
              </div>

              <Form.Item name="side" label="方向">
                <Segmented
                  block
                  options={[
                    {
                      value: "BUY",
                      label: <span style={{ color: buyColor, fontWeight: 600 }}>买入</span>,
                    },
                    {
                      value: "SELL",
                      label: <span style={{ color: sellColor, fontWeight: 600 }}>卖出</span>,
                    },
                  ]}
                />
              </Form.Item>

              <Form.Item name="order_type" label="委托类型">
                <Segmented
                  block
                  options={[
                    { value: "LIMIT", label: "限价" },
                    { value: "MARKET", label: "市价" },
                  ]}
                />
              </Form.Item>

              {orderType === "LIMIT" && (
                <Form.Item
                  name="limit_price"
                  label="委托价格"
                  rules={[{ required: true, message: "请输入限价" }]}
                >
                  <InputNumber
                    style={{ width: "100%" }}
                    min={0.01}
                    step={0.01}
                    precision={2}
                    addonAfter="元"
                  />
                </Form.Item>
              )}

              <Form.Item
                name="quantity"
                label="委托数量"
                rules={[{ required: true, message: "请输入数量" }]}
                extra="A 股以 100 股为一手"
              >
                <InputNumber
                  style={{ width: "100%" }}
                  min={100}
                  step={100}
                  addonAfter="股"
                />
              </Form.Item>

              <Space style={{ marginBottom: 16 }} wrap>
                <Button size="small" onClick={() => setQtyByFraction(0.25)}>
                  1/4
                </Button>
                <Button size="small" onClick={() => setQtyByFraction(0.5)}>
                  半仓
                </Button>
                <Button size="small" onClick={() => setQtyByFraction(1)}>
                  {side === "BUY" ? "全仓" : "全卖"}
                </Button>
              </Space>

              <Divider style={{ margin: "8px 0 16px" }} />

              <div style={{ marginBottom: 16 }}>
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <Text type="secondary">预估金额</Text>
                    <Text strong>¥ {fmtMoney(estimateAmount)}</Text>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <Text type="secondary">可用资金</Text>
                    <Text>¥ {fmtMoney(cash)}</Text>
                  </div>
                  {side === "SELL" && (
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <Text type="secondary">可卖 / 持仓</Text>
                      <Text>
                        {(() => {
                          const pos = positions.find(
                            (p) => p.stock_code === String(stockCode || "").padStart(6, "0")
                          );
                          const a = pos?.available_qty ?? 0;
                          const t = pos?.total_qty ?? 0;
                          return (
                            <>
                              <span style={{ color: a > 0 ? undefined : "#cf1322", fontWeight: 600 }}>
                                {a}
                              </span>
                              {" / "}
                              {t} 股
                            </>
                          );
                        })()}
                        <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                          （T+1）
                        </Text>
                      </Text>
                    </div>
                  )}
                </Space>
              </div>

              {mode === "live" && (
                <Form.Item
                  name="live_confirm"
                  label="实盘确认令牌"
                  rules={[{ required: true, message: "请输入确认令牌" }]}
                >
                  <Input.Password placeholder="实盘确认令牌" />
                </Form.Item>
              )}

              <Button
                type="primary"
                htmlType="submit"
                block
                size="large"
                loading={submitting}
                disabled={!!summary?.is_fused}
                style={{
                  background: side === "BUY" ? buyColor : sellColor,
                  borderColor: side === "BUY" ? buyColor : sellColor,
                  height: 44,
                  fontWeight: 600,
                  fontSize: 16,
                }}
              >
                {summary?.is_fused
                  ? "熔断中，暂停交易"
                  : side === "BUY"
                    ? "买入下单"
                    : "卖出下单"}
              </Button>
            </Form>
          </Card>
        </Col>

        {/* 右侧：持仓 + 委托 */}
        <Col xs={24} lg={16} xl={17}>
          <Card size="small" styles={{ body: { paddingTop: 8 } }}>
            <Tabs
              items={[
                {
                  key: "positions",
                  label: `持仓 (${positions.length})`,
                  children: (
                    <Table<Position>
                      rowKey="stock_code"
                      dataSource={positions}
                      size="small"
                      pagination={false}
                      locale={{ emptyText: "暂无持仓，在左侧下单买入" }}
                      scroll={{ x: 720 }}
                      onRow={(row) => ({
                        onClick: () => fillFromPosition(row, true),
                        style: { cursor: "pointer" },
                      })}
                      columns={[
                        {
                          title: "代码/名称",
                          fixed: "left",
                          width: 130,
                          render: (_, r) => (
                            <div>
                              <div style={{ fontWeight: 600 }}>{r.stock_code}</div>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {r.name || "—"}
                              </Text>
                            </div>
                          ),
                        },
                        {
                          title: "持仓/可卖",
                          width: 100,
                          render: (_, r) => (
                            <span>
                              {r.total_qty ?? 0}
                              <Text type="secondary"> / {r.available_qty ?? 0}</Text>
                            </span>
                          ),
                        },
                        {
                          title: "成本",
                          dataIndex: "avg_cost",
                          width: 90,
                          render: (v) => fmtMoney(Number(v)),
                        },
                        {
                          title: "现价",
                          dataIndex: "current_price",
                          width: 90,
                          render: (v, r) => (
                            <span>
                              {fmtMoney(Number(v))}
                              {r.price_source === "kline" ? (
                                <Text type="secondary" style={{ fontSize: 11, display: "block" }}>
                                  K线
                                </Text>
                              ) : null}
                            </span>
                          ),
                        },
                        {
                          title: "市值",
                          dataIndex: "market_value",
                          width: 100,
                          render: (v) => fmtMoney(Number(v)),
                        },
                        {
                          title: "浮动盈亏",
                          width: 120,
                          render: (_, r) => (
                            <div style={{ color: pnlColor(r.unrealized_pnl) }}>
                              <div style={{ fontWeight: 600 }}>
                                {fmtMoney(r.unrealized_pnl)}
                              </div>
                              <div style={{ fontSize: 12 }}>{fmtPct(r.unrealized_pnl_pct)}</div>
                            </div>
                          ),
                        },
                        {
                          title: "操作",
                          width: 100,
                          fixed: "right",
                          render: (_, r) => (
                            <Space size={4}>
                              <Button
                                type="link"
                                size="small"
                                danger
                                style={{ padding: 0 }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  fillFromPosition(r, true);
                                }}
                              >
                                卖出
                              </Button>
                              <Button
                                type="link"
                                size="small"
                                style={{ padding: 0 }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  fillFromPosition(r, false);
                                }}
                              >
                                加仓
                              </Button>
                            </Space>
                          ),
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "orders",
                  label: `委托 (${orders.length})`,
                  children: (
                    <Table<OrderRow>
                      rowKey="id"
                      dataSource={orders}
                      size="small"
                      locale={{ emptyText: "暂无委托记录" }}
                      scroll={{ x: 800 }}
                      pagination={{ pageSize: 10, size: "small" }}
                      columns={[
                        {
                          title: "时间",
                          dataIndex: "created_at",
                          width: 160,
                          render: (v) => {
                            if (!v) return "—";
                            try {
                              return new Date(String(v)).toLocaleString("zh-CN", {
                                hour12: false,
                                timeZone: "Asia/Shanghai",
                              });
                            } catch {
                              return String(v);
                            }
                          },
                        },
                        {
                          title: "代码",
                          dataIndex: "stock_code",
                          width: 90,
                        },
                        {
                          title: "方向",
                          dataIndex: "side",
                          width: 70,
                          render: (v) => sideTag(String(v)),
                        },
                        {
                          title: "类型",
                          dataIndex: "order_type",
                          width: 70,
                          render: (v) =>
                            String(v).toUpperCase() === "MARKET" ? "市价" : "限价",
                        },
                        {
                          title: "委托价",
                          dataIndex: "limit_price",
                          width: 90,
                          render: (v) => (v != null && v !== "" ? fmtMoney(Number(v)) : "市价"),
                        },
                        {
                          title: "数量",
                          width: 100,
                          render: (_, r) => (
                            <span>
                              {r.filled_quantity ?? 0}/{r.quantity}
                            </span>
                          ),
                        },
                        {
                          title: "成交均价",
                          dataIndex: "avg_fill_price",
                          width: 90,
                          render: (v) => (v != null && v !== "" ? fmtMoney(Number(v)) : "—"),
                        },
                        {
                          title: "状态",
                          dataIndex: "status",
                          width: 90,
                          render: (v) => statusTag(String(v)),
                        },
                        {
                          title: "操作",
                          width: 80,
                          fixed: "right",
                          render: (_, row) =>
                            ["PENDING", "SUBMITTED", "PARTIAL"].includes(
                              String(row.status).toUpperCase()
                            ) ? (
                              <Button
                                size="small"
                                danger
                                type="link"
                                onClick={() => void onCancel(String(row.id))}
                              >
                                撤单
                              </Button>
                            ) : null,
                        },
                      ]}
                    />
                  ),
                },
              ]}
            />
          </Card>

          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message="A 股模拟规则（学习用，非真实下单）"
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                <li>成交价优先使用实时行情（腾讯/通达信等），失败才回退日 K 收盘</li>
                <li>T+1：当日买入次一交易日才可卖；数量须 100 股整数倍（科创板买入≥200）</li>
                <li>涨停无法买、跌停无法卖；限价须在涨跌停范围内</li>
                <li>佣金约万三（最低 5 元），卖出另收印花税 0.05%</li>
                <li>交易时段：工作日 09:15–11:30、13:00–15:00（北京时间）；盘后可按最近行情模拟</li>
                <li>点击持仓可快速填入卖出/加仓</li>
              </ul>
            }
          />
        </Col>
      </Row>
    </PageShell>
  );
}
