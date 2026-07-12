import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import FEATURE_RISK, get_logger
from app.core.timeutil import now_cn_iso
from app.data.cache import CacheManager

logger = get_logger(__name__, feature=FEATURE_RISK)


class FuseManager:
    def __init__(self, db: AsyncSession, cache: CacheManager) -> None:
        self.db = db
        self.cache = cache

    async def activate(self, mode: str, reason: str, portfolio: dict) -> None:
        # 已有活跃熔断则不重复插入
        if await self._db_is_fused(mode):
            logger.info("risk_fuse_already_active", mode=mode, reason=reason)
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
        await self._sync_cache(mode, active=True, reason=reason)
        logger.critical(
            "risk_fuse_db_activated",
            mode=mode,
            reason=reason,
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
        """以数据库 is_active 为准；Redis 仅作缓存加速。"""
        try:
            active = await self._db_is_fused(mode)
        except Exception as exc:
            logger.warning("fuse_db_check_failed", mode=mode, error=str(exc))
            # DB 不可用时降级读缓存（宁可保守：缓存无则 False，避免误拦全部）
            return await self._cache_is_fused(mode)

        # 回写缓存，保证 Redis 重启后仍可从 DB 恢复语义
        if active:
            await self._sync_cache(mode, active=True)
        else:
            await self.cache.delete_raw(f"fuse:{mode}")
        return active

    async def recover(self, mode: str, approved_by: str, note: str) -> None:
        await self.db.execute(
            text(
                """
                UPDATE risk.fuse_records
                SET is_active = FALSE,
                    recovery_approved_by = :approved_by,
                    recovery_note = :note,
                    recovered_at = NOW()
                WHERE mode = :mode AND is_active = TRUE
                """
            ),
            {"mode": mode, "approved_by": approved_by, "note": note},
        )
        await self.cache.delete_raw(f"fuse:{mode}")
        logger.info(
            "risk_fuse_db_recovered",
            mode=mode,
            approved_by=approved_by,
            note=note,
        )
        try:
            from app.monitoring.metrics import set_fuse_active

            set_fuse_active(mode, False)
        except Exception:
            pass

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

    async def _cache_is_fused(self, mode: str) -> bool:
        data = await self.cache.get_raw(f"fuse:{mode}")
        if not data:
            return False
        try:
            return bool(json.loads(data).get("active", False))
        except json.JSONDecodeError:
            return False

    async def _sync_cache(
        self, mode: str, *, active: bool, reason: str | None = None
    ) -> None:
        if not active:
            await self.cache.delete_raw(f"fuse:{mode}")
            return
        payload = {
            "active": True,
            "reason": reason or "",
            "activated_at": now_cn_iso(),
        }
        await self.cache.set_raw(f"fuse:{mode}", json.dumps(payload))
