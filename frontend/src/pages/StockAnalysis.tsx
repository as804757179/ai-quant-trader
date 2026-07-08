import { Card, Input, List, Space } from "antd";
import { createChart, type IChartApi } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { get } from "../api/client";

interface StockItem {
  code: string;
  name: string;
}

interface KlineItem {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export default function StockAnalysis() {
  const [keyword, setKeyword] = useState("");
  const [stocks, setStocks] = useState<StockItem[]>([]);
  const [selected, setSelected] = useState<string>("000001");
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<IChartApi | null>(null);

  useEffect(() => {
    get<{ items: StockItem[] }>("/stock/list", { keyword, page_size: 20 }).then((res) => {
      setStocks(res.data?.items || []);
    });
  }, [keyword]);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!chartInstance.current) {
      chartInstance.current = createChart(chartRef.current, { width: 800, height: 400 });
    }
    const series = chartInstance.current.addCandlestickSeries();
    get<KlineItem[]>(`/stock/${selected}/kline`, { period: "1d", limit: 120 }).then((res) => {
      const data = (res.data || []).map((k) => ({
        time: k.time.slice(0, 10),
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      }));
      series.setData(data as never);
    });
  }, [selected]);

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" style={{ width: "100%" }} size="large">
        <Input.Search
          placeholder="搜索股票代码或名称"
          onSearch={setKeyword}
          allowClear
          style={{ maxWidth: 400 }}
        />
        <List
          bordered
          dataSource={stocks}
          renderItem={(item) => (
            <List.Item onClick={() => setSelected(item.code)} style={{ cursor: "pointer" }}>
              {item.code} {item.name}
            </List.Item>
          )}
        />
        <Card title={`K线图 ${selected}`}>
          <div ref={chartRef} />
        </Card>
      </Space>
    </div>
  );
}