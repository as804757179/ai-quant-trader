import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("系统告警页面使用服务端分页且排除风险事件", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/system/SystemPages.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<SystemAlertListData>\("\/system\/alerts", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useSystemAlerts\(page, pageSize\)/);
  assert.match(page, /本接口不读取 risk\.risk_events/);
  assert.match(page, /不传播为 Readiness/);
  assert.match(page, /tablePagination=/);
  assert.doesNotMatch(page, /system-alerts-ui-v1/);
});
