import { Alert, Button, Form, Input, InputNumber, Select, Table, message } from "antd";
import { useEffect, useState } from "react";
import { get, post } from "../api/client";

export default function Trade() {
  const [positions, setPositions] = useState<Record<string, unknown>[]>([]);
  const [riskMsg, setRiskMsg] = useState<string | null>(null);
  const [form] = Form.useForm();

  const loadPositions = () => {
    get<Record<string, unknown>[]>("/portfolio/positions").then((res) => {
      setPositions(res.data || []);
    });
  };

  useEffect(() => {
    loadPositions();
  }, []);

  const onSubmit = async (values: Record<string, unknown>) => {
    setRiskMsg(null);
    try {
      const res = await post("/trade/order", values);
      if (res.data && (res.data as { success?: boolean }).success === false) {
        const detail = res.data as { message?: string; risk_report?: { checks?: { message: string }[] } };
        setRiskMsg(detail.message || "下单失败");
        if (detail.risk_report?.checks?.length) {
          setRiskMsg(detail.risk_report.checks.map((c) => c.message).join("；"));
        }
        message.error("下单被拦截");
      } else {
        message.success("下单成功");
        loadPositions();
      }
    } catch {
      message.error("下单请求失败");
    }
  };

  return (
    <div style={{ padding: 24 }}>
      {riskMsg && <Alert type="error" message={riskMsg} style={{ marginBottom: 16 }} />}
      <Form
        form={form}
        layout="inline"
        initialValues={{ side: "BUY", order_type: "LIMIT", mode: "simulation", quantity: 100 }}
        onFinish={onSubmit}
      >
        <Form.Item name="stock_code" label="代码" rules={[{ required: true }]}>
          <Input style={{ width: 120 }} placeholder="000001" maxLength={6} />
        </Form.Item>
        <Form.Item name="side" label="方向">
          <Select style={{ width: 100 }} options={[{ value: "BUY" }, { value: "SELL" }]} />
        </Form.Item>
        <Form.Item name="order_type" label="类型">
          <Select style={{ width: 100 }} options={[{ value: "LIMIT" }, { value: "MARKET" }]} />
        </Form.Item>
        <Form.Item name="limit_price" label="限价">
          <InputNumber min={0} step={0.01} />
        </Form.Item>
        <Form.Item name="quantity" label="数量" rules={[{ required: true }]}>
          <InputNumber min={100} step={100} />
        </Form.Item>
        <Form.Item name="mode" hidden>
          <Select />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit">
            提交订单
          </Button>
        </Form.Item>
      </Form>
      <Table
        style={{ marginTop: 24 }}
        rowKey="stock_code"
        dataSource={positions}
        columns={[
          { title: "代码", dataIndex: "stock_code" },
          { title: "名称", dataIndex: "name" },
          { title: "持仓", dataIndex: "total_qty" },
          { title: "可卖", dataIndex: "available_qty" },
          { title: "成本", dataIndex: "avg_cost" },
          { title: "现价", dataIndex: "current_price" },
          { title: "浮盈", dataIndex: "unrealized_pnl" },
        ]}
      />
    </div>
  );
}