# 42-44 — 前端系统完整设计

---

## 1. 技术栈与依赖

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "typescript": "^5.0.0",
    "antd": "^5.12.0",
    "@ant-design/pro-components": "^2.6.0",
    "echarts": "^5.4.3",
    "echarts-for-react": "^3.0.2",
    "lightweight-charts": "^4.1.0",
    "zustand": "^4.4.0",
    "@tanstack/react-query": "^5.0.0",
    "axios": "^1.6.0",
    "dayjs": "^1.11.0",
    "ahooks": "^3.7.0",
    "reconnecting-websocket": "^4.4.0"
  }
}
```

---

## 2. 前端架构

```
frontend/src/
├── pages/                      # 8个主要页面
│   ├── Dashboard/              # 仪表盘
│   ├── StockAnalysis/          # 股票分析
│   ├── AIDecision/             # AI决策中心
│   ├── Screener/               # 选股系统
│   ├── Strategy/               # 策略管理
│   ├── Backtest/               # 回测系统
│   ├── Risk/                   # 风控中心
│   └── Trade/                  # 交易执行
│
├── components/                 # 公共组件
│   ├── KLineChart/             # K线图（TradingView风格）
│   ├── AgentDiscussion/        # Agent讨论展示
│   ├── RiskGauge/              # 风险仪表盘
│   ├── SignalCard/             # 信号卡片
│   ├── PositionTable/          # 持仓表格
│   ├── EquityCurve/            # 收益曲线
│   └── FuseAlert/              # 熔断告警组件
│
├── hooks/                      # 自定义Hooks
│   ├── useWebSocket.ts         # WebSocket连接管理
│   ├── useQuote.ts             # 实时行情
│   ├── useSignals.ts           # 实时信号
│   ├── usePortfolio.ts         # 持仓数据
│   └── useRiskStatus.ts        # 风控状态
│
├── store/                      # Zustand全局状态
│   ├── tradeMode.ts            # 当前交易模式
│   ├── riskStatus.ts           # 风控状态
│   ├── signals.ts              # 最新信号
│   └── portfolio.ts            # 持仓快照
│
├── api/                        # API客户端
│   ├── client.ts               # Axios实例
│   ├── stock.ts
│   ├── ai.ts
│   ├── trade.ts
│   └── backtest.ts
│
└── ws/                         # WebSocket客户端
    ├── client.ts               # 统一WS客户端（含断线重连）
    └── handlers.ts             # 消息处理器
```

---

## 3. WebSocket客户端（含断线重连）

```typescript
// frontend/src/ws/client.ts

import ReconnectingWebSocket from 'reconnecting-websocket';

type MessageHandler = (data: any) => void;

class WSClient {
  private connections: Map<string, ReconnectingWebSocket> = new Map();
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private baseUrl: string;

  constructor() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.baseUrl = `${protocol}//${window.location.host}/ws`;
  }

  subscribe(channel: string, handler: MessageHandler): () => void {
    // 注册消息处理器
    if (!this.handlers.has(channel)) {
      this.handlers.set(channel, new Set());
    }
    this.handlers.get(channel)!.add(handler);

    // 建立WebSocket连接（如果还没有）
    if (!this.connections.has(channel)) {
      this._connect(channel);
    }

    // 返回取消订阅函数
    return () => {
      this.handlers.get(channel)?.delete(handler);
      if (this.handlers.get(channel)?.size === 0) {
        this._disconnect(channel);
      }
    };
  }

  private _connect(channel: string) {
    const url = `${this.baseUrl}/${channel}`;
    const ws = new ReconnectingWebSocket(url, [], {
      maxReconnectionDelay: 5000,
      minReconnectionDelay: 1000,
      reconnectionDelayGrowFactor: 1.5,
      maxRetries: Infinity,
      debug: process.env.NODE_ENV === 'development',
    });

    ws.onopen = () => {
      console.log(`[WS] Connected: ${channel}`);
      // 每30秒发送心跳
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 30000);
      (ws as any)._pingInterval = pingInterval;
    };

    ws.onmessage = (event) => {
      if (event.data === 'pong') return;
      try {
        const data = JSON.parse(event.data);
        this.handlers.get(channel)?.forEach(h => h(data));
      } catch (e) {
        console.error(`[WS] Parse error on ${channel}:`, e);
      }
    };

    ws.onclose = () => {
      console.log(`[WS] Disconnected: ${channel}`);
      clearInterval((ws as any)._pingInterval);
    };

    this.connections.set(channel, ws);
  }

  private _disconnect(channel: string) {
    const ws = this.connections.get(channel);
    if (ws) {
      clearInterval((ws as any)._pingInterval);
      ws.close();
      this.connections.delete(channel);
    }
    this.handlers.delete(channel);
  }
}

export const wsClient = new WSClient();
```

---

## 4. 实时行情 Hook

```typescript
// frontend/src/hooks/useQuote.ts

import { useState, useEffect } from 'react';
import { wsClient } from '../ws/client';

interface Quote {
  code: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  amount: number;
  high: number;
  low: number;
}

export function useQuote(stockCode: string | null) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!stockCode) return;

    setConnected(true);
    const unsubscribe = wsClient.subscribe(
      `quotes/${stockCode}`,
      (data) => {
        if (data.type === 'quote') {
          setQuote(data);
        }
      }
    );

    return () => {
      unsubscribe();
      setConnected(false);
    };
  }, [stockCode]);

  return { quote, connected };
}
```

---

## 5. 页面完整实现

### 5.1 Dashboard（仪表盘）

```tsx
// frontend/src/pages/Dashboard/index.tsx

import React, { useEffect } from 'react';
import { Row, Col, Card, Statistic, Tag, List, Badge } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined, AlertOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { portfolioApi } from '../../api/portfolio';
import { aiApi } from '../../api/ai';
import { useSignals } from '../../hooks/useSignals';
import { useRiskStatus } from '../../hooks/useRiskStatus';
import { EquityCurve } from '../../components/EquityCurve';
import { SignalCard } from '../../components/SignalCard';
import { RiskGauge } from '../../components/RiskGauge';
import { FuseAlert } from '../../components/FuseAlert';
import { useTradeModeStore } from '../../store/tradeMode';

const Dashboard: React.FC = () => {
  const { mode } = useTradeModeStore();
  const { signals } = useSignals();       // 实时信号（WebSocket）
  const { riskStatus } = useRiskStatus(); // 实时风控状态（WebSocket）

  const { data: portfolio } = useQuery({
    queryKey: ['portfolio', 'summary', mode],
    queryFn: () => portfolioApi.getSummary(mode),
    refetchInterval: 30000,              // 每30秒轮询刷新
  });

  const { data: equityData } = useQuery({
    queryKey: ['portfolio', 'equity-curve', mode],
    queryFn: () => portfolioApi.getEquityCurve(mode, 30),
  });

  const isProfit = (portfolio?.daily_pnl ?? 0) >= 0;

  return (
    <div style={{ padding: 24 }}>
      {/* 熔断告警横幅（优先级最高） */}
      {riskStatus?.is_fused && (
        <FuseAlert reason={riskStatus.fuse_reason} mode={mode} />
      )}

      {/* 资产概览卡片 */}
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card bordered={false}>
            <Statistic
              title="总资产"
              value={portfolio?.total_assets}
              precision={2}
              prefix="¥"
              valueStyle={{ fontSize: 28, fontWeight: 'bold' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false}>
            <Statistic
              title="今日盈亏"
              value={portfolio?.daily_pnl}
              precision={2}
              prefix="¥"
              suffix={
                <span style={{ fontSize: 14 }}>
                  ({portfolio?.daily_pnl_pct?.toFixed(2)}%)
                </span>
              }
              valueStyle={{
                color: isProfit ? '#3f8600' : '#cf1322',
                fontSize: 24
              }}
              prefix={isProfit ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false}>
            <Statistic
              title="累计收益"
              value={portfolio?.total_pnl_pct}
              precision={2}
              suffix="%"
              valueStyle={{
                color: (portfolio?.total_pnl_pct ?? 0) >= 0 ? '#3f8600' : '#cf1322'
              }}
            />
            <div style={{ marginTop: 4, color: '#999', fontSize: 12 }}>
              ¥{portfolio?.total_pnl?.toFixed(0)}
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false}>
            <Statistic
              title="当前仓位"
              value={(portfolio?.position_ratio ?? 0) * 100}
              precision={1}
              suffix="%"
            />
            <div style={{ marginTop: 8 }}>
              <RiskGauge
                value={portfolio?.position_ratio ?? 0}
                max={0.80}
                size="small"
              />
            </div>
          </Card>
        </Col>
      </Row>

      {/* 收益曲线 + 最新信号 */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={16}>
          <Card title="近30日收益曲线" bordered={false}>
            <EquityCurve data={equityData} height={280} />
          </Card>
        </Col>
        <Col span={8}>
          <Card
            title={
              <span>
                最新AI信号
                <Badge
                  count={signals.filter(s => s.action === 'BUY').length}
                  style={{ backgroundColor: '#52c41a', marginLeft: 8 }}
                />
              </span>
            }
            bordered={false}
            bodyStyle={{ padding: 0, maxHeight: 320, overflowY: 'auto' }}
          >
            <List
              dataSource={signals.slice(0, 10)}
              renderItem={(signal) => (
                <List.Item style={{ padding: '8px 16px' }}>
                  <SignalCard signal={signal} compact />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      {/* 当前持仓简表 */}
      <Row style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="当前持仓" bordered={false}>
            <PositionSummaryTable mode={mode} />
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Dashboard;
```

### 5.2 AI Decision（AI决策页）

```tsx
// frontend/src/pages/AIDecision/index.tsx

import React, { useState } from 'react';
import { Card, Input, Button, Steps, Tag, Progress, Divider, Typography, Row, Col, Spin } from 'antd';
import { SearchOutlined, RobotOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { aiApi } from '../../api/ai';
import { AgentDiscussion } from '../../components/AgentDiscussion';
import { SignalSummary } from '../../components/SignalSummary';

const { Title, Text } = Typography;

const AIDecisionPage: React.FC = () => {
  const [stockCode, setStockCode] = useState('');
  const [result, setResult] = useState<any>(null);

  const analyzeMutation = useMutation({
    mutationFn: (code: string) => aiApi.analyzeStock(code),
    onSuccess: (data) => setResult(data),
  });

  const handleAnalyze = () => {
    if (!stockCode) return;
    setResult(null);
    analyzeMutation.mutate(stockCode);
  };

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <Title level={3}>
        <RobotOutlined style={{ marginRight: 8 }} />
        AI 多Agent决策中心
      </Title>

      {/* 搜索框 */}
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="输入股票代码，如 000001 或 AAPL"
          value={stockCode}
          onChange={e => setStockCode(e.target.value)}
          onSearch={handleAnalyze}
          enterButton={
            <Button type="primary" icon={<SearchOutlined />} loading={analyzeMutation.isPending}>
              开始AI分析
            </Button>
          }
          size="large"
          style={{ maxWidth: 500 }}
        />
        <Text type="secondary" style={{ marginLeft: 16 }}>
          将触发4个AI Agent并发分析，约需15-30秒
        </Text>
      </Card>

      {/* 分析进度 */}
      {analyzeMutation.isPending && (
        <Card bordered={false} style={{ marginBottom: 16 }}>
          <AnalysisProgress />
        </Card>
      )}

      {/* 分析结果 */}
      {result && (
        <>
          {/* 最终信号 */}
          <SignalSummary signal={result} />

          <Divider>Agent 分析详情</Divider>

          {/* Agent讨论展示 */}
          <AgentDiscussion agentVotes={result.agent_votes} />
        </>
      )}
    </div>
  );
};

// Agent分析进度动画
const AnalysisProgress: React.FC = () => {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setStep(s => Math.min(s + 1, 4));
    }, 3000);
    return () => clearInterval(timer);
  }, []);

  return (
    <Steps
      current={step}
      items={[
        { title: '获取市场数据', description: '行情/资金流/新闻' },
        { title: 'RAG检索', description: '研报/公告向量检索' },
        { title: 'Agent并发分析', description: '4个Agent同时运行' },
        { title: '风控评估', description: '风险评分' },
        { title: '信号聚合', description: '生成最终决策' },
      ]}
    />
  );
};
```

### 5.3 AgentDiscussion 组件

```tsx
// frontend/src/components/AgentDiscussion/index.tsx

import React from 'react';
import { Row, Col, Card, Tag, Progress, Typography, List, Avatar } from 'antd';
import {
  TrendingUpOutlined,
  BarChartOutlined,
  MessageOutlined,
  ThunderboltOutlined,
  SafetyOutlined
} from '@ant-design/icons';

const { Text } = Typography;

const AGENT_META = {
  trend: {
    name: '趋势Agent (GPT-4o)',
    icon: <TrendingUpOutlined />,
    color: '#1677ff',
    avatar: 'T'
  },
  fundamental: {
    name: '基本面Agent (Claude)',
    icon: <BarChartOutlined />,
    color: '#722ed1',
    avatar: 'F'
  },
  sentiment: {
    name: '情绪Agent (Qwen)',
    icon: <MessageOutlined />,
    color: '#fa8c16',
    avatar: 'S'
  },
  shortterm: {
    name: '短线Agent (DeepSeek)',
    icon: <ThunderboltOutlined />,
    color: '#13c2c2',
    avatar: 'ST'
  },
  risk: {
    name: '风控Agent (内部)',
    icon: <SafetyOutlined />,
    color: '#52c41a',
    avatar: 'R'
  },
};

interface Props {
  agentVotes: Record<string, any>;
}

export const AgentDiscussion: React.FC<Props> = ({ agentVotes }) => {
  return (
    <Row gutter={[16, 16]}>
      {Object.entries(agentVotes).map(([agentName, result]) => {
        const meta = AGENT_META[agentName as keyof typeof AGENT_META];
        if (!meta) return null;

        const confidence = result?.confidence ?? 0;
        const isDegraded = result?._degraded;

        return (
          <Col key={agentName} xs={24} sm={12} lg={8}>
            <Card
              bordered={false}
              style={{
                borderLeft: `4px solid ${meta.color}`,
                opacity: isDegraded ? 0.6 : 1
              }}
              title={
                <span>
                  <Avatar
                    style={{ backgroundColor: meta.color, marginRight: 8 }}
                    size="small"
                  >
                    {meta.avatar}
                  </Avatar>
                  {meta.name}
                  {isDegraded && (
                    <Tag color="warning" style={{ marginLeft: 8 }}>降级</Tag>
                  )}
                </span>
              }
            >
              {/* 置信度 */}
              <div style={{ marginBottom: 12 }}>
                <Text type="secondary">置信度</Text>
                <Progress
                  percent={Math.round(confidence * 100)}
                  strokeColor={meta.color}
                  size="small"
                />
              </div>

              {/* Agent特定输出 */}
              <AgentOutput agentName={agentName} result={result} />

              {/* 分析原因 */}
              {result?.reason && (
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {result.reason}
                  </Text>
                </div>
              )}
            </Card>
          </Col>
        );
      })}
    </Row>
  );
};

const AgentOutput: React.FC<{ agentName: string; result: any }> = ({ agentName, result }) => {
  if (agentName === 'trend') {
    return (
      <div>
        <Tag color={result.trend === 'UP' ? 'green' : result.trend === 'DOWN' ? 'red' : 'default'}>
          {result.trend === 'UP' ? '↑ 上涨趋势' : result.trend === 'DOWN' ? '↓ 下跌趋势' : '→ 横盘'}
        </Tag>
        {result.support && (
          <div style={{ marginTop: 4, fontSize: 12 }}>
            支撑位 {result.support} / 压力位 {result.resistance}
          </div>
        )}
      </div>
    );
  }

  if (agentName === 'fundamental') {
    return (
      <div>
        <Tag color={result.grade?.startsWith('A') ? 'green' : result.grade?.startsWith('B') ? 'blue' : 'default'}>
          基本面评级 {result.grade}
        </Tag>
        <Tag color={result.growth_outlook === 'UP' ? 'green' : 'default'} style={{ marginLeft: 4 }}>
          {result.growth_outlook === 'UP' ? '高成长' : result.growth_outlook === 'DOWN' ? '衰退' : '稳定'}
        </Tag>
      </div>
    );
  }

  if (agentName === 'sentiment') {
    return (
      <div>
        <Tag color={result.sentiment === 'POSITIVE' ? 'green' : result.sentiment === 'NEGATIVE' ? 'red' : 'default'}>
          {result.sentiment === 'POSITIVE' ? '😊 积极' : result.sentiment === 'NEGATIVE' ? '😟 消极' : '😐 中性'}
        </Tag>
        <div style={{ fontSize: 12, marginTop: 4 }}>热度 {result.heat_score}/100</div>
      </div>
    );
  }

  if (agentName === 'shortterm') {
    const color = result.short_term_signal === 'BUY' ? 'green'
      : result.short_term_signal === 'SELL' ? 'red'
      : result.short_term_signal === 'AVOID' ? 'volcano' : 'default';
    return (
      <div>
        <Tag color={color}>
          短线: {result.short_term_signal}
        </Tag>
        {result.risk_reward_ratio && (
          <div style={{ fontSize: 12, marginTop: 4 }}>
            风险收益比 {result.risk_reward_ratio}:1
          </div>
        )}
      </div>
    );
  }

  if (agentName === 'risk') {
    return (
      <div>
        <Tag color={result.risk_level === 'LOW' ? 'green' : result.risk_level === 'MEDIUM' ? 'orange' : 'red'}>
          {result.risk_level} RISK
        </Tag>
        {result.issues?.length > 0 && (
          <List
            size="small"
            dataSource={result.issues.slice(0, 2)}
            renderItem={(item: string) => (
              <List.Item style={{ padding: '2px 0', fontSize: 11, color: '#ff4d4f' }}>
                ⚠ {item}
              </List.Item>
            )}
          />
        )}
      </div>
    );
  }

  return null;
};
```

### 5.4 K线图组件

```tsx
// frontend/src/components/KLineChart/index.tsx

import React, { useEffect, useRef } from 'react';
import { createChart, IChartApi, ISeriesApi, CandlestickData } from 'lightweight-charts';

interface Props {
  data: Array<{
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }>;
  signals?: Array<{ time: string; action: 'BUY' | 'SELL'; price: number }>;
  height?: number;
  showVolume?: boolean;
  showMA?: boolean;
}

export const KLineChart: React.FC<Props> = ({
  data,
  signals = [],
  height = 400,
  showVolume = true,
  showMA = true,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi>();
  const candleRef = useRef<ISeriesApi<'Candlestick'>>();

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: '#ffffff' },
        textColor: '#333',
      },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#d4d4d4' },
      timeScale: {
        borderColor: '#d4d4d4',
        timeVisible: true,
      },
    });

    // K线主图
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#ef5350',        // A股：红涨
      downColor: '#26a69a',      // 绿跌
      borderUpColor: '#ef5350',
      borderDownColor: '#26a69a',
      wickUpColor: '#ef5350',
      wickDownColor: '#26a69a',
    });

    const candleData: CandlestickData[] = data.map(d => ({
      time: d.time as any,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));
    candleSeries.setData(candleData);

    // MA线
    if (showMA && data.length >= 20) {
      const ma5 = chart.addLineSeries({ color: '#ff9800', lineWidth: 1, title: 'MA5' });
      const ma20 = chart.addLineSeries({ color: '#2196f3', lineWidth: 1, title: 'MA20' });
      const ma60 = chart.addLineSeries({ color: '#9c27b0', lineWidth: 1, title: 'MA60' });

      const calcMA = (period: number) =>
        data.slice(period - 1).map((d, i) => ({
          time: d.time as any,
          value: data.slice(i, i + period).reduce((s, x) => s + x.close, 0) / period,
        }));

      ma5.setData(calcMA(5));
      ma20.setData(calcMA(20));
      if (data.length >= 60) ma60.setData(calcMA(60));
    }

    // 买卖信号标记
    if (signals.length > 0) {
      const markers = signals.map(s => ({
        time: s.time as any,
        position: s.action === 'BUY' ? 'belowBar' : 'aboveBar' as any,
        color: s.action === 'BUY' ? '#ef5350' : '#26a69a',
        shape: s.action === 'BUY' ? 'arrowUp' : 'arrowDown' as any,
        text: s.action,
        size: 1.5,
      }));
      candleSeries.setMarkers(markers);
    }

    chartRef.current = chart;
    candleRef.current = candleSeries;

    // 自适应宽度
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [data, signals, height]);

  return <div ref={containerRef} style={{ width: '100%', height }} />;
};
```

---

## 6. Zustand 状态管理

```typescript
// frontend/src/store/tradeMode.ts

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type TradeMode = 'simulation' | 'paper' | 'live';

interface TradeModeState {
  mode: TradeMode;
  setMode: (mode: TradeMode) => void;
}

export const useTradeModeStore = create<TradeModeState>()(
  persist(
    (set) => ({
      mode: 'simulation',
      setMode: (mode) => {
        if (mode === 'live') {
          // 切换到实盘需要二次确认
          const confirmed = window.confirm(
            '⚠️ 警告：您即将切换到实盘模式！\n\n' +
            '实盘模式将使用真实资金进行交易。\n' +
            '请确认您已完成：\n' +
            '1. 至少3个月的纸盘验证\n' +
            '2. 风控参数已正确配置\n' +
            '3. QMT账户已连接\n\n' +
            '是否确认切换到实盘模式？'
          );
          if (!confirmed) return;
        }
        set({ mode });
      },
    }),
    { name: 'trade-mode-store' }
  )
);

// frontend/src/store/riskStatus.ts

import { create } from 'zustand';
import { wsClient } from '../ws/client';

interface RiskStatus {
  is_fused: boolean;
  fuse_reason: string | null;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'EXTREME';
  daily_loss_pct: number;
  drawdown_pct: number;
  position_ratio: number;
}

interface RiskStatusState {
  status: RiskStatus | null;
  setStatus: (status: RiskStatus) => void;
  startListening: () => () => void;
}

export const useRiskStatusStore = create<RiskStatusState>((set) => ({
  status: null,
  setStatus: (status) => set({ status }),
  startListening: () => {
    return wsClient.subscribe('alerts', (data) => {
      if (data.type === 'fuse_activated') {
        set(state => ({
          status: state.status
            ? { ...state.status, is_fused: true, fuse_reason: data.reason }
            : null
        }));
      }
    });
  },
}));
```

---

## 7. 左侧菜单与路由

```tsx
// frontend/src/app/layout.tsx

import { ProLayout } from '@ant-design/pro-components';
import { Link, Outlet, useLocation } from 'react-router-dom';
import {
  DashboardOutlined,
  StockOutlined,
  RobotOutlined,
  FilterOutlined,
  ControlOutlined,
  HistoryOutlined,
  SafetyCertificateOutlined,
  TransactionOutlined,
} from '@ant-design/icons';
import { TradeModeSwitch } from '../components/TradeModeSwitch';

const menuItems = [
  { path: '/',           name: '仪表盘',     icon: <DashboardOutlined /> },
  { path: '/stock',      name: '股票分析',   icon: <StockOutlined /> },
  { path: '/ai',         name: 'AI决策',     icon: <RobotOutlined /> },
  { path: '/screener',   name: '智能选股',   icon: <FilterOutlined /> },
  { path: '/strategy',   name: '策略管理',   icon: <ControlOutlined /> },
  { path: '/backtest',   name: '回测系统',   icon: <HistoryOutlined /> },
  { path: '/risk',       name: '风控中心',   icon: <SafetyCertificateOutlined /> },
  { path: '/trade',      name: '交易执行',   icon: <TransactionOutlined /> },
];

export const AppLayout = () => {
  const location = useLocation();

  return (
    <ProLayout
      title="AI Quant Trader Pro"
      logo="/logo.png"
      menuDataRender={() => menuItems}
      menuItemRender={(item, dom) => <Link to={item.path!}>{dom}</Link>}
      location={location}
      rightContentRender={() => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <TradeModeSwitch />
          <MarketStatusBadge />
        </div>
      )}
    >
      <Outlet />
    </ProLayout>
  );
};
```
