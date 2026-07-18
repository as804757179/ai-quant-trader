import assert from "node:assert/strict";
import test from "node:test";

import { readOptional } from "../src/presentation/readOnlyApiCore.mjs";

test("只读响应使用后端时间、版本和请求 ID", async () => {
  const state = await readOptional(
    async () => ({
      data: { value: 1, source_version: "backend-contract-v2" },
      timestamp: "2026-07-15T10:20:30+08:00",
      requestId: "request-001",
    }),
    "fallback-v1",
  );

  assert.equal(state.kind, "live");
  assert.deepEqual(state.provenance, {
    dataCutoff: "2026-07-15 10:20:30",
    sourceVersion: "backend-contract-v2",
    traceId: "request-001",
  });
});

test("空列表保持真实血缘且显示空状态", async () => {
  const state = await readOptional(
    async () => ({
      data: { items: [], total: 0 },
      timestamp: "2026-07-15T11:20:30+08:00",
      requestId: "request-empty",
    }),
    "empty-v1",
  );

  assert.equal(state.kind, "empty");
  assert.equal(state.provenance.traceId, "request-empty");
});

test("无权限和接口失败不会伪装为已接入", async () => {
  const forbidden = await readOptional(async () => {
    const error = new Error("forbidden");
    error.status = 403;
    throw error;
  }, "guard-v1");
  const unavailable = await readOptional(async () => {
    throw new Error("后端不可达");
  }, "guard-v1");

  assert.equal(forbidden.kind, "forbidden");
  assert.equal(unavailable.kind, "unavailable");
  assert.equal(unavailable.message, "后端不可达");
});
