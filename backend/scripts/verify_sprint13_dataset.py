from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
for raw in (ROOT / ".env.host").read_text(encoding="utf-8-sig").splitlines():
    if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

from app.data.certified_store_writer import CertifiedStoreWriter  # noqa: E402
from app.data.dataset_expansion import (  # noqa: E402
    RunBinding,
    dataset_release_gate,
    provider_validation_summary,
    sprint13_dataset_hash,
)
from app.data.kline_contract import KlineContract  # noqa: E402

RUN_ID = "sprint13-controlled-certified-v1-run1"
START = date(2025, 7, 1)
END = date(2026, 6, 30)
MANIFEST_PATH = ROOT / "config" / "datasets" / "sprint13_universe.yaml"


def normalize(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def stable_hash(rows: list[asyncpg.Record]) -> str:
    payload = [{key: normalize(value) for key, value in dict(row).items()} for row in rows]
    payload.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def manifest_scope() -> tuple[dict[str, Any], str, list[str], list[str]]:
    data = MANIFEST_PATH.read_bytes()
    manifest = yaml.safe_load(data)
    codes = [stock["stock_code"] for stock in manifest["stocks"]]
    expected_months = [
        f"{year:04d}-{month:02d}"
        for year, month in [
            (2025, 7), (2025, 8), (2025, 9), (2025, 10), (2025, 11), (2025, 12),
            (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6),
        ]
    ]
    return manifest, hashlib.sha256(data).hexdigest(), codes, expected_months


def run_binding(manifest: dict[str, Any], manifest_hash: str) -> RunBinding:
    return RunBinding(
        dataset_id=manifest["dataset_id"],
        manifest_hash=manifest_hash,
        primary_provider=manifest["primary_provider"]["provider"],
        secondary_provider=manifest["secondary_provider"]["provider"],
        date_from=START,
        date_to=END,
        period="1d",
        adjustment="raw",
        importer_version=CertifiedStoreWriter.IMPORTER_VERSION,
        normalizer_version=KlineContract.NORMALIZER_VERSION,
        schema_version=KlineContract.SCHEMA_VERSION,
    )


async def snapshots(connection: asyncpg.Connection, started_at: datetime) -> dict[str, str]:
    legacy = await connection.fetch(
        """
        SELECT time,stock_code,period,open,high,low,close,volume,amount,turnover_rate
        FROM market.klines ORDER BY stock_code,period,time
        """
    )
    existing_certified = await connection.fetch(
        """
        SELECT stock_code,period,trading_date,adjustment,open,high,low,close,volume,amount,
               provider,source,batch_id,raw_hash,certification_status,quality_status,
               importer_version,normalizer_version,schema_version
        FROM market.certified_klines
        WHERE created_at < $1
        ORDER BY stock_code,period,adjustment,trading_date
        """,
        started_at,
    )
    corporate_actions = await connection.fetch(
        "SELECT * FROM market.corporate_actions ORDER BY action_id,event_version"
    )
    return {
        "legacy": stable_hash(legacy),
        "existing_certified": stable_hash(existing_certified),
        "corporate_actions": stable_hash(corporate_actions),
    }


async def inspection(dataset_hash_stable: bool) -> dict[str, Any]:
    manifest, manifest_hash, codes, expected_months = manifest_scope()
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    connection = await asyncpg.connect(url)
    verifier_blockers: list[str] = []
    p0: list[str] = []
    p1: list[str] = []
    try:
        run = await connection.fetchrow(
            "SELECT * FROM market.dataset_expansion_runs WHERE run_id=$1", RUN_ID
        )
        binding = run_binding(manifest, manifest_hash)
        binding_match = bool(run)
        binding_mismatches: list[str] = []
        if run:
            for field, expected in binding.as_dict().items():
                actual = normalize(run[field])
                if actual != normalize(expected):
                    binding_match = False
                    binding_mismatches.append(f"{field}: stored={actual} expected={normalize(expected)}")
        if not binding_match:
            verifier_blockers.append("run_manifest_binding_mismatch")
            p0.append("run_manifest_binding_mismatch")

        certified_rows = await connection.fetch(
            """
            SELECT stock_code,period,trading_date,adjustment,open,high,low,close,volume,amount,
                   provider,source,batch_id,raw_hash,certification_status,quality_status,
                   importer_version,normalizer_version,schema_version
            FROM market.certified_klines
            WHERE stock_code = ANY($1::varchar[]) AND period='1d' AND adjustment='raw'
              AND trading_date BETWEEN $2 AND $3
            ORDER BY stock_code,trading_date
            """,
            codes,
            START,
            END,
        )
        dataset_hash = sprint13_dataset_hash(
            [dict(row) for row in certified_rows],
            manifest_hash=manifest_hash,
            dataset_id=manifest["dataset_id"],
            stock_codes=codes,
            date_from=START,
            date_to=END,
            period="1d",
            adjustment="raw",
        )
        invalid_rows = await connection.fetchval(
            """
            SELECT COUNT(*) FROM market.certified_klines
            WHERE stock_code=ANY($1::varchar[]) AND period='1d' AND adjustment='raw'
              AND trading_date BETWEEN $2 AND $3 AND
              (provider IN ('unknown','synthetic') OR source IN ('unknown','synthetic')
               OR certification_status<>'certified' OR quality_status<>'pass')
            """,
            codes,
            START,
            END,
        )
        if invalid_rows:
            verifier_blockers.append("invalid_rows_in_certified_store")
            p0.append("invalid_rows_in_certified_store")

        checkpoint_rows = await connection.fetch(
            """
            SELECT stock_code,month_start,status,attempt_count,rows_fetched,rows_certified,
                   error_type,error_reason,last_attempt_at,content_validation_hash,batch_id
            FROM market.dataset_import_checkpoints
            WHERE run_id=$1 ORDER BY stock_code,month_start
            """,
            RUN_ID,
        )
        terminal = {
            "certified",
            "review_required",
            "validation_failed",
            "fetch_failed",
            "write_failed",
            "rejected",
        }
        checkpoint_issues: list[str] = []
        expected_checkpoints = len(codes) * len(expected_months)
        if len(checkpoint_rows) != expected_checkpoints:
            checkpoint_issues.append(
                f"expected {expected_checkpoints} checkpoints, found {len(checkpoint_rows)}"
            )
        checkpoint_states: dict[str, int] = {}
        for row in checkpoint_rows:
            checkpoint_states[row["status"]] = checkpoint_states.get(row["status"], 0) + 1
            if row["status"] not in terminal:
                checkpoint_issues.append(f"{row['stock_code']}:{row['month_start']} is not terminal")
            if row["attempt_count"] < 1:
                checkpoint_issues.append(f"{row['stock_code']}:{row['month_start']} has no provider attempt")
            if row["last_attempt_at"] is None:
                checkpoint_issues.append(f"{row['stock_code']}:{row['month_start']} lacks last_attempt_at")
            if row["content_validation_hash"] is None:
                checkpoint_issues.append(f"{row['stock_code']}:{row['month_start']} lacks content_validation_hash")
            if row["status"] in {"fetch_failed", "validation_failed", "write_failed"} and not row["error_type"]:
                checkpoint_issues.append(f"{row['stock_code']}:{row['month_start']} lacks error classification")
        if checkpoint_issues:
            verifier_blockers.append("checkpoint_integrity_failure")
            p0.append("checkpoint_integrity_failure")
        if checkpoint_states.get("validation_failed"):
            verifier_blockers.append("existing_data_validation_failed")
            p0.append("existing_data_validation_failed")
        if checkpoint_states.get("fetch_failed") or checkpoint_states.get("write_failed"):
            verifier_blockers.append("primary_import_failure")
            p0.append("primary_import_failure")

        provider_rows = await connection.fetch(
            """
            SELECT stock_code,trading_date,result,comparison
            FROM market.provider_validation_reviews WHERE run_id=$1
            ORDER BY stock_code,trading_date
            """,
            RUN_ID,
        )
        by_provider: dict[str, list[dict[str, Any]]] = {code: [] for code in codes}
        provider_errors: dict[str, list[str]] = {code: [] for code in codes}
        for row in provider_rows:
            comparison = row["comparison"]
            if isinstance(comparison, str):
                comparison = json.loads(comparison)
            if comparison.get("provider_fetch_error"):
                provider_errors[row["stock_code"]].append(comparison["provider_fetch_error"])
            by_provider.setdefault(row["stock_code"], []).append(dict(row))
        provider_summary = {
            code: provider_validation_summary(
                by_provider.get(code, []), expected_months,
                fetch_error="; ".join(provider_errors.get(code, [])) or None,
            )
            for code in codes
        }
        if any(not value["passed"] for value in provider_summary.values()):
            verifier_blockers.append("secondary_provider_validation_failed")
            p0.append("secondary_provider_validation_failed")
        secondary_written = await connection.fetchval(
            """
            SELECT COUNT(*) FROM market.certified_klines
            WHERE provider='tencent' OR source LIKE 'tencent%'
            """
        )
        if secondary_written:
            verifier_blockers.append("secondary_provider_wrote_certified_store")
            p0.append("secondary_provider_wrote_certified_store")

        security_rows = await connection.fetch(
            """
            SELECT stock_code,status,count(*) AS count
            FROM market.security_status_reviews
            WHERE run_id=$1 GROUP BY stock_code,status ORDER BY stock_code,status
            """,
            RUN_ID,
        )
        security_summary: dict[str, dict[str, int]] = {code: {} for code in codes}
        for row in security_rows:
            security_summary.setdefault(row["stock_code"], {})[row["status"]] = row["count"]
        if any(summary.get("normal_trade", 0) for summary in security_summary.values()):
            verifier_blockers.append("unsupported_yearly_normal_trade_security_status")
            p0.append("unsupported_yearly_normal_trade_security_status")
        if any(not summary.get("unresolved") for summary in security_summary.values()):
            verifier_blockers.append("missing_fail_closed_security_review")
            p0.append("missing_fail_closed_security_review")

        calendar_counts = await connection.fetch(
            """
            SELECT exchange,count(*) AS count
            FROM market.trading_calendar WHERE trading_date BETWEEN $1 AND $2
            GROUP BY exchange
            """,
            START,
            END,
        )
        calendar_by_exchange = {row["exchange"]: row["count"] for row in calendar_counts}
        date_rows = await connection.fetch(
            """
            SELECT stock_code,status,count(*) AS count
            FROM market.research_date_reviews
            WHERE dataset_scope=$1 GROUP BY stock_code,status ORDER BY stock_code,status
            """,
            RUN_ID,
        )
        date_summary: dict[str, dict[str, int]] = {code: {} for code in codes}
        for row in date_rows:
            date_summary.setdefault(row["stock_code"], {})[row["status"]] = row["count"]
        missing_date_review_codes = []
        for code in codes:
            observed = sum(date_summary.get(code, {}).values())
            expected = calendar_by_exchange.get(code.split(".")[1], 0)
            if observed != expected:
                missing_date_review_codes.append(f"{code}: {observed}/{expected}")
        if missing_date_review_codes:
            verifier_blockers.append("incomplete_trading_date_review_coverage")
            p0.append("incomplete_trading_date_review_coverage")
        unresolved_dates = sum(summary.get("unresolved", 0) for summary in date_summary.values())

        corporate_rows = await connection.fetch(
            """
            SELECT stock_code,verification_status,count(*) AS count
            FROM market.corporate_action_reviews
            WHERE reviewer_version='sprint13-controlled-expansion-v1'
              AND stock_code=ANY($1::varchar[])
            GROUP BY stock_code,verification_status ORDER BY stock_code,verification_status
            """,
            codes,
        )
        corporate_summary: dict[str, dict[str, int]] = {code: {} for code in codes}
        for row in corporate_rows:
            corporate_summary.setdefault(row["stock_code"], {})[row["verification_status"]] = row["count"]
        missing_corporate_discovery = [
            code for code in codes if not sum(corporate_summary.get(code, {}).values())
        ]
        if missing_corporate_discovery:
            verifier_blockers.append("missing_corporate_action_discovery")
            p0.append("missing_corporate_action_discovery")
        unresolved_corporate_actions = sum(
            summary.get("unresolved", 0) for summary in corporate_summary.values()
        )

        readiness_rows = await connection.fetch(
            """
            SELECT stock_code,period,date_from,date_to,adjustment,research_use_scope,
                   requirement_profile,required_fields,readiness_status,
                   corporate_action_status,missingness_status,provider_validation_status
            FROM market.research_readiness_reviews
            WHERE stock_code=ANY($1::varchar[]) AND period='1d'
              AND date_from=$2 AND date_to=$3 AND adjustment='raw'
            ORDER BY stock_code,research_use_scope,requirement_profile
            """,
            codes,
            START,
            END,
        )
        readiness_summary: dict[str, list[dict[str, Any]]] = {code: [] for code in codes}
        readiness_issues: list[str] = []
        ready_codes: set[str] = set()
        for row in readiness_rows:
            item = dict(row)
            readiness_summary.setdefault(row["stock_code"], []).append(item)
            if not row["required_fields"]:
                readiness_issues.append(f"{row['stock_code']}:{row['requirement_profile']} missing required_fields")
            return_profile = row["research_use_scope"] == "return_backtest"
            if return_profile and row["readiness_status"] == "ready" and (
                row["corporate_action_status"] == "unresolved"
                or row["missingness_status"] == "unresolved"
            ):
                readiness_issues.append(
                    f"{row['stock_code']}:{row['requirement_profile']} ready despite unresolved evidence"
                )
            if row["requirement_profile"] == "AMOUNT_FACTOR_V1" and row["readiness_status"] == "ready":
                readiness_issues.append(f"{row['stock_code']}: amount profile was improperly released")
            if row["requirement_profile"] == "EXECUTION_REFERENCE_V1" and row["readiness_status"] != "rejected":
                readiness_issues.append(f"{row['stock_code']}: execution reference is not rejected")
            if "NET" in row["requirement_profile"].upper() and row["readiness_status"] == "ready":
                readiness_issues.append(f"{row['stock_code']}: net-return profile was improperly released")
            if return_profile and row["readiness_status"] == "ready":
                ready_codes.add(row["stock_code"])
        for code in codes:
            profiles = {row["requirement_profile"] for row in readiness_summary.get(code, [])}
            for required_profile in ("OHLCV_RETURN_V1", "AMOUNT_FACTOR_V1", "EXECUTION_REFERENCE_V1"):
                if required_profile not in profiles:
                    readiness_issues.append(f"{code}: missing {required_profile} authorization review")
        if readiness_issues:
            verifier_blockers.append("readiness_authorization_failure")
            p0.append("readiness_authorization_failure")

        coverage_rows = await connection.fetch(
            """
            SELECT stock_code,count(*) AS row_count
            FROM market.certified_klines
            WHERE stock_code=ANY($1::varchar[]) AND period='1d' AND adjustment='raw'
              AND trading_date BETWEEN $2 AND $3
            GROUP BY stock_code
            """,
            list(ready_codes),
            START,
            END,
        ) if ready_codes else []
        ready_coverages: list[float] = []
        scoped_ready_row_count = 0
        for row in coverage_rows:
            expected = await connection.fetchval(
                """
                SELECT count(*) FROM market.trading_calendar
                WHERE exchange=$1 AND trading_date BETWEEN $2 AND $3
                  AND is_trading_day AND status='confirmed'
                """,
                row["stock_code"].split(".")[1],
                START,
                END,
            )
            coverage = row["row_count"] / expected if expected else 0.0
            ready_coverages.append(coverage)
            scoped_ready_row_count += row["row_count"]

        lock_names = [
            "CERTIFIED_BACKTEST_EXECUTION_ENABLED",
            "CERTIFIED_SCREENER_OUTPUT_ENABLED",
            "TRADING_EXECUTION_ENABLED",
            "LIVE_TRADING_ENABLED",
            "AI_ORDER_ENABLED",
            "ALLOW_SCHEDULED_ORDER",
        ]
        locks = {name: os.environ.get(name, "").lower() for name in lock_names}
        if any(value != "false" for value in locks.values()):
            verifier_blockers.append("release_lock_enabled")
            p0.append("release_lock_enabled")
        orders_created = await connection.fetchval(
            "SELECT count(*) FROM trade.orders WHERE created_at >= $1", run["started_at"]
        ) if run else 0
        if orders_created:
            verifier_blockers.append("orders_created_during_dataset_expansion")
            p0.append("orders_created_during_dataset_expansion")
        candidate_tables = await connection.fetch(
            """
            SELECT table_schema,table_name
            FROM information_schema.tables
            WHERE table_schema IN ('market','trade') AND table_name ILIKE '%candidate%'
            ORDER BY table_schema,table_name
            """
        )
        candidates_created = 0
        for table in candidate_tables:
            has_created_at = await connection.fetchval(
                """
                SELECT EXISTS(
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema=$1 AND table_name=$2 AND column_name='created_at'
                )
                """,
                table["table_schema"],
                table["table_name"],
            )
            if has_created_at and run:
                candidates_created += await connection.fetchval(
                    f"SELECT count(*) FROM {table['table_schema']}.{table['table_name']} WHERE created_at >= $1",
                    run["started_at"],
                )
        if candidates_created:
            verifier_blockers.append("candidates_created_during_dataset_expansion")
            p0.append("candidates_created_during_dataset_expansion")

        gate = dataset_release_gate(
            unresolved_corporate_actions=unresolved_corporate_actions,
            unresolved_dates=unresolved_dates,
            scoped_ready_stock_count=len(ready_codes),
            scoped_ready_row_count=scoped_ready_row_count,
            ready_coverages=ready_coverages,
            p0_blockers=verifier_blockers,
            p1_blockers=[],
            dataset_hash_stable=dataset_hash_stable,
        )
        if unresolved_corporate_actions:
            p1.append("corporate_action_discovery_unresolved")
        if unresolved_dates:
            p1.append("trading_date_missingness_unresolved")
        return {
            "verifier_status": "PASS" if not gate["verifier_blockers"] else "FAIL",
            "dataset_release_status": gate["dataset_release_status"],
            "sprint13_status": "BLOCKED" if not gate["sprint14_admission"] else "READY_FOR_ADMISSION_REVIEW",
            "sprint14_admission": gate["sprint14_admission"],
            "manifest_hash": manifest_hash,
            "run_manifest_match": binding_match,
            "run_manifest_mismatches": binding_mismatches,
            "dataset_hash": dataset_hash,
            "dataset_row_count": len(certified_rows),
            "snapshots": await snapshots(connection, run["started_at"]) if run else {},
            "existing_data_validation": {
                "validation_failed_checkpoints": checkpoint_states.get("validation_failed", 0),
                "content_validation_hashes": sum(
                    row["content_validation_hash"] is not None for row in checkpoint_rows
                ),
            },
            "checkpoint_state_summary": checkpoint_states,
            "checkpoint_issues": checkpoint_issues,
            "retry_summary": {
                "total_attempts": sum(row["attempt_count"] for row in checkpoint_rows),
                "max_attempt_count": max((row["attempt_count"] for row in checkpoint_rows), default=0),
            },
            "provider_validation_by_stock": provider_summary,
            "secondary_provider_certified_store_rows": secondary_written,
            "security_status_summary": security_summary,
            "missing_date_summary": date_summary,
            "corporate_action_summary": corporate_summary,
            "readiness_summary": readiness_summary,
            "readiness_issues": readiness_issues,
            "scoped_ready_stock_count": len(ready_codes),
            "scoped_ready_row_count": scoped_ready_row_count,
            "ready_coverages": ready_coverages,
            "release_lock_status": locks,
            "orders_created": orders_created,
            "candidates_created": candidates_created,
            "candidate_audit_tables": [
                f"{table['table_schema']}.{table['table_name']}" for table in candidate_tables
            ],
            "verifier_blockers": gate["verifier_blockers"],
            "P0": sorted(set(p0)),
            "P1": sorted(set(p1)),
            "P2": [],
        }
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-hash-stable", choices=("true", "false"), default="true")
    args = parser.parse_args()
    result = asyncio.run(inspection(args.dataset_hash_stable == "true"))
    print("S13_INSPECTION=" + json.dumps(result, ensure_ascii=False, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
