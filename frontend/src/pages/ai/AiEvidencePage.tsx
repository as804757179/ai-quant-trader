import { pendingState } from "../../presentation/readOnlyApi";
import DataMetaBar from "../../ui/DataMetaBar";
import EmptyState from "../../ui/EmptyState";
import StatusBadge from "../../ui/StatusBadge";

export default function AiEvidencePage() {
  const state = pendingState("AI 证据复核接口待接入", "ai-evidence-ui-v1");

  return (
    <section className="page-frame page-frame--simple">
      <header className="page-header"><div><h1>证据复核</h1><p>AI 上下文、证据来源、数据资格和审核状态</p></div><StatusBadge label="待接入" tone="review" /></header>
      <DataMetaBar provenance={state.provenance} relatedId="ai:evidence" />
      <section className="panel"><div className="panel__title">证据清单</div><div className="panel__body"><EmptyState description={state.message} /></div></section>
      <section className="panel"><div className="panel__title">审核规则</div><div className="panel__body"><p className="soft-note">上下文必须记录来源、截止时间、版本和认证状态。unknown、synthetic 或 uncertified 数据不得被包装成可用于交易判断的证据。</p></div></section>
    </section>
  );
}
