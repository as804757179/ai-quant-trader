import { Card, Col, Row, Statistic } from "antd";
import { useEffect, useState } from "react";
import { get } from "../api/client";

export default function Dashboard() {
  const [summary, setSummary] = useState<Record<string, number | string | boolean>>({});

  useEffect(() => {
    get<Record<string, number | string | boolean>>("/portfolio/summary")
      .then((res) => setSummary(res.data || {}))
      .catch(() => setSummary({}));
  }, []);

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card>
            <Statistic title="总资产" prefix="¥" value={Number(summary.total_assets || 0)} precision={2} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="现金" prefix="¥" value={Number(summary.cash || 0)} precision={2} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="持仓市值" prefix="¥" value={Number(summary.market_value || 0)} precision={2} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日盈亏"
              prefix="¥"
              value={Number(summary.daily_pnl || 0)}
              precision={2}
              valueStyle={{ color: Number(summary.daily_pnl || 0) >= 0 ? "#3f8600" : "#cf1322" }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}