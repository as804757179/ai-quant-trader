import type { CSSProperties } from "react";
import type { TableProps } from "antd";
import { pendingState } from "../../presentation/readOnlyApi";
import DataMetaBar from "../../ui/DataMetaBar";
import MetricCard from "../../ui/MetricCard";
import ReadOnlyTable from "../../ui/ReadOnlyTable";
import StatusBadge from "../../ui/StatusBadge";

interface ReadinessRow {
  key: string;
  stockCode: string;
  range: string;
  profile: string;
  status: string;
  blocker: string;
}

export default function ReadinessPage() {
  const state = pendingState("Research Readiness 接口待接入", "readiness-ui-v1");
  const columns: TableProps<ReadinessRow>["columns"] = [
    { title: "股票代码", dataIndex: "stockCode", width: 150 },
    { title: "审核区间", dataIndex: "range", width: 220 },
    { title: "Requirement Profile", dataIndex: "profile", width: 250 },
    { title: "状态", dataIndex: "status", width: 120, render: () => <StatusBadge label="待接入" tone="review" /> },
    { title: "阻塞归因", dataIndex: "blocker", width: 280 },
  ];

  return (
    <section className="page-frame page-frame--fill">
      <header className="page-header"><div><h1>研究态势 / Research Readiness</h1><p>数据研究可用性、字段级授权与阻断原因</p></div><StatusBadge label="数据资格待审核" tone="review" /></header>
      <DataMetaBar provenance={state.provenance} relatedId="readiness:scoped-review" />
      <div className="metric-grid" style={{ "--metric-columns": 5 } as CSSProperties}>
        <MetricCard label="研究可用范围" value="待接入" detail="按用途与 Profile 审核" tone="review" />
        <MetricCard label="数据覆盖率" value="待接入" detail="不使用未审核覆盖率" tone="review" />
        <MetricCard label="缺失交易日" value="待接入" detail="必须逐日归因" tone="review" />
        <MetricCard label="企业行动审核" value="待接入" detail="不自动推断事件日期" tone="review" />
        <MetricCard label="Return Backtest" value="关闭" detail="公共回测发布锁关闭" tone="idle" />
      </div>
      <div className="readiness-grid">
        <section className="panel table-panel"><div className="panel__title">按股票与研究用途审核</div><div className="panel__body"><ReadOnlyTable columns={columns} data={[]} rowKey="key" emptyDescription={state.message} /></div></section>
        <section className="panel"><div className="panel__title">阻塞原因分布</div><div className="panel__body"><p className="soft-note">缺失交易日、企业行动、Provider 验证和字段级未决项必须保留真实归因；未认证数据不得进入可信研究。</p></div></section>
      </div>
      <section className="panel"><div className="panel__title">授权规则</div><div className="panel__body policy-list"><span>Certified 不等于所有用途 ready</span><span>权限键必须包含标的、区间、复权口径、用途和 Requirement Profile</span><span>一个 Profile 的 ready 不得传播到 Amount 或 Execution Reference</span></div></section>
    </section>
  );
}
