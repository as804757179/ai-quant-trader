from datetime import UTC, datetime

from sqlalchemy import text

from app.core.config import settings
from app.db import get_db
from app.risk.fuse import FuseManager
from app.risk.monitor import RiskMonitor
from app.data.cache import CacheManager


class PortfolioService:
    async def get_summary(self, mode: str | None = None) -> dict:
        mode = mode or settings.TRADE_MODE
        cache = CacheManager()

        async with get_db() as db:
            await self._set_read_only(db)
            monitor = RiskMonitor(db)
            snapshot = await monitor.get_portfolio_snapshot(mode)
            fuse_mgr = FuseManager(db, cache)
            is_fused = await fuse_mgr.is_fused(mode)

        return {
            "mode": mode,
            "account_record_id": snapshot["account_record_id"],
            "snapshot_time": snapshot["snapshot_time"],
            "account_snapshot_time": snapshot["account_snapshot_time"],
            "account_snapshot_age_seconds": snapshot["account_snapshot_age_seconds"],
            "account_snapshot_freshness": snapshot["account_snapshot_freshness"],
            "total_assets": snapshot["total_assets"],
            "cash": snapshot["cash"],
            "market_value": snapshot["total_market_value"],
            "daily_pnl": snapshot["daily_pnl"],
            "daily_pnl_pct": snapshot["daily_pnl_pct"],
            "drawdown_from_peak": snapshot["drawdown_from_peak"],
            "position_count": len(snapshot["positions"]),
            "position_ratio": (
                snapshot["total_market_value"] / snapshot["total_assets"]
                if snapshot["total_market_value"] is not None
                and snapshot["total_assets"] is not None
                and snapshot["total_assets"] > 0
                else None
            ),
            "is_fused": is_fused,
            "valuation_status": snapshot["valuation_status"],
            "valuation_stale": snapshot["valuation_stale"],
            "valuation_freshness": snapshot["valuation_freshness"],
            "valuation_as_of": snapshot["valuation_as_of"],
            "valuation_age_seconds": snapshot["valuation_age_seconds"],
            "valuation_unavailable_positions": snapshot[
                "valuation_unavailable_positions"
            ],
            "valuation_source": snapshot["valuation_source"],
            "source": snapshot["source"],
            "source_version": snapshot["source_version"],
        }

    async def get_equity_curve(self, mode: str, days: int) -> dict:
        async with get_db() as db:
            await self._set_read_only(db)
            result = await db.execute(
                text(
                    """
                    WITH daily AS (
                        SELECT DISTINCT ON (
                            (record_time AT TIME ZONE 'Asia/Shanghai')::date
                        )
                            id, record_time, total_assets, cash, market_value,
                            daily_pnl, total_pnl, total_pnl_pct, position_count,
                            position_ratio, data_type
                        FROM trade.account_records
                        WHERE mode = :mode
                          AND record_time >= NOW() - make_interval(days => :days)
                        ORDER BY
                            (record_time AT TIME ZONE 'Asia/Shanghai')::date,
                            record_time DESC
                    )
                    SELECT * FROM daily ORDER BY record_time
                    """
                ),
                {"mode": mode, "days": int(days)},
            )
            rows = [dict(row) for row in result.mappings().all()]

        now = datetime.now(UTC)
        numeric_fields = (
            "total_assets",
            "cash",
            "market_value",
            "daily_pnl",
            "total_pnl",
            "total_pnl_pct",
            "position_ratio",
        )
        for row in rows:
            record_time = self._as_utc(row.get("record_time"))
            row["record_time"] = record_time.isoformat() if record_time else None
            row["valuation_status"] = (
                "recorded_snapshot" if record_time else "unavailable"
            )
            row["valuation_freshness"] = (
                "historical_record" if record_time else "stale_or_missing"
            )
            row["valuation_stale"] = True
            row["valuation_as_of"] = row["record_time"]
            row["valuation_age_seconds"] = self._age_seconds(record_time, now)
            row["valuation_source"] = {
                "table": "trade.account_records",
                "record_id": str(row["id"]) if row.get("id") is not None else None,
                "data_type": row.get("data_type"),
            }
            for field in numeric_fields:
                if row.get(field) is not None:
                    row[field] = float(row[field])

        latest = rows[-1] if rows else None
        latest_is_snapshot = bool(
            latest and latest.get("valuation_status") == "recorded_snapshot"
        )
        return {
            "mode": mode,
            "days": days,
            "items": rows,
            "total": len(rows),
            "latest_at": rows[-1]["record_time"] if rows else None,
            "source": "trade.account_records",
            "source_version": "account-equity-curve-v3",
            "valuation_status": (
                "historical_record" if latest_is_snapshot else "unavailable"
            ),
            "valuation_stale": True,
            "valuation_freshness": (
                "historical_record" if latest_is_snapshot else "stale_or_missing"
            ),
            "valuation_as_of": latest.get("valuation_as_of") if latest else None,
            "valuation_age_seconds": (
                latest.get("valuation_age_seconds") if latest else None
            ),
            "valuation_source": {
                "table": "trade.account_records",
                "record_count": len(rows),
                "latest_record_id": (
                    str(latest["id"])
                    if latest and latest.get("id") is not None
                    else None
                ),
            },
        }

    async def get_positions(self, mode: str | None = None) -> list[dict]:
        mode = mode or settings.TRADE_MODE
        freshness_threshold = max(60, int(settings.DATA_CACHE_TTL_QUOTE) * 3)
        async with get_db() as db:
            await self._set_read_only(db)
            result = await db.execute(
                text(
                    """
                    SELECT p.*, s.name, s.sector,
                           quote.price AS observed_price,
                           quote.quote_time, quote.provider AS quote_provider,
                           quote.source AS quote_source, quote.raw_hash AS quote_raw_hash,
                           quote.received_at AS quote_received_at, quote.batch_id AS quote_batch_id
                    FROM trade.positions AS p
                    LEFT JOIN fundamental.stocks AS s ON p.stock_code = s.code
                    LEFT JOIN LATERAL (
                        SELECT q.price, q.time AS quote_time,
                               provenance.provider, provenance.source,
                               provenance.raw_hash, provenance.received_at,
                               batch.batch_id::text AS batch_id
                        FROM market.quotes AS q
                        INNER JOIN market.quote_provenance AS provenance
                            ON provenance.stock_code = q.stock_code
                           AND provenance.quote_time = q.time
                        INNER JOIN market.quote_batches AS batch
                            ON batch.batch_id = provenance.batch_id
                        WHERE provenance.quality_status = 'pass'
                          AND provenance.fallback_used = FALSE
                          AND batch.status IN ('success', 'partial')
                          AND q.price > 0
                          AND q.stock_code = p.stock_code
                        ORDER BY q.time DESC
                        LIMIT 1
                    ) AS quote ON TRUE
                    WHERE p.mode = :mode
                    ORDER BY p.market_value DESC NULLS LAST
                    """
                ),
                {"mode": mode},
            )
            rows = [dict(row) for row in result.mappings().all()]

        now = datetime.now(UTC)
        for row in rows:
            qty = int(row.get("total_qty") or 0)
            avg_cost = float(row.get("avg_cost") or 0)
            observed_price = row.pop("observed_price", None)
            quote_time = self._as_utc(row.pop("quote_time", None))
            quote_provider = row.pop("quote_provider", None)
            quote_source = row.pop("quote_source", None)
            quote_raw_hash = row.pop("quote_raw_hash", None)
            quote_received_at = self._as_utc(row.pop("quote_received_at", None))
            quote_batch_id = row.pop("quote_batch_id", None)
            quote_age_seconds: int | None = None
            if quote_time is not None:
                quote_age_seconds = self._age_seconds(quote_time, now)
            is_fresh = (
                observed_price is not None
                and quote_age_seconds is not None
                and quote_age_seconds <= freshness_threshold
                and quote_time <= now
            )
            observed_value = float(observed_price) if observed_price is not None else None
            row["cost_basis"] = avg_cost if avg_cost > 0 else None
            row["cost_basis_value"] = avg_cost * qty if avg_cost > 0 else None
            row["recorded_market_value"] = self._as_float(row.get("market_value"))
            row["recorded_current_price"] = self._as_float(row.get("current_price"))
            row["current_price"] = observed_value if is_fresh else None
            row["market_value"] = observed_value * qty if is_fresh else None
            row["unrealized_pnl"] = (
                (observed_value - avg_cost) * qty if is_fresh and avg_cost > 0 else None
            )
            row["unrealized_pnl_pct"] = (
                (observed_value / avg_cost - 1) * 100
                if is_fresh and avg_cost > 0
                else None
            )
            row["valuation_status"] = "observed" if is_fresh else "unavailable"
            row["valuation_stale"] = not is_fresh
            row["valuation_freshness"] = "fresh" if is_fresh else "stale_or_missing"
            row["valuation_as_of"] = (
                quote_time.isoformat() if quote_time else None
            )
            row["valuation_age_seconds"] = quote_age_seconds
            row["valuation_source"] = (
                {
                    "provider": quote_provider,
                    "source": quote_source,
                    "raw_hash": quote_raw_hash,
                    "received_at": (
                        quote_received_at.isoformat()
                        if quote_received_at
                        else None
                    ),
                    "batch_id": quote_batch_id,
                    "freshness_threshold_seconds": freshness_threshold,
                }
                if quote_time
                else None
            )
            row["price_source"] = "observed_quote" if is_fresh else "unavailable"
            for key, value in list(row.items()):
                if hasattr(value, "as_tuple"):
                    row[key] = float(value)
                elif hasattr(value, "isoformat"):
                    row[key] = value.isoformat()
        return rows

    @staticmethod
    def _as_float(value: object) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    async def _set_read_only(db) -> None:
        await db.execute(text("SET TRANSACTION READ ONLY"))

    @staticmethod
    def _as_utc(value: object) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _age_seconds(value: datetime | None, now: datetime) -> int | None:
        if value is None:
            return None
        return max(0, int((now - value).total_seconds()))
