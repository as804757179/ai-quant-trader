# Sprint13 Tracking Report

## 结论

Sprint13 **未通过**，不得进入 Sprint14。认证导入、幂等重跑、批次/checkpoint、交易日历、第二 Provider、逐日缺失记录和用途级审核框架已真实运行，但 10 股企业行动仍为 unresolved，688981.SH 另有 6 个交易日缺失未能证明是停牌还是 Provider 缺失。没有强制 ready。

## 冻结清单与 Provider

冻结 10 股：600519.SH（食品饮料/上证主板）、601318.SH（非银金融/上证主板）、600276.SH（医药/上证主板）、000001.SZ（银行/深证主板）、000333.SZ（家电/深证主板）、002415.SZ（计算机设备/深证主板）、300308.SZ（通信/创业板）、300750.SZ（电力设备/创业板）、688981.SH（电子/科创板）、600036.SH（银行/上证主板）。未使用未来收益或策略表现选股。

主 Provider 为 Sohu `sohu_daily_kline`，第二 Provider 为腾讯 `tencent_fqkline_raw` 只读；无 fallback。Importer 为 `sprint07-sohu-certified-store-v1`，Normalizer 为 `sprint07-kline-contract-v1`，schema 为 `certified-kline-v1`。

## 数据结果

| 股票 | Certified | 覆盖率 | unresolved | OHLCV Profile |
|---|---:|---:|---:|---|
| 600519.SH | 242 | 100% | 0 | review_required |
| 601318.SH | 242 | 100% | 0 | review_required |
| 600276.SH | 242 | 100% | 0 | review_required |
| 000001.SZ | 242 | 100% | 0 | review_required |
| 000333.SZ | 242 | 100% | 0 | review_required |
| 002415.SZ | 242 | 100% | 0 | review_required |
| 300308.SZ | 242 | 100% | 0 | review_required |
| 300750.SZ | 242 | 100% | 0 | review_required |
| 688981.SH | 236 | 97.52% | 6 | review_required |
| 600036.SH | 242 | 100% | 0 | review_required |

合计 2,414 行；scoped-ready 0 行。120 个第二 Provider 月度样本 OHLC 全部 PASS；amount 未验证。重复、非交易日、unknown/synthetic 写入为 0。企业行动审核 10 个，全部 unresolved，官方证据归档 0。

120 个 checkpoint 均有终态：119 certified、1 review_required。数据集 Hash 两次重跑稳定为 `2006b4e8e361abaff49d93258375ee12aa26e0fc98273a07c7165e274ac34b6d`。legacy、Sprint13 前既有 Certified 在重跑前后 Hash 不变。

## Readiness 与安全

每股均建立完整区间的 OHLCV、Amount、Execution Reference 审核。OHLCV/Amount 为 review_required；Execution Reference 为 rejected；Gross 未传播；净税后 blocked。六个发布锁均为 false。未运行策略、未创建订单、未输出候选或收益指标。

## 文件

新增冻结清单、Alembic 013、可恢复导入器、扩展验收脚本、ADR-011 和三份数据报告。修改 `verify_local_env.ps1` 的 migration head、既有 readiness 验收的历史数据范围隔离，以及项目状态快照。未修改 legacy 或既有 Certified 数据。

## 验收与优先级

既有完整验收链 PASS；Backend 192 passed、Worker 19 passed，skip/xfail/xpass 均为 0。扩展验收按设计返回 FAIL，且仅剩以下真实阻塞：

- P0：10 股企业行动官方事件级证据、日期、比例和 Hash 尚未完成。
- P1：688981.SH 六个日期尚未归因为停牌或 Provider 缺失；覆盖率 97.52%。
- P1：当前 scoped-ready 股票 0、记录 0，未达到 Sprint14 的 6 股/1,400 行门槛。
- P2：amount 独立验证未闭环；既有异步 RuntimeWarning。

Sprint13 是否通过：否。Sprint14 是否准入：否。状态快照保持“受控认证数据扩展”，并记录上述阻塞。
