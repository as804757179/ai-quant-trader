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
    TEST_ONLY_LICENSE_EVIDENCE,
    TEST_ONLY_PROVIDER,
    TEST_ONLY_SOURCE,
    TEST_ONLY_STOCK_CODE,
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
    data_mode: str
    not_realtime: bool
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
        if not batch.bars:
            raise ShadowContractError("P3_DATA_UNAVAILABLE", "test fixture 输入缺失")
        if not self.provider.verify(batch):
            raise ShadowContractError("P3_INPUT_HASH_MISMATCH", "test fixture Hash 不一致")
        visible = tuple(
            bar for bar in batch.bars if bar.available_at <= request.information_cutoff
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
        evidence_hash = self._hash(
            {"bars": [(bar.available_at.isoformat(), bar.close) for bar in visible]}
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
                "data_mode": request.data_mode,
                "input_snapshot_hash": evidence_hash,
                "decision_dedup_key": decision_dedup_key,
            }
        )
        return TestOnlyShadowRunResult(
            generator_version=TEST_FIXTURE_GENERATOR_VERSION,
            data_mode="test",
            not_realtime=True,
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
