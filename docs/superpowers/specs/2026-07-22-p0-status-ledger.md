# P0 状态账本

更新日期：2026-07-22

## 任务状态

| 任务 | 状态 | 依据 |
| --- | --- | --- |
| P0-1 财报页级候选人工复核 | `final_accepted` | `3b7b6b3`、前后端契约测试、真实鉴权 HTTP 与浏览器验收 |
| P0-2 Certified Store 只读查询 | `final_accepted` | 认证 K 线血缘定向测试、HTTP 与页面验收 |
| P0-3 认证批次与质量结果 | `final_accepted` | 批次/质量定向测试、HTTP 与页面验收 |
| P0-4 数据阻塞归因 | `final_accepted` | 阻塞归因定向测试、HTTP 与页面验收 |
| P0-5 Provider 交叉验证 | `final_accepted` | Provider 验证定向测试、HTTP 与页面验收 |
| P0-6 日历、证券状态与规则 | `final_accepted` | 日历/规则/证券状态定向测试、HTTP 与页面验收 |

## 不变量

- `CERTIFIED_BACKTEST_EXECUTION_ENABLED=false`
- `CERTIFIED_SCREENER_OUTPUT_ENABLED=false`
- `TRADING_EXECUTION_ENABLED=false`
- `LIVE_TRADING_ENABLED=false`
- `AI_ORDER_ENABLED=false`
- `ALLOW_SCHEDULED_ORDER=false`
- P0 不授予 Research Readiness，不解除 P3、P4 或 P5 的数据和运行准入阻塞。

## 下一准入

P1 全量集成验收与归档为唯一下一实施任务。验收范围仅限已存在的 P1 接口、页面、权限和运行时证据；不新增交易能力。
