import type { TableProps } from "antd";
import type { DataProvenance, StatusTone } from "../../presentation/contracts";
import { useResearchCandidateStatus } from "../../presentation/coreModels";
import { formatChinaDateTime } from "../../presentation/time";
import SectionPage from "../shared/SectionPage";

interface CandidateRow { key: string; runId: string; stockCode: string; enteredAt: string; expiresAt: string; profile: string; dataStatus: string; tradingStatus: string; reason: string; }

export default function ResearchCandidatesPage() {
  const state = useResearchCandidateStatus(50);
  const candidateKnown = (state.kind === "live" || state.kind === "empty") && Boolean(state.data);
  const tradable = candidateKnown ? state.data?.tradable : undefined;
  const tradingStatus = tradable === true ? "可交易" : tradable === false ? "禁止交易" : "状态未知";
  const candidateStatus = candidateKnown ? state.data?.candidate_status : undefined;
  const releaseLock = candidateKnown ? state.data?.release_lock : undefined;
  const releaseStatus = !candidateKnown
    ? { label: "状态未知", tone: "review" as const }
    : !releaseLock
      ? { label: "未记录", tone: "review" as const }
      : releaseLock.enabled
        ? { label: "开启", tone: "review" as const }
        : { label: "关闭", tone: "reject" as const };
  const orderStatus = !candidateKnown
    ? { label: "状态未知", tone: "review" as const }
    : state.data?.order_created === true
      ? { label: "异常", tone: "reject" as const }
      : state.data?.order_created === false
        ? { label: "关闭", tone: "pass" as const }
        : { label: "未记录", tone: "review" as const };
  const countValue = (value: number | undefined) => candidateKnown ? value ?? "未记录" : "状态未知";
  const provenance: DataProvenance = {
    ...state.provenance,
    dataCutoff: "不适用（研究候选控制状态）",
    sourceVersion: state.data?.source_version ?? state.provenance.sourceVersion,
  };
  const statusTone: StatusTone = candidateStatus === "published"
    ? "pass"
    : candidateStatus === "release_locked"
      ? "reject"
      : "review";
  const rows: CandidateRow[] = (state.data?.items ?? []).map((item, index) => ({
    key: item.review_id ?? `candidate-status-${index}`,
    runId: item.review_id ?? "未记录",
    stockCode: item.stock_code ?? "待接入",
    enteredAt: formatChinaDateTime(item.reviewed_at),
    expiresAt: item.date_to ?? "未记录",
    profile: item.requirement_profile ?? "未记录",
    dataStatus: item.readiness_status ?? "未记录",
    tradingStatus,
    reason: item.review_reason ?? "未记录",
  }));
  const columns: TableProps<CandidateRow>["columns"] = [{ title: "审核记录 ID", dataIndex: "runId", width: 210 }, { title: "股票代码", dataIndex: "stockCode", width: 140 }, { title: "审核时间", dataIndex: "enteredAt", width: 190 }, { title: "区间截止", dataIndex: "expiresAt", width: 150 }, { title: "Requirement Profile", dataIndex: "profile", width: 240 }, { title: "数据状态", dataIndex: "dataStatus", width: 140 }, { title: "交易权限", dataIndex: "tradingStatus", width: 150 }, { title: "排除/待复核原因", dataIndex: "reason", width: 320 }];
  return <SectionPage title="研究候选" subtitle="候选、排除、待复核和不可交易的研究状态" relatedId="research:candidates" provenance={provenance} metadataStatusText="研究候选只读 · 发布锁与交易状态以接口返回为准 · 本页不创建订单" statusLabel={candidateStatus ?? state.message} statusTone={statusTone} metrics={[{ label: "已发布候选", value: candidateKnown ? state.data?.candidate_count ?? "未记录" : "状态未知", detail: "发布锁关闭时不得展示伪候选", tone: statusTone }, { label: "待复核", value: countValue(state.data?.counts?.review_required), detail: "研究资格与交易资格分离", tone: "review" }, { label: "已排除", value: countValue(state.data?.counts?.rejected), detail: "保留真实阻断原因", tone: "reject" }, { label: "自动下单", value: orderStatus.label, detail: "候选不能直接产生订单", tone: orderStatus.tone }]} tableTitle="资格排除与待复核记录" columns={columns} tableData={rows} rowKey="key" emptyDescription={state.message} auditTitle="候选准入" auditItems={[{ label: "数据认证", value: "必需", detail: "unknown/synthetic 不得进入", tone: "info" }, { label: "Readiness", value: "必需", detail: "按用途与 Profile 授权", tone: "info" }, { label: "投资候选发布", value: releaseStatus.label, detail: releaseLock?.reason ?? "发布锁状态未知", tone: releaseStatus.tone }]} note="当前接口仅展示真实 Readiness 排除与待复核记录，不运行 Screener、不发布投资候选，也不创建订单。" />;
}
