import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

test("AI 摘要复用审计与信号接口且不推断证据或交易资格", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/ai/AiSummaryPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<AiSignalListData>\("\/ai\/signals", \{ page: 1, page_size: 50 \}\)/);
  assert.match(models, /get<AiAuditSummaryData>\("\/ai\/audit-summary", \{ days: 30 \}\)/);
  assert.match(page, /useAiSignals\(\)/);
  assert.match(page, /useAiAuditSummary\(\)/);
  assert.match(page, /证据关联未记录/);
  assert.match(page, /不推断信号与任何新闻、公告或财报证据存在关联/);
  assert.match(page, /recommendation_only 不等于 Research Readiness、回测资格或策略结论/);
  assert.match(page, /AI 输出不能绕过 Risk Engine、人工授权或 Execution Gate/);
  assert.doesNotMatch(page, /pendingState\(/);
});
