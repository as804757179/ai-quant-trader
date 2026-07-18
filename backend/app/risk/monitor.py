from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


class RiskMonitor:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_portfolio_snapshot(self, mode: str) -> dict[str, Any]:
        account_result = await self.db.execute(
            text(
                """
                SELECT * FROM trade.account_records
                WHERE mode = :mode
                ORDER BY record_time DESC
                LIMIT 1
                """
            ),
            {"mode": mode},
        )
        account = account_result.mappings().first()

        positions_result = await self.db.execute(
            text(
                """
                WITH latest_observed_quote AS (
                    SELECT DISTINCT ON (q.stock_code)
                           q.stock_code, q.price, q.time AS quote_time,
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
                    ORDER BY q.stock_code, q.time DESC
                )
                SELECT p.*, s.name, s.sector,
                       quote.price AS observed_price,
                       quote.quote_time, quote.provider AS quote_provider,
                       quote.source AS quote_source, quote.raw_hash AS quote_raw_hash,
                       quote.received_at AS quote_received_at, quote.batch_id AS quote_batch_id
                FROM trade.positions AS p
                LEFT JOIN fundamental.stocks AS s ON p.stock_code = s.code
                LEFT JOIN latest_observed_quote AS quote ON quote.stock_code = p.stock_code
                WHERE p.mode = :mode
                ORDER BY p.stock_code
                """
            ),
            {"mode": mode},
        )
        position_rows = positions_result.mappings().all()

        peak_result = await self.db.execute(
            text(
                """
                SELECT MAX(total_assets) AS peak
                FROM trade.account_records
                WHERE mode = :mode
                """
            ),
            {"mode": mode},
        )
        peak_row = peak_result.mappings().first()

        now = datetime.now(UTC)
        freshness_seconds = max(60, int(settings.DATA_CACHE_TTL_QUOTE) * 3)
        account_time = self._as_utc(account.get("record_time") if account else None)
        account_age_seconds = self._age_seconds(account_time, now)
        account_fresh = (
            account is not None
            and account_age_seconds is not None
            and account_age_seconds <= freshness_seconds
        )

        positions: dict[str, dict[str, Any]] = {}
        valued_market_value = 0.0
        quote_times: list[datetime] = []
        unavailable_positions: list[str] = []

        for raw_position in position_rows:
            position = dict(raw_position)
            stock_code = str(position["stock_code"])
            quantity = int(position.get("total_qty") or 0)
            average_cost = self._as_float(position.get("avg_cost"))
            observed_price = self._as_float(position.pop("observed_price", None))
            quote_time = self._as_utc(position.pop("quote_time", None))
            quote_provider = position.pop("quote_provider", None)
            quote_source = position.pop("quote_source", None)
            quote_raw_hash = position.pop("quote_raw_hash", None)
            quote_received_at = self._as_utc(position.pop("quote_received_at", None))
            quote_batch_id = position.pop("quote_batch_id", None)
            quote_age_seconds = self._age_seconds(quote_time, now)
            quote_fresh = (
                observed_price is not None
                and quote_age_seconds is not None
                and quote_age_seconds <= freshness_seconds
            )

            position["cost_basis"] = average_cost if average_cost and average_cost > 0 else None
            position["cost_basis_value"] = (
                average_cost * quantity if average_cost and average_cost > 0 else None
            )
            position["recorded_current_price"] = self._as_float(
                position.get("current_price")
            )
            position["recorded_market_value"] = self._as_float(
                position.get("market_value")
            )
            position["current_price"] = observed_price if quote_fresh else None
            position["market_value"] = (
                observed_price * quantity if quote_fresh else None
            )
            position["unrealized_pnl"] = (
                (observed_price - average_cost) * quantity
                if quote_fresh and average_cost and average_cost > 0
                else None
            )
            position["unrealized_pnl_pct"] = (
                (observed_price / average_cost - 1) * 100
                if quote_fresh and average_cost and average_cost > 0
                else None
            )
            position["valuation_status"] = "observed" if quote_fresh else "unavailable"
            position["valuation_stale"] = not quote_fresh
            position["valuation_freshness"] = (
                "fresh" if quote_fresh else "stale_or_missing"
            )
            position["valuation_as_of"] = (
                quote_time.isoformat() if quote_time else None
            )
            position["valuation_age_seconds"] = quote_age_seconds
            position["valuation_source"] = (
                {
                    "provider": quote_provider,
                    "source": quote_source,
                    "raw_hash": quote_raw_hash,
                    "received_at": (
                        quote_received_at.isoformat() if quote_received_at else None
                    ),
                    "batch_id": quote_batch_id,
                }
                if quote_time
                else None
            )
            position["price_source"] = "observed_quote" if quote_fresh else "unavailable"
            positions[stock_code] = self._serialize(position)

            if quantity <= 0:
                continue
            if quote_fresh:
                valued_market_value += observed_price * quantity
                quote_times.append(quote_time)
            else:
                unavailable_positions.append(stock_code)

        cash = self._as_float(account.get("cash") if account else None)
        valuation_available = (
            account_fresh and cash is not None and not unavailable_positions
        )
        total_market_value = valued_market_value if valuation_available else None
        total_assets = (
            cash + valued_market_value
            if valuation_available and cash is not None
            else None
        )
        daily_pnl = (
            self._as_float(account.get("daily_pnl"))
            if valuation_available and account
            else None
        )
        peak = self._as_float(peak_row.get("peak") if peak_row else None)
        if total_assets is not None and peak is not None:
            peak = max(peak, total_assets)
        drawdown = (
            (total_assets - peak) / peak
            if total_assets is not None and peak and peak > 0
            else None
        )
        daily_pnl_pct = (
            daily_pnl / total_assets
            if daily_pnl is not None and total_assets is not None and total_assets > 0
            else 0.0
            if total_assets == 0
            else None
        )

        valuation_times = [account_time, *quote_times] if valuation_available else []
        valuation_as_of = min(valuation_times).isoformat() if valuation_times else None
        valuation_age_seconds = (
            max(self._age_seconds(value, now) or 0 for value in valuation_times)
            if valuation_times
            else None
        )
        valuation_status = (
            "cash_only" if valuation_available and not quote_times else "observed"
            if valuation_available
            else "unavailable"
        )

        return {
            "account_record_id": account.get("id") if account else None,
            "snapshot_time": account_time.isoformat() if account_time else None,
            "account_snapshot_time": account_time.isoformat() if account_time else None,
            "account_snapshot_age_seconds": account_age_seconds,
            "account_snapshot_freshness": (
                "fresh" if account_fresh else "stale_or_missing"
            ),
            "recorded_cash": cash,
            "total_assets": total_assets,
            "cash": cash if valuation_available else None,
            "total_market_value": total_market_value,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "drawdown_from_peak": drawdown,
            "positions": positions,
            "valuation_status": valuation_status,
            "valuation_stale": not valuation_available,
            "valuation_freshness": (
                "fresh" if valuation_available else "stale_or_missing"
            ),
            "valuation_as_of": valuation_as_of,
            "valuation_age_seconds": valuation_age_seconds,
            "valuation_unavailable_positions": unavailable_positions,
            "valuation_source": {
                "account_record_id": str(account["id"]) if account else None,
                "quote_count": len(quote_times),
                "freshness_threshold_seconds": freshness_seconds,
            },
            "source": "trade.account_records + market.quotes + market.quote_provenance + market.quote_batches",
            "source_version": "portfolio-risk-valuation-v3",
        }

    @staticmethod
    def _as_float(value: object) -> float | None:
        return float(value) if value is not None else None

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

    @classmethod
    def _serialize(cls, value: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, item in value.items():
            if hasattr(item, "as_tuple"):
                output[key] = float(item)
            elif isinstance(item, datetime):
                output[key] = cls._as_utc(item).isoformat()
            else:
                output[key] = item
        return output
