from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

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
from app.data.research_profiles import ResearchDataRequirementProfile  # noqa: E402
from app.data.sohu_daily_importer import ProviderFetchResult, SohuDailyKlineImporter  # noqa: E402
from app.db import get_db  # noqa: E402

MANIFEST_PATH = ROOT / "config" / "datasets" / "sprint13_universe.yaml"
DATE_FROM = date(2025, 7, 1)
DATE_TO = date(2026, 6, 30)
RUN_ID = "sprint13-controlled-certified-v1-run1"
TENCENT_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def months():
    current = DATE_FROM.replace(day=1)
    while current <= DATE_TO:
        yield current
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)


def month_end(start: date) -> date:
    following = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    from datetime import timedelta
    return min(DATE_TO, following - timedelta(days=1))


async def existing_count(db, code: str, start: date, end: date) -> int:
    result = await db.execute(text("""
      SELECT COUNT(*) FROM market.certified_klines
       WHERE stock_code=:code AND period='1d' AND adjustment='raw'
         AND trading_date BETWEEN :start AND :end
    """), {"code": code, "start": start, "end": end})
    return int(result.scalar() or 0)


async def expected_count(db, exchange: str, start: date, end: date) -> int:
    result = await db.execute(text("""
      SELECT COUNT(*) FROM market.trading_calendar
       WHERE exchange=:exchange AND trading_date BETWEEN :start AND :end
         AND is_trading_day AND status='confirmed'
    """), {"exchange": exchange, "start": start, "end": end})
    return int(result.scalar() or 0)


async def checkpoint(db, code, month, status, *, batch_id=None, fetched=0, certified=0, error=None):
    await db.execute(text("""
      INSERT INTO market.dataset_import_checkpoints
        (run_id,stock_code,month_start,batch_id,status,attempt_count,rows_fetched,rows_certified,error_reason,updated_at)
      VALUES (:run,:code,:month,:batch,:status,1,:fetched,:certified,:error,NOW())
      ON CONFLICT(run_id,stock_code,month_start) DO UPDATE SET
        batch_id=EXCLUDED.batch_id,status=EXCLUDED.status,
        attempt_count=market.dataset_import_checkpoints.attempt_count+1,
        rows_fetched=EXCLUDED.rows_fetched,rows_certified=EXCLUDED.rows_certified,
        error_reason=EXCLUDED.error_reason,updated_at=NOW()
    """), {"run": RUN_ID, "code": code, "month": month, "batch": batch_id,
             "status": status, "fetched": fetched, "certified": certified, "error": error})


async def fetch_tencent(client: httpx.AsyncClient, code: str):
    prefix = code.split(".")[1].lower() + code.split(".")[0]
    rows = {}
    for year in (2025, 2026):
        response = await client.get(TENCENT_ENDPOINT, params={"param": f"{prefix},day,{year}-01-01,{year}-12-31,640,"})
        response.raise_for_status()
        raw = response.json()["data"][prefix]["day"]
        for item in raw:
            day = date.fromisoformat(item[0])
            if DATE_FROM <= day <= DATE_TO:
                rows[day] = {"open": float(item[1]), "close": float(item[2]), "high": float(item[3]), "low": float(item[4])}
    return rows


async def audit_stock(code: str, manifest_stock: dict, primary_rows: list[dict], secondary: dict):
    primary = {row["trading_date"]: row for row in primary_rows}
    common = sorted(set(primary) & set(secondary))
    samples = []
    for month in months():
        candidates = [day for day in common if day.year == month.year and day.month == month.month]
        if candidates:
            samples.append(candidates[len(candidates) // 2])
    async with get_db() as db:
        for day in samples:
            fields = {}
            result = "PASS"
            for field in ("open", "high", "low", "close"):
                left, right = float(primary[day][field]), float(secondary[day][field])
                absolute = abs(left - right)
                relative = absolute / abs(right) if right else None
                passed = absolute <= 0.01
                if not passed:
                    result = "FAIL"
                fields[field] = {"primary": left, "secondary": right, "absolute_difference": absolute,
                                 "relative_difference": relative, "tolerance": "abs<=0.01 CNY", "passed": passed}
            await db.execute(text("""
              INSERT INTO market.provider_validation_reviews
                (run_id,stock_code,trading_date,primary_provider,secondary_provider,result,comparison,endpoint_versions,reviewed_at)
              VALUES (:run,:code,:day,'sohu','tencent',:result,CAST(:comparison AS jsonb),CAST(:versions AS jsonb),NOW())
              ON CONFLICT(run_id,stock_code,trading_date) DO UPDATE SET
                result=EXCLUDED.result,comparison=EXCLUDED.comparison,reviewed_at=NOW()
            """), {"run": RUN_ID, "code": code, "day": day, "result": result,
                     "comparison": json.dumps({"fields": fields, "volume": "not_compared", "amount": "unresolved"}),
                     "versions": json.dumps({"primary": SohuDailyKlineImporter.IMPORTER_VERSION,
                                              "secondary": "tencent-fqkline-raw-v1", "endpoint": TENCENT_ENDPOINT})})
        await db.execute(text("""
          INSERT INTO market.security_status_reviews
            (run_id,stock_code,effective_from,effective_to,status,evidence_source,evidence_version,reviewed_at)
          VALUES (:run,:code,:start,:end,'normal_trade',:source,'sprint13-manifest-freeze-v1',NOW())
          ON CONFLICT DO NOTHING
        """), {"run": RUN_ID, "code": code, "start": DATE_FROM, "end": DATE_TO,
                 "source": "SSE/SZSE official ordinary-share lists recorded in frozen manifest"})
        calendar = (await db.execute(text("""
          SELECT trading_date,is_trading_day,source_reference FROM market.trading_calendar
           WHERE exchange=:exchange AND trading_date BETWEEN :start AND :end ORDER BY trading_date
        """), {"exchange": code.split('.')[1], "start": DATE_FROM, "end": DATE_TO})).all()
        for day, is_open, source in calendar:
            status = "exchange_closed" if not is_open else ("normal_trade" if day in primary else "unresolved")
            await db.execute(text("""
              INSERT INTO market.research_date_reviews
                (date_review_id,dataset_scope,stock_code,trading_date,status,evidence_source,evidence_time,reason,reviewer_version,reviewed_at)
              VALUES (:id,:scope,:code,:day,:status,:source,NOW(),:reason,'sprint13-controlled-expansion-v1',NOW())
              ON CONFLICT(dataset_scope,stock_code,trading_date) DO UPDATE SET
                status=EXCLUDED.status,evidence_source=EXCLUDED.evidence_source,reason=EXCLUDED.reason,reviewed_at=NOW()
            """), {"id": f"s13-{code.replace('.','')}-{day:%Y%m%d}", "scope": RUN_ID,
                     "code": code, "day": day, "status": status, "source": source,
                     "reason": "official calendar closed" if not is_open else ("certified provider bar exists" if day in primary else "trading day missing; suspension versus provider missing unresolved")})
        event_id = f"s13-ca-{code.replace('.','')}-discovery"
        await db.execute(text("""
          INSERT INTO market.corporate_action_reviews
            (event_id,stock_code,event_type,source,verification_status,evidence,reviewer_version,reviewed_at)
          VALUES (:id,:code,'discovery_review',:source,'unresolved',CAST(:evidence AS jsonb),'sprint13-controlled-expansion-v1',NOW())
          ON CONFLICT(event_id) DO UPDATE SET evidence=EXCLUDED.evidence,reviewed_at=NOW()
        """), {"id": event_id, "code": code,
                 "source": f"https://www.cninfo.com.cn/new/fulltextSearch?keyWord={code.split('.')[0]}",
                 "evidence": json.dumps({"status": "official announcement discovery requires event-level evidence review",
                                          "target_range": f"{DATE_FROM}/{DATE_TO}"})})
        unresolved = any(is_open and day not in primary for day, is_open, _ in calendar)
        provider_pass = len(samples) == 12 and all(
            max(abs(float(primary[d][f]) - secondary[d][f]) for f in ("open","high","low","close")) <= 0.01
            for d in samples
        )
        ohlcv = ResearchDataRequirementProfile.get("OHLCV_RETURN_V1")
        amount = ResearchDataRequirementProfile.get("AMOUNT_FACTOR_V1")
        execution = ResearchDataRequirementProfile.get("EXECUTION_REFERENCE_V1")
        reviews = [
            ("OHLCV_RETURN_V1", "return_backtest", "review_required", ohlcv.required_fields,
             list(ohlcv.required_fields), [], ["corporate_action_status"]),
            ("AMOUNT_FACTOR_V1", "return_backtest", "review_required", amount.required_fields,
             list(ohlcv.required_fields), ["amount_provider_validation"], []),
            ("EXECUTION_REFERENCE_V1", "execution_reference", "rejected", execution.required_fields,
             ["execution_gate"], [], ["quote_time","price_applicability","explicit_authorization"]),
        ]
        for profile, scope, status, required, validated, unresolved_fields, rejected in reviews:
            await db.execute(text("""
              INSERT INTO market.research_readiness_reviews
                (review_id,stock_code,period,date_from,date_to,adjustment,readiness_status,research_use_scope,
                 corporate_action_status,missingness_status,provider_validation_status,review_reason,evidence,
                 reviewer_version,reviewed_at,requirement_profile,required_fields,validated_fields,
                 unresolved_fields,rejected_fields,policy_version)
              VALUES (:id,:code,'1d',:start,:end,'raw',:status,:scope,'unresolved',:missing,
                :provider_status,:reason,CAST(:evidence AS jsonb),'sprint13-controlled-expansion-v1',NOW(),
                :profile,CAST(:required AS jsonb),CAST(:validated AS jsonb),CAST(:unresolved_fields AS jsonb),
                CAST(:rejected AS jsonb),'field-readiness-v1')
              ON CONFLICT(stock_code,period,date_from,date_to,adjustment,research_use_scope,requirement_profile)
              DO UPDATE SET readiness_status=EXCLUDED.readiness_status,corporate_action_status=EXCLUDED.corporate_action_status,
                missingness_status=EXCLUDED.missingness_status,provider_validation_status=EXCLUDED.provider_validation_status,
                review_reason=EXCLUDED.review_reason,evidence=EXCLUDED.evidence,reviewed_at=NOW(),
                validated_fields=EXCLUDED.validated_fields,unresolved_fields=EXCLUDED.unresolved_fields,
                rejected_fields=EXCLUDED.rejected_fields
            """), {"id": f"s13-{code.replace('.','')}-{profile.lower()}", "code": code,
                     "start": DATE_FROM, "end": DATE_TO, "status": status, "scope": scope,
                     "missing": "unresolved" if unresolved else "complete",
                     "provider_status": "pass" if provider_pass else "partial_pass",
                     "reason": "Corporate-action discovery is unresolved; fail closed for return research." if scope == "return_backtest" else "Execution reference remains unauthorized.",
                     "evidence": json.dumps({"samples": len(samples), "amount": "unresolved", "corporate_actions": "unresolved"}),
                     "profile": profile, "required": json.dumps(required), "validated": json.dumps(validated),
                     "unresolved_fields": json.dumps(unresolved_fields), "rejected": json.dumps(rejected)})


async def run():
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = yaml.safe_load(manifest_bytes)
    if not manifest["frozen"] or len(manifest["stocks"]) != 10:
        raise ValueError("Sprint13 manifest must be frozen with exactly 10 stocks")
    async with get_db() as db:
        await db.execute(text("""
          INSERT INTO market.dataset_expansion_runs
            (run_id,dataset_id,manifest_hash,primary_provider,secondary_provider,date_from,date_to,status,started_at)
          VALUES (:run,:dataset,:hash,'sohu','tencent',:start,:end,'running',NOW())
          ON CONFLICT(run_id) DO UPDATE SET status='running',failure_reason=NULL
        """), {"run": RUN_ID, "dataset": manifest["dataset_id"],
                 "hash": hashlib.sha256(manifest_bytes).hexdigest(), "start": DATE_FROM, "end": DATE_TO})
    importer = SohuDailyKlineImporter()
    secondary_client = httpx.AsyncClient(timeout=30, trust_env=False)
    outcomes = []
    try:
        for stock in manifest["stocks"]:
            code = stock["stock_code"]
            secondary = await fetch_tencent(secondary_client, code)
            all_primary = []
            try:
                fetched_all = await importer.fetch(code, DATE_FROM, DATE_TO)
            except Exception as exc:
                async with get_db() as db:
                    for month in months():
                        await checkpoint(db, code, month, "fetch_failed", error=str(exc))
                outcomes.extend(
                    {"stock_code": code, "month": str(month), "status": "fetch_failed", "rows": 0, "reason": str(exc)}
                    for month in months()
                )
                continue
            for month in months():
                end = month_end(month)
                monthly_rows = [row for row in fetched_all.rows if month <= row["trading_date"] <= end]
                async with get_db() as db:
                    expected = await expected_count(db, code.split('.')[1], month, end)
                    existing = await existing_count(db, code, month, end)
                    if existing and existing == len(monthly_rows):
                        rows = (await db.execute(text("SELECT trading_date,open,high,low,close FROM market.certified_klines WHERE stock_code=:code AND trading_date BETWEEN :start AND :end ORDER BY trading_date"), {"code": code,"start": month,"end": end})).mappings().all()
                        all_primary.extend(dict(row) for row in rows)
                        state = "certified" if existing == expected else "review_required"
                        reason = None if state == "certified" else "provider month is incomplete against certified calendar"
                        await checkpoint(db, code, month, state, fetched=existing, certified=existing, error=reason)
                        outcomes.append({"stock_code": code,"month": str(month),"status":f"{state}_existing","rows":existing,"reason":reason})
                        continue
                try:
                    fetched = ProviderFetchResult(
                        stock_code=fetched_all.stock_code, provider=fetched_all.provider,
                        source=fetched_all.source, provider_priority=fetched_all.provider_priority,
                        fallback_used=False, fetch_url_or_endpoint=fetched_all.fetch_url_or_endpoint,
                        fetch_time=fetched_all.fetch_time, raw_hash=fetched_all.raw_hash,
                        rows=monthly_rows,
                    )
                    if not monthly_rows:
                        raise ValueError("primary provider returned no rows for month")
                    all_primary.extend(fetched.rows)
                    async with get_db() as db:
                        result = await CertifiedStoreWriter().ingest(db, fetched)
                        await checkpoint(db, code, month, result.status, batch_id=result.batch_id,
                                         fetched=result.total_rows, certified=result.accepted_rows, error=result.reject_reason)
                    outcomes.append({"stock_code":code,"month":str(month),"status":result.status,"rows":result.accepted_rows,"reason":result.reject_reason})
                except Exception as exc:
                    async with get_db() as db:
                        await checkpoint(db, code, month, "fetch_failed", error=str(exc))
                    outcomes.append({"stock_code":code,"month":str(month),"status":"fetch_failed","rows":0,"reason":str(exc)})
            await audit_stock(code, stock, all_primary, secondary)
        async with get_db() as db:
            await db.execute(text("UPDATE market.dataset_expansion_runs SET status='review_required',completed_at=NOW() WHERE run_id=:run"), {"run": RUN_ID})
    finally:
        await importer.close()
        await secondary_client.aclose()
    print(json.dumps({"run_id":RUN_ID,"outcomes":outcomes}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    asyncio.run(run())
