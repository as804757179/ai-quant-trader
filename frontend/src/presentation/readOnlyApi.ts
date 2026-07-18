import {
  emptyState as createEmptyState,
  forbiddenState as createForbiddenState,
  liveState as createLiveState,
  loadingState as createLoadingState,
  pendingState as createPendingState,
  readOptional as readOptionalState,
  unavailableState as createUnavailableState,
} from "./readOnlyApiCore.mjs";
import type { DataProvenance, DisplayState } from "./contracts";

export function liveState<T>(
  data: T,
  sourceVersion: string,
  provenance?: Partial<DataProvenance>,
): DisplayState<T> {
  return createLiveState(data, sourceVersion, provenance);
}

export function loadingState(message = "加载中", sourceVersion = "待接入"): DisplayState<never> {
  return createLoadingState(message, sourceVersion);
}

export function emptyState<T>(
  data: T,
  message = "暂无数据",
  sourceVersion = "待接入",
  provenance?: Partial<DataProvenance>,
): DisplayState<T> {
  return createEmptyState(data, message, sourceVersion, provenance);
}

export function pendingState(message = "待接入", sourceVersion = "待接入"): DisplayState<never> {
  return createPendingState(message, sourceVersion);
}

export function unavailableState(
  message = "接口暂不可用",
  sourceVersion = "待接入",
): DisplayState<never> {
  return createUnavailableState(message, sourceVersion);
}

export function forbiddenState(message = "无权限", sourceVersion = "待接入"): DisplayState<never> {
  return createForbiddenState(message, sourceVersion);
}

export function readOptional<T>(
  loader: () => Promise<{ data: T }>,
  sourceVersion: string,
): Promise<DisplayState<T>> {
  return readOptionalState(loader, sourceVersion);
}
