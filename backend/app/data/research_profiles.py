from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchDataRequirementProfile:
    name: str
    required_fields: tuple[str, ...]
    allowed_scopes: tuple[str, ...]
    policy_version: str = "field-readiness-v1"

    _OHLCV_FIELDS = (
        "trading_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjustment",
        "trading_calendar",
        "corporate_action_status",
    )

    @classmethod
    def get(cls, name: str | None) -> "ResearchDataRequirementProfile":
        if not name:
            raise ValueError("requirement_profile must be explicitly declared")
        profiles = {
            "OHLCV_RETURN_V1": cls(
                "OHLCV_RETURN_V1",
                cls._OHLCV_FIELDS,
                ("raw_price_analysis", "return_backtest"),
            ),
            "AMOUNT_FACTOR_V1": cls(
                "AMOUNT_FACTOR_V1",
                cls._OHLCV_FIELDS
                + ("amount", "amount_unit", "amount_provider_validation"),
                ("return_backtest",),
            ),
            "EXECUTION_REFERENCE_V1": cls(
                "EXECUTION_REFERENCE_V1",
                (
                    "quote_time",
                    "price_applicability",
                    "explicit_authorization",
                    "execution_gate",
                ),
                ("execution_reference",),
            ),
            "OHLCV_TOTAL_RETURN_GROSS_V1": cls(
                "OHLCV_TOTAL_RETURN_GROSS_V1",
                cls._OHLCV_FIELDS
                + (
                    "verified_corporate_action_event",
                    "record_date",
                    "ex_date",
                    "cash_payment_date",
                    "share_credit_date",
                    "corporate_action_processor_version",
                    "gross_total_return_policy",
                ),
                ("return_backtest",),
                "corporate-action-pit-v1",
            ),
        }
        profile = profiles.get(name)
        if not profile:
            raise ValueError(f"unknown requirement profile: {name}")
        return profile

    def validate_declaration(
        self, *, research_use_scope: str, required_fields: list[str] | tuple[str, ...] | None
    ) -> tuple[str, ...]:
        if research_use_scope not in self.allowed_scopes:
            raise ValueError("requirement profile does not allow the requested use scope")
        if not required_fields:
            raise ValueError("required_fields must be explicitly declared")
        declared = tuple(dict.fromkeys(required_fields))
        if set(declared) != set(self.required_fields):
            raise ValueError("required_fields do not match requirement profile")
        return declared
