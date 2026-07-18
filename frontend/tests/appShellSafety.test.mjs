import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("execution status does not default to simulation when unavailable", async () => {
  const source = await readFile(new URL("../src/layout/AppShell.tsx", import.meta.url), "utf8");
  assert.match(source, /const executionKnown = execution\.kind === "live"/);
  assert.doesNotMatch(source, /\?\? "SIMULATION"/);
  assert.match(source, /"模式未知"/);
});

test("交易控制台不会将未知状态误报为关闭或通过", async () => {
  const source = await readFile(new URL("../src/pages/core/TradeControlPage.tsx", import.meta.url), "utf8");

  assert.match(source, /const modeKnown = mode\.kind === "live" && Boolean\(mode\.data\);/);
  assert.match(source, /const brokerKnown = broker\.kind === "live" && Boolean\(broker\.data\);/);
  assert.match(source, /const executionKnown = execution\.kind === "live" && Boolean\(execution\.data\);/);
  assert.match(source, /return \{ label: "状态未知", tone: "review" as const \};/);
  assert.match(source, /dataCutoff: "不适用（执行安全状态）"/);
  assert.doesNotMatch(source, /all_release_locks_closed \? "全部关闭" : "存在开启项"/);
  assert.doesNotMatch(source, /order_audit\?\.unknown_caller \? "reject" : "pass"/);
});

test("总览和研究候选页将风险与候选未知状态保持为未知", async () => {
  const [overview, candidates] = await Promise.all([
    readFile(new URL("../src/pages/core/OverviewPage.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/pages/research/ResearchCandidatesPage.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(overview, /const dashboardKnown = dashboard\.kind === "live" && Boolean\(dashboard\.data\);/);
  assert.match(overview, /const candidateKnown = \(candidates\.kind === "live" \|\| candidates\.kind === "empty"\) && Boolean\(candidates\.data\);/);
  assert.match(overview, /"熔断状态未知"/);
  assert.doesNotMatch(overview, /counts\?\.ready \?\? 0/);
  assert.match(candidates, /const candidateKnown = \(state\.kind === "live" \|\| state\.kind === "empty"\) && Boolean\(state\.data\);/);
  assert.match(candidates, /dataCutoff: "不适用（研究候选控制状态）"/);
  assert.doesNotMatch(candidates, /counts\?\.review_required \?\? 0/);
  assert.doesNotMatch(candidates, /state\.data\?\.order_created \? "异常" : "关闭"/);
});

test("AI 信号行动字段以非订单标签展示", async () => {
  const [source, models] = await Promise.all([
    readFile(new URL("../src/pages/core/AiAuditPage.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/presentation/coreModels.ts", import.meta.url), "utf8"),
  ]);

  assert.match(source, /AI 输出标签（非订单）/);
  assert.match(source, /AI 标签：\$\{value\}（非订单）/);
  assert.doesNotMatch(source, /title: "输出类型"/);
  assert.match(models, /record_type\?: string;/);
  assert.match(models, /recommendation_only\?: boolean;/);
  assert.match(models, /tradable\?: boolean;/);
  assert.match(models, /research_eligible\?: boolean;/);
});
