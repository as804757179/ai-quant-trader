import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("排除与阻断页面使用服务端分页且不混入风险事件", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/research/ResearchExcludedPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<ResearchExclusionListData>\("\/research\/exclusions", \{ page, page_size: pageSize/);
  assert.match(page, /useResearchExclusions\(page, pageSize\)/);
  assert.match(page, /风险事件不纳入本接口/);
  assert.match(page, /不提供人工强制放行/);
  assert.match(page, /tablePagination=/);
  assert.doesNotMatch(page, /research-excluded-ui-v1/);
});
