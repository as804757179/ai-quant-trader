from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

from app.strategy.version_service import StrategyVersionError, StrategyVersionService


class FreeObservationStrategySnapshotError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FreeObservationStrategySnapshotExporter:
    """Read one governed active strategy version without changing governance state."""

    async def export(self, db: Any, *, strategy_type: str = "dual_ma") -> dict[str, Any]:
        if strategy_type != "dual_ma":
            raise FreeObservationStrategySnapshotError("FREE_OBSERVATION_STRATEGY_INVALID", "免费观测仅支持 dual_ma")
        result = await db.execute(
            text(
                """
                SELECT s.id AS strategy_id, s.strategy_type, s.is_active,
                       h.revision, h.active_version_id,
                       v.version_id, v.version_number, v.enabled, v.params,
                       v.catalog_hash, v.config_hash, a.status AS approval_status
                FROM strategy.strategies AS s
                JOIN strategy.strategy_version_heads AS h ON h.strategy_id = s.id
                JOIN strategy.strategy_versions AS v ON v.version_id = h.active_version_id
                JOIN strategy.strategy_version_approvals AS a ON a.version_id = v.version_id
                WHERE s.strategy_type = :strategy_type AND s.is_active IS TRUE
                ORDER BY s.id
                """
            ),
            {"strategy_type": strategy_type},
        )
        rows = [dict(row) for row in result.mappings().all()]
        if len(rows) != 1:
            raise FreeObservationStrategySnapshotError(
                "FREE_OBSERVATION_STRATEGY_UNCONFIRMED",
                "未找到唯一 active 的 dual_ma 策略主体",
            )
        row = rows[0]
        if (
            row.get("active_version_id") != row.get("version_id")
            or row.get("revision") != row.get("version_number")
            or row.get("approval_status") != "approved"
            or row.get("enabled") is not True
        ):
            raise FreeObservationStrategySnapshotError(
                "FREE_OBSERVATION_STRATEGY_UNCONFIRMED",
                "active head、审批或启用状态不满足免费观测快照条件",
            )
        try:
            enabled, params = StrategyVersionService._verified_config(
                strategy_type=strategy_type,
                enabled=row["enabled"],
                params=row["params"],
                catalog_hash=row["catalog_hash"],
                config_hash=row["config_hash"],
            )
        except StrategyVersionError as exc:
            raise FreeObservationStrategySnapshotError("FREE_OBSERVATION_STRATEGY_UNCONFIRMED", str(exc)) from exc
        snapshot = {
            "strategy_type": strategy_type,
            "strategy_id": row["strategy_id"],
            "version_id": row["version_id"],
            "version": row["version_number"],
            "enabled": enabled,
            "params": params,
            "catalog_hash": row["catalog_hash"],
            "config_hash": row["config_hash"],
        }
        return {
            **snapshot,
            "snapshot_hash": self._hash(snapshot),
            "data_mode": "free_observation",
            "formal_use": False,
            "source": "strategy.strategy_versions + strategy.strategy_version_heads",
            "blocked_from": ["formal_p3", "formal_p4", "p5", "trade_execution"],
        }

    @staticmethod
    def _hash(payload: object) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
