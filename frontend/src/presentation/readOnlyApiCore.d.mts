import type { DataProvenance, DisplayState } from "./contracts";

export function liveState<T>(
  data: T,
  sourceVersion: string,
  provenance?: Partial<DataProvenance>,
): DisplayState<T>;

export function loadingState(message?: string, sourceVersion?: string): DisplayState<never>;

export function emptyState<T>(
  data: T,
  message?: string,
  sourceVersion?: string,
  provenance?: Partial<DataProvenance>,
): DisplayState<T>;

export function pendingState(message?: string, sourceVersion?: string): DisplayState<never>;

export function unavailableState(message?: string, sourceVersion?: string): DisplayState<never>;

export function forbiddenState(message?: string, sourceVersion?: string): DisplayState<never>;

export function readOptional<T>(
  loader: () => Promise<{
    data: T;
    timestamp?: string;
    requestId?: string;
  }>,
  sourceVersion: string,
): Promise<DisplayState<T>>;
