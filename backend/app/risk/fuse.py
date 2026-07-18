from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import FEATURE_RISK, get_logger
from app.core.timeutil import now_cn_iso
from app.data.cache import CacheManager


logger = get_logger(__name__, feature=FEATURE_RISK)
FUSE_CACHE_VERSION = 1
FUSE_STATUS_VERSION = "risk-fuse-status-v2"


class FuseManager:
    def __init__(self, db: AsyncSession, cache: CacheManager) -> None:
        self.db = db
        self.cache = cache

    async def activate(
        self,
        mode: str,
        reason: str,
        portfolio: dict,
        *,
        activated_by: str,
    ) -> None:
        if await self._db_is_fused(mode):
            await self.db.execute(
                text(
                    """
                    INSERT INTO risk.risk_events
                    (rule_code, trigger_value, threshold, action_taken, detail)
                    VALUES (:rule_code, :trigger_value, :threshold, :action_taken, CAST(:detail AS jsonb))
                    """
                ),
                {
                    "rule_code": "FUSE_ACTIVATION_NOOP",
                    "trigger_value": 1,
                    "threshold": 0,
                    "action_taken": "noop",
                    "detail": json.dumps(
                        {
                            "message": f"{mode} 模式熔断已处于激活状态",
                            "mode": mode,
                            "reason": reason,
                            "activated_by": activated_by,
                            "source": "risk.fuse_records",
                        }
                    ),
                },
            )
            logger.info(
                "risk_fuse_already_active",
                mode=mode,
                reason=reason,
                activated_by=activated_by,
            )
            await self._sync_cache(mode, active=True, reason=reason)
            return

        await self.db.execute(
            text(
                """
                INSERT INTO risk.fuse_records (mode, fuse_reason, portfolio_snapshot, is_active)
                VALUES (:mode, :reason, CAST(:portfolio AS jsonb), TRUE)
                """
            ),
            {
                "mode": mode,
                "reason": reason,
                "portfolio": json.dumps(portfolio, default=str),
            },
        )
        await self.db.execute(
            text(
                """
                INSERT INTO risk.risk_events
                (rule_code, trigger_value, threshold, action_taken, detail)
                VALUES (:rule_code, :trigger_value, :threshold, :action_taken, CAST(:detail AS jsonb))
                """
            ),
            {
                "rule_code": "FUSE_ACTIVATED",
                "trigger_value": 1,
                "threshold": 0,
                "action_taken": "critical",
                "detail": json.dumps(
                    {
                        "message": f"{mode} 模式熔断已触发：{reason}",
                        "mode": mode,
                        "reason": reason,
                        "activated_by": activated_by,
                        "source": "risk.fuse_records",
                    }
                ),
            },
        )
        await self._sync_cache(mode, active=True, reason=reason)
        logger.critical(
            "risk_fuse_db_activated",
            mode=mode,
            reason=reason,
            activated_by=activated_by,
            total_assets=portfolio.get("total_assets"),
        )

        try:
            from app.monitoring.metrics import set_fuse_active

            set_fuse_active(mode, True)
        except Exception:
            pass

        from app.ws.publisher import publish_alert

        await publish_alert(
            alert_type="fuse_activated",
            level="CRITICAL",
            message=f"{mode} 模式熔断已触发：{reason}",
            detail={"mode": mode, "reason": reason},
        )

    async def is_fused(self, mode: str) -> bool:
        """Return fused on every dependency, cache, or cache-version uncertainty."""
        return bool((await self.get_state(mode))["is_active"])

    async def get_state(self, mode: str) -> dict:
        try:
            active = await self._db_is_fused(mode)
        except Exception as exc:
            logger.warning(
                "fuse_state_unavailable",
                mode=mode,
                source="risk.fuse_records",
                error_type=type(exc).__name__,
            )
            return self._state(
                mode,
                is_active=True,
                status="blocked_unknown",
                reason="db_unavailable",
                evidence=[{"source": "risk.fuse_records", "status": "unavailable"}],
            )

        try:
            cached = await self._cache_state(mode)
        except Exception as exc:
            logger.warning(
                "fuse_state_unavailable",
                mode=mode,
                source="cache",
                error_type=type(exc).__name__,
            )
            return self._state(
                mode,
                is_active=True,
                status="blocked_unknown",
                reason="cache_unavailable",
                evidence=[
                    {"source": "risk.fuse_records", "status": "active" if active else "inactive"},
                    {"source": "cache", "status": "unavailable"},
                ],
            )

        if active:
            return self._state(
                mode,
                is_active=True,
                status="active",
                reason=None,
                evidence=[
                    {"source": "risk.fuse_records", "status": "active"},
                    {"source": "cache", "status": "active" if cached is not None else "empty"},
                ],
            )
        if cached is not None:
            logger.warning("fuse_state_mismatch", mode=mode, cached=cached)
            return self._state(
                mode,
                is_active=True,
                status="blocked_inconsistent",
                reason="cache_active_while_db_inactive",
                evidence=[
                    {"source": "risk.fuse_records", "status": "inactive"},
                    {"source": "cache", "status": "active"},
                ],
            )
        return self._state(
            mode,
            is_active=False,
            status="inactive",
            reason=None,
            evidence=[
                {"source": "risk.fuse_records", "status": "inactive"},
                {"source": "cache", "status": "empty"},
            ],
        )

    @staticmethod
    def _state(
        mode: str,
        *,
        is_active: bool,
        status: str,
        reason: str | None,
        evidence: list[dict[str, str]],
    ) -> dict:
        return {
            "mode": mode,
            "is_active": is_active,
            "status": status,
            "reason": reason,
            "status_version": FUSE_STATUS_VERSION,
            "observed_at": now_cn_iso(),
            "evidence": evidence,
        }

    async def recover(
        self,
        mode: str,
        fuse_record_id: int,
        approved_by: str,
        note: str,
    ) -> bool:
        result = await self.db.execute(
            text(
                """
                UPDATE risk.fuse_records
                SET is_active = FALSE,
                    recovery_approved_by = :approved_by,
                    recovery_note = :note,
                    recovered_at = NOW()
                WHERE id = :fuse_record_id AND mode = :mode AND is_active = TRUE
                RETURNING id
                """
            ),
            {
                "mode": mode,
                "fuse_record_id": fuse_record_id,
                "approved_by": approved_by,
                "note": note,
            },
        )
        if not result.mappings().first():
            logger.warning(
                "risk_fuse_recovery_conflict",
                mode=mode,
                fuse_record_id=fuse_record_id,
            )
            return False
        await self.db.execute(
            text(
                """
                INSERT INTO risk.risk_events
                (rule_code, trigger_value, threshold, action_taken, detail)
                VALUES (:rule_code, :trigger_value, :threshold, :action_taken, CAST(:detail AS jsonb))
                """
            ),
            {
                "rule_code": "FUSE_RECOVERED",
                "trigger_value": 0,
                "threshold": 0,
                "action_taken": "recovered",
                "detail": json.dumps(
                    {
                        "message": f"{mode} 模式熔断已解除",
                        "mode": mode,
                        "fuse_record_id": fuse_record_id,
                        "approved_by": approved_by,
                        "note": note,
                        "source": "risk.fuse_records",
                    }
                ),
            },
        )
        await self.cache.delete_raw_strict(f"fuse:{mode}")
        logger.info(
            "risk_fuse_db_recovered",
            mode=mode,
            fuse_record_id=fuse_record_id,
            approved_by=approved_by,
        )
        try:
            from app.monitoring.metrics import set_fuse_active

            set_fuse_active(mode, False)
        except Exception:
            pass
        return True

    async def _db_is_fused(self, mode: str) -> bool:
        result = await self.db.execute(
            text(
                """
                SELECT 1 FROM risk.fuse_records
                WHERE mode = :mode AND is_active = TRUE
                LIMIT 1
                """
            ),
            {"mode": mode},
        )
        return result.scalar() is not None

    async def _cache_state(self, mode: str) -> dict | None:
        data = await self.cache.get_raw_strict(f"fuse:{mode}")
        if not data:
            return None
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("invalid fuse cache payload")
        if payload.get("version") != FUSE_CACHE_VERSION:
            raise ValueError("unsupported fuse cache version")
        if payload.get("active") is not True:
            raise ValueError("inactive fuse cache payload is invalid")
        return payload

    async def _sync_cache(
        self, mode: str, *, active: bool, reason: str | None = None
    ) -> None:
        if not active:
            await self.cache.delete_raw_strict(f"fuse:{mode}")
            return
        payload = {
            "version": FUSE_CACHE_VERSION,
            "active": True,
            "reason": reason or "",
            "activated_at": now_cn_iso(),
        }
        await self.cache.set_raw_strict(f"fuse:{mode}", json.dumps(payload))
