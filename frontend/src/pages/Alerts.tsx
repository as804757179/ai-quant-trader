import { Alert, Button, Card, Select, Space, Table, Tag, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { get } from "../api/client";
import PageShell from "../components/PageShell";
import { useWebSocket } from "../hooks/useWebSocket";

interface AlertItem {
  type?: string;
  level?: string;
  message?: string;
  ts?: string;
  detail?: Record<string, unknown>;
}

const levelColor: Record<string, string> = {
  INFO: "blue",
  WARNING: "orange",
  ERROR: "red",
  CRITICAL: "magenta",
};

export default function Alerts() {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [liveBanner, setLiveBanner] = useState<string | null>(null);
  const [levelFilter, setLevelFilter] = useState<string | undefined>(undefined);
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined);

  const load = useCallback(() => {
    const params: Record<string, unknown> = { limit: 80 };
    if (levelFilter) params.level = levelFilter;
    if (typeFilter) params.alert_type = typeFilter;
    get<{ items: AlertItem[] }>("/risk/alerts", params)
      .then((res) => setItems(res.data?.items || []))
      .catch(() => message.warning("加载历史告警失败（可能 Redis 未就绪）"));
  }, [levelFilter, typeFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const { connected } = useWebSocket("/ws/alerts", (msg) => {
    const m = msg as AlertItem;
    if (!m?.message && !m?.type) return;
    if (levelFilter && (m.level || "").toUpperCase() !== levelFilter) return;
    if (typeFilter && m.type !== typeFilter) return;
    setLiveBanner(`${m.level || "INFO"}: ${m.message || m.type}`);
    setItems((prev) => [m, ...prev].slice(0, 100));
  });

  const typeOptions = useMemo(() => {
    const set = new Set<string>();
    items.forEach((i) => i.type && set.add(i.type));
    return Array.from(set).map((t) => ({ value: t, label: t }));
  }, [items]);

  return (
    <PageShell
      title="告警中心"
      subtitle="实时推送与历史告警"
      extra={
        <Space wrap className="page-actions">
          <Select
            allowClear
            placeholder="级别"
            style={{ minWidth: 110, width: 130 }}
            value={levelFilter}
            onChange={setLevelFilter}
            options={[
              { value: "CRITICAL", label: "严重" },
              { value: "ERROR", label: "错误" },
              { value: "WARNING", label: "警告" },
              { value: "INFO", label: "信息" },
            ]}
          />
          <Select
            allowClear
            placeholder="类型"
            style={{ minWidth: 120, width: 160 }}
            value={typeFilter}
            onChange={setTypeFilter}
            options={typeOptions}
          />
          <Tag color={connected ? "green" : "default"}>
            {connected ? "推送已连接" : "推送未连接"}
          </Tag>
          <Button size="small" onClick={load}>
            刷新
          </Button>
        </Space>
      }
    >
      <Card title="告警列表">
        {liveBanner && (
          <Alert
            type="info"
            showIcon
            message={liveBanner}
            closable
            onClose={() => setLiveBanner(null)}
            style={{ marginBottom: 16 }}
          />
        )}
        <div className="page-table-scroll">
          <Table
            rowKey={(_, i) => String(i)}
            dataSource={items}
            size="small"
            scroll={{ x: 720 }}
            columns={[
              {
                title: "级别",
                dataIndex: "level",
                width: 100,
                render: (v: string) => (
                  <Tag color={levelColor[v] || "default"}>{v || "—"}</Tag>
                ),
              },
              { title: "类型", dataIndex: "type", width: 140 },
              { title: "消息", dataIndex: "message", ellipsis: true },
              { title: "时间", dataIndex: "ts", width: 180 },
            ]}
            pagination={{ pageSize: 15, responsive: true }}
            expandable={{
              expandedRowRender: (row) => (
                <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                  {JSON.stringify(row.detail || {}, null, 2)}
                </pre>
              ),
            }}
          />
        </div>
      </Card>
    </PageShell>
  );
}
