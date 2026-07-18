import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("系统任务页面使用服务端分页且不将调度声明视为运行成功", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/system/SystemPages.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<SystemJobListData>\("\/system\/jobs", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useSystemJobs\(page, pageSize\)/);
  assert.match(page, /调度运行状态未观测/);
  assert.match(page, /不启动、停止、重试或修改任务/);
  assert.match(page, /tablePagination=/);
  assert.doesNotMatch(page, /system-schedule-ui-v1/);
});
