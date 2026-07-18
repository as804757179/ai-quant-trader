import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("持仓再评估页面关联持仓与审核且不伪造风险或动作", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/research/ResearchHoldingsPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<ResearchHoldingReviewListData>\("\/research\/holdings-review", \{ page, page_size: pageSize, mode \}/);
  assert.match(page, /useResearchHoldingsReview\(page, pageSize\)/);
  assert.match(page, /风险事件无证券关联时保持未记录/);
  assert.match(page, /不生成持仓处置或订单/);
  assert.match(page, /tablePagination=/);
  assert.doesNotMatch(page, /research-holdings-ui-v1/);
});
