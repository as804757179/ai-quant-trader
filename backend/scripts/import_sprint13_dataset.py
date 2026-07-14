from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
for raw in (ROOT / ".env.host").read_text(encoding="utf-8-sig").splitlines():
    if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

from app.data.certified_store_writer import CertifiedStoreWriter  # noqa: E402
from app.data.dataset_expansion import (  # noqa: E402
    RunBinding,
    assert_run_binding,
    classify_checkpoint_error,
    existing_month_decision,
    provider_validation_summary,
    retry_async,
    security_identity_review,
    sprint13_dataset_hash,
    validate_existing_rows,
)
from app.data.kline_contract import KlineContract  # noqa: E402
from app.data.research_profiles import ResearchDataRequirementProfile  # noqa: E402
from app.data.sohu_daily_importer import ProviderFetchResult, SohuDailyKlineImporter  # noqa: E402
from app.db import get_db  # noqa: E402

MANIFEST_PATH = ROOT / "config" / "datasets" / "sprint13_universe.yaml"
DATE_FROM = date(2025, 7, 1)
DATE_TO = date(2026, 6, 30)
RUN_ID = "sprint13-controlled-certified-v1-run1"
TENCENT_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
MAX_PROVIDER_ATTEMPTS = 3
RETRY_BASE_SECONDS = 1.0


def months() -> list[date]:
    current = DATE_FROM.replace(day=1)
    result: list[date] = []
    while current <= DATE_TO:
        result.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return result


def month_end(start: date) -> date:
    following = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return min(DATE_TO, following - timedelta(days=1))


def month_keys() -> list[str]:
    return [month.strftime("%Y-%m") for month in months()]


def _manifest() -> tuple[dict[str, Any], str]:
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = yaml.safe_load(manifest_bytes)
    if not manifest["frozen"] or len(manifest["stocks"]) != 10:
        raise ValueError("Sprint13 manifest must be frozen with exactly 10 stocks")
    if (
        manifest["date_from"] != DATE_FROM.isoformat()
        or manifest["date_to"] != DATE_TO.isoformat()
        or manifest["period"] != "1d"
        or manifest["adjustment"] != "raw"
        or manifest["primary_provider"]["provider"] != "sohu"
        or manifest["secondary_provider"]["provider"] != "tencent"
    ):
        raise ValueError("Sprint13 manifest does not match the immutable approved scope")
    return manifest, hashlib.sha256(manifest_bytes).hexdigest()


def _run_binding(manifest: dict[str, Any], manifest_hash: str) -> RunBinding:
    return RunBinding(
        dataset_id=manifest["dataset_id"],
        manifest_hash=manifest_hash,
        primary_provider=manifest["primary_provider"]["provider"],
        secondary_provider=manifest["secondary_provider"]["provider"],
        date_from=DATE_FROM,
        date_to=DATE_TO,
        period="1d",
        adjustment="raw",
        importer_version=CertifiedStoreWriter.IMPORTER_VERSION,
        normalizer_version=KlineContract.NORMALIZER_VERSION,
        schema_version=KlineContract.SCHEMA_VERSION,
    )


async def bind_run(binding: RunBinding) -> bool:
    """Create a run once, or prove that a replay uses its immutable definition."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM market.dataset_expansion_runs WHERE run_id=:run"),
            {"run": RUN_ID},
        )
        existing = result.mappings().one_or_none()
        if existing:
            assert_run_binding(dict(existing), binding)
            await db.execute(
                text(
                    """
                    UPDATE market.dataset_expansion_runs
                    SET status='running', failure_reason=NULL
                    WHERE run_id=:run
                    """
                ),
                {"run": RUN_ID},
            )
            return False
        await db.execute(
            text(
                """
                INSERT INTO market.dataset_expansion_runs
                  (run_id,dataset_id,manifest_hash,primary_provider,secondary_provider,
                   date_from,date_to,period,adjustment,importer_version,
                   normalizer_version,schema_version,status,started_at)
                VALUES
                  (:run,:dataset_id,:manifest_hash,:primary_provider,:secondary_provider,
                   :date_from,:date_to,:period,:adjustment,:importer_version,
                   :normalizer_version,:schema_version,'running',NOW())
                """
            ),
            {"run": RUN_ID, **binding.as_dict()},
        )
        return True


async def checkpoint(
    db,
    code: str,
    month: date,
    status: str,
    *,
    batch_id: str | None = None,
    fetched: int = 0,
    certified: int = 0,
    error_type: str | None = None,
    error_reason: str | None = None,
    attempts: int = 0,
    content_validation_hash: str | None = None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO market.dataset_import_checkpoints
              (run_id,stock_code,month_start,batch_id,status,attempt_count,
               rows_fetched,rows_certified,error_type,error_reason,
               last_attempt_at,content_validation_hash,updated_at)
            VALUES
              (:run,:code,:month,:batch,:status,:attempts,:fetched,:certified,
               :error_type,:error_reason,
               CASE WHEN :attempts > 0 THEN NOW() ELSE NULL END,:validation_hash,NOW())
            ON CONFLICT(run_id,stock_code,month_start) DO UPDATE SET
              batch_id=COALESCE(EXCLUDED.batch_id,market.dataset_import_checkpoints.batch_id),
              status=EXCLUDED.status,
              attempt_count=market.dataset_import_checkpoints.attempt_count + EXCLUDED.attempt_count,
              rows_fetched=EXCLUDED.rows_fetched,
              rows_certified=EXCLUDED.rows_certified,
              error_type=EXCLUDED.error_type,
              error_reason=EXCLUDED.error_reason,
              last_attempt_at=COALESCE(EXCLUDED.last_attempt_at,market.dataset_import_checkpoints.last_attempt_at),
              content_validation_hash=EXCLUDED.content_validation_hash,
              updated_at=NOW()
            """
        ),
        {
            "run": RUN_ID,
            "code": code,
            "month": month,
            "batch": batch_id,
            "status": status,
            "attempts": attempts,
            "fetched": fetched,
            "certified": certified,
            "error_type": error_type,
            "error_reason": error_reason,
            "validation_hash": content_validation_hash,
        },
    )


async def expected_count(db, exchange: str, start: date, end: date) -> int:
    result = await db.execute(
        text(
            """
            SELECT COUNT(*) FROM market.trading_calendar
            WHERE exchange=:exchange AND trading_date BETWEEN :start AND :end
              AND is_trading_day AND status='confirmed'
            """
        ),
        {"exchange": exchange, "start": start, "end": end},
    )
    return int(result.scalar() or 0)


async def existing_rows(db, code: str, start: date, end: date) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT stock_code,period,trading_date,adjustment,open,high,low,close,volume,amount,
                   provider,source,market_close_time,timezone,price_currency,volume_unit,amount_unit,
                   normalizer_version,schema_version,importer_version,raw_hash,batch_id,
                   certification_status,quality_status
            FROM market.certified_klines
            WHERE stock_code=:code AND period='1d' AND adjustment='raw'
              AND trading_date BETWEEN :start AND :end
            ORDER BY trading_date
            """
        ),
        {"code": code, "start": start, "end": end},
    )
    return [dict(row) for row in result.mappings().all()]


async def existing_batch_lineage(db, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    batch_ids = sorted({str(row["batch_id"]) for row in rows if row.get("batch_id")})
    if not batch_ids:
        return {}
    result = await db.execute(
        text(
            """
            SELECT batch_id,provider,source,raw_hash,importer_version
            FROM market.data_batches
            WHERE batch_id=ANY(:batch_ids)
            """
        ),
        {"batch_ids": batch_ids},
    )
    return {str(row["batch_id"]): dict(row) for row in result.mappings().all()}


async def fetch_tencent(client: httpx.AsyncClient, code: str) -> tuple[dict[date, dict[str, Decimal]], int]:
    prefix = code.split(".")[1].lower() + code.split(".")[0]
    rows: dict[date, dict[str, Decimal]] = {}
    attempts = 0
    for year in (2025, 2026):
        async def request() -> httpx.Response:
            response = await client.get(
                TENCENT_ENDPOINT,
                params={"param": f"{prefix},day,{year}-01-01,{year}-12-31,640,"},
            )
            response.raise_for_status()
            return response

        response, used = await retry_async(
            request,
            max_attempts=MAX_PROVIDER_ATTEMPTS,
            base_delay_seconds=RETRY_BASE_SECONDS,
        )
        attempts += used
        raw = response.json()["data"][prefix]["day"]
        for item in raw:
            trading_date = date.fromisoformat(item[0])
            if DATE_FROM <= trading_date <= DATE_TO:
                rows[trading_date] = {
                    "open": Decimal(str(item[1])),
                    "close": Decimal(str(item[2])),
                    "high": Decimal(str(item[3])),
                    "low": Decimal(str(item[4])),
                }
    return rows, attempts


def _provider_comparison(
    primary: dict[str, Any], secondary: dict[str, Decimal]
) -> tuple[str, dict[str, Any]]:
    fields: dict[str, Any] = {}
    result = "PASS"
    tolerance = Decimal("0.01")
    for field in ("open", "high", "low", "close"):
        left = Decimal(str(primary[field]))
        right = Decimal(str(secondary[field]))
        absolute = abs(left - right)
        passed = absolute <= tolerance
        if not passed:
            result = "FAIL"
        fields[field] = {
            "primary": str(left),
            "secondary": str(right),
            "absolute_difference": str(absolute),
            "relative_difference": str(absolute / abs(right)) if right else None,
            "tolerance": "abs<=0.01 CNY",
            "passed": passed,
        }
    return result, fields


async def audit_stock(
    code: str,
    primary_rows: list[dict[str, Any]],
    secondary_rows: dict[date, dict[str, Decimal]],
    secondary_fetch_error: str | None,
) -> dict[str, Any]:
    primary = {row["trading_date"]: row for row in primary_rows}
    common = sorted(set(primary) & set(secondary_rows))
    samples: list[date] = []
    for month in months():
        candidates = [day for day in common if day.year == month.year and day.month == month.month]
        if candidates:
            samples.append(candidates[len(candidates) // 2])
    review_rows: list[dict[str, Any]] = []
    async with get_db() as db:
        await db.execute(
            text("DELETE FROM market.provider_validation_reviews WHERE run_id=:run AND stock_code=:code"),
            {"run": RUN_ID, "code": code},
        )
        if secondary_fetch_error:
            await db.execute(
                text(
                    """
                    INSERT INTO market.provider_validation_reviews
                      (run_id,stock_code,trading_date,primary_provider,secondary_provider,result,
                       comparison,endpoint_versions,reviewed_at)
                    VALUES (:run,:code,:day,'sohu','tencent','REVIEW',CAST(:comparison AS jsonb),
                            CAST(:versions AS jsonb),NOW())
                    """
                ),
                {
                    "run": RUN_ID,
                    "code": code,
                    "day": DATE_FROM,
                    "comparison": json.dumps({"provider_fetch_error": secondary_fetch_error}),
                    "versions": json.dumps(
                        {
                            "primary": SohuDailyKlineImporter.IMPORTER_VERSION,
                            "secondary": "tencent-fqkline-raw-v1",
                            "endpoint": TENCENT_ENDPOINT,
                        }
                    ),
                },
            )
            review_rows.append({"trading_date": DATE_FROM, "result": "REVIEW"})
        else:
            for day in samples:
                result, fields = _provider_comparison(primary[day], secondary_rows[day])
                review_rows.append({"trading_date": day, "result": result})
                await db.execute(
                    text(
                        """
                        INSERT INTO market.provider_validation_reviews
                          (run_id,stock_code,trading_date,primary_provider,secondary_provider,result,
                           comparison,endpoint_versions,reviewed_at)
                        VALUES (:run,:code,:day,'sohu','tencent',:result,CAST(:comparison AS jsonb),
                                CAST(:versions AS jsonb),NOW())
                        """
                    ),
                    {
                        "run": RUN_ID,
                        "code": code,
                        "day": day,
                        "result": result,
                        "comparison": json.dumps(
                            {"fields": fields, "volume": "not_compared", "amount": "unresolved"}
                        ),
                        "versions": json.dumps(
                            {
                                "primary": SohuDailyKlineImporter.IMPORTER_VERSION,
                                "secondary": "tencent-fqkline-raw-v1",
                                "endpoint": TENCENT_ENDPOINT,
                            }
                        ),
                    },
                )
        summary = provider_validation_summary(
            review_rows, month_keys(), fetch_error=secondary_fetch_error
        )
        identity = security_identity_review()
        await db.execute(
            text(
                """
                DELETE FROM market.security_status_reviews
                WHERE run_id=:run AND stock_code=:code AND status='normal_trade'
                """
            ),
            {"run": RUN_ID, "code": code},
        )
        await db.execute(
            text(
                """
                INSERT INTO market.security_status_reviews
                  (run_id,stock_code,effective_from,effective_to,status,evidence_source,
                   evidence_version,reviewed_at)
                VALUES (:run,:code,:start,:end,:status,:source,'sprint13.1-neutral-security-status-v1',NOW())
                ON CONFLICT(run_id,stock_code,effective_from,status) DO UPDATE SET
                  effective_to=EXCLUDED.effective_to,evidence_source=EXCLUDED.evidence_source,
                  evidence_version=EXCLUDED.evidence_version,reviewed_at=NOW()
                """
            ),
            {
                "run": RUN_ID,
                "code": code,
                "start": DATE_FROM,
                "end": DATE_TO,
                "status": identity["status"],
                "source": identity["reason"],
            },
        )
        calendar = (
            await db.execute(
                text(
                    """
                    SELECT trading_date,is_trading_day,source_reference
                    FROM market.trading_calendar
                    WHERE exchange=:exchange AND trading_date BETWEEN :start AND :end
                    ORDER BY trading_date
                    """
                ),
                {"exchange": code.split(".")[1], "start": DATE_FROM, "end": DATE_TO},
            )
        ).all()
        certified_dates = {
            row["trading_date"] for row in await existing_rows(db, code, DATE_FROM, DATE_TO)
        }
        for day, is_open, source in calendar:
            if not is_open:
                status, reason = "exchange_closed", "official calendar closed"
            elif day in certified_dates:
                status, reason = "normal_trade", "certified provider bar observed; security status remains unresolved"
            else:
                status, reason = "unresolved", "trading day missing; suspension versus provider missing unresolved"
            await db.execute(
                text(
                    """
                    INSERT INTO market.research_date_reviews
                      (date_review_id,dataset_scope,stock_code,trading_date,status,evidence_source,
                       evidence_time,reason,reviewer_version,reviewed_at)
                    VALUES (:id,:scope,:code,:day,:status,:source,NOW(),:reason,
                            'sprint13-controlled-expansion-v1',NOW())
                    ON CONFLICT(dataset_scope,stock_code,trading_date) DO UPDATE SET
                      status=EXCLUDED.status,evidence_source=EXCLUDED.evidence_source,
                      reason=EXCLUDED.reason,reviewed_at=NOW()
                    """
                ),
                {
                    "id": f"s13-{code.replace('.', '')}-{day:%Y%m%d}",
                    "scope": RUN_ID,
                    "code": code,
                    "day": day,
                    "status": status,
                    "source": source,
                    "reason": reason,
                },
            )
        event_id = f"s13-ca-{code.replace('.', '')}-discovery"
        await db.execute(
            text(
                """
                INSERT INTO market.corporate_action_reviews
                  (event_id,stock_code,event_type,source,verification_status,evidence,
                   reviewer_version,reviewed_at)
                VALUES (:id,:code,'discovery_review',:source,'unresolved',CAST(:evidence AS jsonb),
                        'sprint13-controlled-expansion-v1',NOW())
                ON CONFLICT(event_id) DO UPDATE SET evidence=EXCLUDED.evidence,reviewed_at=NOW()
                """
            ),
            {
                "id": event_id,
                "code": code,
                "source": f"https://www.cninfo.com.cn/new/fulltextSearch?keyWord={code.split('.')[0]}",
                "evidence": json.dumps(
                    {
                        "status": "official announcement discovery requires event-level evidence review",
                        "target_range": f"{DATE_FROM}/{DATE_TO}",
                    }
                ),
            },
        )
        unresolved_dates = any(is_open and day not in certified_dates for day, is_open, _ in calendar)
        await _write_readiness_reviews(
            db,
            code,
            provider_status=summary["status"],
            unresolved_dates=unresolved_dates,
        )
    return summary


async def _write_readiness_reviews(
    db,
    code: str,
    *,
    provider_status: str,
    unresolved_dates: bool,
) -> None:
    ohlcv = ResearchDataRequirementProfile.get("OHLCV_RETURN_V1")
    amount = ResearchDataRequirementProfile.get("AMOUNT_FACTOR_V1")
    execution = ResearchDataRequirementProfile.get("EXECUTION_REFERENCE_V1")
    reviews = [
        (
            "OHLCV_RETURN_V1",
            "return_backtest",
            "review_required",
            ohlcv.required_fields,
            list(ohlcv.required_fields),
            [],
            ["corporate_action_status", "security_status"],
        ),
        (
            "AMOUNT_FACTOR_V1",
            "return_backtest",
            "review_required",
            amount.required_fields,
            list(ohlcv.required_fields),
            ["amount_provider_validation"],
            ["corporate_action_status", "security_status"],
        ),
        (
            "EXECUTION_REFERENCE_V1",
            "execution_reference",
            "rejected",
            execution.required_fields,
            ["execution_gate"],
            [],
            ["quote_time", "price_applicability", "explicit_authorization"],
        ),
    ]
    for profile, scope, status, required, validated, unresolved, rejected in reviews:
        await db.execute(
            text(
                """
                INSERT INTO market.research_readiness_reviews
                  (review_id,stock_code,period,date_from,date_to,adjustment,readiness_status,
                   research_use_scope,corporate_action_status,missingness_status,
                   provider_validation_status,review_reason,evidence,reviewer_version,reviewed_at,
                   requirement_profile,required_fields,validated_fields,unresolved_fields,
                   rejected_fields,policy_version)
                VALUES (:id,:code,'1d',:start,:end,'raw',:status,:scope,'unresolved',:missing,
                        :provider_status,:reason,CAST(:evidence AS jsonb),
                        'sprint13-controlled-expansion-v1',NOW(),:profile,CAST(:required AS jsonb),
                        CAST(:validated AS jsonb),CAST(:unresolved AS jsonb),CAST(:rejected AS jsonb),
                        'field-readiness-v1')
                ON CONFLICT(stock_code,period,date_from,date_to,adjustment,research_use_scope,requirement_profile)
                DO UPDATE SET readiness_status=EXCLUDED.readiness_status,
                  corporate_action_status=EXCLUDED.corporate_action_status,
                  missingness_status=EXCLUDED.missingness_status,
                  provider_validation_status=EXCLUDED.provider_validation_status,
                  review_reason=EXCLUDED.review_reason,evidence=EXCLUDED.evidence,
                  reviewed_at=NOW(),validated_fields=EXCLUDED.validated_fields,
                  unresolved_fields=EXCLUDED.unresolved_fields,rejected_fields=EXCLUDED.rejected_fields
                """
            ),
            {
                "id": f"s13-{code.replace('.', '')}-{profile.lower()}",
                "code": code,
                "start": DATE_FROM,
                "end": DATE_TO,
                "status": status,
                "scope": scope,
                "missing": "unresolved" if unresolved_dates else "complete",
                "provider_status": provider_status,
                "reason": (
                    "Corporate-action discovery and daily security status remain unresolved; fail closed."
                    if scope == "return_backtest"
                    else "Execution reference remains unauthorized."
                ),
                "evidence": json.dumps(
                    {
                        "amount": "unresolved",
                        "corporate_actions": "unresolved",
                        "security_status": "unresolved",
                    }
                ),
                "profile": profile,
                "required": json.dumps(required),
                "validated": json.dumps(validated),
                "unresolved": json.dumps(unresolved),
                "rejected": json.dumps(rejected),
            },
        )


async def process_month(
    importer: SohuDailyKlineImporter,
    code: str,
    start: date,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    end = month_end(start)
    async with get_db() as db:
        await checkpoint(db, code, start, "running")
    try:
        fetched, attempts = await retry_async(
            lambda: importer.fetch(code, start, end),
            max_attempts=MAX_PROVIDER_ATTEMPTS,
            base_delay_seconds=RETRY_BASE_SECONDS,
        )
    except Exception as exc:
        status, error_type = classify_checkpoint_error(exc, "fetch")
        async with get_db() as db:
            await checkpoint(
                db,
                code,
                start,
                status,
                error_type=error_type,
                error_reason=str(exc),
                attempts=getattr(exc, "attempts", MAX_PROVIDER_ATTEMPTS),
            )
        return {
            "stock_code": code,
            "month": start.isoformat(),
            "status": status,
            "rows": 0,
            "attempts": getattr(exc, "attempts", MAX_PROVIDER_ATTEMPTS),
            "reason": str(exc),
        }, []

    async with get_db() as db:
        expected = await expected_count(db, code.split(".")[1], start, end)
        prior_rows = await existing_rows(db, code, start, end)
        if prior_rows:
            batch_lineage = await existing_batch_lineage(db, prior_rows)
            validation = validate_existing_rows(
                prior_rows,
                fetched.rows,
                provider=fetched.provider,
                source=fetched.source,
                importer_version=CertifiedStoreWriter.IMPORTER_VERSION,
                provider_response_raw_hash=fetched.raw_hash,
                batch_lineage=batch_lineage,
            )
            decision = existing_month_decision(
                validation, actual_count=len(prior_rows), expected_count=expected
            )
            detail = {
                "reason": decision.reason,
                "missing_keys": validation.missing_keys,
                "extra_keys": validation.extra_keys,
                "differences": validation.differences,
            }
            await checkpoint(
                db,
                code,
                start,
                decision.status,
                fetched=len(fetched.rows),
                certified=len(prior_rows) if decision.status == "certified" else 0,
                error_type=None if decision.status == "certified" else "ExistingDataValidation",
                error_reason=None if decision.status == "certified" else json.dumps(detail, default=str),
                attempts=attempts,
                content_validation_hash=decision.content_validation_hash,
            )
            return {
                "stock_code": code,
                "month": start.isoformat(),
                "status": f"{decision.status}_existing",
                "rows": len(prior_rows),
                "attempts": attempts,
                "content_validation_hash": decision.content_validation_hash,
                "reason": decision.reason,
            }, fetched.rows

        if not fetched.rows:
            exc = ValueError("primary provider returned no rows for month")
            status, error_type = classify_checkpoint_error(exc, "validation")
            await checkpoint(
                db,
                code,
                start,
                status,
                error_type=error_type,
                error_reason=str(exc),
                attempts=attempts,
            )
            return {
                "stock_code": code,
                "month": start.isoformat(),
                "status": status,
                "rows": 0,
                "attempts": attempts,
                "reason": str(exc),
            }, []
        try:
            result = await CertifiedStoreWriter().ingest(db, fetched)
        except Exception as exc:
            status, error_type = classify_checkpoint_error(exc, "write")
            await checkpoint(
                db,
                code,
                start,
                status,
                error_type=error_type,
                error_reason=str(exc),
                attempts=attempts,
            )
            return {
                "stock_code": code,
                "month": start.isoformat(),
                "status": status,
                "rows": 0,
                "attempts": attempts,
                "reason": str(exc),
            }, fetched.rows
        status = "certified" if result.status == "certified" else "validation_failed"
        await checkpoint(
            db,
            code,
            start,
            status,
            batch_id=result.batch_id,
            fetched=result.total_rows,
            certified=result.accepted_rows,
            error_type=None if status == "certified" else "CertificationRejected",
            error_reason=result.reject_reason,
            attempts=attempts,
        )
        return {
            "stock_code": code,
            "month": start.isoformat(),
            "status": status,
            "rows": result.accepted_rows,
            "attempts": attempts,
            "batch_id": result.batch_id,
            "reason": result.reject_reason,
        }, fetched.rows


async def dataset_rows(stock_codes: list[str]) -> list[dict[str, Any]]:
    async with get_db() as db:
        result = await db.execute(
            text(
                """
                SELECT stock_code,period,trading_date,adjustment,open,high,low,close,volume,amount,
                       provider,source,batch_id,raw_hash,certification_status,quality_status,
                       importer_version,normalizer_version,schema_version
                FROM market.certified_klines
                WHERE stock_code=ANY(:codes) AND period='1d' AND adjustment='raw'
                  AND trading_date BETWEEN :start AND :end
                ORDER BY stock_code,trading_date
                """
            ),
            {"codes": stock_codes, "start": DATE_FROM, "end": DATE_TO},
        )
        return [dict(row) for row in result.mappings().all()]


async def run() -> None:
    manifest, manifest_hash = _manifest()
    binding = _run_binding(manifest, manifest_hash)
    created = await bind_run(binding)
    importer = SohuDailyKlineImporter(max_attempts=1)
    secondary_client = httpx.AsyncClient(timeout=30.0, trust_env=False)
    outcomes: list[dict[str, Any]] = []
    provider_summaries: dict[str, dict[str, Any]] = {}
    try:
        for stock in manifest["stocks"]:
            code = stock["stock_code"]
            secondary_rows: dict[date, dict[str, Decimal]] = {}
            secondary_error: str | None = None
            try:
                secondary_rows, _ = await fetch_tencent(secondary_client, code)
            except Exception as exc:
                secondary_error = str(exc)
            primary_by_date: dict[date, dict[str, Any]] = {}
            for month in months():
                outcome, primary_rows = await process_month(importer, code, month)
                outcomes.append(outcome)
                for row in primary_rows:
                    primary_by_date[row["trading_date"]] = row
            try:
                provider_summaries[code] = await audit_stock(
                    code,
                    list(primary_by_date.values()),
                    secondary_rows,
                    secondary_error,
                )
            except Exception as exc:
                provider_summaries[code] = provider_validation_summary(
                    [], month_keys(), fetch_error=f"audit failed: {exc}"
                )
                outcomes.append(
                    {
                        "stock_code": code,
                        "month": None,
                        "status": "audit_failed",
                        "rows": 0,
                        "reason": str(exc),
                    }
                )
        rows = await dataset_rows([stock["stock_code"] for stock in manifest["stocks"]])
        dataset_hash = sprint13_dataset_hash(
            rows,
            manifest_hash=manifest_hash,
            dataset_id=manifest["dataset_id"],
            stock_codes=[stock["stock_code"] for stock in manifest["stocks"]],
            date_from=DATE_FROM,
            date_to=DATE_TO,
            period="1d",
            adjustment="raw",
        )
        async with get_db() as db:
            await db.execute(
                text(
                    """
                    UPDATE market.dataset_expansion_runs
                    SET status='review_required', completed_at=NOW(),
                        failure_reason='Corporate-action discovery and security-status evidence remain unresolved.'
                    WHERE run_id=:run
                    """
                ),
                {"run": RUN_ID},
            )
    finally:
        await importer.close()
        await secondary_client.aclose()
    print(
        json.dumps(
            {
                "run_id": RUN_ID,
                "run_created": created,
                "manifest_hash": manifest_hash,
                "dataset_hash": dataset_hash,
                "dataset_row_count": len(rows),
                "outcomes": outcomes,
                "provider_validation_by_stock": provider_summaries,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    asyncio.run(run())
