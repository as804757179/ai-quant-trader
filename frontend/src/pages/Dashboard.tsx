import { Alert, Card, Col, Row, Select, Space, Statistic, Tag, Button } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get } from "../api/client";
import PageShell from "../components/PageShell";
import { useWebSocket } from "../hooks/useWebSocket";

interface DashData {
  mode?: string;
  portfolio?: Record<string, number>;
  fuse?: { is_active?: boolean };
  alerts?: {
    total?: number;
    critical?: number;
    error?: number;
    warning?: number;
    info?: number;
    latest?: { level?: string; message?: string; ts?: string; type?: string };
  };
}

const MODE_OPTS = [
  { value: "simulation", label: "模拟交易" },
  { value: "paper", label: "纸面/模拟券商" },
  { value: "live", label: "实盘交易" },
];

const MODE_LABEL: Record<string, string> = {
  simulation: "模拟",
  paper: "纸面",
  live: "实盘",
};

export default function Dashboard() {
  const [mode, setMode] = useState("simulation");
  const [data, setData] = useState<DashData>({});
  const [banner, setBanner] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    get<DashData>("/risk/dashboard", { mode })
      .then((res) => setData(res.data || {}))
      .catch(() =>
        get<Record<string, number>>("/portfolio/summary", { mode }).then((res) =>
          setData({ portfolio: res.data || {}, mode })
        )
      );
  }, [mode]);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  const { connected } = useWebSocket("/ws/alerts", (msg) => {
    const m = msg as { level?: string; message?: string; type?: string };
    if (m?.message) {
      setBanner(`${m.level || "INFO"}: ${m.message}`);
      load();
    }
  });

  const p = data.portfolio || {};
  const a = data.alerts || {};
  const fused = Boolean(data.fuse?.is_active);

  return (
    <PageShell
      title="仪表盘"
      subtitle="账户总览 · 中国时区 UTC+8"
      extra={
        <Space wrap className="page-actions">
          <Select
            style={{ minWidth: 140, width: "100%", maxWidth: 200 }}
            value={mode}
            options={MODE_OPTS}
            onChange={setMode}
          />
          <Tag color={mode === "live" ? "red" : mode === "paper" ? "orange" : "blue"}>
            {MODE_LABEL[mode] || mode}
          </Tag>
          <Button size="small" onClick={load}>
            刷新
          </Button>
        </Space>
      }
    >
        {fused && (
          <Alert
            type="error"
            showIcon
            message={`${mode} 熔断已激活`}
            description="交易已暂停，请到风控页处理"
            action={
              <Button size="small" danger onClick={() => navigate("/risk")}>
                去处理
              </Button>
            }
          />
        )}
        {banner && (
          <Alert
            type="warning"
            showIcon
            message={banner}
            closable
            onClose={() => setBanner(null)}
            action={
              <Button size="small" onClick={() => navigate("/alerts")}>
                告警中心
              </Button>
            }
          />
        )}

        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic title="总资产" prefix="¥" value={Number(p.total_assets || 0)} precision={2} />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic title="现金" prefix="¥" value={Number(p.cash || 0)} precision={2} />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic title="持仓市值" prefix="¥" value={Number(p.market_value || 0)} precision={2} />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic
                title="今日盈亏"
                prefix="¥"
                value={Number(p.daily_pnl || 0)}
                precision={2}
                valueStyle={{
                  color: Number(p.daily_pnl || 0) >= 0 ? "#cf1322" : "#389e0d",
                }}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic
                title="仓位比"
                value={Number(p.position_ratio || 0) * 100}
                precision={1}
                suffix="%"
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic
                title="回撤"
                value={Math.abs(Number(p.drawdown_from_peak || 0)) * 100}
                precision={2}
                suffix="%"
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic title="持仓只数" value={Number(p.position_count || 0)} />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Space direction="vertical" size={4}>
                <span>
                  熔断{" "}
                  <Tag color={fused ? "red" : "green"}>{fused ? "已激活" : "正常"}</Tag>
                </span>
                <span>
                  推送{" "}
                  <Tag color={connected ? "green" : "default"}>
                    {connected ? "在线" : "离线"}
                  </Tag>
                </span>
              </Space>
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}>
            <Card
              title="告警概览"
              extra={
                <Button type="link" onClick={() => navigate("/alerts")}>
                  查看全部
                </Button>
              }
            >
              <Row gutter={[12, 12]}>
                <Col xs={12} sm={6}>
                  <Statistic title="合计" value={a.total || 0} />
                </Col>
                <Col xs={12} sm={6}>
                  <Statistic
                    title="严重"
                    value={a.critical || 0}
                    valueStyle={{ color: "#cf1322" }}
                  />
                </Col>
                <Col xs={12} sm={6}>
                  <Statistic title="错误" value={a.error || 0} valueStyle={{ color: "#fa541c" }} />
                </Col>
                <Col xs={12} sm={6}>
                  <Statistic
                    title="警告"
                    value={a.warning || 0}
                    valueStyle={{ color: "#fa8c16" }}
                  />
                </Col>
              </Row>
              {a.latest && (
                <Alert
                  style={{ marginTop: 16 }}
                  type={a.latest.level === "CRITICAL" ? "error" : "info"}
                  message={a.latest.message || a.latest.type}
                  description={a.latest.ts}
                />
              )}
            </Card>
          </Col>
          <Col xs={24} md={12}>
            <Card title="快捷入口">
              <Space wrap>
                <Button type="primary" onClick={() => navigate("/trade")}>
                  交易
                </Button>
                <Button onClick={() => navigate("/risk")}>风控</Button>
                <Button onClick={() => navigate("/alerts")}>告警</Button>
                <Button onClick={() => navigate("/backtest")}>回测</Button>
                <Button onClick={() => navigate("/ai")}>AI 分析</Button>
                <Button onClick={() => navigate("/strategy")}>策略</Button>
              </Space>
            </Card>
          </Col>
        </Row>
    </PageShell>
  );
}
