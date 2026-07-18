import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("市场情绪页面在无合格证据时明确展示不可用且不生成分数", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/market/MarketSentimentPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<MarketSentimentData>\("\/market\/sentiment", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useMarketSentiment\(\)/);
  assert.match(page, /正式情绪数据源尚未接入/);
  assert.match(page, /不生成虚假分数/);
  assert.match(page, /只能是 derived，不是 observed/);
  assert.match(page, /不把 AI\/LLM 输出标记为 observed/);
  assert.doesNotMatch(page, /market-sentiment-ui-v1/);
});
