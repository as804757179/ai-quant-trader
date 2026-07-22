from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shadow.contracts import ShadowContractError


class ShadowRepository:
    async def create_run(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        idempotency_key: str,
        request_hash: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        result = await db.execute(
            text(
                """
                INSERT INTO shadow.runs
                    (run_id, idempotency_key, request_hash, status, block_code,
                     data_mode, not_realtime, realtime_data_approved, provider, source,
                     dataset_version, license_evidence_ref, sample_reference_id, sample_hash,
                     strategy_reference_id, strategy_hash, input_profile_reference_id,
                     input_profile_hash, information_cutoff, input_snapshot_hash,
                     release_locks_before, release_locks_after)
                VALUES
                    (:run_id, :idempotency_key, :request_hash, :status, :block_code,
                     :data_mode, :not_realtime, :realtime_data_approved, :provider, :source,
                     :dataset_version, :license_evidence_ref, :sample_reference_id, :sample_hash,
                     :strategy_reference_id, :strategy_hash, :input_profile_reference_id,
                     :input_profile_hash, :information_cutoff, :input_snapshot_hash,
                     CAST(:release_locks_before AS jsonb), CAST(:release_locks_after AS jsonb))
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING run_id::text AS run_id, request_hash, status, block_code,
                          data_mode, not_realtime, realtime_data_approved, created_at
                """
            ),
            {"run_id": str(run_id), "idempotency_key": idempotency_key, "request_hash": request_hash, **payload},
        )
        created = result.mappings().first()
        if created:
            return dict(created), True
        existing = await self.get_run_by_idempotency(db, idempotency_key=idempotency_key)
        if not existing:
            raise ShadowContractError("P3_RUN_IDEMPOTENCY_UNAVAILABLE", "影子运行幂等状态不可用")
        if existing["request_hash"] != request_hash:
            raise ShadowContractError(
                "P3_IDEMPOTENCY_PAYLOAD_CONFLICT", "同一幂等键不能绑定不同影子运行输入"
            )
        return existing, False

    async def get_run_by_idempotency(
        self, db: AsyncSession, *, idempotency_key: str
    ) -> dict[str, Any] | None:
        result = await db.execute(
            text(
                """
                SELECT run_id::text AS run_id, request_hash, status, block_code,
                       data_mode, not_realtime, realtime_data_approved, created_at, completed_at
                FROM shadow.runs
                WHERE idempotency_key = :idempotency_key
                """
            ),
            {"idempotency_key": idempotency_key},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def append_input_batch(
        self,
        db: AsyncSession,
        *,
        input_batch_id: UUID,
        run_id: UUID,
        batch_id: str,
        raw_hash: str,
        provider_time: datetime | None,
        fetched_at: datetime,
        received_at: datetime,
        data_as_of: datetime,
    ) -> None:
        await db.execute(
            text(
                """
                INSERT INTO shadow.run_input_batches
                    (input_batch_id, run_id, batch_id, raw_hash, provider_time,
                     fetched_at, received_at, data_as_of)
                VALUES
                    (:input_batch_id, :run_id, :batch_id, :raw_hash, :provider_time,
                     :fetched_at, :received_at, :data_as_of)
                ON CONFLICT (run_id, batch_id, raw_hash) DO NOTHING
                """
            ),
            {
                "input_batch_id": str(input_batch_id),
                "run_id": str(run_id),
                "batch_id": batch_id,
                "raw_hash": raw_hash,
                "provider_time": provider_time,
                "fetched_at": fetched_at,
                "received_at": received_at,
                "data_as_of": data_as_of,
            },
        )

    async def append_decision(
        self, db: AsyncSession, *, payload: dict[str, Any]
    ) -> None:
        await db.execute(
            text(
                """
                INSERT INTO shadow.decisions
                    (decision_id, run_id, stock_code, information_cutoff, decision_state,
                     would_action, reason_code, decision_rule_hash, decision_dedup_key,
                     evidence_hash)
                VALUES
                    (:decision_id, :run_id, :stock_code, :information_cutoff, :decision_state,
                     :would_action, :reason_code, :decision_rule_hash, :decision_dedup_key,
                     :evidence_hash)
                ON CONFLICT (decision_dedup_key) DO NOTHING
                """
            ),
            payload,
        )

    async def append_decision_evidence(
        self, db: AsyncSession, *, payload: dict[str, Any]
    ) -> None:
        await db.execute(
            text(
                """
                INSERT INTO shadow.decision_evidence
                    (decision_evidence_id, decision_id, input_batch_id,
                     evidence_reference_id, evidence_hash, evidence_type, available_at)
                VALUES
                    (:decision_evidence_id, :decision_id, :input_batch_id,
                     :evidence_reference_id, :evidence_hash, :evidence_type, :available_at)
                ON CONFLICT (decision_id, evidence_reference_id, evidence_hash) DO NOTHING
                """
            ),
            payload,
        )
