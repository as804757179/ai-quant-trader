import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("平台审计页面使用服务端分页并保留完整性哈希未记录状态", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/system/SystemPages.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<SystemAuditEventListData>\("\/system\/audit-events", \{ page, page_size: pageSize, event_type: filters\.eventType/);
  assert.match(page, /useSystemAuditEvents\(page, pageSize\)/);
  assert.match(page, /服务端支持事件类型、关联 ID、主体和时间范围筛选/);
  assert.match(page, /未提供逐事件完整性 Hash/);
  assert.match(page, /tablePagination=/);
  assert.doesNotMatch(page, /system-audit-ui-v1/);
});
