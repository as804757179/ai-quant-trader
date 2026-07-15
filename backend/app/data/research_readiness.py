from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text

from app.data.kline_contract import KlineContract
from app.data.research_profiles import ResearchDataRequirementProfile
from app.db import get_db


@dataclass(frozen=True)
class ReadinessDecision:
    status: str
    reasons: tuple[str, ...]


class ResearchReadinessService:
    SCOPES = {"raw_price_analysis", "return_backtest", "execution_reference"}

    @classmethod
    def evaluate(
        cls,
        *,
        certified: bool,
        metadata_complete: bool,
        adjustment: str,
        calendar_complete: bool,
        missingness_status: str,
        corporate_action_status: str,
        provider_validation_status: str,
        unexplained_major_jump: bool,
        research_use_scope: str,
        requirement_profile: str | None,
        required_fields: list[str] | tuple[str, ...] | None,
        validated_fields: list[str] | tuple[str, ...],
        unresolved_fields: list[str] | tuple[str, ...],
        rejected_fields: list[str] | tuple[str, ...],
        corporate_action_handled: bool = False,
        execution_freshness_pass: bool = False,
    ) -> ReadinessDecision:
        profile = ResearchDataRequirementProfile.get(requirement_profile)
        declared = profile.validate_declaration(
            research_use_scope=research_use_scope, required_fields=required_fields
        )
        required = set(declared)
        validated = set(validated_fields)
        unresolved = required & set(unresolved_fields)
        rejected_required = required & set(rejected_fields)
        rejected: list[str] = []
        review: list[str] = []
        if not certified:
            rejected.append("dataset is not certified")
        if not metadata_complete:
            rejected.append("provider/source/batch metadata is incomplete")
        if adjustment not in {"raw", "qfq", "hfq"}:
            rejected.append("adjustment is not explicit")
        if not calendar_complete or missingness_status != "complete":
            review.append("trading-day missingness is unresolved")
        if corporate_action_status == "unresolved":
            review.append("corporate-action review is unresolved")
        if rejected_required:
            rejected.append(
                "required fields are rejected: " + ",".join(sorted(rejected_required))
            )
        if unresolved:
            review.append(
                "required fields are unresolved: " + ",".join(sorted(unresolved))
            )
        unvalidated = required - validated - unresolved - rejected_required
        if unvalidated:
            review.append(
                "required fields are not validated: " + ",".join(sorted(unvalidated))
            )
        if provider_validation_status != "pass" and not unresolved:
            review.append("required cross-provider validation is incomplete")
        if unexplained_major_jump:
            review.append("major price jump is unexplained")
        if (
            research_use_scope == "return_backtest"
            and corporate_action_status == "event_verified"
            and not corporate_action_handled
        ):
            rejected.append("corporate action is not handled for return backtest")
        if research_use_scope == "execution_reference" and not execution_freshness_pass:
            rejected.append("execution-reference freshness is not approved")
        if rejected:
            return ReadinessDecision("rejected", tuple(rejected + review))
        if review:
            return ReadinessDecision("review_required", tuple(review))
        return ReadinessDecision("ready", ())

    async def get_review(
        self,
        stock_code: str,
        *,
        period: str,
        adjustment: str,
        research_use_scope: str,
        requirement_profile: str | None,
        required_fields: list[str] | tuple[str, ...] | None,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any] | None:
        profile = ResearchDataRequirementProfile.get(requirement_profile)
        profile.validate_declaration(
            research_use_scope=research_use_scope, required_fields=required_fields
        )
        symbol = KlineContract.canonical_symbol(stock_code)[0]
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT * FROM market.research_readiness_reviews
                    WHERE stock_code=:code AND period=:period AND adjustment=:adjustment
                      AND research_use_scope=:scope
                      AND requirement_profile=:requirement_profile
                      AND date_from<=:start_date AND date_to>=:end_date
                    ORDER BY (date_to - date_from) ASC, reviewed_at DESC LIMIT 1
                    """
                ),
                {
                    "code": symbol,
                    "period": period,
                    "adjustment": adjustment,
                    "scope": research_use_scope,
                    "requirement_profile": profile.name,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            row = result.mappings().first()
        return dict(row) if row else None

    async def assert_ready(
        self,
        stock_codes: list[str],
        *,
        period: str,
        adjustment: str,
        research_use_scope: str,
        requirement_profile: str | None,
        required_fields: list[str] | tuple[str, ...] | None,
        start_date: date,
        end_date: date,
    ) -> None:
        for stock_code in stock_codes:
            review = await self.get_review(
                stock_code,
                period=period,
                adjustment=adjustment,
                research_use_scope=research_use_scope,
                requirement_profile=requirement_profile,
                required_fields=required_fields,
                start_date=start_date,
                end_date=end_date,
            )
            if not review or review["readiness_status"] != "ready":
                raise ValueError(
                    f"research readiness gate rejected {stock_code} for {research_use_scope}"
                )
            required = set(required_fields or ())
            validated = set(review["validated_fields"] or ())
            unresolved = set(review["unresolved_fields"] or ())
            rejected = set(review["rejected_fields"] or ())
            if required - validated or required & unresolved or required & rejected:
                raise ValueError("ready review has invalid field-level evidence")
            if review["missingness_status"] != "complete" or review[
                "corporate_action_status"
            ] not in {"verified_no_event", "event_verified_handled"}:
                raise ValueError("ready review violates readiness invariants")

    async def get_ready_codes(
        self,
        stock_codes: list[str],
        *,
        period: str,
        adjustment: str,
        research_use_scope: str,
        requirement_profile: str | None,
        required_fields: list[str] | tuple[str, ...] | None,
        start_date: date,
        end_date: date,
    ) -> list[str]:
        ready: list[str] = []
        for stock_code in stock_codes:
            try:
                await self.assert_ready(
                    [stock_code],
                    period=period,
                    adjustment=adjustment,
                    research_use_scope=research_use_scope,
                    requirement_profile=requirement_profile,
                    required_fields=required_fields,
                    start_date=start_date,
                    end_date=end_date,
                )
                ready.append(KlineContract.canonical_symbol(stock_code)[0])
            except ValueError:
                continue
        return ready
