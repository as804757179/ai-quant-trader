from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shadow.contracts import ShadowContractError


class ShadowRepository:
    @staticmethod
    def _page(page: int, page_size: int) -> tuple[int, int]:
        return max(1, page), max(1, min(200, page_size))

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

    async def list_runs(
        self,
        db: AsyncSession,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        page, page_size = self._page(page, page_size)
        params = {"status": status, "limit": page_size, "offset": (page - 1) * page_size}
        where = "WHERE (CAST(:status AS varchar) IS NULL OR status = CAST(:status AS varchar))"
        total = await db.scalar(text(f"SELECT COUNT(*) FROM shadow.runs {where}"), params)
        result = await db.execute(
            text(
                f"""
                SELECT run_id::text AS run_id, status, block_code, data_mode, not_realtime,
                       realtime_data_approved, provider, source, dataset_version,
                       information_cutoff, input_snapshot_hash, result_hash,
                       tradable, order_created, order_count, order_service_calls,
                       execution_service_calls, capital_write_count, position_write_count,
                       release_locks_before, release_locks_after, created_at, completed_at
                FROM shadow.runs {where}
                ORDER BY created_at DESC, run_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        return [dict(row) for row in result.mappings().all()], int(total or 0)

    async def get_run(self, db: AsyncSession, *, run_id: UUID) -> dict[str, Any] | None:
        result = await db.execute(
            text(
                """
                SELECT run_id::text AS run_id, idempotency_key, request_hash, status, block_code,
                       data_mode, not_realtime, realtime_data_approved, provider, source,
                       dataset_version, license_evidence_ref, sample_reference_id, sample_hash,
                       strategy_reference_id, strategy_hash, input_profile_reference_id,
                       input_profile_hash, information_cutoff, input_snapshot_hash, result_hash,
                       tradable, order_created, order_count, order_service_calls,
                       execution_service_calls, capital_write_count, position_write_count,
                       release_locks_before, release_locks_after, created_at, completed_at
                FROM shadow.runs
                WHERE run_id = CAST(:run_id AS uuid)
                """
            ),
            {"run_id": str(run_id)},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def list_decisions(
        self, db: AsyncSession, *, run_id: UUID, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        page, page_size = self._page(page, page_size)
        params = {"run_id": str(run_id), "limit": page_size, "offset": (page - 1) * page_size}
        total = await db.scalar(
            text("SELECT COUNT(*) FROM shadow.decisions WHERE run_id = CAST(:run_id AS uuid)"),
            params,
        )
        result = await db.execute(
            text(
                """
                SELECT decision_id::text AS decision_id, run_id::text AS run_id, stock_code,
                       information_cutoff, decision_state, would_action, reason_code,
                       decision_rule_hash, decision_dedup_key, evidence_hash,
                       tradable, order_created, created_at
                FROM shadow.decisions
                WHERE run_id = CAST(:run_id AS uuid)
                ORDER BY created_at DESC, decision_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        return [dict(row) for row in result.mappings().all()], int(total or 0)

    async def list_decision_evidence(
        self, db: AsyncSession, *, decision_id: UUID
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            text(
                """
                SELECT evidence.decision_evidence_id::text AS decision_evidence_id,
                       evidence.decision_id::text AS decision_id,
                       evidence.input_batch_id::text AS input_batch_id,
                       evidence.evidence_reference_id, evidence.evidence_hash,
                       evidence.evidence_type, evidence.available_at, evidence.created_at,
                       input.batch_id, input.raw_hash, input.provider_time, input.fetched_at,
                       input.received_at, input.data_as_of
                FROM shadow.decision_evidence AS evidence
                LEFT JOIN shadow.run_input_batches AS input
                    ON input.input_batch_id = evidence.input_batch_id
                WHERE evidence.decision_id = CAST(:decision_id AS uuid)
                ORDER BY evidence.created_at, evidence.decision_evidence_id
                """
            ),
            {"decision_id": str(decision_id)},
        )
        return [dict(row) for row in result.mappings().all()]

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
