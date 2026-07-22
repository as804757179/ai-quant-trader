from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


DataMode = Literal["test", "replay", "realtime"]

RELEASE_LOCK_KEYS = (
    "CERTIFIED_BACKTEST_EXECUTION_ENABLED",
    "CERTIFIED_SCREENER_OUTPUT_ENABLED",
    "TRADING_EXECUTION_ENABLED",
    "LIVE_TRADING_ENABLED",
    "AI_ORDER_ENABLED",
    "ALLOW_SCHEDULED_ORDER",
)


class ShadowContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ImmutableReference:
    reference_id: str
    content_hash: str
    test_only: bool = False

    def validate(self, *, label: str, data_mode: DataMode) -> None:
        if not self.reference_id or not self.content_hash:
            raise ShadowContractError(
                f"P3_{label.upper()}_UNCONFIRMED", f"{label} 引用不完整"
            )
        if data_mode == "test":
            if not self.test_only or not self.reference_id.startswith("test:"):
                raise ShadowContractError(
                    "P3_TEST_ONLY_REFERENCE_REQUIRED",
                    f"test 模式的 {label} 必须使用 test-only 引用",
                )
        elif self.test_only or self.reference_id.startswith("test:"):
            raise ShadowContractError(
                "P3_TEST_REFERENCE_OUTSIDE_TEST_MODE",
                f"{label} 的 test-only 引用不能用于非 test 模式",
            )


@dataclass(frozen=True)
class ProviderReference:
    provider: str
    source: str
    dataset_version: str
    license_evidence_ref: str
    data_mode: DataMode
    not_realtime: bool
    realtime_data_approved: bool = False

    def validate(self) -> None:
        if self.data_mode not in {"test", "replay", "realtime"}:
            raise ShadowContractError("P3_DATA_MODE_INVALID", "data_mode 无效")
        if not all(
            (self.provider, self.source, self.dataset_version, self.license_evidence_ref)
        ):
            raise ShadowContractError(
                "P3_PROVIDER_LICENSE_UNCONFIRMED", "Provider 或许可证据不完整"
            )
        if self.data_mode == "test":
            if not self.not_realtime:
                raise ShadowContractError(
                    "P3_TEST_NOT_REALTIME_REQUIRED", "test 数据必须标记 not_realtime=true"
                )
            if not (
                self.provider.startswith("test:")
                and self.source.startswith("test:")
                and self.license_evidence_ref == "test-only"
            ):
                raise ShadowContractError(
                    "P3_TEST_ONLY_PROVIDER_REQUIRED",
                    "test 数据必须使用 test-only Provider 和许可证据",
                )
        elif self.data_mode == "replay":
            if not self.not_realtime:
                raise ShadowContractError(
                    "P3_REPLAY_NOT_REALTIME", "replay 数据不得标记为实时"
                )
        elif not self.realtime_data_approved:
            raise ShadowContractError(
                "P3_REALTIME_DATA_NOT_APPROVED", "实时数据尚未批准"
            )


@dataclass(frozen=True)
class InputBatchReference:
    batch_id: str
    raw_hash: str
    data_as_of: datetime
    fetched_at: datetime
    received_at: datetime

    def validate(self, *, information_cutoff: datetime) -> None:
        if not self.batch_id or not self.raw_hash:
            raise ShadowContractError(
                "P3_INPUT_LINEAGE_INCOMPLETE", "输入批次引用不完整"
            )
        if self.fetched_at > self.received_at:
            raise ShadowContractError("P3_INPUT_TIME_REGRESSION", "抓取时间晚于接收时间")
        if self.data_as_of > information_cutoff:
            raise ShadowContractError(
                "P3_FUTURE_DATA_LEAK", "输入数据晚于信息截止时间"
            )


@dataclass(frozen=True)
class ShadowRunRequest:
    data_mode: DataMode
    provider: ProviderReference
    sample: ImmutableReference
    strategy: ImmutableReference
    input_profile: ImmutableReference
    input_batch: InputBatchReference
    information_cutoff: datetime

    def validate(self) -> None:
        self.provider.validate()
        self.sample.validate(label="sample", data_mode=self.data_mode)
        self.strategy.validate(label="strategy_version", data_mode=self.data_mode)
        self.input_profile.validate(label="input_profile", data_mode=self.data_mode)
        self.input_batch.validate(information_cutoff=self.information_cutoff)


@dataclass(frozen=True)
class RunSafetyAssertion:
    run_id: str
    tradable: bool
    order_created: bool
    order_count: int
    order_service_calls: int
    execution_service_calls: int
    capital_write_count: int
    position_write_count: int
    release_locks_before: dict[str, bool]
    release_locks_after: dict[str, bool]

    def validate(self) -> None:
        if not self.run_id:
            raise ShadowContractError("P3_RUN_ID_REQUIRED", "run_id 不能为空")
        if self.tradable or self.order_created:
            raise ShadowContractError(
                "P3_ZERO_ORDER_ASSERTION_FAILED", "影子运行不得可交易或创建订单"
            )
        counts = (
            self.order_count,
            self.order_service_calls,
            self.execution_service_calls,
            self.capital_write_count,
            self.position_write_count,
        )
        if any(value != 0 for value in counts):
            raise ShadowContractError(
                "P3_ZERO_ORDER_ASSERTION_FAILED", "当前 run 检测到禁止的副作用"
            )
        for key in RELEASE_LOCK_KEYS:
            if self.release_locks_before.get(key) is not False or self.release_locks_after.get(key) is not False:
                raise ShadowContractError(
                    "P3_RELEASE_LOCK_CHANGED", "发布或交易锁必须在运行前后保持 false"
                )
