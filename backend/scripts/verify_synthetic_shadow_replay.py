from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "synthetic-test-only-secret-key-32chars")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://synthetic-test-only@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

from app.data.p3_replay_profile import PROFILE_NAME, STATUS, is_runner_usable
from app.core.config import settings
from app.shadow.contracts import RELEASE_LOCK_KEYS
from app.shadow.contracts import ShadowContractError
from app.shadow.test_execution import TestOnlyShadowRunner
from app.shadow.test_fixtures import (
    TEST_ONLY_FIXTURE_KIND,
    TestOnlyFixtureProvider,
    test_only_now,
)


def build_verification_report() -> dict[str, object]:
    if settings.is_production():
        raise RuntimeError("synthetic/test-only 验证命令仅允许 local_development，拒绝 production")
    if STATUS != "draft" or is_runner_usable():
        raise RuntimeError("正式 P3 Profile 状态不符合 draft/disabled 安全边界")

    cutoff = test_only_now()
    request = TestOnlyShadowRunner.build_request(information_cutoff=cutoff)
    runner = TestOnlyShadowRunner()
    results = tuple(
        runner.execute(run_id=f"synthetic-test-only-verification-{index}", request=request)
        for index in range(1, 4)
    )
    first = results[0]
    if any(result.result_hash != first.result_hash for result in results):
        raise RuntimeError("三次运行 result_hash 不一致")
    if any(
        result.decision.decision_dedup_key != first.decision.decision_dedup_key
        for result in results
    ):
        raise RuntimeError("三次运行 decision_dedup_key 不一致")
    if any(result.fixture_kind != TEST_ONLY_FIXTURE_KIND for result in results):
        raise RuntimeError("运行结果不是 synthetic/test-only")
    if any(result.data_mode != "test" or not result.not_realtime for result in results):
        raise RuntimeError("test-only 运行被错误标记为 replay 或 realtime")
    for result in results:
        safety = result.safety
        if any(
            (
                safety.tradable,
                safety.order_created,
                safety.order_count,
                safety.order_service_calls,
                safety.execution_service_calls,
                safety.capital_write_count,
                safety.position_write_count,
            )
        ):
            raise RuntimeError("检测到禁止的交易或写入副作用")
        if any(safety.release_locks_before[key] or safety.release_locks_after[key] for key in RELEASE_LOCK_KEYS):
            raise RuntimeError("检测到发布或交易锁被打开")
    failure_cases = (
        ("missing", "P3_DATA_UNAVAILABLE"),
        ("stale", "P3_DATA_STALE"),
        ("hash_mismatch", "P3_INPUT_HASH_MISMATCH"),
        ("time_regression", "P3_INPUT_TIME_REGRESSION"),
        ("available_at_missing", "P3_INPUT_AVAILABLE_AT_MISSING"),
        ("lineage_missing", "P3_INPUT_LINEAGE_UNVERIFIED"),
        ("row_hash_mismatch", "P3_INPUT_HASH_MISMATCH"),
        ("duplicate", "P3_INPUT_DUPLICATE"),
        ("row_time_regression", "P3_INPUT_TIME_REGRESSION"),
        ("manifest_hash_mismatch", "P3_INPUT_HASH_MISMATCH"),
    )
    failure_report = []
    for scenario, expected_code in failure_cases:
        try:
            TestOnlyShadowRunner(TestOnlyFixtureProvider(scenario=scenario)).execute(
                run_id=f"synthetic-test-only-failure-{scenario}", request=request
            )
        except ShadowContractError as exc:
            if exc.code != expected_code:
                raise RuntimeError(
                    f"场景 {scenario} 返回错误码 {exc.code}，预期 {expected_code}"
                ) from exc
            failure_report.append({"scenario": scenario, "error_code": exc.code, "blocked": True})
        else:
            raise RuntimeError(f"场景 {scenario} 未 fail-closed")
    class NonSyntheticFixtureProvider(TestOnlyFixtureProvider):
        def load(self, *, information_cutoff):
            return replace(
                super().load(information_cutoff=information_cutoff),
                fixture_kind="replay",
            )

    class ForeignProvider:
        network_request_count = 0

        def load(self, *, information_cutoff):
            raise AssertionError("foreign provider must not be called")

    for label, provider in (
        ("non_synthetic_fixture", NonSyntheticFixtureProvider()),
        ("foreign_provider_type", ForeignProvider()),
    ):
        try:
            TestOnlyShadowRunner(provider).execute(
                run_id=f"synthetic-test-only-boundary-{label}", request=request
            )
        except ShadowContractError as exc:
            if exc.code != "P3_TEST_ONLY_FIXTURE_REQUIRED":
                raise RuntimeError(
                    f"输入边界 {label} 返回错误码 {exc.code}，预期 P3_TEST_ONLY_FIXTURE_REQUIRED"
                ) from exc
            failure_report.append(
                {"scenario": label, "error_code": exc.code, "blocked": True}
            )
        else:
            raise RuntimeError(f"输入边界 {label} 未 fail-closed")
    future_low = TestOnlyShadowRunner(TestOnlyFixtureProvider(future_close=-1.0)).execute(
        run_id="synthetic-test-only-future-low", request=request
    )
    future_high = TestOnlyShadowRunner(TestOnlyFixtureProvider(future_close=1_000_000.0)).execute(
        run_id="synthetic-test-only-future-high", request=request
    )
    if future_low.result_hash != future_high.result_hash:
        raise RuntimeError("截止时间后的未来数据改变了结果 Hash")
    report = {
        "fixture_kind": first.fixture_kind,
        "data_mode": first.data_mode,
        "not_realtime": first.not_realtime,
        "profile": {"name": PROFILE_NAME, "status": STATUS, "runner_usable": is_runner_usable()},
        "information_cutoff": cutoff.isoformat(),
        "runs": [
            {
                "run_id": result.safety.run_id,
                "input_manifest_hash": result.input_manifest_hash,
                "dataset_hash": result.dataset_hash,
                "row_hashes": list(result.row_hashes),
                "strategy_reference_id": result.strategy_reference_id,
                "strategy_hash": result.strategy_hash,
                "parameter_snapshot": dict(result.parameter_snapshot),
                "parameter_hash": result.parameter_hash,
                "input_snapshot_hash": result.input_snapshot_hash,
                "result_hash": result.result_hash,
                "decision_dedup_key": result.decision.decision_dedup_key,
                "network_request_count": result.network_request_count,
                "zero_writes": {
                    "order_count": result.safety.order_count,
                    "order_service_calls": result.safety.order_service_calls,
                    "execution_service_calls": result.safety.execution_service_calls,
                    "capital_write_count": result.safety.capital_write_count,
                    "position_write_count": result.safety.position_write_count,
                },
                "locks_before": result.safety.release_locks_before,
                "locks_after": result.safety.release_locks_after,
            }
            for result in results
        ],
        "deterministic": True,
        "failure_cases": failure_report,
        "future_data_excluded": True,
        "formal_replay": "blocked/deferred",
        "realtime_data_approved": False,
    }
    report["audit_report_hash"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the explicit local synthetic/test-only shadow verification.")
    parser.add_argument(
        "--confirm-test-only",
        action="store_true",
        help="Acknowledge that this command is test-only and never starts formal replay.",
    )
    args = parser.parse_args()
    if not args.confirm_test_only:
        print("必须显式传入 --confirm-test-only；本命令不会启动正式 replay。", file=sys.stderr)
        return 2
    try:
        print(json.dumps(build_verification_report(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"synthetic/test-only 验证失败（fail-closed）：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
