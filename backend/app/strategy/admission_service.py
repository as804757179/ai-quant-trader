"""Fail-closed strategy admission resolution for P3 governance."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.strategy.version_service import StrategyVersionError, StrategyVersionService


class StrategyAdmissionService:
    @staticmethod
    def resolve(
        *,
        strategy_type: str,
        subjects: list[dict[str, Any]],
        snapshot: dict[str, Any] | None,
        validity_events: list[dict[str, Any]],
        as_of: datetime,
    ) -> dict[str, Any]:
        active_subjects = [item for item in subjects if item.get("is_active") is True]
        if len(active_subjects) != 1:
            raise StrategyVersionError("策略主体未唯一激活", "P3_STRATEGY_VERSION_UNCONFIRMED", 409)
        subject = active_subjects[0]
        if subject.get("strategy_type") != strategy_type:
            raise StrategyVersionError("策略类型无有效主体", "P3_STRATEGY_VERSION_UNCONFIRMED", 409)
        if not snapshot or snapshot.get("active_version_id") != snapshot.get("version_id"):
            raise StrategyVersionError("策略 active head 无效", "P3_STRATEGY_VERSION_UNCONFIRMED", 409)
        if snapshot.get("approval_status") != "approved" or snapshot.get("enabled") is not True:
            raise StrategyVersionError("策略版本未审批启用", "P3_STRATEGY_VERSION_UNCONFIRMED", 409)
        try:
            _, params = StrategyVersionService._verified_config(
                strategy_type=strategy_type,
                enabled=snapshot.get("enabled"),
                params=snapshot.get("params"),
                catalog_hash=snapshot.get("catalog_hash"),
                config_hash=snapshot.get("config_hash"),
            )
        except StrategyVersionError as exc:
            raise StrategyVersionError(str(exc), "P3_STRATEGY_VERSION_UNCONFIRMED", 409) from exc
        events = [item for item in validity_events if item.get("effective_at") <= as_of]
        active = [
            item for item in events
            if item.get("event_type") == "activated"
            and item.get("valid_until") is not None
            and as_of < item["valid_until"]
        ]
        if len(active) != 1:
            raise StrategyVersionError("策略生命周期未确认", "P3_STRATEGY_VERSION_UNCONFIRMED", 409)
        activated_at = active[0]["effective_at"]
        if any(
            item.get("event_type") in {"revoked", "expired"}
            and item.get("effective_at") >= activated_at
            for item in events
        ):
            raise StrategyVersionError("策略版本已撤销或过期", "P3_STRATEGY_VERSION_UNCONFIRMED", 409)
        return {"strategy_id": subject["id"], "version_id": snapshot["version_id"], "params": params,
                "config_hash": snapshot["config_hash"], "catalog_hash": snapshot["catalog_hash"]}
