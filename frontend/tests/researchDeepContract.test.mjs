import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("深度分析页面使用服务端分页且只展示可得时间证据", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/research/ResearchDeepPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<DeepAnalysisListData>\("\/research\/deep-analysis", \{ page, page_size: pageSize/);
  assert.match(page, /useDeepAnalysis\(page, pageSize\)/);
  assert.match(page, /仅以 available_at 作为证据可得时点/);
  assert.match(page, /不生成分析结论/);
  assert.match(page, /tablePagination=/);
  assert.doesNotMatch(page, /research-deep-ui-v1/);
});
