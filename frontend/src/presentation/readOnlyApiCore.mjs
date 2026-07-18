import { formatChinaDateTime } from "./timeCore.mjs";

function createProvenance(sourceVersion, provenance = {}) {
  return {
    dataCutoff: provenance.dataCutoff ?? formatChinaDateTime(new Date()),
    sourceVersion: provenance.sourceVersion ?? sourceVersion,
    traceId: provenance.traceId ?? "待接入",
  };
}

function responseProvenance(response, sourceVersion) {
  const data = response?.data && typeof response.data === "object" ? response.data : {};
  return {
    dataCutoff: formatChinaDateTime(data.data_cutoff ?? response?.timestamp),
    sourceVersion: data.source_version ?? sourceVersion,
    traceId: data.trace_id ?? response?.requestId ?? "待接入",
  };
}

export function liveState(data, sourceVersion, provenance) {
  return {
    kind: "live",
    data,
    message: "已接入",
    provenance: createProvenance(sourceVersion, provenance),
  };
}

export function loadingState(message = "加载中", sourceVersion = "待接入") {
  return {
    kind: "loading",
    message,
    provenance: {
      dataCutoff: "待接入",
      sourceVersion,
      traceId: "待接入",
    },
  };
}

export function emptyState(data, message = "暂无数据", sourceVersion = "待接入", provenance) {
  return {
    kind: "empty",
    data,
    message,
    provenance: createProvenance(sourceVersion, provenance),
  };
}

export function pendingState(message = "待接入", sourceVersion = "待接入") {
  return {
    kind: "pending",
    message,
    provenance: {
      dataCutoff: "待接入",
      sourceVersion,
      traceId: "待接入",
    },
  };
}

export function unavailableState(message = "接口暂不可用", sourceVersion = "待接入") {
  return {
    kind: "unavailable",
    message,
    provenance: {
      dataCutoff: "待接入",
      sourceVersion,
      traceId: "待接入",
    },
  };
}

export function forbiddenState(message = "无权限", sourceVersion = "待接入") {
  return {
    kind: "forbidden",
    message,
    provenance: {
      dataCutoff: "待接入",
      sourceVersion,
      traceId: "待接入",
    },
  };
}

function isEmptyData(data) {
  if (data == null) {
    return true;
  }
  if (Array.isArray(data)) {
    return data.length === 0;
  }
  return Boolean(
    typeof data === "object" &&
      Array.isArray(data.items) &&
      data.items.length === 0 &&
      (data.total == null || data.total === 0),
  );
}

function getErrorStatus(error) {
  return error?.status ?? error?.response?.status;
}

export async function readOptional(loader, sourceVersion) {
  try {
    const response = await loader();
    const provenance = responseProvenance(response, sourceVersion);
    if (isEmptyData(response.data)) {
      return emptyState(response.data, "暂无数据", sourceVersion, provenance);
    }
    return liveState(response.data, sourceVersion, provenance);
  } catch (error) {
    if (getErrorStatus(error) === 401 || getErrorStatus(error) === 403) {
      return forbiddenState("无权限", sourceVersion);
    }
    return unavailableState(error?.message || "接口暂不可用", sourceVersion);
  }
}
