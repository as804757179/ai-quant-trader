import { Button, Card, Form, InputNumber, Space, Switch, Table, message } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, post } from "../api/client";
import PageShell from "../components/PageShell";

interface StrategyItem {
  type: string;
  name: string;
  description: string;
  scenario: string;
  enabled: boolean;
  params: Record<string, number>;
}

export default function Strategy() {
  const [items, setItems] = useState<StrategyItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<StrategyItem | null>(null);
  const [form] = Form.useForm();
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    try {
      const res = await get<{ items: StrategyItem[] }>("/strategy/list");
      setItems(res.data?.items || []);
    } catch {
      message.error("加载策略失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const toggle = async (row: StrategyItem, enabled: boolean) => {
    try {
      await post(`/strategy/${row.type}/update`, { enabled });
      message.success(enabled ? "已启用" : "已禁用");
      load();
    } catch {
      message.error("更新失败");
    }
  };

  const openEdit = (row: StrategyItem) => {
    setEditing(row);
    form.setFieldsValue(row.params);
  };

  const saveParams = async (values: Record<string, number>) => {
    if (!editing) return;
    try {
      await post(`/strategy/${editing.type}/update`, { params: values });
      message.success("参数已保存");
      setEditing(null);
      load();
    } catch {
      message.error("保存失败");
    }
  };

  return (
    <PageShell
      title="策略管理"
      subtitle="内置策略开关与参数配置"
      extra={
        <Button onClick={load} loading={loading}>
          刷新
        </Button>
      }
    >
      <Card title="内置策略">
        <div className="page-table-scroll">
          <Table
            rowKey="type"
            loading={loading}
            dataSource={items}
            scroll={{ x: 800 }}
            columns={[
              { title: "名称", dataIndex: "name", width: 140 },
              { title: "类型", dataIndex: "type", width: 120 },
              { title: "场景", dataIndex: "scenario", width: 100 },
              { title: "说明", dataIndex: "description", ellipsis: true },
              {
                title: "启用",
                dataIndex: "enabled",
                width: 80,
                render: (v: boolean, row) => (
                  <Switch checked={v} onChange={(c) => toggle(row, c)} />
                ),
              },
              {
                title: "操作",
                width: 160,
                fixed: "right",
                render: (_, row) => (
                  <Space wrap>
                    <Button size="small" onClick={() => openEdit(row)}>
                      参数
                    </Button>
                    <Button
                      size="small"
                      type="link"
                      onClick={() =>
                        navigate("/backtest", {
                          state: { strategy_type: row.type, params: row.params },
                        })
                      }
                    >
                      回测
                    </Button>
                  </Space>
                ),
              },
            ]}
            pagination={false}
          />
        </div>
      </Card>

      {editing && (
        <Card
          title={`编辑参数 — ${editing.name}`}
          extra={<Button onClick={() => setEditing(null)}>关闭</Button>}
        >
          <Form form={form} layout="inline" className="page-form-bar" onFinish={saveParams}>
            {Object.keys(editing.params).map((key) => (
              <Form.Item key={key} name={key} label={key}>
                <InputNumber step={key.includes("pct") || key.includes("mult") ? 0.05 : 1} />
              </Form.Item>
            ))}
            <Form.Item>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
            </Form.Item>
          </Form>
        </Card>
      )}
    </PageShell>
  );
}
