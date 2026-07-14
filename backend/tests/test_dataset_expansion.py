import asyncio
from copy import deepcopy
from datetime import date

import pytest

from app.data import dataset_expansion as expansion
from app.data.sohu_daily_importer import SohuDailyKlineImporter


def _provider_row(**overrides):
    row = {
        "stock_code": "600519.SH",
        "period": "1d",
        "trading_date": date(2025, 7, 1),
        "adjustment": "raw",
        "open": "1400.10",
        "high": "1410.20",
        "low": "1395.00",
        "close": "1405.30",
        "volume": 100000,
        "amount": "140530000.00",
        "provider": "sohu",
        "source": "sohu_daily_kline",
        "market_close_time": "15:00:00",
        "timezone": "Asia/Shanghai",
        "price_currency": "CNY",
        "volume_unit": "share",
        "amount_unit": "CNY",
        "normalizer_version": "sprint07-kline-contract-v1",
        "schema_version": "certified-kline-v1",
    }
    row.update(overrides)
    return row


def _stored_row(provider_row=None, **overrides):
    row = expansion.expected_store_row(
        provider_row or _provider_row(),
        provider="sohu",
        source="sohu_daily_kline",
        importer_version="sprint07-sohu-certified-store-v1",
    )
    row.update(overrides)
    return row


def _binding(**overrides):
    values = {
        "dataset_id": "sprint13-controlled-certified-v1",
        "manifest_hash": "a" * 64,
        "primary_provider": "sohu",
        "secondary_provider": "tencent",
        "date_from": date(2025, 7, 1),
        "date_to": date(2026, 6, 30),
        "period": "1d",
        "adjustment": "raw",
        "importer_version": "sprint07-sohu-certified-store-v1",
        "normalizer_version": "sprint07-kline-contract-v1",
        "schema_version": "certified-kline-v1",
    }
    values.update(overrides)
    return expansion.RunBinding(**values)


def _validation(existing=None, provider=None):
    source = provider or _provider_row()
    return expansion.validate_existing_rows(
        existing or [_stored_row(source)],
        [source],
        provider="sohu",
        source="sohu_daily_kline",
        importer_version="sprint07-sohu-certified-store-v1",
    )


def test_existing_rows_with_same_business_content_pass() -> None:
    result = _validation()
    assert result.passed
    assert result.missing_keys == ()
    assert result.extra_keys == ()
    assert result.differences == ()


def test_existing_rows_with_same_count_but_different_dates_fail_closed() -> None:
    result = _validation(existing=[_stored_row(_provider_row(trading_date=date(2025, 7, 2)))])
    assert not result.passed
    assert result.missing_keys
    assert result.extra_keys


@pytest.mark.parametrize("field,value", [("open", "1400.20"), ("high", "1410.30"), ("low", "1394.90"), ("close", "1405.40")])
def test_existing_rows_with_ohlc_difference_fail_closed(field, value) -> None:
    result = _validation(existing=[_stored_row(**{field: value})])
    assert not result.passed
    assert {difference["field"] for difference in result.differences} == {field}


@pytest.mark.parametrize("field,value", [("volume", 100001), ("amount", "140530000.01")])
def test_existing_rows_with_volume_or_amount_difference_fail_closed(field, value) -> None:
    result = _validation(existing=[_stored_row(**{field: value})])
    assert not result.passed
    assert {difference["field"] for difference in result.differences} == {field}


@pytest.mark.parametrize("field,value", [("provider", "unknown"), ("source", "other_source"), ("raw_hash", "f" * 64)])
def test_existing_rows_with_provenance_difference_fail_closed(field, value) -> None:
    result = _validation(existing=[_stored_row(**{field: value})])
    assert not result.passed
    assert {difference["field"] for difference in result.differences} == {field}


def test_existing_validation_does_not_mutate_inputs() -> None:
    provider = _provider_row()
    existing = _stored_row(provider)
    provider_before, existing_before = deepcopy(provider), deepcopy(existing)
    _validation(existing=[existing], provider=provider)
    assert provider == provider_before
    assert existing == existing_before


def test_legacy_row_hash_schema_requires_matching_immutable_batch_lineage() -> None:
    provider = _provider_row()
    existing = _stored_row(
        provider,
        batch_id="legacy-batch",
        importer_version="sprint06-sohu-daily-v1",
        raw_hash="legacy-row-hash",
    )
    result = expansion.validate_existing_rows(
        [existing],
        [provider],
        provider="sohu",
        source="sohu_daily_kline",
        importer_version="sprint07-sohu-certified-store-v1",
        provider_response_raw_hash="provider-response-hash",
        batch_lineage={
            "legacy-batch": {
                "provider": "sohu",
                "source": "sohu_daily_kline",
                "raw_hash": "provider-response-hash",
                "importer_version": "sprint06-sohu-daily-v1",
            }
        },
    )
    assert result.passed
    assert result.lineage_modes == ("batch_raw_hash",)


def test_legacy_row_hash_schema_fails_when_batch_lineage_does_not_match_response() -> None:
    provider = _provider_row()
    existing = _stored_row(
        provider,
        batch_id="legacy-batch",
        importer_version="sprint06-sohu-daily-v1",
        raw_hash="legacy-row-hash",
    )
    result = expansion.validate_existing_rows(
        [existing],
        [provider],
        provider="sohu",
        source="sohu_daily_kline",
        importer_version="sprint07-sohu-certified-store-v1",
        provider_response_raw_hash="provider-response-hash",
        batch_lineage={
            "legacy-batch": {
                "provider": "sohu",
                "source": "sohu_daily_kline",
                "raw_hash": "different-response-hash",
                "importer_version": "sprint06-sohu-daily-v1",
            }
        },
    )
    assert not result.passed
    assert {difference["field"] for difference in result.differences} == {"importer_version", "raw_hash"}


def test_equal_content_and_complete_calendar_is_the_only_skippable_existing_month() -> None:
    decision = expansion.existing_month_decision(_validation(), actual_count=1, expected_count=1)
    assert decision.status == "certified"
    assert decision.can_skip is True
    assert decision.content_validation_hash == _validation().validation_hash


def test_existing_month_with_content_difference_is_not_skippable() -> None:
    decision = expansion.existing_month_decision(
        _validation(existing=[_stored_row(close="1405.40")]), actual_count=1, expected_count=1
    )
    assert decision.status == "validation_failed"
    assert decision.can_skip is False


def test_existing_month_with_calendar_gap_is_review_required_not_skippable() -> None:
    decision = expansion.existing_month_decision(_validation(), actual_count=1, expected_count=2)
    assert decision.status == "review_required"
    assert decision.can_skip is False


def test_same_run_binding_is_accepted() -> None:
    binding = _binding()
    expansion.assert_run_binding(binding.as_dict(), binding)


@pytest.mark.parametrize(
    "field,value",
    [
        ("manifest_hash", "b" * 64),
        ("date_from", date(2025, 7, 2)),
        ("primary_provider", "other"),
        ("period", "5m"),
    ],
)
def test_changed_run_binding_is_rejected_before_writes(field, value) -> None:
    stored = _binding().as_dict()
    stored[field] = value
    with pytest.raises(ValueError, match="create a new run_id and dataset_id"):
        expansion.assert_run_binding(stored, _binding())


def test_retry_succeeds_after_controlled_failures() -> None:
    async def run():
        attempts = 0

        async def operation():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError("temporary")
            return "ok"

        delays = []

        async def sleep(seconds):
            delays.append(seconds)

        result, used = await expansion.retry_async(operation, max_attempts=3, base_delay_seconds=0.25, sleep=sleep)
        assert result == "ok"
        assert used == 3
        assert delays == [0.25, 0.5]

    asyncio.run(run())


def test_retry_stops_after_maximum_attempts() -> None:
    async def run():
        calls = 0

        async def operation():
            nonlocal calls
            calls += 1
            raise TimeoutError("offline")

        with pytest.raises(expansion.RetryExhaustedError) as exc_info:
            await expansion.retry_async(operation, max_attempts=3, base_delay_seconds=0, sleep=lambda _: asyncio.sleep(0))
        assert calls == 3
        assert exc_info.value.attempts == 3

    asyncio.run(run())


@pytest.mark.parametrize(
    "stage,status",
    [("fetch", "fetch_failed"), ("validation", "validation_failed"), ("write", "write_failed")],
)
def test_checkpoint_error_classification_is_stage_specific(stage, status) -> None:
    assert expansion.classify_checkpoint_error(RuntimeError("boom"), stage)[0] == status


def test_provider_validation_requires_all_months_to_pass() -> None:
    months = ["2025-07", "2025-08"]
    result = expansion.provider_validation_summary(
        [
            {"trading_date": "2025-07-15", "result": "PASS"},
            {"trading_date": "2025-08-15", "result": "PASS"},
        ],
        months,
    )
    assert result["passed"] is True
    assert result["pass_count"] == 2
    assert result["fail_count"] == 0


def test_provider_validation_fails_for_a_failed_sample_or_missing_month() -> None:
    failed = expansion.provider_validation_summary(
        [
            {"trading_date": "2025-07-15", "result": "PASS"},
            {"trading_date": "2025-08-15", "result": "FAIL"},
        ],
        ["2025-07", "2025-08"],
    )
    missing = expansion.provider_validation_summary(
        [{"trading_date": "2025-07-15", "result": "PASS"}], ["2025-07", "2025-08"]
    )
    assert failed["passed"] is False
    assert failed["fail_count"] == 1
    assert missing["passed"] is False
    assert missing["missing_months"] == ["2025-08"]


def test_provider_validation_reports_isolated_secondary_fetch_error() -> None:
    summary = expansion.provider_validation_summary(
        [], ["2025-07", "2025-08"], fetch_error="ReadTimeout: tencent unavailable"
    )
    assert summary["passed"] is False
    assert summary["status"] == "review_required"
    assert summary["provider_fetch_errors"] == ["ReadTimeout: tencent unavailable"]


def _hash(rows, manifest_hash="a" * 64):
    return expansion.sprint13_dataset_hash(
        rows,
        manifest_hash=manifest_hash,
        dataset_id="sprint13-controlled-certified-v1",
        stock_codes=["600519.SH"],
        date_from=date(2025, 7, 1),
        date_to=date(2026, 6, 30),
        period="1d",
        adjustment="raw",
    )


def test_dataset_hash_is_deterministic_and_order_independent() -> None:
    rows = [_stored_row(), _stored_row(_provider_row(trading_date=date(2025, 7, 2)))]
    assert _hash(rows) == _hash(list(reversed(rows)))


def test_dataset_hash_excludes_records_outside_frozen_scope() -> None:
    scoped = [_stored_row()]
    outside = _stored_row(_provider_row(stock_code="000001.SZ"))
    assert _hash(scoped) == _hash([*scoped, outside])


@pytest.mark.parametrize(
    "field,value",
    [("close", "1405.40"), ("provider", "other"), ("batch_id", "changed-batch"), ("raw_hash", "e" * 64)],
)
def test_dataset_hash_changes_when_scoped_content_or_lineage_changes(field, value) -> None:
    baseline = [_stored_row()]
    changed = [_stored_row(**{field: value})]
    assert _hash(baseline) != _hash(changed)


def test_dataset_hash_changes_when_manifest_changes() -> None:
    assert _hash([_stored_row()], manifest_hash="a" * 64) != _hash([_stored_row()], manifest_hash="b" * 64)


def test_security_identity_review_fails_closed_without_daily_status_evidence() -> None:
    review = expansion.security_identity_review()
    assert review["status"] == "unresolved"
    assert "daily" in review["reason"]


def test_sprint13_can_delegate_three_attempt_limit_to_outer_month_retry() -> None:
    importer = SohuDailyKlineImporter(client=object(), max_attempts=1)
    assert importer.max_attempts == 1


def test_release_gate_keeps_current_dataset_blocked_without_failing_verifier() -> None:
    gate = expansion.dataset_release_gate(
        unresolved_corporate_actions=10,
        unresolved_dates=6,
        scoped_ready_stock_count=0,
        scoped_ready_row_count=0,
        ready_coverages=[],
        p0_blockers=[],
        p1_blockers=[],
        dataset_hash_stable=True,
    )
    assert gate["dataset_release_status"] == "BLOCKED"
    assert gate["sprint14_admission"] is False
    assert gate["verifier_blockers"] == []


def test_release_gate_can_be_review_required_when_integrity_is_clean_but_sample_is_small() -> None:
    gate = expansion.dataset_release_gate(
        unresolved_corporate_actions=0,
        unresolved_dates=0,
        scoped_ready_stock_count=1,
        scoped_ready_row_count=242,
        ready_coverages=[1.0],
        p0_blockers=[],
        p1_blockers=[],
        dataset_hash_stable=True,
    )
    assert gate["dataset_release_status"] == "REVIEW_REQUIRED"
    assert gate["sprint14_admission"] is False


def test_release_gate_admits_only_a_complete_verified_dataset() -> None:
    gate = expansion.dataset_release_gate(
        unresolved_corporate_actions=0,
        unresolved_dates=0,
        scoped_ready_stock_count=6,
        scoped_ready_row_count=1400,
        ready_coverages=[0.98] * 6,
        p0_blockers=[],
        p1_blockers=[],
        dataset_hash_stable=True,
    )
    assert gate["dataset_release_status"] == "READY"
    assert gate["sprint14_admission"] is True
