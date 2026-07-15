import { pendingState } from "../../presentation/readOnlyApi";
import DataMetaBar from "../../ui/DataMetaBar";
import EmptyState from "../../ui/EmptyState";
import StatusBadge from "../../ui/StatusBadge";

export default function AiSummaryPage() {
  const state = pendingState("AI 摘要接口待接入", "ai-summary-ui-v1");

  return (
    <section className="page-frame page-frame--simple">
      <header className="page-header"><div><h1>AI 摘要</h1><p>展示性分析摘要，不生成订单或交易指令</p></div><StatusBadge label="仅展示" tone="idle" /></header>
      <DataMetaBar provenance={state.provenance} relatedId="ai:summary" />
      <section className="panel"><div className="panel__title">摘要任务</div><div className="panel__body"><EmptyState description={state.message} /></div></section>
      <section className="panel"><div className="panel__title">使用边界</div><div className="panel__body"><p className="soft-note">历史数据未认证时，AI 输出必须明确“仅可用于展示，不可用于交易判断”。AI 摘要不会创建 simulated、paper 或 live order。</p></div></section>
    </section>
  );
}
