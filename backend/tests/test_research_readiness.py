from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.data.certified_kline_repository import CertifiedKlineRepository
from app.backtest.service import BacktestService
from app.core.config import settings
from app.data.research_readiness import ResearchReadinessService
from app.data.research_profiles import ResearchDataRequirementProfile
from app.screener.engine import ScreenerEngine


OHLCV_FIELDS = list(
    ResearchDataRequirementProfile.get("OHLCV_RETURN_V1").required_fields
)

BASE = {
    "certified": True,
    "metadata_complete": True,
    "adjustment": "raw",
    "calendar_complete": True,
    "missingness_status": "complete",
    "corporate_action_status": "verified_no_event",
    "provider_validation_status": "pass",
    "unexplained_major_jump": False,
    "research_use_scope": "return_backtest",
    "requirement_profile": "OHLCV_RETURN_V1",
    "required_fields": OHLCV_FIELDS,
    "validated_fields": OHLCV_FIELDS,
    "unresolved_fields": [],
    "rejected_fields": [],
}


def test_evaluate_distinguishes_all_readiness_states() -> None:
    assert ResearchReadinessService.evaluate(**BASE).status == "ready"
    assert ResearchReadinessService.evaluate(
        **{**BASE, "provider_validation_status": "partial_pass"}
    ).status == "review_required"
    assert ResearchReadinessService.evaluate(
        **{**BASE, "certified": False}
    ).status == "rejected"


def test_unresolved_missingness_and_corporate_action_block_ready() -> None:
    missing = ResearchReadinessService.evaluate(
        **{**BASE, "missingness_status": "unresolved"}
    )
    action = ResearchReadinessService.evaluate(
        **{**BASE, "corporate_action_status": "unresolved"}
    )
    assert missing.status == "review_required"
    assert action.status == "review_required"


def test_unhandled_action_rejects_raw_return_backtest() -> None:
    decision = ResearchReadinessService.evaluate(
        **{**BASE, "corporate_action_status": "event_verified"}
    )
    assert decision.status == "rejected"
    assert "not handled" in " ".join(decision.reasons)


def test_execution_reference_requires_explicit_freshness() -> None:
    fields = list(
        ResearchDataRequirementProfile.get("EXECUTION_REFERENCE_V1").required_fields
    )
    decision = ResearchReadinessService.evaluate(
        **{
            **BASE,
            "research_use_scope": "execution_reference",
            "requirement_profile": "EXECUTION_REFERENCE_V1",
            "required_fields": fields,
            "validated_fields": ["execution_gate"],
            "rejected_fields": [
                "quote_time",
                "price_applicability",
                "explicit_authorization",
            ],
        }
    )
    assert decision.status == "rejected"


def test_missing_profile_and_field_mismatch_fail_closed() -> None:
    with pytest.raises(ValueError, match="explicitly declared"):
        ResearchReadinessService.evaluate(**{**BASE, "requirement_profile": None})
    with pytest.raises(ValueError, match="do not match"):
        ResearchReadinessService.evaluate(
            **{**BASE, "required_fields": ["close"]}
        )


def test_backtest_without_profile_fails_before_data_access() -> None:
    with patch.object(settings, "CERTIFIED_BACKTEST_EXECUTION_ENABLED", True):
        with pytest.raises(ValueError, match="requirement_profile"):
            asyncio.run(
                BacktestService().create_and_run(
                    strategy_type="dual_ma",
                    stock_codes=["300308.SZ"],
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 6, 30),
                )
            )


def test_non_required_amount_does_not_block_ohlcv_profile() -> None:
    decision = ResearchReadinessService.evaluate(
        **{**BASE, "unresolved_fields": ["amount"]}
    )
    assert decision.status == "ready"


def test_amount_profile_blocks_unresolved_amount() -> None:
    fields = list(
        ResearchDataRequirementProfile.get("AMOUNT_FACTOR_V1").required_fields
    )
    decision = ResearchReadinessService.evaluate(
        **{
            **BASE,
            "requirement_profile": "AMOUNT_FACTOR_V1",
            "required_fields": fields,
            "validated_fields": OHLCV_FIELDS + ["amount_unit"],
            "unresolved_fields": ["amount", "amount_provider_validation"],
            "provider_validation_status": "partial_pass",
        }
    )
    assert decision.status == "review_required"


def test_required_ohlcv_field_unresolved_blocks_ready() -> None:
    decision = ResearchReadinessService.evaluate(
        **{**BASE, "unresolved_fields": ["volume"]}
    )
    assert decision.status == "review_required"


def test_no_review_fails_closed() -> None:
    service = ResearchReadinessService()
    service.get_review = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="readiness gate rejected"):
        asyncio.run(
            service.assert_ready(
                ["300308.SZ"],
                period="1d",
                adjustment="raw",
                research_use_scope="return_backtest",
                requirement_profile="OHLCV_RETURN_V1",
                required_fields=OHLCV_FIELDS,
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 30),
            )
        )


def test_repository_delegates_to_scope_readiness_gate() -> None:
    repository = CertifiedKlineRepository()
    repository.get_bars = AsyncMock(
        return_value=[{"stock_code": "300308.SZ", "trading_date": date(2026, 6, 1)}]
    )
    gate = SimpleNamespace(assert_ready=AsyncMock())
    with patch(
        "app.data.certified_kline_repository.ResearchReadinessService",
        return_value=gate,
    ):
        asyncio.run(
            repository.assert_dataset_ready(
                ["300308.SZ"],
                period="1d",
                adjustment="raw",
                research_use_scope="return_backtest",
                requirement_profile="OHLCV_RETURN_V1",
                required_fields=OHLCV_FIELDS,
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 30),
            )
        )
    gate.assert_ready.assert_awaited_once()


def test_screener_excludes_all_non_ready_symbols() -> None:
    repository = AsyncMock()
    repository.get_certified_universe.return_value = ["300308.SZ"]
    repository.get_bars.return_value = [
        {"stock_code": "300308.SZ", "trading_date": date(2026, 6, 1)}
    ]
    readiness = AsyncMock()
    readiness.get_ready_codes.return_value = []
    engine = ScreenerEngine(kline_repository=repository, release_enabled=True)
    with patch(
        "app.screener.engine.ResearchReadinessService", return_value=readiness
    ):
        result = asyncio.run(
            engine._load_universe(
                requirement_profile="AMOUNT_FACTOR_V1",
                required_fields=list(
                    ResearchDataRequirementProfile.get(
                        "AMOUNT_FACTOR_V1"
                    ).required_fields
                ),
            )
        )
    assert result == []
    readiness.get_ready_codes.assert_awaited_once()
