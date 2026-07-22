# P3-1D 数据源尽调报告

状态：`NO_COMPLIANT_REPLAY_DATA_SOURCE_FOUND`

日期：2026-07-22

## 结论

当前未找到同时满足 A 股历史日线、项目用途许可、自动化处理、本地存储、二次处理、历史 replay、逐行 PIT 血缘、公司行动证据及免费条件的合格来源。

正式 P3 replay 保持 `blocked/deferred`。在新的官方许可、正式授权数据服务或完整逐行 PIT/血缘证据出现前，不再重复开展同类数据源搜索。项目仅保留 synthetic/test-only 工程验证；该验证不得描述为真实历史 replay、模拟实盘或阶段 C 通过。

## 候选核验

| 候选 | 官方证据 | 结论 |
| --- | --- | --- |
| 上证所信息历史数据产品 | [历史数据产品说明书 2.0.0](https://www.sseinfo.com/services/assortment/market/hqywwd/wdcpsms/c/10782125/files/f2ba70dea74a4323bf13b76fffce0e40.pdf)（2025-06-12）覆盖 Level-1/2 日 K；[历史数据接口说明书 1.1.5](https://www.sseinfo.com/services/assortment/market/hqywwd/wdzsjk/c/10824356/files/4ddcd5a592f9429f9288b0d2cb0c9549.pdf)（2026-03-27）定义 CSV、OHLCV 和交易日字段。[联合授权声明](https://www.sseinfo.com/aboutus/authstatement/)要求接收或使用证券信息须分别申请许可。 | `review_required`：未取得适用于本项目的合同、收费、自动化、本地存储、二次处理、replay、逐行 `available_at` 或公司行动 PIT 权利；仅覆盖沪市。 |
| 深证信数据服务平台 | [深圳证券信息有限公司数据服务平台](https://webapi.cninfo.com.cn/)公开提供数据服务、API 文档与行情中心入口。 | `review_required`：未取得正式 API 合同、许可版本、日线覆盖、费用、自动化频率、本地存储、二次处理、replay 或 PIT 血缘权利。 |
| Tushare | 官方 [`daily` 文档](https://tushare.pro/document/1?doc_id=27)提供 A 股未复权日线，并说明交易日约 15:00–16:00 入库。 | `rejected`：[服务协议](https://tushare.pro/document/1?doc_id=405)仅授予个人、不可转让、非商业、可撤销且仅供个人查看的许可，不满足项目级数据复用、存储和 replay 准入。 |
| 巨潮资讯网 / CNINFO | [巨潮资讯网](https://www.cninfo.com.cn/new/fulltextSearch?keyWord=002892)为深交所法定信息披露平台，可作为公告发布时间证据的未来候选。 | `rejected`：不是完整 A 股历史日线来源，且自动化、本地存储、二次处理许可未证实；不能单独构成 replay 数据集。 |

## 保持 blocked

- `P3_PROVIDER_LICENSE_UNCONFIRMED`
- `P3_INPUT_LINEAGE_UNVERIFIED`
- `P3_INPUT_AVAILABLE_AT_MISSING`
- `P3_INPUT_HASH_MISSING`
- `P3_INPUT_CORPORATE_ACTION_UNVERIFIED`
- `P3_REALTIME_DATA_NOT_APPROVED`
- `realtime_data_approved=false`

Sprint13 不得用于正式 P3 replay。`P3_REPLAY_DUAL_MA_RAW_OHLCV_V1` 保持 `draft/disabled`，runner 不可用。六个发布和交易锁保持 `false`。

## 重新评估触发条件

仅在以下任一变化出现后，重新启动数据准入评估：

1. 新的官方许可或正式授权数据服务，明确覆盖项目的自动化、本地存储、二次处理和历史 replay 用途。
2. 可验证的完整逐行 `available_at`、`row_hash`、dataset/batch Hash、交易日历和公司行动 PIT 证据。

本报告不授权接入、调用、抓取或使用任何候选数据源。
