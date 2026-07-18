import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("成交量页面读取已观察流动性快照且不授权未验证 amount", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/market/MarketVolumePage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<ObservedLiquidityListData>\("\/stock\/liquidity", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useObservedLiquidity\(page, pageSize\)/);
  assert.match(page, /amount 未通过独立字段验证/);
  assert.match(page, /不构造流动性结论/);
  assert.match(page, /tablePagination=/);
  assert.doesNotMatch(page, /pendingState\(/);
});
