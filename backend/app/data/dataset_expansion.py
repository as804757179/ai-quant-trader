from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Awaitable, Callable, Mapping, Sequence


PRICE_FIELDS = ("open", "high", "low", "close")
CONTENT_FIELDS = (
    "stock_code",
    "period",
    "trading_date",
    "adjustment",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "provider",
    "source",
    "market_close_time",
    "timezone",
    "price_currency",
    "volume_unit",
    "amount_unit",
    "normalizer_version",
    "schema_version",
    "importer_version",
    "raw_hash",
)
DATASET_ROW_FIELDS = (
    "stock_code",
    "period",
    "trading_date",
    "adjustment",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "provider",
    "source",
    "batch_id",
    "raw_hash",
    "certification_status",
    "quality_status",
    "importer_version",
    "normalizer_version",
    "schema_version",
)


def _decimal(value: Any, quantum: str) -> str:
    return format(Decimal(str(value)).quantize(Decimal(quantum), rounding=ROUND_HALF_UP), "f")


def _plain(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    return value


def canonical_value(field: str, value: Any) -> Any:
    if field in PRICE_FIELDS:
        return _decimal(value, "0.0001")
    if field == "amount":
        return _decimal(value, "0.01")
    if field == "volume":
        return int(value)
    return _plain(value)


def normalized_row_hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def expected_store_row(
    row: Mapping[str, Any],
    *,
    provider: str,
    source: str,
    importer_version: str,
) -> dict[str, Any]:
    output = dict(row)
    output.update(
        provider=provider,
        source=source,
        importer_version=importer_version,
        raw_hash=normalized_row_hash(row),
    )
    return output


def business_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row["stock_code"]),
        str(row["period"]),
        str(canonical_value("trading_date", row["trading_date"])),
        str(row["adjustment"]),
    )


@dataclass(frozen=True)
class ExistingDataValidation:
    passed: bool
    missing_keys: tuple[tuple[str, str, str, str], ...]
    extra_keys: tuple[tuple[str, str, str, str], ...]
    differences: tuple[dict[str, Any], ...]
    lineage_modes: tuple[str, ...]
    validation_hash: str


@dataclass(frozen=True)
class ExistingMonthDecision:
    status: str
    can_skip: bool
    reason: str | None
    content_validation_hash: str


def validate_existing_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    provider_rows: Sequence[Mapping[str, Any]],
    *,
    provider: str,
    source: str,
    importer_version: str,
    provider_response_raw_hash: str | None = None,
    batch_lineage: Mapping[str, Mapping[str, Any]] | None = None,
) -> ExistingDataValidation:
    expected = {
        business_key(row): expected_store_row(
            row, provider=provider, source=source, importer_version=importer_version
        )
        for row in provider_rows
    }
    actual = {business_key(row): dict(row) for row in existing_rows}
    expected_keys, actual_keys = set(expected), set(actual)
    missing = tuple(sorted(expected_keys - actual_keys))
    extra = tuple(sorted(actual_keys - expected_keys))
    differences: list[dict[str, Any]] = []
    lineage_modes: list[str] = []
    for key in sorted(expected_keys & actual_keys):
        actual_row = actual[key]
        lineage = (batch_lineage or {}).get(str(actual_row.get("batch_id")))
        uses_batch_raw_hash = bool(
            provider_response_raw_hash
            and lineage
            and actual_row.get("importer_version") == lineage.get("importer_version")
            and actual_row.get("importer_version") != importer_version
            and actual_row.get("provider") == lineage.get("provider") == provider
            and actual_row.get("source") == lineage.get("source") == source
            and lineage.get("raw_hash") == provider_response_raw_hash
        )
        lineage_modes.append("batch_raw_hash" if uses_batch_raw_hash else "row_hash")
        for field in CONTENT_FIELDS:
            if uses_batch_raw_hash and field in {"importer_version", "raw_hash"}:
                continue
            expected_value = canonical_value(field, expected[key].get(field))
            actual_value = canonical_value(field, actual_row.get(field))
            if expected_value != actual_value:
                differences.append(
                    {
                        "key": key,
                        "field": field,
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )
    payload = {
        "actual": [
            {field: canonical_value(field, actual[key].get(field)) for field in CONTENT_FIELDS}
            for key in sorted(actual)
        ],
        "expected": [
            {field: canonical_value(field, expected[key].get(field)) for field in CONTENT_FIELDS}
            for key in sorted(expected)
        ],
        "missing_keys": missing,
        "extra_keys": extra,
        "differences": differences,
        "lineage_modes": lineage_modes,
        "provider_response_raw_hash": provider_response_raw_hash,
        "batch_lineage": {
            key: {
                field: _plain(value)
                for field, value in value_map.items()
                if field in {"provider", "source", "raw_hash", "importer_version"}
            }
            for key, value_map in sorted((batch_lineage or {}).items())
        },
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return ExistingDataValidation(
        passed=not missing and not extra and not differences,
        missing_keys=missing,
        extra_keys=extra,
        differences=tuple(differences),
        lineage_modes=tuple(lineage_modes),
        validation_hash=digest,
    )


def existing_month_decision(
    validation: ExistingDataValidation,
    *,
    actual_count: int,
    expected_count: int,
) -> ExistingMonthDecision:
    if not validation.passed:
        return ExistingMonthDecision(
            status="validation_failed",
            can_skip=False,
            reason="existing certified rows differ from the current normalized provider rows",
            content_validation_hash=validation.validation_hash,
        )
    if actual_count != expected_count:
        return ExistingMonthDecision(
            status="review_required",
            can_skip=False,
            reason=(
                "existing certified rows match the provider response but do not cover the "
                "confirmed trading calendar"
            ),
            content_validation_hash=validation.validation_hash,
        )
    return ExistingMonthDecision(
        status="certified",
        can_skip=True,
        reason=None,
        content_validation_hash=validation.validation_hash,
    )


@dataclass(frozen=True)
class RunBinding:
    dataset_id: str
    manifest_hash: str
    primary_provider: str
    secondary_provider: str
    date_from: date
    date_to: date
    period: str
    adjustment: str
    importer_version: str
    normalizer_version: str
    schema_version: str

    def as_dict(self) -> dict[str, Any]:
        return {key: _plain(value) for key, value in self.__dict__.items()}


def assert_run_binding(existing: Mapping[str, Any], requested: RunBinding) -> None:
    mismatches = []
    for field, expected in requested.__dict__.items():
        actual = existing.get(field)
        if _plain(actual) != _plain(expected):
            mismatches.append(f"{field}: stored={_plain(actual)} requested={_plain(expected)}")
    if mismatches:
        raise ValueError(
            "run_id is bound to a different immutable dataset definition; "
            "create a new run_id and dataset_id. " + "; ".join(mismatches)
        )


class RetryExhaustedError(RuntimeError):
    def __init__(self, attempts: int, last_error: Exception):
        super().__init__(f"provider request failed after {attempts} attempts: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


async def retry_async(
    operation: Callable[[], Awaitable[Any]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[Any, int]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation(), attempt
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                await sleep(base_delay_seconds * (2 ** (attempt - 1)))
    raise RetryExhaustedError(max_attempts, last_error or RuntimeError("unknown failure"))


def classify_checkpoint_error(exc: Exception, stage: str) -> tuple[str, str]:
    if stage == "fetch":
        return "fetch_failed", type(exc).__name__
    if stage == "validation":
        return "validation_failed", type(exc).__name__
    if stage == "write":
        return "write_failed", type(exc).__name__
    raise ValueError(f"unknown checkpoint stage: {stage}")


def provider_validation_summary(
    results: Sequence[Mapping[str, Any]],
    expected_months: Sequence[str],
    *,
    fetch_error: str | None = None,
) -> dict[str, Any]:
    observed_months = {str(row["trading_date"])[:7] for row in results}
    counts = {status: sum(row["result"] == status for row in results) for status in ("PASS", "REVIEW", "FAIL")}
    missing = sorted(set(expected_months) - observed_months)
    actual = len(results)
    passed = (
        fetch_error is None
        and actual == len(expected_months)
        and counts == {"PASS": actual, "REVIEW": 0, "FAIL": 0}
        and not missing
    )
    return {
        "expected_sample_count": len(expected_months),
        "actual_sample_count": actual,
        "pass_count": counts["PASS"],
        "review_count": counts["REVIEW"],
        "fail_count": counts["FAIL"],
        "missing_months": missing,
        "provider_fetch_errors": [fetch_error] if fetch_error else [],
        "status": "pass" if passed else "review_required",
        "passed": passed,
    }


def sprint13_dataset_hash(
    rows: Sequence[Mapping[str, Any]],
    *,
    manifest_hash: str,
    dataset_id: str,
    stock_codes: Sequence[str],
    date_from: date,
    date_to: date,
    period: str,
    adjustment: str,
) -> str:
    allowed = set(stock_codes)
    scoped = [
        row
        for row in rows
        if row["stock_code"] in allowed
        and date_from <= row["trading_date"] <= date_to
        and row["period"] == period
        and row["adjustment"] == adjustment
    ]
    scoped.sort(key=business_key)
    payload = {
        "manifest_hash": manifest_hash,
        "dataset_id": dataset_id,
        "stock_codes": sorted(stock_codes),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "period": period,
        "adjustment": adjustment,
        "rows": [
            {field: canonical_value(field, row.get(field)) for field in DATASET_ROW_FIELDS}
            for row in scoped
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def security_identity_review() -> dict[str, str]:
    return {
        "status": "unresolved",
        "reason": (
            "ordinary-share identity is confirmed, but daily ST, suspension and special-price-limit "
            "status are not proven by the manifest"
        ),
    }


def dataset_release_gate(
    *,
    unresolved_corporate_actions: int,
    unresolved_dates: int,
    scoped_ready_stock_count: int,
    scoped_ready_row_count: int,
    ready_coverages: Sequence[float],
    p0_blockers: Sequence[str],
    p1_blockers: Sequence[str],
    dataset_hash_stable: bool,
) -> dict[str, Any]:
    verifier_blockers = [*p0_blockers, *p1_blockers]
    if not dataset_hash_stable:
        verifier_blockers.append("dataset_hash_unstable")
    business_blockers = []
    if unresolved_corporate_actions:
        business_blockers.append("unresolved_corporate_actions")
    if unresolved_dates:
        business_blockers.append("unresolved_trading_dates")
    admission_ready = (
        not verifier_blockers
        and not business_blockers
        and scoped_ready_stock_count >= 6
        and scoped_ready_row_count >= 1400
        and len(ready_coverages) >= 6
        and all(coverage >= 0.98 for coverage in ready_coverages)
    )
    if business_blockers:
        release_status = "BLOCKED"
    elif admission_ready:
        release_status = "READY"
    else:
        release_status = "REVIEW_REQUIRED"
    return {
        "dataset_release_status": release_status,
        "sprint14_admission": admission_ready,
        "verifier_blockers": verifier_blockers,
        "business_blockers": business_blockers,
    }
