import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("服务健康页面分离基础设施、数据资格和业务发布状态", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/system/SystemPages.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<SystemHealthData>\("\/system\/health"\)/);
  assert.match(page, /useSystemHealth\(\)/);
  assert.match(page, /不将基础设施可用推断为数据就绪或业务发布/);
  assert.match(page, /不传播为 Research Readiness/);
  assert.match(page, /健康接口只读，不能创建订单或变更发布锁/);
  assert.doesNotMatch(page, /system-health-ui-v1/);
});
