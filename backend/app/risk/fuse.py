import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.cache import CacheManager


class FuseManager:
    def __init__(self, db: AsyncSession, cache: CacheManager) -> None:
        self.db = db
        self.cache = cache

    async def activate(self, mode: str, reason: str, portfolio: dict) -> None:
        fuse_key = f"fuse:{mode}"
        await self.cache.set_raw(
            fuse_key,
            json.dumps(
                {
                    "active": True,
                    "reason": reason,
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
        await self.db.execute(
            text(
                """
                INSERT INTO risk.fuse_records (mode, fuse_reason, portfolio_snapshot)
                VALUES (:mode, :reason, :portfolio::jsonb)
                """
            ),
            {
                "mode": mode,
                "reason": reason,
                "portfolio": json.dumps(portfolio, default=str),
            },
        )
        from app.ws.publisher import publish_alert

        await publish_alert(
            alert_type="fuse_activated",
            level="CRITICAL",
            message=f"{mode} 模式熔断已触发：{reason}",
            detail={"mode": mode, "reason": reason},
        )

    async def is_fused(self, mode: str) -> bool:
        data = await self.cache.get_raw(f"fuse:{mode}")
        if not data:
            return False
        try:
            return json.loads(data).get("active", False)
        except json.JSONDecodeError:
            return False

    async def recover(self, mode: str, approved_by: str, note: str) -> None:
        await self.cache.delete_raw(f"fuse:{mode}")
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