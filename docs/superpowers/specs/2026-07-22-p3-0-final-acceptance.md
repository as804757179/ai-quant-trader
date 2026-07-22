# P3-0 通用基础设施最终验收记录

状态：最终验收通过。

最终结论：`P3-0 通用基础设施最终验收通过；P3-0 未引入新增回归；仓库保留 1 项已在开发前基线复现的既存 strategy runtime error。`

## 验收范围与边界

- 本记录仅覆盖 P3-0 通用 shadow run、shadow decision、evidence/input lineage、只读审计接口、迁移 `042` 和 test-only 执行链路。
- 不代表完整 P3、阶段 C 实时验收、样本冻结、生产策略批准、P3 input Profile 批准或交易准入。
- 未创建订单，未调用执行服务，未写入资金或持仓，未接入外部行情 Provider。

## 代码与迁移证据

| 项目 | 证据路径或提交 | 验收结果 |
| --- | --- | --- |
| 通用契约、存储、test-only 链路和只读接口 | `1237d56`、`c81d521`、`1323058`、`5a87e9f`、`f8af0c8` | 已完成 |
| 迁移 042 回滚 | `28c2544`；`backend/alembic/versions/042_p3_shadow_run_infrastructure.py` | `042 -> 041` 后移除 `shadow` schema；可再次升级 |
| PostgreSQL 只读筛选兼容性 | `fcacc09`；`backend/app/shadow/repository.py` | `status=None` 可在 PostgreSQL 上查询 |
| 迁移存储与只读接口契约 | `backend/tests/test_p3_shadow_storage_contracts.py`、`backend/tests/test_p3_shadow_read_api_contracts.py` | 定向通过 |

## 真实 TimescaleDB 迁移验收

隔离环境使用仓库 `docker-compose.yml` 的 `timescale/timescaledb:latest-pg15` 镜像；临时容器、数据库、端口和随机凭据均独立，未连接项目 compose 数据库或生产数据库。

| 项目 | 实际结果 |
| --- | --- |
| PostgreSQL / TimescaleDB | `15.18` / `2.28.2` |
| 扩展 | `CREATE EXTENSION IF NOT EXISTS timescaledb` 退出码 0 |
| 空库升级 | `alembic upgrade 041`、`alembic upgrade 042` 均退出码 0；版本依次为 `041`、`042` |
| 042 对象 | `shadow.runs`、`shadow.run_input_batches`、`shadow.decisions`、`shadow.decision_evidence`；62 个字段、26 个约束、14 个索引 |
| 合法写入与关联 | 最小 run、input batch、decision、evidence 写入成功；四表关联查询返回 1 条 |
| 非法写入 | 重复去重键、缺少必填 run 引用、无效外键、`tradable=true`、`order_count=1` 均被数据库拒绝 |
| 只读 API | 匿名读取关闭时 `GET /api/v1/shadow/runs` 返回 401；按既有非生产匿名读取策略开启时 4 个 shadow GET 路由均返回 200 |
| 回滚与重升 | `alembic downgrade 041` 退出码 0，`shadow` schema/table 数均为 0；再次 `alembic upgrade 042` 退出码 0，恢复 4 表、26 约束、14 索引 |
| 清理 | 临时容器及其匿名数据卷均已删除；临时端口已释放 |

## 安全与 test-only 证据

- 定向命令：`backend/.venv/Scripts/python.exe -m unittest tests.test_p3_shadow_contracts tests.test_p3_shadow_storage_contracts tests.test_p3_shadow_test_execution tests.test_p3_shadow_read_api_contracts tests.test_p3_shadow_acceptance`，26 项通过，退出码 0。
- Legacy L0：`scripts/verify_legacy_api_l0.ps1`，6 项通过，退出码 0。
- `TestOnlyShadowRunner` 结果：`data_mode=test`、`not_realtime=true`、`network_request_count=0`、`tradable=false`、`order_created=false`，订单、订单服务、执行服务、资金与持仓写入计数均为 0。
- 六锁执行前后均为 false：`CERTIFIED_BACKTEST_EXECUTION_ENABLED`、`CERTIFIED_SCREENER_OUTPUT_ENABLED`、`TRADING_EXECUTION_ENABLED`、`LIVE_TRADING_ENABLED`、`AI_ORDER_ENABLED`、`ALLOW_SCHEDULED_ORDER`。
- 准确结论：P3 test-only 模块及验收测试链路未调用外部 Provider；本记录不声称整个系统不存在网络访问。

## 完整回归与既存 error

最终命令：`backend/.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"`。

- 当前结果：326 项，passed 325、failed 0、error 1、退出码 1。
- 既存 error：`test_strategy_runtime_hash_is_stable_and_declares_data_profile`；摘要：`build_strategy_runtime_status() missing 1 required positional argument: 'items'`。
- 基线对照：P3-0 开发前提交 `f600ced` 的独立 worktree、同一 `.venv`、同一完整命令复现同名同摘要 error。
- 分类：`PRE_EXISTING_NOT_INTRODUCED_BY_P3_0`。不修复、不跳过、不隐藏该测试；不得描述为完整回归全部通过。
- 准确表述：`P3-0 未引入新增测试回归；仓库仍存在 1 项已由基线复现的既存 error。`

## 保持 blocked 的业务决策

- `realtime_data_approved=false`
- `P3_REALTIME_DATA_NOT_APPROVED`
- `P3_STRATEGY_VERSION_UNCONFIRMED`
- 未冻结正式样本、生产策略版本、P3 input Profile、运行时间、时效阈值、稳定周期或真实 Provider。

本验收记录完成后停止；后续 P3 业务开发必须取得单独用户授权。
