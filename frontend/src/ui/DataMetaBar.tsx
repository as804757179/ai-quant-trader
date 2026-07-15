import type { DataProvenance } from "../presentation/contracts";

interface DataMetaBarProps {
  provenance: DataProvenance;
  relatedId?: string;
  statusText?: string;
}

export default function DataMetaBar({
  provenance,
  relatedId = "待接入",
  statusText = "基础设施 待接入 · 数据资格 待审核 · 业务发布 关闭",
}: DataMetaBarProps) {
  return (
    <section className="data-meta-bar" aria-label="数据血缘">
      <div>
        <span>数据截止时间</span>
        <strong>{provenance.dataCutoff}</strong>
      </div>
      <div>
        <span>来源与版本</span>
        <strong>{provenance.sourceVersion}</strong>
      </div>
      <div>
        <span>关联 ID</span>
        <strong>{relatedId === "待接入" ? provenance.traceId : relatedId}</strong>
      </div>
      <div>
        <span>状态语义</span>
        <strong>{statusText}</strong>
      </div>
    </section>
  );
}
