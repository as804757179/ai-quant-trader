import type { TableProps } from "antd";
import type { DataProvenance, StatusTone } from "../../presentation/contracts";
import {
  type StrategyRuntimeStatusItem,
  useStrategyRuntimeStatus,
} from "../../presentation/coreModels";
import StatusBadge from "../../ui/StatusBadge";
import SectionPage from "../shared/SectionPage";

interface StrategyVersionRow {
  key: string;
  strategyId: string;
  version: string;
  configHash: string;
  approval: string;
  approvalTone: StatusTone;
  effectiveStatus: string;
  effectiveTone: StatusTone;
  paramsSource: string;
}

function configStatusLabel(status: string | undefined): string {
  if (status === "approved") return "已审批启用";
  if (status === "approved_disabled") return "已审批禁用";
  if (status === "pending_approval") return "待独立审批";
  if (status === "unconfigured") return "未配置";
  if (status === "invalid") return "配置无效";
  return "未知";
}

function configStatusTone(status: string | undefined): StatusTone {
  if (status === "approved") return "pass";
  if (status === "approved_disabled" || status === "unconfigured") return "idle";
  if (status === "pending_approval") return "review";
  if (status === "invalid") return "reject";
  return "review";
}

function approvalLabel(status: string | null | undefined, configStatus: string | undefined): string {
  if (status === "approved") return "已审批";
  if (status === "pending") return "待独立审批";
  return configStatus === "unconfigured" ? "未提交" : "未记录";
}

function approvalTone(status: string | null | undefined): StatusTone {
  if (status === "approved") return "pass";
  if (status === "pending") return "review";
  return "idle";
}

function paramsSourceLabel(source: string | undefined): string {
  if (source === "approved_version") return "已审批版本";
  if (source === "pending_version_not_active") return "待审批版本（未生效）";
  if (source === "catalog_default_not_active") return "目录默认值（未生效）";
  if (source === "unavailable") return "不可用";
  return "未记录";
}

function toRow(item: StrategyRuntimeStatusItem): StrategyVersionRow {
  const strategyType = item.type ?? "未记录";
  const version = item.version == null ? "未登记" : `v${item.version}`;
  const revision = item.revision == null ? "未登记" : `r${item.revision}`;

  return {
    key: item.version_id?.toString() ?? `${strategyType}-${item.revision ?? "none"}`,
    strategyId: item.strategy_id == null ? strategyType : `${strategyType} · #${item.strategy_id}`,
    version: `${version} / ${revision}`,
    configHash: item.config_hash ?? "未记录",
    approval: approvalLabel(item.approval_status, item.config_status),
    approvalTone: approvalTone(item.approval_status),
    effectiveStatus: configStatusLabel(item.config_status),
    effectiveTone: configStatusTone(item.config_status),
    paramsSource: paramsSourceLabel(item.params_source),
  };
}

export default function StrategyVersionsPage() {
  const strategy = useStrategyRuntimeStatus();
  const items = strategy.data?.items ?? [];
  const rows = items.map(toRow);
  const hasReadResult = strategy.kind === "live" || strategy.kind === "empty";
  const registeredCount = strategy.data?.total ?? rows.length;
  const enabledCount = strategy.data?.enabled_count
    ?? items.filter((item) => item.config_status === "approved" && item.enabled === true).length;
  const pendingCount = items.filter((item) => item.config_status === "pending_approval").length;
  const invalidCount = items.filter((item) => item.config_status === "invalid").length;
  const countValue = (value: number) => (hasReadResult ? String(value) : "未记录");
  const provenance: DataProvenance = {
    ...strategy.provenance,
    dataCutoff: "不适用（策略控制面状态）",
    sourceVersion: strategy.data?.source_version ?? strategy.provenance.sourceVersion,
  };
  const columns: TableProps<StrategyVersionRow>["columns"] = [
    { title: "策略 ID", dataIndex: "strategyId", width: 190 },
    { title: "版本 / 修订", dataIndex: "version", width: 150 },
    { title: "配置 Hash", dataIndex: "configHash", width: 260 },
    {
      title: "审批状态",
      dataIndex: "approval",
      width: 150,
      render: (_value, row) => <StatusBadge label={row.approval} tone={row.approvalTone} />,
    },
    {
      title: "生效状态",
      dataIndex: "effectiveStatus",
      width: 160,
      render: (_value, row) => <StatusBadge label={row.effectiveStatus} tone={row.effectiveTone} />,
    },
    { title: "参数来源", dataIndex: "paramsSource", width: 200 },
  ];

  return (
    <SectionPage
      title="策略版本"
      subtitle="已登记策略的版本、配置 Hash 与独立审批状态；仅只读展示"
      relatedId="strategy:runtime-status"
      provenance={provenance}
      metadataStatusText="策略控制面只读 · 审批状态以接口返回为准 · 本页不授予执行权限"
      statusLabel={strategy.kind === "live" ? "已接入（只读）" : strategy.message}
      statusTone={strategy.kind === "live" ? "info" : "review"}
      metrics={[
        {
          label: "已登记策略",
          value: countValue(registeredCount),
          detail: hasReadResult
            ? `目录版本：${strategy.data?.catalog_version ?? "未记录"}`
            : "接口未返回可核验的策略登记数",
          tone: strategy.kind === "live" ? "info" : "review",
        },
        {
          label: "已审批启用",
          value: countValue(enabledCount),
          detail: "仅反映当前已审批启用配置，不构成交易执行授权",
          tone: !hasReadResult ? "review" : enabledCount > 0 ? "pass" : "idle",
        },
        {
          label: "待独立审批",
          value: countValue(pendingCount),
          detail: "待审批版本未生效，不能作为回测或运行时策略配置",
          tone: !hasReadResult ? "review" : pendingCount > 0 ? "review" : "idle",
        },
        {
          label: "配置异常",
          value: countValue(invalidCount),
          detail: "异常配置保持不可用，需由后端控制面处理",
          tone: !hasReadResult ? "review" : invalidCount > 0 ? "reject" : "idle",
        },
      ]}
      tableTitle="策略版本与审批"
      columns={columns}
      tableData={rows}
      rowKey="key"
      emptyDescription={strategy.message}
      auditTitle="控制面纪律"
      auditItems={[
        {
          label: "审批分离",
          value: "只读展示",
          detail: "提交、审批与生效由后端控制，本页没有审批操作。",
          tone: "info",
        },
        {
          label: "回测快照",
          value: "后端校验",
          detail: "回测使用的策略配置需要与当前已审批启用版本匹配。",
          tone: "info",
        },
        {
          label: "执行权限",
          value: "未授予",
          detail: "策略版本存在、已审批或已启用均不构成交易执行授权。",
          tone: "reject",
        },
      ]}
      note="本页只展示后端返回的策略控制面状态，不提供调参、提交、审批、上线或交易操作；控制面读取时间不代表市场数据截止时间。"
    />
  );
}
