# Project Skill v1 Tracking Report

生成日期：2026-07-12

## 1. 原有规范与创建位置

定向检查未发现仓库根级 `.codex`、`AGENTS.md`、`CLAUDE.md`、项目 Agent/Skill 索引。仓库中的 `a-stock-data/SKILL.md` 与 `AI-Trader/skills/*` 属于子组件或第三方能力，不是本项目治理规范，且其 Frontmatter 不完全遵循当前 Codex 仅使用 `name`、`description` 的标准。

采用当前 Codex 标准项目路径：`.codex/skills/ai-quant-trader-governance/`。没有创建用户全局或系统全局 Skill，也没有修改项目索引。

创建文件：

- `.codex/skills/ai-quant-trader-governance/SKILL.md`
- `.codex/skills/ai-quant-trader-governance/references/current-project-state.md`
- `.codex/skills/ai-quant-trader-governance/agents/openai.yaml`
- `Project Skill v1 Tracking Report.md`

`agents/openai.yaml` 是 `skill-creator` 当前推荐的 UI 元数据，包含显示名、简述和默认调用提示，不增加项目治理规则。

## 2. 尺寸与静态验证

| 文件 | 字符数 | 中文字符 | 行数 | 估算 Token |
|---|---:|---:|---:|---:|
| SKILL.md | 2,733 | 1,044 | 67 | 约 1,500–1,900 |
| current-project-state.md | 1,397 | 303 | 36 | 约 600–850 |

SKILL.md 的中文字符低于建议的 2,200；状态快照低于约 1,500 字符。估算 Token 仅用于评估，不作为精确计费值。

使用官方 `quick_validate.py` 验证：`Skill is valid!`。Frontmatter 名称、描述、目录命名与 YAML 均通过。

## 3. 长期规则与刻意排除内容

Skill 仅保存：A 股长期推进路径；稳定数据、回测和交易安全边界；开发验收纪律；定向读取；冲突优先级；Skill 更新条件。默认发布锁被表述为“当前安全默认值”，明确不是永久开发禁令。

刻意排除：具体股票、日期区间、数据条数、测试数量、Result Hash、Provider 临时故障、临时 P1/P2、函数细节、行号、未 Accepted 架构、完整命令输出、固定 Provider/策略、Sprint 永久顺序。当前阶段和阻塞只放低优先级状态快照。

## 4. 优先级与冲突处理

优先级明确为：当前需求及补充 → 当前任务设计/验收 → 最新 Accepted ADR → 当前代码/迁移/测试 → Skill → README/旧报告/旧注释。

当前需求与 Skill 冲突时，Codex 应简短指出冲突，按当前明确需求执行，不得机械拒绝或擅改需求。若改变长期原则，任务结束时建议更新 ADR 或 Skill。涉及关键安全能力绕过时，必须先说明风险和影响，再依据用户最终明确决定执行。状态快照不能覆盖新事实。

## 5. 定向读取与扩大范围

默认顺序：当前需求 → SKILL.md → 目标文件 → 对应测试 → 最新直接相关 Accepted ADR；只有确有状态需要时才读 current-project-state.md。

优先精确路径、`rg`、调用方搜索、错误栈、对应测试和 `git diff`。按数据、回测、交易、AI 四类模块定向读取，不默认扫描全仓、全部迁移、全部 ADR、全部 Tracking Report 或生成完整项目摘要。

仅在用户要求全项目审计、跨模块架构改造、明显冲突、调用链无法确认、测试显示影响扩散、迁移跨模块或安全边界受影响时扩大范围；扩大前说明原因，仍按模块与精确搜索执行。ADR 只在当前任务直接相关或发现设计冲突时读取，不要求每次加载全部 ADR。

## 6. 未来能力与更新条件

Skill 不会永久阻止回测、选股、Paper 或 Live。用户未来明确授权时，可按当前需求实施，但开启前应完成对应准入、测试、Accepted ADR 和回滚方案。

Skill 仅在长期架构/安全边界、核心访问路径、稳定阶段、Accepted 开发纪律变化或用户明确要求时更新。状态快照仅在重大阶段、下一阶段、主要阻塞或发布权限变化，或用户明确要求时更新。普通 Bug、数量变化、临时故障和小任务均不触发更新。

## 7. 八个模拟场景

| 场景 | 结果 | 原因 | 过度读取风险 | 限制未来开发风险 |
|---|---|---|---|---|
| 1 局部 Bug | PASS | 只要求目标文件、对应测试和必要调用方 | 低 | 无 |
| 2 当前需求与 Skill 冲突 | PASS | 明确当前需求优先、指出冲突后执行 | 低 | 无；建议更新长期文档 |
| 3 数据任务 | PASS | 聚焦数据、Certification、Readiness 与相关 ADR | 低；不自动加载交易/AI | 无 |
| 4 回测任务 | PASS | 聚焦 Backtest、Repository、Market Rules 与测试 | 低；不加载实盘/新闻 | 无 |
| 5 未来开放能力 | PASS | 默认关闭被定义为安全状态而非永久禁令 | 低 | 无；按准入/测试/ADR/回滚开放 |
| 6 状态快照过时 | PASS | 当前需求、最新 ADR、代码和测试优先 | 低 | 无 |
| 7 无关小任务 | PASS | 只应用相关通用纪律，不强制量化模块 | 低 | 无 |
| 8 全项目审计 | PASS | 允许扩大范围，但先分组和定向搜索 | 中且合理可控 | 无 |

未发现机械拒绝新需求、固化旧 Sprint、每次全仓扫描、永久阻止发布或快照覆盖高优先级事实的问题，因此无需第二轮修改。

## 8. Token 节省评估

1. 项目目标与稳定规则只需加载一次 Skill：PASS。
2. 不要求重读历史 Sprint：PASS。
3. 不要求加载全部 ADR：PASS。
4. 能按数据、回测、交易、AI 模块导航：PASS。
5. SKILL.md 长度适中：PASS。
6. 易过时内容已隔离到快照或排除：PASS。
7. 未复制 README/ADR 全文：PASS。
8. 不强制加载无关规则和模块：PASS。
9. 不阻止合理新需求和架构演进：PASS。
10. 当前明确需求优先：PASS。

## 9. 边界确认与建议

- 修改业务代码：否。
- 修改数据库或迁移：否；未执行 Alembic。
- 修改业务测试：否；未运行业务测试。
- 改变发布锁或环境变量文件：否。
- 继续执行 Sprint12：否。
- 修改历史 Accepted ADR 或 Tracking Report：否。

剩余建议：人工审核 Skill 的规则密度和触发描述。审核通过后，可在下一项真实任务中观察是否能按目标触发并减少读取；除非发现长期规则变化或明显导航缺陷，不要因普通任务频繁更新 Skill。

结论：Project Skill v1 满足 Definition of Done，等待人工确认。
