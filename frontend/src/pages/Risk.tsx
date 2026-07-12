import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { get, post } from "../api/client";
import PageShell from "../components/PageShell";

const MODE_OPTS = [
  { value: "simulation", label: "模拟" },
  { value: "paper", label: "纸面" },
  { value: "live", label: "实盘" },
];

export default function Risk() {
  const [rules, setRules] = useState<Record<string, unknown>[]>([]);
  const [fuse, setFuse] = useState<{ is_active?: boolean; history?: Record<string, unknown>[] }>(
    {}
  );
  const [exposure, setExposure] = useState<Record<string, unknown> | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<Record<string, unknown>[]>([]);
  const [mode, setMode] = useState("simulation");

  const load = useCallback(async () => {
    try {
      const [r1, r2, r3, r4] = await Promise.all([
        get<{ items: Record<string, unknown>[] }>("/risk/rules"),
        get<{ is_active: boolean; history: Record<string, unknown>[] }>("/risk/fuse-status", {
          mode,
        }),
        get<Record<string, unknown>>("/risk/exposure", { mode }),
        get<{ items: Record<string, unknown>[] }>("/risk/alerts", { limit: 5 }),
      ]);
      setRules(r1.data?.items || []);
      setFuse(r2.data || {});
      setExposure(r3.data || null);
      setRecentAlerts(r4.data?.items || []);
    } catch {
      message.error("风控数据加载失败");
    }
  }, [mode]);

  useEffect(() => {
    load();
  }, [load]);

  const recover = async (values: { approved_by: string; note: string }) => {
    try {
      await post("/risk/fuse/recover", { mode, ...values });
      message.success("熔断已解除");
      load();
    } catch {
      message.error("解除失败");
    }
  };

  return (
    <PageShell
      title="风险控制"
      subtitle="熔断、暴露度与规则管理"
      extra={
        <Space wrap className="page-actions">
          <Select style={{ minWidth: 120, width: 140 }} value={mode} options={MODE_OPTS} onChange={setMode} />
          <Button size="small" onClick={load}>
            刷新
          </Button>
        </Space>
      }
    >
        {fuse.is_active && (
          <Alert
            type="error"
            showIcon
            message={`${mode} 熔断已激活 — 所有交易暂停`}
            description="需人工确认后解除"
          />
        )}

        {recentAlerts.length > 0 && (
          <Card title="最近告警" size="small">
            <Space direction="vertical" style={{ width: "100%" }}>
              {recentAlerts.map((a, i) => (
                <Alert
                  key={i}
                  type={
                    a.level === "CRITICAL" || a.level === "ERROR"
                      ? "error"
                      : a.level === "WARNING"
                        ? "warning"
                        : "info"
                  }
                  showIcon
                  message={`${a.level || ""} ${a.message || a.type || ""}`}
                  description={String(a.ts || "")}
                />
              ))}
            </Space>
          </Card>
        )}

        <Card title="账户暴露">
          <Row gutter={[16, 16]}>
            <Col xs={12} sm={8} md={4}>
              <Statistic
                title="总资产"
                prefix="¥"
                value={Number(exposure?.total_assets || 0)}
                precision={2}
              />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic title="现金" prefix="¥" value={Number(exposure?.cash || 0)} precision={2} />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic
                title="仓位比"
                value={Number(exposure?.position_ratio || 0) * 100}
                precision={1}
                suffix="%"
              />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic
                title="日盈亏%"
                value={Number(exposure?.daily_pnl_pct || 0) * 100}
                precision={2}
                suffix="%"
              />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic
                title="回撤"
                value={Math.abs(Number(exposure?.drawdown_from_peak || 0)) * 100}
                precision={2}
                suffix="%"
              />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <div style={{ paddingTop: 4 }}>
                <Tag color={fuse.is_active ? "red" : "green"}>
                  熔断: {fuse.is_active ? "已激活" : "正常"}
                </Tag>
              </div>
            </Col>
          </Row>
        </Card>

        <Card title="持仓集中度">
          <div className="page-table-scroll">
            <Table
              rowKey="stock_code"
              dataSource={(exposure?.positions as Record<string, unknown>[]) || []}
              size="small"
              scroll={{ x: 560 }}
              columns={[
                { title: "代码", dataIndex: "stock_code" },
                { title: "行业", dataIndex: "sector" },
                { title: "市值", dataIndex: "market_value" },
                {
                  title: "占比",
                  dataIndex: "ratio",
                  render: (v: number) => `${((v || 0) * 100).toFixed(1)}%`,
                },
                { title: "浮盈", dataIndex: "unrealized_pnl" },
              ]}
              pagination={false}
            />
          </div>
        </Card>

        <Card title="风控规则">
          <div className="page-table-scroll">
            <Table
              rowKey="rule_code"
              dataSource={rules}
              size="small"
              scroll={{ x: 720 }}
              columns={[
                { title: "代码", dataIndex: "rule_code", width: 160 },
                { title: "名称", dataIndex: "rule_name", width: 120 },
                { title: "阈值", dataIndex: "threshold", width: 90 },
                { title: "动作", dataIndex: "action", width: 90 },
                {
                  title: "硬性",
                  dataIndex: "is_hard",
                  width: 70,
                  render: (v: boolean) => (v ? "是" : "否"),
                },
                { title: "说明", dataIndex: "description", ellipsis: true },
              ]}
              pagination={false}
            />
          </div>
        </Card>

        {fuse.is_active && (
          <Card title="解除熔断">
            <Form
              layout="inline"
              className="page-form-bar"
              onFinish={recover}
              initialValues={{ approved_by: "operator" }}
            >
              <Form.Item name="approved_by" label="审批人" rules={[{ required: true }]}>
                <Input style={{ minWidth: 120 }} />
              </Form.Item>
              <Form.Item name="note" label="备注">
                <Input style={{ minWidth: 160, width: 240 }} />
              </Form.Item>
              <Form.Item>
                <Button danger type="primary" htmlType="submit">
                  确认恢复
                </Button>
              </Form.Item>
            </Form>
          </Card>
        )}
    </PageShell>
  );
}
