import { Button, Card, Form, Input, Table, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { get, post } from "../api/client";
import PageShell from "../components/PageShell";

interface SignalRow {
  id: string;
  stock_code: string;
  action: string;
  confidence: number;
  risk_level: string;
  price_at?: number;
  reason?: string;
  signal_time?: string;
}

export default function AI() {
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [form] = Form.useForm();

  const loadSignals = async () => {
    setLoading(true);
    try {
      const res = await get<{ items: SignalRow[] }>("/ai/signals", {
        page_size: 50,
      });
      setSignals(res.data?.items || []);
    } catch {
      message.error("加载信号失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSignals();
  }, []);

  const onAnalyze = async (values: { code: string }) => {
    setAnalyzing(true);
    try {
      const res = await post(`/ai/${values.code}/analyze`, {});
      message.success(res.message || "分析完成");
      await loadSignals();
    } catch {
      message.error("分析请求失败（需行情与 AI Key）");
    } finally {
      setAnalyzing(false);
    }
  };

  const actionColor = (a: string) =>
    a === "BUY" ? "red" : a === "SELL" ? "green" : "default";

  return (
    <PageShell
      title="AI 决策"
      subtitle="多模型分析与交易信号（需配置 API Key）"
      extra={
        <Button onClick={loadSignals} loading={loading}>
          刷新列表
        </Button>
      }
    >
      <Card title="触发分析">
        <Form
          form={form}
          layout="inline"
          className="page-form-bar"
          onFinish={onAnalyze}
          initialValues={{ code: "000001" }}
        >
          <Form.Item name="code" label="股票代码" rules={[{ required: true }]}>
            <Input maxLength={6} style={{ minWidth: 120, width: 140 }} placeholder="000001" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={analyzing}>
              开始分析
            </Button>
          </Form.Item>
        </Form>
      </Card>
      <Card title="最近信号">
        <div className="page-table-scroll">
          <Table
            rowKey="id"
            loading={loading}
            dataSource={signals}
            scroll={{ x: 800 }}
            columns={[
              { title: "代码", dataIndex: "stock_code", width: 100 },
              {
                title: "动作",
                dataIndex: "action",
                width: 90,
                render: (v: string) => (
                  <Tag color={actionColor(v)}>
                    {v === "BUY" ? "买入" : v === "SELL" ? "卖出" : v}
                  </Tag>
                ),
              },
              {
                title: "置信度",
                dataIndex: "confidence",
                width: 100,
                render: (v: number) => (v != null ? `${(v * 100).toFixed(1)}%` : "—"),
              },
              { title: "风险", dataIndex: "risk_level", width: 100 },
              { title: "价格", dataIndex: "price_at", width: 100 },
              { title: "理由", dataIndex: "reason", ellipsis: true },
              { title: "时间", dataIndex: "signal_time", width: 180 },
            ]}
            pagination={{ pageSize: 10, responsive: true }}
          />
        </div>
      </Card>
    </PageShell>
  );
}
