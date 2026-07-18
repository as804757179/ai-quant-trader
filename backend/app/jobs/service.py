"""Durable, auditable job state shared by long-running backend operations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.auth import Principal
from app.db import get_db


RUNNABLE_STATUSES = frozenset({"queued", "retry_wait"})
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "blocked"})
_PRIVILEGED_JOB_ROLES = frozenset({"auditor", "admin", "service_worker"})


class AsyncJobError(Exception):
    code = "ASYNC_JOB_ERROR"
    status_code = 409


class AsyncJobNotFound(AsyncJobError):
    code = "JOB_NOT_FOUND"
    status_code = 404


class AsyncJobConflict(AsyncJobError):
    code = "IDEMPOTENCY_KEY_PAYLOAD_CONFLICT"
    status_code = 409


class AsyncJobStateError(AsyncJobError):
    code = "JOB_STATE_CONFLICT"
    status_code = 409


class AsyncJobResultUnavailable(AsyncJobError):
    code = "JOB_RESULT_UNAVAILABLE"
    status_code = 409


def canonical_input_hash(payload: dict[str, Any]) -> str:
    """Hash a request payload without relying on JSON key insertion order."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_uuid(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise AsyncJobNotFound("任务不存在") from exc


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise AsyncJobStateError("任务输入载荷损坏")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class AsyncJobStore:
    """PostgreSQL-backed job state; it never dispatches or executes work itself."""

    async def enqueue(
        self,
        *,
        job_type: str,
        requester: Principal,
        idempotency_key: str,
        input_payload: dict[str, Any],
        initial_status: str = "queued",
        initial_error_code: str | None = None,
        max_retries: int = 2,
        db: Any | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if requester.is_anonymous:
            raise AsyncJobStateError("匿名主体不能创建任务")
        if initial_status not in RUNNABLE_STATUSES | TERMINAL_STATUSES:
            raise AsyncJobStateError("非法任务初始状态")
        if not 8 <= len(idempotency_key) <= 128:
            raise AsyncJobStateError("缺少有效的 Idempotency-Key")
        if not 0 <= max_retries <= 10:
            raise AsyncJobStateError("任务重试上限非法")

        input_hash = canonical_input_hash(input_payload)
        if db is not None:
            return await self._enqueue_in_transaction(
                db,
                job_type=job_type,
                requester=requester,
                idempotency_key=idempotency_key,
                input_payload=input_payload,
                input_hash=input_hash,
                initial_status=initial_status,
                initial_error_code=initial_error_code,
                max_retries=max_retries,
            )
        async with get_db() as session:
            return await self._enqueue_in_transaction(
                session,
                job_type=job_type,
                requester=requester,
                idempotency_key=idempotency_key,
                input_payload=input_payload,
                input_hash=input_hash,
                initial_status=initial_status,
                initial_error_code=initial_error_code,
                max_retries=max_retries,
            )

    async def _enqueue_in_transaction(
        self,
        db: Any,
        *,
        job_type: str,
        requester: Principal,
        idempotency_key: str,
        input_payload: dict[str, Any],
        input_hash: str,
        initial_status: str,
        initial_error_code: str | None,
        max_retries: int,
    ) -> tuple[dict[str, Any], bool]:
        created = await db.execute(
                text(
                    """
                    INSERT INTO audit.async_jobs (
                        job_type, requester_principal_id, idempotency_key,
                        input_hash, input_payload, status, error_code, max_retries,
                        finished_at
                    ) VALUES (
                        :job_type, CAST(:requester_principal_id AS uuid), :idempotency_key,
                        :input_hash, CAST(:input_payload AS jsonb), CAST(:status AS VARCHAR(32)), :error_code,
                        :max_retries,
                        CASE WHEN CAST(:status AS VARCHAR(32)) IN ('blocked', 'failed', 'cancelled', 'succeeded')
                             THEN NOW() ELSE NULL END
                    )
                    ON CONFLICT (requester_principal_id, idempotency_key) DO NOTHING
                    RETURNING *
                    """
                ),
                {
                    "job_type": job_type,
                    "requester_principal_id": requester.principal_id,
                    "idempotency_key": idempotency_key,
                    "input_hash": input_hash,
                    "input_payload": json.dumps(input_payload, ensure_ascii=False, default=str),
                    "status": initial_status,
                    "error_code": initial_error_code,
                    "max_retries": max_retries,
                },
            )
        row = created.mappings().first()
        if row is not None:
            return self._public(dict(row)), True

        existing = await db.execute(
                text(
                    """
                    SELECT * FROM audit.async_jobs
                    WHERE requester_principal_id = CAST(:requester_principal_id AS uuid)
                      AND idempotency_key = :idempotency_key
                    """
                ),
                {
                    "requester_principal_id": requester.principal_id,
                    "idempotency_key": idempotency_key,
                },
            )
        row = existing.mappings().first()
        if row is None:
            raise AsyncJobStateError("任务幂等状态不可确定")
        if str(row["input_hash"]) != input_hash or str(row["job_type"]) != job_type:
            raise AsyncJobConflict("同一 Idempotency-Key 不能绑定不同任务输入")
        return self._public(dict(row)), False

    async def bind_operation_approval(
        self,
        db: Any,
        *,
        job_id: str,
        approval_id: str,
    ) -> None:
        result = await db.execute(
            text(
                """
                UPDATE audit.async_jobs
                SET operation_approval_id = CAST(:approval_id AS uuid), updated_at = NOW()
                WHERE job_id = CAST(:job_id AS uuid)
                  AND status = 'queued'
                  AND operation_approval_id IS NULL
                RETURNING job_id
                """
            ),
            {"job_id": _as_uuid(job_id), "approval_id": approval_id},
        )
        if not result.mappings().first():
            raise AsyncJobStateError("操作任务无法绑定审批")

    async def get(self, job_id: str, principal: Principal) -> dict[str, Any]:
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            row = await self._select_visible(db, normalized, principal)
        return self._public(row)

    async def request_cancel(self, job_id: str, principal: Principal) -> dict[str, Any]:
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            row = await self._select_visible(db, normalized, principal, for_update=True)
            state = str(row["status"])
            if state in TERMINAL_STATUSES:
                return self._public(row)
            if state in {"queued", "retry_wait"}:
                updated = await db.execute(
                    text(
                        """
                        UPDATE audit.async_jobs
                        SET status = 'cancelled', error_code = 'JOB_CANCELLED',
                            cancel_requested_at = NOW(), finished_at = NOW(), updated_at = NOW()
                        WHERE job_id = CAST(:job_id AS uuid)
                        RETURNING *
                        """
                    ),
                    {"job_id": normalized},
                )
                await self._finish_latest_attempt(
                    db, normalized, "cancelled", "JOB_CANCELLED"
                )
                return self._public(dict(updated.mappings().one()))
            if state == "running":
                updated = await db.execute(
                    text(
                        """
                        UPDATE audit.async_jobs
                        SET status = 'cancel_requested', cancel_requested_at = NOW(), updated_at = NOW()
                        WHERE job_id = CAST(:job_id AS uuid)
                        RETURNING *
                        """
                    ),
                    {"job_id": normalized},
                )
                return self._public(dict(updated.mappings().one()))
            return self._public(row)

    async def claim(
        self,
        job_id: str,
        worker: Principal,
        *,
        lease_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Atomically assign a runnable job to a service worker.

        ``None`` means a concurrent cancellation won the race; all other unsafe
        states raise instead of silently executing stale or blocked work.
        """
        if lease_seconds is not None and not 30 <= lease_seconds <= 3600:
            raise AsyncJobStateError("任务租约时长非法")
        normalized = _as_uuid(job_id)
        lease_token = str(uuid4()) if lease_seconds is not None else None
        async with get_db() as db:
            result = await db.execute(
                text(
                    "SELECT * FROM audit.async_jobs WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"
                ),
                {"job_id": normalized},
            )
            row = result.mappings().first()
            if row is None:
                raise AsyncJobNotFound("任务不存在")
            record = dict(row)
            state = str(record["status"])
            if state == "cancel_requested":
                await db.execute(
                    text(
                        """
                        UPDATE audit.async_jobs
                        SET status = 'cancelled', error_code = 'JOB_CANCELLED',
                            finished_at = NOW(), updated_at = NOW()
                        WHERE job_id = CAST(:job_id AS uuid)
                        """
                    ),
                    {"job_id": normalized},
                )
                await self._finish_latest_attempt(
                    db, normalized, "cancelled", "JOB_CANCELLED"
                )
                return None
            if state not in RUNNABLE_STATUSES:
                raise AsyncJobStateError(f"任务当前不可执行: {state}")
            retry_at = record.get("next_retry_at")
            if state == "retry_wait" and retry_at and retry_at > datetime.now(timezone.utc):
                raise AsyncJobStateError("任务尚未到达下一次重试时间")

            attempt_number = int(record["retry_count"] or 0) + 1
            claimed = await db.execute(
                text(
                    """
                    UPDATE audit.async_jobs
                    SET status = 'running', progress = GREATEST(progress, 1),
                        worker_principal_id = CAST(:worker_principal_id AS uuid),
                        started_at = COALESCE(started_at, NOW()), next_retry_at = NULL,
                        lease_token = CAST(:lease_token AS uuid),
                        lease_expires_at = CASE
                            WHEN CAST(:lease_seconds AS INTEGER) IS NULL THEN NULL
                            ELSE NOW() + (CAST(:lease_seconds AS INTEGER) * INTERVAL '1 second')
                        END,
                        updated_at = NOW()
                    WHERE job_id = CAST(:job_id AS uuid)
                    RETURNING *
                    """
                ),
                {
                    "job_id": normalized,
                    "worker_principal_id": worker.principal_id,
                    "lease_token": lease_token,
                    "lease_seconds": lease_seconds,
                },
            )
            await db.execute(
                text(
                    """
                    INSERT INTO audit.async_job_attempts (
                        job_id, attempt_number, worker_principal_id, status
                    ) VALUES (
                        CAST(:job_id AS uuid), :attempt_number,
                        CAST(:worker_principal_id AS uuid), 'running'
                    )
                    """
                ),
                {
                    "job_id": normalized,
                    "attempt_number": attempt_number,
                    "worker_principal_id": worker.principal_id,
                },
            )
            claimed_row = dict(claimed.mappings().one())
            claimed_row["input_payload"] = _as_mapping(claimed_row["input_payload"])
            return claimed_row

    async def update_progress(
        self,
        job_id: str,
        progress: int,
        *,
        lease_token: str | None = None,
        lease_seconds: int | None = None,
    ) -> dict[str, Any]:
        if not 0 <= progress <= 100:
            raise AsyncJobStateError("任务进度非法")
        if (lease_token is None) != (lease_seconds is None):
            raise AsyncJobStateError("任务租约参数不完整")
        if lease_seconds is not None and not 30 <= lease_seconds <= 3600:
            raise AsyncJobStateError("任务租约时长非法")
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            updated = await db.execute(
                text(
                    """
                    UPDATE audit.async_jobs
                        SET progress = GREATEST(progress, :progress),
                        lease_expires_at = CASE
                            WHEN CAST(:lease_seconds AS INTEGER) IS NULL THEN lease_expires_at
                            ELSE NOW() + (CAST(:lease_seconds AS INTEGER) * INTERVAL '1 second')
                        END,
                        updated_at = NOW()
                    WHERE job_id = CAST(:job_id AS uuid) AND status = 'running'
                      AND (
                        CAST(:lease_token AS uuid) IS NULL
                        OR lease_token = CAST(:lease_token AS uuid)
                      )
                    RETURNING *
                    """
                ),
                {
                    "job_id": normalized,
                    "progress": progress,
                    "lease_token": lease_token,
                    "lease_seconds": lease_seconds,
                },
            )
            row = updated.mappings().first()
            if row is None:
                raise AsyncJobStateError("任务当前不可更新进度")
            return self._public(dict(row))

    async def cancel_if_requested(
        self, job_id: str, *, lease_token: str
    ) -> dict[str, Any] | None:
        """Finish a cancellation that won before an external operation starts."""
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            current = await db.execute(
                text(
                    "SELECT * FROM audit.async_jobs "
                    "WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"
                ),
                {"job_id": normalized},
            )
            row = current.mappings().first()
            if row is None:
                raise AsyncJobNotFound("任务不存在")
            record = dict(row)
            if str(record.get("lease_token") or "") != lease_token:
                raise AsyncJobStateError("任务租约已失效")
            if str(record["status"]) == "running":
                return None
            if str(record["status"]) != "cancel_requested":
                raise AsyncJobStateError("任务当前不可确认取消")
            updated = await db.execute(
                text(
                    """
                    UPDATE audit.async_jobs
                    SET status = 'cancelled', error_code = 'JOB_CANCELLED',
                        lease_token = NULL, lease_expires_at = NULL,
                        finished_at = NOW(), updated_at = NOW()
                    WHERE job_id = CAST(:job_id AS uuid)
                    RETURNING *
                    """
                ),
                {"job_id": normalized},
            )
            await self._finish_latest_attempt(
                db, normalized, "cancelled", "JOB_CANCELLED"
            )
            return self._public(dict(updated.mappings().one()))

    async def complete_with_result(
        self,
        job_id: str,
        result_payload: dict[str, Any],
        *,
        lease_token: str,
    ) -> dict[str, Any]:
        """Persist an operation result and its terminal success state atomically."""
        normalized = _as_uuid(job_id)
        result_hash = canonical_input_hash(result_payload)
        encoded_payload = json.dumps(result_payload, ensure_ascii=False, default=str)
        result_ref = f"async_job_results:{normalized}"
        async with get_db() as db:
            current = await db.execute(
                text(
                    "SELECT status, lease_token FROM audit.async_jobs "
                    "WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"
                ),
                {"job_id": normalized},
            )
            row = current.mappings().first()
            if row is None:
                raise AsyncJobNotFound("任务不存在")
            if str(row.get("lease_token") or "") != lease_token:
                raise AsyncJobStateError("任务租约已失效")
            if str(row["status"]) not in {"running", "cancel_requested"}:
                raise AsyncJobStateError("任务当前不可写入结果")
            created = await db.execute(
                text(
                    """
                    INSERT INTO audit.async_job_results (
                        job_id, result_hash, result_payload
                    ) VALUES (
                        CAST(:job_id AS uuid), :result_hash,
                        CAST(:result_payload AS jsonb)
                    )
                    ON CONFLICT (job_id) DO NOTHING
                    RETURNING result_hash
                    """
                ),
                {
                    "job_id": normalized,
                    "result_hash": result_hash,
                    "result_payload": encoded_payload,
                },
            )
            existing = created.mappings().first()
            if existing is None:
                existing_result = await db.execute(
                    text(
                        "SELECT result_hash FROM audit.async_job_results "
                        "WHERE job_id = CAST(:job_id AS uuid)"
                    ),
                    {"job_id": normalized},
                )
                existing = existing_result.mappings().first()
            if existing is None or str(existing["result_hash"]) != result_hash:
                raise AsyncJobStateError("任务结果幂等性冲突")
            updated = await db.execute(
                text(
                    """
                    UPDATE audit.async_jobs
                    SET status = 'succeeded', progress = 100, result_ref = :result_ref,
                        error_code = NULL, lease_token = NULL, lease_expires_at = NULL,
                        finished_at = NOW(), updated_at = NOW()
                    WHERE job_id = CAST(:job_id AS uuid)
                    RETURNING *
                    """
                ),
                {"job_id": normalized, "result_ref": result_ref},
            )
            await self._finish_latest_attempt(db, normalized, "succeeded", None)
            return self._public(dict(updated.mappings().one()))

    async def mark_dispatch_pending(
        self, job_id: str, *, error_code: str
    ) -> dict[str, Any]:
        return await self._mark_dispatch_state(job_id, error_code=error_code)

    async def mark_dispatch_accepted(self, job_id: str) -> dict[str, Any]:
        return await self._mark_dispatch_state(job_id, error_code=None)

    async def _mark_dispatch_state(
        self, job_id: str, *, error_code: str | None
    ) -> dict[str, Any]:
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            current = await db.execute(
                text(
                    "SELECT * FROM audit.async_jobs "
                    "WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"
                ),
                {"job_id": normalized},
            )
            row = current.mappings().first()
            if row is None:
                raise AsyncJobNotFound("任务不存在")
            record = dict(row)
            if str(record["status"]) not in RUNNABLE_STATUSES:
                return self._public(record)
            updated = await db.execute(
                text(
                    """
                    UPDATE audit.async_jobs
                    SET error_code = :error_code, updated_at = NOW()
                    WHERE job_id = CAST(:job_id AS uuid)
                    RETURNING *
                    """
                ),
                {"job_id": normalized, "error_code": error_code},
            )
            return self._public(dict(updated.mappings().one()))

    async def mark_blocked(self, job_id: str, *, error_code: str) -> dict[str, Any]:
        return await self._finish(job_id, status="blocked", error_code=error_code)

    async def mark_dispatch_blocked(
        self, job_id: str, *, error_code: str
    ) -> dict[str, Any]:
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            current = await db.execute(
                text(
                    "SELECT * FROM audit.async_jobs "
                    "WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"
                ),
                {"job_id": normalized},
            )
            row = current.mappings().first()
            if row is None:
                raise AsyncJobNotFound("任务不存在")
            record = dict(row)
            if str(record["status"]) == "blocked":
                return self._public(record)
            if str(record["status"]) not in RUNNABLE_STATUSES:
                raise AsyncJobStateError("任务当前不可标记为分发阻塞")
            updated = await db.execute(
                text(
                    """
                    UPDATE audit.async_jobs
                    SET status = 'blocked', error_code = :error_code,
                        finished_at = NOW(), updated_at = NOW()
                    WHERE job_id = CAST(:job_id AS uuid)
                    RETURNING *
                    """
                ),
                {"job_id": normalized, "error_code": error_code},
            )
            return self._public(dict(updated.mappings().one()))

    async def recover_expired_leases(
        self, *, job_types: set[str], limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return stale operation Jobs to the durable retry queue."""
        if not job_types or not 1 <= limit <= 500:
            raise AsyncJobStateError("任务回收参数非法")
        async with get_db() as db:
            expired = await db.execute(
                text(
                    """
                    SELECT * FROM audit.async_jobs
                    WHERE job_type = ANY(CAST(:job_types AS varchar[]))
                      AND status IN ('running', 'cancel_requested')
                      AND lease_expires_at <= NOW()
                    ORDER BY lease_expires_at, created_at
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"job_types": sorted(job_types), "limit": limit},
            )
            records = [dict(row) for row in expired.mappings().all()]
            recovered: list[dict[str, Any]] = []
            for record in records:
                job_id = str(record["job_id"])
                retry_count = int(record["retry_count"] or 0)
                max_retries = int(record["max_retries"] or 0)
                if str(record["status"]) == "cancel_requested":
                    updated = await db.execute(
                        text(
                            """
                            UPDATE audit.async_jobs
                            SET status = 'cancelled', error_code = 'JOB_CANCELLED',
                                lease_token = NULL, lease_expires_at = NULL,
                                finished_at = NOW(), updated_at = NOW()
                            WHERE job_id = CAST(:job_id AS uuid)
                            RETURNING *
                            """
                        ),
                        {"job_id": job_id},
                    )
                    await self._finish_latest_attempt(
                        db, job_id, "cancelled", "JOB_CANCELLED"
                    )
                elif retry_count < max_retries:
                    updated = await db.execute(
                        text(
                            """
                            UPDATE audit.async_jobs
                            SET status = 'retry_wait',
                                error_code = 'OPERATION_JOB_LEASE_EXPIRED',
                                retry_count = :retry_count, next_retry_at = NOW(),
                                lease_token = NULL, lease_expires_at = NULL,
                                updated_at = NOW()
                            WHERE job_id = CAST(:job_id AS uuid)
                            RETURNING *
                            """
                        ),
                        {"job_id": job_id, "retry_count": retry_count + 1},
                    )
                    await self._finish_latest_attempt(
                        db, job_id, "retry_wait", "OPERATION_JOB_LEASE_EXPIRED"
                    )
                else:
                    updated = await db.execute(
                        text(
                            """
                            UPDATE audit.async_jobs
                            SET status = 'failed',
                                error_code = 'OPERATION_JOB_LEASE_EXPIRED',
                                lease_token = NULL, lease_expires_at = NULL,
                                finished_at = NOW(), updated_at = NOW()
                            WHERE job_id = CAST(:job_id AS uuid)
                            RETURNING *
                            """
                        ),
                        {"job_id": job_id},
                    )
                    await self._finish_latest_attempt(
                        db, job_id, "failed", "OPERATION_JOB_LEASE_EXPIRED"
                    )
                recovered.append(self._public(dict(updated.mappings().one())))
        return recovered

    async def list_dispatchable(
        self, *, job_types: set[str], limit: int = 100
    ) -> list[dict[str, Any]]:
        """List persisted operation Jobs that may be safely dispatched again."""
        if not job_types or not 1 <= limit <= 500:
            raise AsyncJobStateError("任务投递参数非法")
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT * FROM audit.async_jobs
                    WHERE job_type = ANY(CAST(:job_types AS varchar[]))
                      AND (
                        status = 'queued'
                        OR (
                            status = 'retry_wait'
                            AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                        )
                      )
                    ORDER BY created_at, job_id
                    LIMIT :limit
                    """
                ),
                {"job_types": sorted(job_types), "limit": limit},
            )
            return [self._public(dict(row)) for row in result.mappings().all()]

    async def mark_succeeded(self, job_id: str, *, result_ref: str) -> dict[str, Any]:
        return await self._finish(job_id, status="succeeded", result_ref=result_ref)

    async def store_result(self, job_id: str, result_payload: dict[str, Any]) -> str:
        normalized = _as_uuid(job_id)
        result_hash = canonical_input_hash(result_payload)
        encoded_payload = json.dumps(result_payload, ensure_ascii=False, default=str)
        async with get_db() as db:
            current = await db.execute(
                text(
                    "SELECT status FROM audit.async_jobs "
                    "WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"
                ),
                {"job_id": normalized},
            )
            row = current.mappings().first()
            if row is None:
                raise AsyncJobNotFound("任务不存在")
            if str(row["status"]) != "running":
                raise AsyncJobStateError("任务当前不可写入结果")
            created = await db.execute(
                text(
                    """
                    INSERT INTO audit.async_job_results (
                        job_id, result_hash, result_payload
                    ) VALUES (
                        CAST(:job_id AS uuid), :result_hash,
                        CAST(:result_payload AS jsonb)
                    )
                    ON CONFLICT (job_id) DO NOTHING
                    RETURNING result_hash
                    """
                ),
                {
                    "job_id": normalized,
                    "result_hash": result_hash,
                    "result_payload": encoded_payload,
                },
            )
            existing = created.mappings().first()
            if existing is None:
                existing_result = await db.execute(
                    text(
                        "SELECT result_hash FROM audit.async_job_results "
                        "WHERE job_id = CAST(:job_id AS uuid)"
                    ),
                    {"job_id": normalized},
                )
                existing = existing_result.mappings().first()
            if existing is None or str(existing["result_hash"]) != result_hash:
                raise AsyncJobStateError("任务结果幂等性冲突")
        return f"async_job_results:{normalized}"

    async def get_result(self, job_id: str, principal: Principal) -> dict[str, Any]:
        job = await self.get(job_id, principal)
        normalized = _as_uuid(job_id)
        expected_ref = f"async_job_results:{normalized}"
        if job["status"] != "succeeded" or job.get("result_ref") != expected_ref:
            raise AsyncJobResultUnavailable("任务尚未产生可读取的结果")
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT result_hash, result_payload, created_at
                    FROM audit.async_job_results
                    WHERE job_id = CAST(:job_id AS uuid)
                    """
                ),
                {"job_id": normalized},
            )
            row = result.mappings().first()
        if row is None:
            raise AsyncJobResultUnavailable("任务结果记录不可用")
        record = dict(row)
        return {
            "job": job,
            "result": _as_mapping(record["result_payload"]),
            "result_hash": str(record["result_hash"]),
            "result_created_at": _iso(record.get("created_at")),
        }

    async def mark_failure(
        self,
        job_id: str,
        *,
        error_code: str,
        retryable: bool,
        lease_token: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        error_stage: str | None = None,
        traceback_summary: str | None = None,
    ) -> dict[str, Any]:
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            result = await db.execute(
                text(
                    "SELECT * FROM audit.async_jobs WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"
                ),
                {"job_id": normalized},
            )
            row = result.mappings().first()
            if row is None:
                raise AsyncJobNotFound("任务不存在")
            record = dict(row)
            if lease_token is not None and str(record.get("lease_token") or "") != lease_token:
                raise AsyncJobStateError("任务租约已失效")
            state = str(record["status"])
            if state == "cancel_requested":
                return await self._finish_in_transaction(
                    db, normalized, "cancelled", "JOB_CANCELLED"
                )
            if state != "running":
                raise AsyncJobStateError(f"任务当前不可标记失败: {state}")

            retry_count = int(record["retry_count"] or 0)
            max_retries = int(record["max_retries"] or 0)
            await self._record_attempt_diagnostics(
                db,
                normalized,
                error_type=error_type,
                error_message=error_message,
                error_stage=error_stage,
                traceback_summary=traceback_summary,
            )
            if retryable and retry_count < max_retries:
                new_retry_count = retry_count + 1
                delay_seconds = min(300, 15 * (2 ** (new_retry_count - 1)))
                updated = await db.execute(
                    text(
                        """
                        UPDATE audit.async_jobs
                        SET status = 'retry_wait', error_code = :error_code,
                            retry_count = :retry_count,
                            next_retry_at = NOW() + (:delay_seconds * INTERVAL '1 second'),
                            lease_token = NULL, lease_expires_at = NULL,
                            updated_at = NOW()
                        WHERE job_id = CAST(:job_id AS uuid)
                        RETURNING *
                        """
                    ),
                    {
                        "job_id": normalized,
                        "error_code": error_code,
                        "retry_count": new_retry_count,
                        "delay_seconds": delay_seconds,
                    },
                )
                await self._finish_latest_attempt(
                    db, normalized, "retry_wait", error_code
                )
                return self._public(dict(updated.mappings().one()))
            return await self._finish_in_transaction(
                db, normalized, "failed", error_code, lease_token=lease_token
            )

    async def mark_stage(
        self, job_id: str, stage: str, *, celery_task_id: str | None = None
    ) -> None:
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            await db.execute(
                text(
                    "UPDATE audit.async_jobs SET last_stage = :stage, updated_at = NOW() "
                    "WHERE job_id = CAST(:job_id AS uuid)"
                ),
                {"job_id": normalized, "stage": stage[:64]},
            )
            await db.execute(
                text(
                    "UPDATE audit.async_job_attempts SET last_stage = :stage, "
                    "celery_task_id = COALESCE(:celery_task_id, celery_task_id) "
                    "WHERE attempt_id = (SELECT attempt_id FROM audit.async_job_attempts "
                    "WHERE job_id = CAST(:job_id AS uuid) ORDER BY attempt_number DESC LIMIT 1)"
                ),
                {"job_id": normalized, "stage": stage[:64], "celery_task_id": celery_task_id},
            )

    async def _record_attempt_diagnostics(
        self,
        db: Any,
        job_id: str,
        *,
        error_type: str | None,
        error_message: str | None,
        error_stage: str | None,
        traceback_summary: str | None,
    ) -> None:
        await db.execute(
            text(
                "UPDATE audit.async_job_attempts SET error_type = :error_type, "
                "error_message = :error_message, error_stage = :error_stage, "
                "traceback_summary = :traceback_summary "
                "WHERE attempt_id = (SELECT attempt_id FROM audit.async_job_attempts "
                "WHERE job_id = CAST(:job_id AS uuid) ORDER BY attempt_number DESC LIMIT 1)"
            ),
            {
                "job_id": job_id,
                "error_type": (error_type or "")[:128] or None,
                "error_message": (error_message or "")[:512] or None,
                "error_stage": (error_stage or "")[:64] or None,
                "traceback_summary": (traceback_summary or "")[:4096] or None,
            },
        )

    async def _finish(
        self,
        job_id: str,
        status: str,
        error_code: str | None = None,
        result_ref: str | None = None,
    ) -> dict[str, Any]:
        normalized = _as_uuid(job_id)
        async with get_db() as db:
            return await self._finish_in_transaction(
                db,
                normalized,
                status,
                error_code,
                result_ref=result_ref,
            )

    async def _finish_in_transaction(
        self,
        db: Any,
        job_id: str,
        status: str,
        error_code: str | None,
        *,
        result_ref: str | None = None,
        lease_token: str | None = None,
    ) -> dict[str, Any]:
        current = await db.execute(
            text("SELECT status FROM audit.async_jobs WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"),
            {"job_id": job_id},
        )
        row = current.mappings().first()
        if row is None:
            raise AsyncJobNotFound("任务不存在")
        current_status = str(row["status"])
        if lease_token is not None:
            lease = await db.execute(
                text(
                    "SELECT lease_token FROM audit.async_jobs "
                    "WHERE job_id = CAST(:job_id AS uuid)"
                ),
                {"job_id": job_id},
            )
            lease_row = lease.mappings().first()
            if lease_row is None or str(lease_row.get("lease_token") or "") != lease_token:
                raise AsyncJobStateError("任务租约已失效")
        if current_status not in {"running", "cancel_requested"}:
            raise AsyncJobStateError(f"任务当前不可完成: {current_status}")
        final_status = status
        final_error_code = error_code
        if current_status == "cancel_requested":
            final_status = "cancelled"
            final_error_code = "JOB_CANCELLED"
            result_ref = None
        updated = await db.execute(
            text(
                """
                UPDATE audit.async_jobs
                SET status = CAST(:status AS varchar),
                    progress = CASE WHEN CAST(:status AS varchar) = 'succeeded' THEN 100 ELSE progress END,
                    result_ref = :result_ref, error_code = :error_code,
                    lease_token = NULL, lease_expires_at = NULL,
                    finished_at = NOW(), updated_at = NOW()
                WHERE job_id = CAST(:job_id AS uuid)
                RETURNING *
                """
            ),
            {
                "job_id": job_id,
                "status": final_status,
                "result_ref": result_ref,
                "error_code": final_error_code,
            },
        )
        await self._finish_latest_attempt(db, job_id, final_status, final_error_code)
        return self._public(dict(updated.mappings().one()))

    async def _finish_latest_attempt(
        self, db: Any, job_id: str, status: str, error_code: str | None
    ) -> None:
        await db.execute(
            text(
                """
                UPDATE audit.async_job_attempts
                SET status = :status, error_code = :error_code, finished_at = NOW()
                WHERE attempt_id = (
                    SELECT attempt_id FROM audit.async_job_attempts
                    WHERE job_id = CAST(:job_id AS uuid)
                    ORDER BY attempt_number DESC
                    LIMIT 1
                )
                """
            ),
            {"job_id": job_id, "status": status, "error_code": error_code},
        )

    async def _select_visible(
        self, db: Any, job_id: str, principal: Principal, *, for_update: bool = False
    ) -> dict[str, Any]:
        access_all = principal.role in _PRIVILEGED_JOB_ROLES
        suffix = " FOR UPDATE" if for_update else ""
        result = await db.execute(
            text(
                """
                SELECT * FROM audit.async_jobs
                WHERE job_id = CAST(:job_id AS uuid)
                  AND (
                    requester_principal_id = CAST(:principal_id AS uuid)
                    OR :access_all
                  )
                """
                + suffix
            ),
            {
                "job_id": job_id,
                "principal_id": principal.principal_id,
                "access_all": access_all,
            },
        )
        row = result.mappings().first()
        if row is None:
            raise AsyncJobNotFound("任务不存在或无权访问")
        return dict(row)

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": str(row["job_id"]),
            "job_type": str(row["job_type"]),
            "status": str(row["status"]),
            "progress": int(row["progress"] or 0),
            "input_hash": str(row["input_hash"]),
            "result_ref": row.get("result_ref"),
            "error_code": row.get("error_code"),
            "retry": {
                "count": int(row["retry_count"] or 0),
                "max_retries": int(row["max_retries"] or 0),
                "next_retry_at": _iso(row.get("next_retry_at")),
            },
            "created_at": _iso(row.get("created_at")),
            "started_at": _iso(row.get("started_at")),
            "finished_at": _iso(row.get("finished_at")),
            "cancel_requested_at": _iso(row.get("cancel_requested_at")),
        }
