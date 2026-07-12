import { Button, Card, Form, Input, InputNumber, Select, Table, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { get, post } from "../api/client";
import PageShell from "../components/PageShell";

const { Text } = Typography;

export default function Screener() {
  const [presets, setPresets] = useState<{ id: string; name: string; description?: string }[]>([]);
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState("");
  const [form] = Form.useForm();

  useEffect(() => {
    get<{ items: { id: string; name: string; description?: string }[] }>("/screener/presets")
      .then((res) => {
        const list = res.data?.items || [];
        setPresets(list);
        if (list.length) form.setFieldsValue({ preset_id: list[0].id });
      })
      .catch(() => message.warning("预设加载失败"));
  }, [form]);

  const runPreset = async (values: { preset_id: string; limit: number }) => {
    setLoading(true);
    try {
      const res = await post<{
        items: Record<string, unknown>[];
        total?: number;
        universe_size?: number;
        note?: string;
      }>("/screener/screen", {
        preset_id: values.preset_id,
        limit: values.limit,
      });
      setItems(res.data?.items || []);
      const note =
        res.data?.note ||
        `股票池 ${res.data?.universe_size ?? "?"} 只 → 筛选 ${res.data?.total ?? res.data?.items?.length ?? 0} 只`;
      setMeta(note);
      message.success(note);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "选股失败");
    } finally {
      setLoading(false);
    }
  };

  const runTheme = async (values: { theme: string; limit: number }) => {
    setLoading(true);
    try {
      const res = await post<{ items: Record<string, unknown>[] }>("/screener/theme", {
        theme: values.theme,
        limit: values.limit,
      });
      setItems(res.data?.items || []);
      setMeta(`主题选股完成，共 ${res.data?.items?.length || 0} 只`);
      message.success(`主题选股完成，共 ${res.data?.items?.length || 0} 只`);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "主题选股失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <PageShell title="智能选股" subtitle="预设条件与主题筛选 · 基于全市场股票池">
      <Card title="预设选股">
        <Form
          form={form}
          layout="inline"
          className="page-form-bar"
          onFinish={runPreset}
          initialValues={{ preset_id: "all_active", limit: 50 }}
        >
          <Form.Item name="preset_id" label="预设">
            <Select
              style={{ minWidth: 200, width: 260 }}
              options={presets.map((p) => ({
                value: p.id,
                label: p.name,
                title: p.description,
              }))}
            />
          </Form.Item>
          <Form.Item name="limit" label="返回上限">
            <InputNumber min={5} max={200} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading}>
              运行
            </Button>
          </Form.Item>
        </Form>
        {meta ? (
          <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
            {meta}
          </Text>
        ) : null}
      </Card>

      <Card title="主题选股">
        <Form
          layout="inline"
          className="page-form-bar"
          onFinish={runTheme}
          initialValues={{ theme: "AI", limit: 30 }}
        >
          <Form.Item name="theme" label="主题" rules={[{ required: true }]}>
            <Input style={{ minWidth: 140, width: 180 }} placeholder="AI / 新能源" />
          </Form.Item>
          <Form.Item name="limit" label="数量">
            <InputNumber min={5} max={100} />
          </Form.Item>
          <Form.Item>
            <Button htmlType="submit" loading={loading}>
              主题筛选
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title={`结果（${items.length}）`}>
        <div className="page-table-scroll">
          <Table
            rowKey={(r) => String(r.code || r.stock_code)}
            loading={loading}
            dataSource={items}
            scroll={{ x: 720 }}
            columns={[
              { title: "代码", dataIndex: "code", width: 100 },
              { title: "名称", dataIndex: "name", width: 120 },
              { title: "行业", dataIndex: "sector", width: 120 },
              { title: "涨跌%", dataIndex: "change_pct", width: 90 },
              { title: "量比", dataIndex: "volume_ratio", width: 90 },
              { title: "AI动作", dataIndex: "ai_action", width: 90 },
              { title: "置信度", dataIndex: "ai_confidence", width: 90 },
            ]}
            pagination={{ pageSize: 15, responsive: true }}
          />
        </div>
      </Card>
    </PageShell>
  );
}
