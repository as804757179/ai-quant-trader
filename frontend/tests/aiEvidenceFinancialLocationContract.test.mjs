import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("财报页级候选与复核复用既有接口和血缘字段", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/ai/AiEvidencePage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /get<FinancialLocationCandidateListData>\(`\/research\/evidence\/\$\{encodeURIComponent\(evidenceId\)\}\/financial-location-candidates`/);
  assert.match(models, /raw_hash\?: string; locator_version\?: string/);
  assert.match(page, /useFinancialLocationCandidates\(selectedEvidenceId, candidatePage, candidatePageSize, refreshVersion\)/);
  assert.match(page, /页文本 Hash/);
  assert.match(page, /parse run/);
});

test("财报页级复核提交复用幂等键并在成功后刷新候选和历史", async () => {
  const [models, page] = await Promise.all([
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/ai/AiEvidencePage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(models, /"Idempotency-Key": idempotencyKey/);
  assert.match(page, /sameRequest/);
  assert.match(page, /submission\.idempotencyKey/);
  assert.match(page, /setRefreshVersion\(\(value\) => value \+ 1\)/);
  assert.match(page, /location_id: submission\.location_id/);
  assert.match(page, /appendFinancialLocationReview\([\s\S]*?submission\.idempotencyKey/);
});

test("财报页级复核对空态、失效候选、权限和冲突失败保持如实状态", async () => {
  const page = await readFile(new URL("../src/pages/ai/AiEvidencePage.tsx", import.meta.url), "utf8");

  assert.match(page, /!selectedEvidenceId \|\| !selectedCandidate\?\.location_id/);
  assert.match(page, /row\.extraction_status !== "text_observed"/);
  assert.match(page, /error instanceof Error \? error\.message/);
  assert.match(page, /setSubmitMessage\(error instanceof Error \? error\.message/);
  assert.doesNotMatch(page, /research_readiness:\s*["']ready/);
});
