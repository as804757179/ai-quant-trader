import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("行业与板块页面只展示非 PIT 的当前快照", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/market/MarketSectorPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<MarketClassificationListData>\("\/market\/industry-classifications", \{ page, page_size: pageSize \}\)/);
  assert.match(models, /get<UnavailableMarketObservationData>\("\/market\/concept-boards", \{ page, page_size: pageSize \}\)/);
  assert.match(page, /useIndustryClassifications\(page, pageSize\)/);
  assert.match(page, /当前快照、非历史还原数据/);
  assert.match(page, /正式数据源尚未接入，不使用行业字段替代/);
  assert.match(page, /不进入回测、Walk Forward、训练或历史因子/);
  assert.match(page, /tablePagination=/);
  assert.doesNotMatch(page, /market-sector-ui-v1/);
});
