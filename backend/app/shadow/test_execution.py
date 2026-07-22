from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from app.core.config import settings
from app.shadow.contracts import (
    RELEASE_LOCK_KEYS,
    ImmutableReference,
    InputBatchReference,
    ProviderReference,
    RunSafetyAssertion,
    ShadowContractError,
    ShadowRunRequest,
)
from app.shadow.test_fixtures import (
    TEST_FIXTURE_GENERATOR_VERSION,
    TEST_ONLY_FIXTURE_KIND,
    TEST_ONLY_LICENSE_EVIDENCE,
    TEST_ONLY_MANIFEST_ID,
    TEST_ONLY_PROVIDER,
    TEST_ONLY_SOURCE,
    TEST_ONLY_STOCK_CODE,
    TEST_ONLY_STRATEGY_PARAMETERS,
    TestOnlyFixtureProvider,
    test_only_reference_hash,
)


@dataclass(frozen=True)
class TestOnlyShadowDecision:
    stock_code: str
    would_action: str
    information_cutoff: datetime
    decision_dedup_key: str
    evidence_hash: str
    tradable: bool = False
    order_created: bool = False


@dataclass(frozen=True)
class TestOnlyShadowRunResult:
    generator_version: str
    fixture_kind: str
    data_mode: str
    not_realtime: bool
    input_manifest_hash: str
    dataset_hash: str
    row_hashes: tuple[str, ...]
    strategy_reference_id: str
    strategy_hash: str
    parameter_snapshot: tuple[tuple[str, object], ...]
    parameter_hash: str
    input_snapshot_hash: str
    result_hash: str
    decision: TestOnlyShadowDecision
    safety: RunSafetyAssertion
    network_request_count: int


class TestOnlyShadowRunner:
    """Run deterministic P3-0 contract tests without external providers or trading services."""

    def __init__(self, provider: TestOnlyFixtureProvider | None = None) -> None:
        self.provider = provider or TestOnlyFixtureProvider()

    @staticmethod
    def build_request(*, information_cutoff: datetime) -> ShadowRunRequest:
        return ShadowRunRequest(
            data_mode="test",
            provider=ProviderReference(
                provider=TEST_ONLY_PROVIDER,
                source=TEST_ONLY_SOURCE,
                dataset_version=TEST_FIXTURE_GENERATOR_VERSION,
                license_evidence_ref=TEST_ONLY_LICENSE_EVIDENCE,
                data_mode="test",
                not_realtime=True,
            ),
            sample=ImmutableReference(
                "test:p3-shadow-sample-v1",
                test_only_reference_hash("sample"),
                test_only=True,
            ),
            strategy=ImmutableReference(
                "test:p3-shadow-strategy-v1",
                test_only_reference_hash("strategy"),
                test_only=True,
            ),
            input_profile=ImmutableReference(
                "test:p3-shadow-profile-v1",
                test_only_reference_hash("profile"),
                test_only=True,
            ),
            input_batch=InputBatchReference(
                "test:p3-shadow-batch-v1",
                test_only_reference_hash("batch"),
                information_cutoff,
                information_cutoff,
                information_cutoff,
            ),
            information_cutoff=information_cutoff,
        )

    def execute(
        self,
        *,
        run_id: str,
        request: ShadowRunRequest,
        max_age_seconds: int = 60,
    ) -> TestOnlyShadowRunResult:
        if request.data_mode != "test":
            raise ShadowContractError(
                "P3_TEST_EXECUTION_ONLY", "通用测试执行链路只允许 data_mode=test"
            )
        if not isinstance(self.provider, TestOnlyFixtureProvider):
            raise ShadowContractError(
                "P3_TEST_ONLY_FIXTURE_REQUIRED", "runner 只接受内置 synthetic/test-only provider"
            )
        request.validate()
        locks_before = self._release_locks()
        RunSafetyAssertion(
            run_id=run_id,
            tradable=False,
            order_created=False,
            order_count=0,
            order_service_calls=0,
            execution_service_calls=0,
            capital_write_count=0,
            position_write_count=0,
            release_locks_before=locks_before,
            release_locks_after=dict(locks_before),
        ).validate()
        batch = self.provider.load(information_cutoff=request.information_cutoff)
        if self.provider.network_request_count != 0:
            raise ShadowContractError(
                "P3_EXTERNAL_PROVIDER_FORBIDDEN", "synthetic/test-only runner 不得访问外部 Provider"
            )
        if (
            batch.fixture_kind != TEST_ONLY_FIXTURE_KIND
            or batch.manifest_id != TEST_ONLY_MANIFEST_ID
        ):
            raise ShadowContractError(
                "P3_TEST_ONLY_FIXTURE_REQUIRED", "runner 只接受 synthetic/test-only fixture"
            )
        if batch.manifest_hash != TestOnlyFixtureProvider._manifest_hash():
            raise ShadowContractError("P3_INPUT_HASH_MISMATCH", "test fixture manifest Hash 不一致")
        if not batch.bars:
            raise ShadowContractError("P3_DATA_UNAVAILABLE", "test fixture 输入缺失")
        if not self.provider.verify(batch):
            raise ShadowContractError("P3_INPUT_HASH_MISMATCH", "test fixture Hash 不一致")
        seen_trading_at: set[datetime] = set()
        previous_trading_at: datetime | None = None
        previous_available_at: datetime | None = None
        for bar in batch.bars:
            if bar.available_at is None or bar.available_at.tzinfo is None:
                raise ShadowContractError(
                    "P3_INPUT_AVAILABLE_AT_MISSING", "test fixture 缺少可审计 available_at"
                )
            if not bar.lineage_ref:
                raise ShadowContractError(
                    "P3_INPUT_LINEAGE_UNVERIFIED", "test fixture 缺少 lineage 引用"
                )
            if bar.trading_at.tzinfo is None:
                raise ShadowContractError(
                    "P3_INPUT_TIME_REGRESSION", "test fixture 交易时间必须包含时区"
                )
            if bar.trading_at in seen_trading_at:
                raise ShadowContractError("P3_INPUT_DUPLICATE", "test fixture 存在重复交易时间")
            if (
                previous_trading_at is not None
                and bar.trading_at <= previous_trading_at
            ) or (
                previous_available_at is not None
                and bar.available_at <= previous_available_at
            ):
                raise ShadowContractError("P3_INPUT_TIME_REGRESSION", "test fixture 时间顺序倒退")
            if (
                bar.trading_at > request.information_cutoff
                and bar.available_at <= request.information_cutoff
            ):
                raise ShadowContractError("P3_FUTURE_DATA_LEAK", "未来交易数据提前可见")
            expected_row_hash = TestOnlyFixtureProvider._row_hash(
                bar.trading_at, bar.available_at, bar.close
            )
            if bar.row_hash != expected_row_hash:
                raise ShadowContractError("P3_INPUT_HASH_MISMATCH", "test fixture row Hash 不一致")
            seen_trading_at.add(bar.trading_at)
            previous_trading_at = bar.trading_at
            previous_available_at = bar.available_at
        visible = tuple(
            bar
            for bar in batch.bars
            if bar.available_at <= request.information_cutoff
            and bar.trading_at <= request.information_cutoff
        )
        if len(visible) < 2:
            raise ShadowContractError("P3_DATA_UNAVAILABLE", "test fixture 可见输入不足")
        input_batch = InputBatchReference(
            request.input_batch.batch_id,
            batch.content_hash,
            max(bar.available_at for bar in visible),
            batch.fetched_at,
            batch.received_at,
        )
        input_batch.validate(information_cutoff=request.information_cutoff)
        age_seconds = int((request.information_cutoff - input_batch.data_as_of).total_seconds())
        if age_seconds > max_age_seconds:
            raise ShadowContractError("P3_DATA_STALE", "test fixture 输入已过期")

        would_action = "BUY" if visible[-1].close > visible[-2].close else "HOLD"
        visible_rows = [
            {
                "trading_at": bar.trading_at.isoformat(),
                "available_at": bar.available_at.isoformat(),
                "close": bar.close,
                "row_hash": bar.row_hash,
                "lineage_ref": bar.lineage_ref,
            }
            for bar in visible
        ]
        evidence_hash = self._hash({"bars": visible_rows})
        dataset_hash = evidence_hash
        parameter_hash = self._hash(
            {
                "strategy_reference_id": request.strategy.reference_id,
                "strategy_hash": request.strategy.content_hash,
                "parameters": dict(TEST_ONLY_STRATEGY_PARAMETERS),
            }
        )
        decision_dedup_key = self._hash(
            {
                "sample": request.sample.content_hash,
                "strategy": request.strategy.content_hash,
                "profile": request.input_profile.content_hash,
                "input": evidence_hash,
                "cutoff": request.information_cutoff.isoformat(),
                "stock_code": TEST_ONLY_STOCK_CODE,
            }
        )
        decision = TestOnlyShadowDecision(
            stock_code=TEST_ONLY_STOCK_CODE,
            would_action=would_action,
            information_cutoff=request.information_cutoff,
            decision_dedup_key=decision_dedup_key,
            evidence_hash=evidence_hash,
        )
        locks_after = self._release_locks()
        safety = RunSafetyAssertion(
            run_id=run_id,
            tradable=decision.tradable,
            order_created=decision.order_created,
            order_count=0,
            order_service_calls=0,
            execution_service_calls=0,
            capital_write_count=0,
            position_write_count=0,
            release_locks_before=locks_before,
            release_locks_after=locks_after,
        )
        safety.validate()
        result_hash = self._hash(
            {
                "generator_version": TEST_FIXTURE_GENERATOR_VERSION,
                "fixture_kind": TEST_ONLY_FIXTURE_KIND,
                "data_mode": request.data_mode,
                "input_manifest_hash": batch.manifest_hash,
                "dataset_hash": dataset_hash,
                "row_hashes": [bar.row_hash for bar in visible],
                "strategy_reference_id": request.strategy.reference_id,
                "strategy_hash": request.strategy.content_hash,
                "parameter_hash": parameter_hash,
                "input_snapshot_hash": evidence_hash,
                "decision_dedup_key": decision_dedup_key,
            }
        )
        return TestOnlyShadowRunResult(
            generator_version=TEST_FIXTURE_GENERATOR_VERSION,
            fixture_kind=TEST_ONLY_FIXTURE_KIND,
            data_mode="test",
            not_realtime=True,
            input_manifest_hash=batch.manifest_hash,
            dataset_hash=dataset_hash,
            row_hashes=tuple(bar.row_hash for bar in visible),
            strategy_reference_id=request.strategy.reference_id,
            strategy_hash=request.strategy.content_hash,
            parameter_snapshot=TEST_ONLY_STRATEGY_PARAMETERS,
            parameter_hash=parameter_hash,
            input_snapshot_hash=evidence_hash,
            result_hash=result_hash,
            decision=decision,
            safety=safety,
            network_request_count=self.provider.network_request_count,
        )

    @staticmethod
    def _release_locks() -> dict[str, bool]:
        return {key: bool(getattr(settings, key)) for key in RELEASE_LOCK_KEYS}

    @staticmethod
    def _hash(payload: dict) -> str:
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
