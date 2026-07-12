from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text

from app.db import get_db


@dataclass(frozen=True)
class CorporateActionEvent:
    action_id: str
    stock_code: str
    event_type: str
    announcement_date: date
    record_date: date
    ex_date: date
    cash_payment_date: date
    share_credit_date: date
    cash_dividend_per_10: Decimal
    share_increase_per_10: Decimal
    source_name: str
    source_reference: str
    evidence_hash: str
    captured_at: datetime
    event_version: str
    verification_status: str


@dataclass(frozen=True)
class CorporateActionEntitlement:
    action_id: str
    eligible_quantity: int
    share_increase: int
    gross_cash_dividend: Decimal


class CorporateActionRepository:
    async def visible_events(self, stock_code: str, as_of: date) -> list[CorporateActionEvent]:
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT action_id, stock_code, event_type, announcement_date, record_date,
                           ex_date, cash_payment_date, share_credit_date,
                           cash_dividend_per_10, share_increase_per_10, source_name,
                           source_reference, evidence_hash, captured_at, event_version,
                           verification_status
                    FROM market.corporate_actions
                    WHERE stock_code=:stock_code AND announcement_date<=:as_of
                      AND verification_status='verified'
                    ORDER BY announcement_date, event_version
                    """
                ),
                {"stock_code": stock_code, "as_of": as_of},
            )
            return [CorporateActionEvent(**dict(row)) for row in result.mappings().all()]

    async def verified_events(self, stock_code: str, start_date: date, end_date: date) -> list[CorporateActionEvent]:
        events = await self.visible_events(stock_code, end_date)
        return [event for event in events if start_date <= event.record_date <= end_date]


class CorporateActionProcessor:
    VERSION = "corporate-action-processor-v1"
    POLICY = "GROSS_PRETAX_TOTAL_RETURN_V1"
    DAILY_ORDER = (
        "apply_due_corporate_actions",
        "release_t1_holdings",
        "execute_orders",
        "capture_record_date_entitlements",
        "close_valuation",
        "generate_signals",
        "end_of_day_audit",
    )

    @classmethod
    def validate_event(cls, event: CorporateActionEvent) -> None:
        if event.verification_status != "verified":
            raise ValueError("corporate action is not verified")
        if event.source_name in {"", "unknown"} or not event.source_reference:
            raise ValueError("corporate action source is not reproducible")
        if len(event.evidence_hash) != 64:
            raise ValueError("corporate action evidence hash is invalid")
        if not (event.announcement_date <= event.record_date <= event.ex_date):
            raise ValueError("corporate action dates are inconsistent")
        if event.cash_payment_date < event.ex_date or event.share_credit_date < event.ex_date:
            raise ValueError("corporate action payment/credit date precedes ex-date")

    @classmethod
    def calculate_entitlement(cls, event: CorporateActionEvent, eligible_quantity: int) -> CorporateActionEntitlement:
        cls.validate_event(event)
        if eligible_quantity < 0:
            raise ValueError("eligible quantity cannot be negative")
        share_value = Decimal(eligible_quantity) * event.share_increase_per_10 / Decimal("10")
        if share_value != share_value.to_integral_value():
            raise ValueError("fractional share allocation requires an explicit official allocation rule")
        return CorporateActionEntitlement(
            action_id=event.action_id,
            eligible_quantity=eligible_quantity,
            share_increase=int(share_value),
            gross_cash_dividend=(
                Decimal(eligible_quantity) * event.cash_dividend_per_10 / Decimal("10")
            ),
        )
