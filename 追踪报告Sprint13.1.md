# Sprint13.1 Tracking Report

生成日期：2026-07-12（Asia/Shanghai）  
任务范围：受控认证数据扩展的导入器与验收完整性修复；未开展策略、回测收益、选股或交易功能。

## 结论

- **Sprint13.1 验收：PASS。** `scripts/verify_certified_dataset_expansion.ps1` 返回 `PASS`。
- **Sprint13 数据集发布：BLOCKED。** 这是数据治理的真实业务结论，不是验收失败。
- **Sprint14 准入：false。** 不得进入扩大样本后的回测完整性复验。
- 六个发布与交易开关均为 `false`；未创建订单、候选或策略结果。
- 冻结范围未变：`000001.SZ`、`000333.SZ`、`002415.SZ`、`300308.SZ`、`300750.SZ`、`600036.SH`、`600276.SH`、`600519.SH`、`601318.SH`、`688981.SH`，`2025-07-01` 至 `2026-06-30`、`1d/raw`。

## 修改与新增文件

| 类型 | 文件 | 作用 |
| --- | --- | --- |
| 修改 | `.gitignore` | 为本 Sprint 新增的两个 `backend/app/data` Python 源文件添加精确例外，避免根目录 `data/` 规则吞掉交付源码。未放开其他历史未跟踪文件。 |
| 修改 | `backend/scripts/import_sprint13_dataset.py` | 固定运行绑定、按股票×月份检查点、内容级既有数据校验、受控重试、主/第二 Provider 隔离、证券状态与 Readiness 写入。 |
| 修改 | `scripts/verify_certified_dataset_expansion.ps1` | 动态调用检查器、验证前后不可变快照与 Hash、串联既有验收、全量测试及结构化摘要。 |
| 新增 | `backend/app/data/dataset_expansion.py` | 可测试的内容校验、运行绑定、重试、Provider 汇总、数据集 Hash、fail-closed 证券状态和发布判定纯逻辑。 |
| 新增 | `backend/app/data/sohu_daily_importer.py` | Sprint13 受控的 Sohu 日线导入适配与重试边界。 |
| 新增 | `backend/scripts/verify_sprint13_dataset.py` | 只读动态检查器，输出 `S13_INSPECTION`。 |
| 新增 | `backend/tests/test_dataset_expansion.py` | 42 项 Sprint13.1 聚焦回归测试。 |
| 新增 | `追踪报告Sprint13.1.md` | 本报告。 |

未新增 Alembic migration；复用已存在的 `014_dataset_expansion_integrity` 结构。未新增或修改 ADR，未修改项目 Skill 或状态快照；状态仍是“受控认证数据扩展 / BLOCKED / 不进入 Sprint14”。未修改 Certified/legacy 原始 K 线、企业行动处理器、发布锁、前端或策略。

## 导入完整性修复

1. **既有 Certified 数据不再按行数跳过。**
   - 使用稳定业务键：`stock_code + period + trading_date + adjustment`。
   - 比较标准化 OHLCV、`amount`、`provider/source`、单位、版本、`raw_hash` 或可验证的 batch 原始响应血缘。
   - 行数相同但日期不同、OHLCV 不同、amount 不同或 provenance 不同都会 fail closed。
   - 既有数据只读验证，不覆盖、不删除、不重新认证。
   - 兼容 Sprint06/Sprint07 的历史 hash 算法差异时，必须同时证明旧 batch 的 `raw_hash` 与当前真实 Provider 原始响应 hash 相同；不能仅凭数量放行。

2. **同一 `run_id` 不可变绑定。**
   - 在网络请求或数据库写入前校验 manifest hash、股票清单、主/第二 Provider、日期范围、period、adjustment、importer/normalizer/schema 版本。
   - 任一字段变化立即拒绝；聚焦测试覆盖 manifest、日期、Provider 与 period 冲突。

3. **可恢复执行。**
   - 检查点粒度为股票×月份，记录状态、尝试次数、错误类型/原因、最后尝试时间、batch 与内容校验 hash。
   - 外层请求最大三次受控重试并指数退避；checkpoint 中的 `max_attempt_count=10` 是多次幂等重跑的累计次数，不是单次请求越界重试。
   - 错误按 fetch、validation、write 分类；第二 Provider 腾讯只读失败不会触发写入或替代 Sohu 主 Provider。

4. **证券状态 fail closed。**
   - 普通证券身份不能推导全年 `normal_trade` 证券状态；十只股票均保留 `unresolved` 状态证据。
   - `normal_trade` 仅用于已观测到 Certified bar 的日期缺失归因，不等同证券全年状态授权。

## 动态验收与数据集结果

| 项目 | 实际结果 |
| --- | --- |
| 当前 run 与冻结 manifest | 匹配，manifest hash `d4936757c7c1a669e82ad13f0a5e8593e8f844549478c6f8181f29301ccc9b25` |
| Certified 范围内记录 | 2,414 条 |
| checkpoint | `certified=119`，`review_required=1`，`validation_failed=0` |
| 内容校验 hash | 120 个检查点均存在 |
| 第二 Provider 校验 | 10/10 股票均为 `12 expected / 12 actual / 12 PASS / 0 REVIEW / 0 FAIL` |
| 第二 Provider 写入 Certified Store | 0 条 |
| 数据集 hash | `531874cbb380921a519be0873b5fc734123f63512c6cec92d695084f98c728b2` |
| Hash 确定性 | 导入前后相同；测试覆盖输入顺序变化、范围外记录排除、范围内内容/血缘变化导致 Hash 变化 |
| 旧数据快照 | legacy、既有 Certified、corporate actions 三类快照均未变化 |
| 订单 / 候选 | `0 / 0` |

验收器不再把 `ready=0`、企业行动计数或 Provider 结果写死。它动态读取 30 条用途级 Readiness 审核与 10 条企业行动发现审核，并明确分离：

```text
verifier_status=PASS
dataset_release_status=BLOCKED
sprint13_status=BLOCKED
sprint14_admission=false
```

## Readiness 与真实阻塞

- 10 只股票均有三类完整授权键审核（共 30 条）：
  - `return_backtest + OHLCV_RETURN_V1`：`review_required`
  - `return_backtest + AMOUNT_FACTOR_V1`：`review_required`
  - `execution_reference + EXECUTION_REFERENCE_V1`：`rejected`
- scoped-ready 股票数 / 行数均为 `0`。
- 十只股票的企业行动发现尚为 `unresolved`。
- `688981.SH` 有 6 个交易日缺失仍为 `unresolved`；其他股票日期缺失已按交易日历归因。
- 因此没有把未完成的企业行动、缺失日期、amount 或 Execution Reference 权限传播为 ready。

## 安全与发布状态

以下开关全部保持 `false`：

- `CERTIFIED_BACKTEST_EXECUTION_ENABLED`
- `CERTIFIED_SCREENER_OUTPUT_ENABLED`
- `TRADING_EXECUTION_ENABLED`
- `LIVE_TRADING_ENABLED`
- `AI_ORDER_ENABLED`
- `ALLOW_SCHEDULED_ORDER`

未运行策略，未输出收益、Sharpe、回撤、候选股或投资结论；AI、Celery、Paper 自动交易与 Live 均未获得订单创建权限。

## 验证证据

| 验证 | 结果 |
| --- | --- |
| `pytest backend/tests/test_dataset_expansion.py backend/tests/test_certified_ingestion_pilot.py -q` | 51 passed（其中 Sprint13.1 聚焦测试 42 项） |
| `scripts/verify_certified_dataset_expansion.ps1` | PASS |
| 既有十个验收脚本 | 全部 PASS |
| `pytest backend/tests -q` | 234 passed，1 个既有 RuntimeWarning |
| `pytest worker/tests -q` | 19 passed，1 个既有 RuntimeWarning |
| skipped / xfailed / xpassed | `0 / 0 / 0` |
| Engine / Reference 与市场微观场景 | 由既有验收链通过；未在本 Sprint 改动其业务语义 |

既有验收脚本：Data Certification、Execution Safety、Certified Ingestion Pilot、Certified Kline Store、Research Readiness、Field-Level Readiness、Backtest Integrity、Market Rules、Market Microstructure Boundaries、Corporate Action PIT 均在本次最终链中返回 PASS。

## 剩余问题

- **P0：无。**
- **P1：** 十只股票的企业行动发现与证据归档尚未完成；`688981.SH` 的 6 个目标交易日缺失尚未归因。这两项均正确阻止 Readiness 与 Sprint14 准入。
- **P2：** 后端与 Worker 全量测试各保留 1 个既有 RuntimeWarning；本 Sprint 未隐藏 warning、未 skip 测试，也未扩大为无关修复。

## 准入结论

- **Sprint13.1：可签收。** 其目标是修复导入/验收完整性，已通过。
- **Sprint13：仍处于 BLOCKED。** 不能将“验收器 PASS”误报为“数据样本可用于研究”。
- **可进入 Sprint13.2：可以。** 仅用于逐标的企业行动发现、官方证据归档与 `688981.SH` 缺失归因的受控闭环。
- **可进入 Sprint14：不可以。** 尚不满足至少 6 只 scoped-ready、至少 1,400 scoped-ready 行且无影响回测完整性的 P0/P1 的附加门槛。
