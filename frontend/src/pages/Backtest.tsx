import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Statistic,
  Table,
  message,
} from "antd";
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { get, post } from "../api/client";
import PageShell from "../components/PageShell";

dayjs.locale("zh-cn");

const STRATEGY_OPTS = [
  { value: "dual_ma", label: "双均线" },
  { value: "bollinger", label: "布林带" },
  { value: "rsi", label: "RSI" },
  { value: "macd", label: "MACD" },
];

export default function Backtest() {
  const location = useLocation();
  const state = (location.state || {}) as { strategy_type?: string; params?: Record<string, number> };
  const [form] = Form.useForm();
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<Record<string, number> | null>(null);
  const [trades, setTrades] = useState<Record<string, unknown>[]>([]);
  const [tasks, setTasks] = useState<Record<string, unknown>[]>([]);

  const loadTasks = () => {
    get<{ items: Record<string, unknown>[] }>("/backtest/tasks", { limit: 20 })
      .then((res) => setTasks(res.data?.items || []))
      .catch(() => undefined);
  };

  useEffect(() => {
    form.setFieldsValue({
      strategy_type: state.strategy_type || "dual_ma",
      stock_codes: "000001",
      range: [dayjs().subtract(12, "month"), dayjs()],
      initial_cash: 1_000_000,
    });
    loadTasks();
  }, []);

  const onRun = async (values: Record<string, unknown>) => {
    setRunning(true);
    setMetrics(null);
    setTrades([]);
    try {
      const range = values.range as [dayjs.Dayjs, dayjs.Dayjs];
      const codes = String(values.stock_codes)
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await post<{
        metrics: Record<string, number>;
        trades: Record<string, unknown>[];
        task_id: number;
        data_meta?: { synthetic_used?: boolean };
      }>("/backtest/run", {
        strategy_type: values.strategy_type,
        stock_codes: codes,
        start_date: range[0].format("YYYY-MM-DD"),
        end_date: range[1].format("YYYY-MM-DD"),
        initial_cash: values.initial_cash,
        params: state.params,
        auto_backfill: true,
        allow_synthetic: true,
      });
      setMetrics(res.data?.metrics || null);
      setTrades(res.data?.trades || []);
      const synth = res.data?.data_meta?.synthetic_used;
      message.success(
        synth
          ? `回测完成（合成K线演示） 任务号=${res.data?.task_id}`
          : `回测完成 任务号=${res.data?.task_id}`
      );
      loadTasks();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "回测失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <PageShell title="策略回测" subtitle="A 股 T+1 规则 · 支持自动回填 K 线">
      <Card title="运行回测">
        <Form form={form} layout="inline" className="page-form-bar" onFinish={onRun}>
          <Form.Item name="strategy_type" label="策略" rules={[{ required: true }]}>
            <Select style={{ minWidth: 120, width: 140 }} options={STRATEGY_OPTS} />
          </Form.Item>
          <Form.Item name="stock_codes" label="代码" rules={[{ required: true }]}>
            <Input style={{ minWidth: 140, width: 180 }} placeholder="000001,600519" />
          </Form.Item>
          <Form.Item name="range" label="区间" rules={[{ required: true }]}>
            <DatePicker.RangePicker style={{ width: "100%", minWidth: 220 }} />
          </Form.Item>
          <Form.Item name="initial_cash" label="本金">
            <InputNumber min={10000} step={10000} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={running}>
              开始回测
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {metrics && (
        <Card title="绩效">
          <Row gutter={[16, 16]}>
            <Col xs={12} sm={8} md={4}>
              <Statistic
                title="总收益"
                value={(metrics.total_return || 0) * 100}
                precision={2}
                suffix="%"
              />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic
                title="年化"
                value={(metrics.annual_return || 0) * 100}
                precision={2}
                suffix="%"
              />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic
                title="最大回撤"
                value={(metrics.max_drawdown || 0) * 100}
                precision={2}
                suffix="%"
              />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic title="夏普" value={metrics.sharpe_ratio || 0} precision={2} />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic
                title="胜率"
                value={(metrics.win_rate || 0) * 100}
                precision={1}
                suffix="%"
              />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Statistic title="成交笔数" value={metrics.total_trades || 0} />
            </Col>
          </Row>
        </Card>
      )}

      <Card title="成交明细">
        <div className="page-table-scroll">
          <Table
            rowKey={(_, i) => String(i)}
            dataSource={trades}
            size="small"
            scroll={{ x: 800 }}
            columns={[
              { title: "代码", dataIndex: "stock_code" },
              { title: "方向", dataIndex: "side" },
              { title: "信号日", dataIndex: "signal_date" },
              { title: "成交日", dataIndex: "execution_date" },
              { title: "数量", dataIndex: "quantity" },
              { title: "价格", dataIndex: "fill_price" },
              { title: "状态", dataIndex: "status" },
              { title: "失败原因", dataIndex: "fail_reason", ellipsis: true },
            ]}
            pagination={{ pageSize: 8, responsive: true }}
          />
        </div>
      </Card>

      <Card title="历史任务" extra={<Button onClick={loadTasks}>刷新</Button>}>
        <div className="page-table-scroll">
          <Table
            rowKey="task_id"
            dataSource={tasks}
            size="small"
            scroll={{ x: 640 }}
            columns={[
              { title: "ID", dataIndex: "task_id", width: 70 },
              { title: "名称", dataIndex: "name", ellipsis: true },
              { title: "状态", dataIndex: "status", width: 90 },
              { title: "进度", dataIndex: "progress", width: 70 },
              {
                title: "区间",
                render: (_, r) => `${r.start_date} ~ ${r.end_date}`,
              },
              { title: "标的", dataIndex: "universe", ellipsis: true },
            ]}
            pagination={{ pageSize: 5, responsive: true }}
          />
        </div>
      </Card>
    </PageShell>
  );
}
