import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get, post } from "../api/client";
import KlineChart from "../components/KlineChart";
import PageShell from "../components/PageShell";

const { Text } = Typography;

/** 高亮关键词 */
function highlightMatch(text: string, keyword: string): JSX.Element | string {
  const kw = keyword.trim();
  if (!kw || !text) return text;
  try {
    const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(${escaped})`, "ig");
    if (text.toLowerCase().includes(kw.toLowerCase())) {
      const parts = text.split(re);
      return (
        <>
          {parts.map((part, i) =>
            part.toLowerCase() === kw.toLowerCase() ? (
              <mark
                key={i}
                style={{ background: "rgba(250,173,20,0.35)", color: "inherit", padding: 0 }}
              >
                {part}
              </mark>
            ) : (
              <span key={i}>{part}</span>
            )
          )}
        </>
      );
    }
  } catch {
    /* ignore */
  }
  const chars = new Set([...kw].map((c) => c.toLowerCase()));
  return (
    <>
      {[...text].map((ch, i) =>
        chars.has(ch.toLowerCase()) ? (
          <mark
            key={i}
            style={{ background: "rgba(250,173,20,0.28)", color: "inherit", padding: 0 }}
          >
            {ch}
          </mark>
        ) : (
          <span key={i}>{ch}</span>
        )
      )}
    </>
  );
}

interface StockItem {
  code: string;
  name: string;
  market?: string;
  sector?: string | null;
  is_st?: boolean;
}

interface QuoteData {
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
  [key: string]: unknown;
}

interface ProfileData {
  code: string;
  name: string;
  market?: string;
  sector?: string | null;
  board?: string | null;
  is_st?: boolean;
}

export default function StockAnalysis() {
  const [keyword, setKeyword] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [stocks, setStocks] = useState<StockItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [selected, setSelected] = useState<string>("");
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [quote, setQuote] = useState<QuoteData | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [page, setPage] = useState(1);

  const searchSeq = useRef(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadStocks = useCallback(async (kw: string, pageNo = 1, append = false) => {
    const seq = ++searchSeq.current;
    setListLoading(true);
    setError(null);
    try {
      const res = await get<{ items: StockItem[]; total: number; keyword?: string }>(
        "/stock/list",
        {
          keyword: kw || undefined,
          page: pageNo,
          page_size: 100,
        }
      );
      if (seq !== searchSeq.current) return;
      const items = res.data?.items || [];
      setTotal(res.data?.total || items.length);
      setPage(pageNo);
      setKeyword(kw);
      setStocks((prev) => (append ? [...prev, ...items] : items));
      setSelected((prev) => {
        if (append) return prev;
        if (prev && items.some((s) => s.code === prev)) return prev;
        if (kw.trim() && items[0]) return items[0].code;
        return items[0]?.code || prev || "";
      });
      if (!items.length && pageNo === 1) {
        setError(
          kw.trim()
            ? `未找到匹配「${kw.trim()}」的股票`
            : "股票池为空。请点击「同步全市场」。"
        );
      }
    } catch (e) {
      if (seq !== searchSeq.current) return;
      setError(`加载股票列表失败: ${e instanceof Error ? e.message : String(e)}`);
      if (!append) setStocks([]);
    } finally {
      if (seq === searchSeq.current) setListLoading(false);
    }
  }, []);

  const onSearchInputChange = useCallback(
    (value: string) => {
      setSearchInput(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        void loadStocks(value.trim(), 1, false);
      }, 320);
    },
    [loadStocks]
  );

  const runSearch = useCallback(
    (value?: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      const v = (value ?? searchInput).trim();
      setSearchInput(v);
      void loadStocks(v, 1, false);
    },
    [loadStocks, searchInput]
  );

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const onSyncUniverse = async () => {
    setSyncing(true);
    try {
      const res = await post<{ total_active: number }>(
        "/stock/sync-universe?backfill_top_n=0&allow_synthetic=true"
      );
      message.success(
        res.message || `全市场同步完成，当前有效股票 ${res.data?.total_active ?? ""} 只`
      );
      await loadStocks(searchInput.trim(), 1, false);
    } catch (e) {
      message.error(`同步失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    void loadStocks("", 1, false);
  }, [loadStocks]);

  // 选中 → 档案 + 行情（K 线由 KlineChart 自行拉取）
  useEffect(() => {
    if (!selected) {
      setProfile(null);
      setQuote(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    (async () => {
      try {
        const [profileRes, quoteRes] = await Promise.all([
          get<ProfileData>(`/stock/${selected}/profile`).catch(() => null),
          get<QuoteData | null>(`/stock/${selected}/quote`).catch(() => null),
        ]);
        if (cancelled) return;
        setProfile(profileRes?.data || { code: selected, name: selected });
        setQuote(quoteRes?.data || null);
      } catch (e) {
        if (!cancelled) {
          setError(`加载详情失败: ${e instanceof Error ? e.message : String(e)}`);
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const searchHint = useMemo(() => {
    if (!keyword.trim()) return null;
    return `模糊匹配「${keyword}」共 ${total} 只`;
  }, [keyword, total]);

  const selectedName =
    profile?.name || stocks.find((s) => s.code === selected)?.name || "";

  return (
    <PageShell
      title="股票分析"
      subtitle="全市场 A 股 · 分时默认 · 参考同花顺/支付宝 · 中国时区 UTC+8"
    >
      {error && (
        <Alert
          type="warning"
          showIcon
          message={error}
          action={
            <Button size="small" onClick={() => void loadStocks(keyword || searchInput)}>
              重试
            </Button>
          }
        />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={7} xl={6}>
          <Card
            title={
              keyword.trim()
                ? `搜索结果（${total} 只）`
                : `股票池（${total} 只，本页 ${stocks.length}）`
            }
            size="small"
            extra={
              <Button size="small" loading={syncing} onClick={() => void onSyncUniverse()}>
                同步全市场
              </Button>
            }
          >
            <Input.Search
              placeholder="模糊搜索：代码 / 名称 / 行业"
              allowClear
              enterButton="搜索"
              loading={listLoading}
              value={searchInput}
              onChange={(e) => onSearchInputChange(e.target.value)}
              onSearch={(v) => runSearch(v)}
              onClear={() => {
                setSearchInput("");
                void loadStocks("", 1, false);
              }}
              style={{ marginBottom: 8 }}
            />
            <div style={{ marginBottom: 8, minHeight: 22 }}>
              {searchHint ? (
                <Space size={4} wrap>
                  <Tag color="blue">{searchHint}</Tag>
                  <Button
                    type="link"
                    size="small"
                    style={{ padding: 0 }}
                    onClick={() => {
                      setSearchInput("");
                      void loadStocks("", 1, false);
                    }}
                  >
                    清除
                  </Button>
                </Space>
              ) : (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  支持代码前缀、名称片段、隔字匹配
                </Text>
              )}
            </div>
            <Spin spinning={listLoading}>
              {stocks.length === 0 ? (
                <Empty
                  description={
                    keyword.trim()
                      ? `无匹配「${keyword}」`
                      : "暂无股票，请点右上角「同步全市场」"
                  }
                />
              ) : (
                <>
                  <List
                    size="small"
                    bordered
                    dataSource={stocks}
                    style={{ maxHeight: "min(62vh, 560px)", overflow: "auto" }}
                    renderItem={(item) => (
                      <List.Item
                        onClick={() => setSelected(item.code)}
                        style={{
                          cursor: "pointer",
                          background:
                            item.code === selected ? "rgba(22,119,255,0.1)" : undefined,
                          fontWeight: item.code === selected ? 600 : 400,
                        }}
                      >
                        <Space wrap>
                          <Text code>{highlightMatch(item.code, keyword)}</Text>
                          <span>{highlightMatch(item.name, keyword)}</span>
                          {item.sector ? (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {highlightMatch(item.sector, keyword)}
                            </Text>
                          ) : null}
                          {item.is_st ? <Text type="danger">ST</Text> : null}
                        </Space>
                      </List.Item>
                    )}
                  />
                  {stocks.length < total && (
                    <Button
                      block
                      style={{ marginTop: 8 }}
                      loading={listLoading}
                      onClick={() => void loadStocks(keyword, page + 1, true)}
                    >
                      加载更多（{stocks.length}/{total}）
                    </Button>
                  )}
                </>
              )}
            </Spin>
          </Card>
        </Col>

        <Col xs={24} lg={17} xl={18}>
          <Card size="small" styles={{ body: { padding: 16 } }}>
            <Spin spinning={detailLoading && !!selected}>
              {selected ? (
                <KlineChart
                  code={selected}
                  name={selectedName}
                  quote={quote}
                  height={460}
                />
              ) : (
                <Empty description="从左侧列表选择一只股票查看分时/K线" />
              )}
            </Spin>
          </Card>
        </Col>
      </Row>
    </PageShell>
  );
}
