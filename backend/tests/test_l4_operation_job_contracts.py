import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI


os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "l4-operation-job-contract-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.api import ai, jobs, stock, trade  # noqa: E402
from app.core.auth import Principal, ROLE_SCOPES, route_access  # noqa: E402
from app.core.response import register_exception_handlers  # noqa: E402
from app.jobs.dispatch import OperationJobDispatchError  # noqa: E402
from app.jobs.service import AsyncJobStateError, AsyncJobStore  # noqa: E402
from app.jobs.operations import (  # noqa: E402
    OperationJobInputError,
    OperationJobPermanentFailure,
    OperationJobService,
    OperationJobUnsupported,
    OperationJobWorkerForbidden,
)
from app.trade.execution_authorization import ExecutionAuthorizationError  # noqa: E402


JOB_ID = "2cfb98c0-5a7a-4c4b-8cf2-4c689dfa14f6"


def principal(*, role="strategy_admin", principal_type="human"):
    return Principal(
        principal_id=str(uuid4()),
        display_name="l4-operation-contract",
        principal_type=principal_type,
        role=role,
        scopes=ROLE_SCOPES[role],
        source="credential",
        credential_id=str(uuid4()),
    )


def send(app, method, path, **kwargs):
    async def _send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_send())


def operation_job(job_type):
    return {
        "job_id": JOB_ID,
        "job_type": job_type,
        "status": "queued",
        "progress": 0,
        "result_ref": None,
    }


class _SubmitService:
    def __init__(self, job_type, *, created=True):
        self.job_type = job_type
        self.created = created
        self.kwargs = None

    async def submit(self, **kwargs):
        self.kwargs = kwargs
        return operation_job(self.job_type), self.created


class _JobsApiService:
    async def get_status(self, job_id, request_principal):
        return {**operation_job("market.sync_universe"), "job_id": job_id, "principal": request_principal.principal_id}

    async def get_result(self, job_id, request_principal):
        return {
            "job": {**operation_job("market.sync_universe"), "job_id": job_id},
            "result": {"accepted": True},
        }

    async def cancel(self, job_id, request_principal):
        return {**operation_job("market.sync_universe"), "job_id": job_id, "status": "cancel_requested"}

    async def execute(self, job_id, worker):
        return {**operation_job("market.sync_universe"), "job_id": job_id, "status": "succeeded"}


class _OperationStore:
    def __init__(self, *, current_job=None, created=True):
        self.current_job = current_job or operation_job("market.sync_universe")
        self.created = created
        self.calls = []

    async def enqueue(self, **kwargs):
        self.calls.append(("enqueue", kwargs))
        return operation_job(kwargs["job_type"]), self.created

    async def get(self, job_id, request_principal):
        self.calls.append(("get", job_id, request_principal.principal_id))
        return dict(self.current_job)

    async def claim(self, job_id, worker):
        self.calls.append(("claim", job_id, worker.principal_id))
        return dict(self.current_job)


class _LeaseExecutionStore:
    def __init__(self, *, cancellation=None):
        self.current_job = {
            **operation_job("market.sync_universe"),
            "status": "running",
            "lease_token": "current-lease-token",
        }
        self.cancellation = cancellation
        self.calls = []

    async def get(self, job_id, request_principal):
        self.calls.append(("get", job_id))
        return dict(self.current_job)

    async def claim(self, job_id, worker, *, lease_seconds):
        self.calls.append(("claim", job_id, lease_seconds))
        return dict(self.current_job)

    async def cancel_if_requested(self, job_id, *, lease_token):
        self.calls.append(("cancel_if_requested", job_id, lease_token))
        return self.cancellation

    async def update_progress(self, job_id, progress, *, lease_token, lease_seconds):
        self.calls.append(("progress", job_id, progress, lease_token, lease_seconds))
        return dict(self.current_job)

    async def complete_with_result(self, job_id, result, *, lease_token):
        self.calls.append(("complete", job_id, result, lease_token))
        return {**self.current_job, "status": "succeeded", "result_ref": "async_job_results:test"}

    async def mark_stage(self, job_id, stage, *, celery_task_id=None):
        self.calls.append(("stage", job_id, stage, celery_task_id))

    async def mark_failure(self, job_id, **kwargs):
        self.calls.append(("failure", job_id, kwargs))
        return {**self.current_job, "status": "failed"}


class _TransactionContext:
    def __init__(self):
        self.db = object()
        self.exit_error = None

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, _traceback):
        self.exit_error = exc
        return False


class _ReconcileStore:
    def __init__(self):
        self.enqueue_kwargs = None
        self.bind_kwargs = None
        self.dispatch_accepted = None

    async def enqueue(self, **kwargs):
        self.enqueue_kwargs = kwargs
        return operation_job("trade.reconcile"), True

    async def bind_operation_approval(self, db, **kwargs):
        self.bind_kwargs = {"db": db, **kwargs}

    async def mark_dispatch_accepted(self, job_id):
        self.dispatch_accepted = job_id
        return operation_job("trade.reconcile")


class _ApprovedAuthorization:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.kwargs = None

    async def consume_operation_approval(self, db, **kwargs):
        self.kwargs = {"db": db, **kwargs}
        if self.failure is not None:
            raise self.failure
        return {"approval_id": "7a10f24b-21a4-4b8e-af42-00af1d1c0c42"}


class L4OperationJobContracts(unittest.TestCase):
    def _submit_response(self, module, router, prefix, method_path, job_type, *, params=None, json=None, created=True):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix=prefix)
        fake = _SubmitService(job_type, created=created)
        with patch.object(module, "OperationJobService", return_value=fake), patch.object(
            module, "get_request_principal", return_value=principal()
        ):
            response = send(
                app,
                "POST",
                method_path,
                headers={"Idempotency-Key": "operation-job-key-0001"},
                params=params,
                json=json,
            )
        return response, fake

    def test_stock_sync_returns_202_location_and_idempotency_contract(self):
        response, fake = self._submit_response(
            stock,
            stock.router,
            "/api/v1/stock",
            "/api/v1/stock/sync-universe",
            "market.sync_universe",
            params={"backfill_top_n": 3, "allow_synthetic": "false"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["location"], f"/api/v1/jobs/{JOB_ID}")
        self.assertEqual(response.json()["data"]["location"], f"/api/v1/jobs/{JOB_ID}")
        self.assertFalse(response.json()["data"]["idempotent_replay"])
        self.assertEqual(fake.kwargs["job_type"], "market.sync_universe")
        self.assertEqual(fake.kwargs["payload"]["backfill_top_n"], 3)

    def test_kline_backfill_returns_202_location_and_idempotency_contract(self):
        response, fake = self._submit_response(
            stock,
            stock.router,
            "/api/v1/stock",
            "/api/v1/stock/backfill-kline",
            "market.backfill_kline",
            json={"codes": ["000001.SZ"], "limit": 250, "concurrency": 2},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["location"], f"/api/v1/jobs/{JOB_ID}")
        self.assertFalse(response.json()["data"]["idempotent_replay"])
        self.assertEqual(fake.kwargs["payload"]["codes"], ["000001.SZ"])

    def test_ai_analyze_returns_202_location_and_idempotency_contract(self):
        response, fake = self._submit_response(
            ai,
            ai.router,
            "/api/v1/ai",
            "/api/v1/ai/000001.SZ/analyze",
            "ai.analyze",
            params={"force_refresh": "true", "strategy_id": 7},
            created=False,
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["location"], f"/api/v1/jobs/{JOB_ID}")
        self.assertTrue(response.json()["data"]["idempotent_replay"])
        self.assertEqual(fake.kwargs["payload"], {"code": "000001.SZ", "force_refresh": True, "strategy_id": 7})

    def test_order_sync_returns_202_location_and_idempotency_contract(self):
        response, fake = self._submit_response(
            trade,
            trade.router,
            "/api/v1/trade",
            "/api/v1/trade/orders/sync",
            "trade.orders_sync",
            params={"mode": "paper"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["location"], f"/api/v1/jobs/{JOB_ID}")
        self.assertFalse(response.json()["data"]["idempotent_replay"])
        self.assertEqual(fake.kwargs["payload"], {"mode": "paper"})

    def test_generic_job_status_result_cancel_and_execute_routes_are_distinct(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(jobs.router, prefix="/api/v1/jobs")
        fake = _JobsApiService()
        request_principal = principal()
        with patch("app.api.jobs.OperationJobService", return_value=fake), patch(
            "app.api.jobs.get_request_principal", return_value=request_principal
        ):
            status = send(app, "GET", f"/api/v1/jobs/{JOB_ID}")
            result = send(app, "GET", f"/api/v1/jobs/{JOB_ID}/result")
            cancel = send(app, "POST", f"/api/v1/jobs/{JOB_ID}/cancel")
            execute = send(app, "POST", f"/api/v1/jobs/{JOB_ID}/execute")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(result.json()["data"]["result"], {"accepted": True})
        self.assertEqual(cancel.json()["data"]["status"], "cancel_requested")
        self.assertEqual(execute.json()["data"]["status"], "succeeded")

    def test_job_route_scopes_and_roles_protect_execution(self):
        self.assertEqual(route_access("GET", f"/api/v1/jobs/{JOB_ID}").scope, "jobs:read")
        self.assertEqual(route_access("POST", f"/api/v1/jobs/{JOB_ID}/cancel").scope, "jobs:cancel")
        self.assertEqual(route_access("POST", f"/api/v1/jobs/{JOB_ID}/execute").scope, "jobs:execute")
        self.assertIn("jobs:execute", ROLE_SCOPES["service_worker"])
        self.assertNotIn("jobs:execute", ROLE_SCOPES["strategy_admin"])
        self.assertNotIn("jobs:execute", ROLE_SCOPES["data_operator"])

    def test_only_service_worker_can_execute_operation_job(self):
        store = _OperationStore()
        service = OperationJobService(store=store)
        with self.assertRaises(OperationJobWorkerForbidden):
            asyncio.run(service.execute(JOB_ID, principal()))
        self.assertEqual(store.calls, [])

    def test_non_operation_jobs_are_rejected_before_claim(self):
        store = _OperationStore(current_job=operation_job("backtest.run"))
        worker = principal(role="service_worker", principal_type="service")
        with self.assertRaises(OperationJobUnsupported):
            asyncio.run(OperationJobService(store=store).execute(JOB_ID, worker))
        self.assertEqual([call[0] for call in store.calls], ["get"])

    def test_submission_replay_never_dispatches_again(self):
        store = _OperationStore(created=False)
        service = OperationJobService(store=store)
        with patch("app.jobs.operations.dispatch_operation_job") as dispatch:
            job, created = asyncio.run(
                service.submit(
                    job_type="trade.orders_sync",
                    principal=principal(),
                    idempotency_key="operation-job-key-0002",
                    payload={"mode": "paper"},
                )
            )
        self.assertFalse(created)
        self.assertEqual(job["job_type"], "trade.orders_sync")
        dispatch.assert_not_called()

    def test_dispatch_failure_marks_persisted_job_pending_for_recovery(self):
        store = _OperationStore()
        store.mark_dispatch_pending = AsyncMock(return_value={"status": "dispatch_pending"})
        service = OperationJobService(store=store)
        with patch(
            "app.jobs.operations.dispatch_operation_job",
            side_effect=OperationJobDispatchError("broker unavailable"),
        ):
            result = asyncio.run(service.dispatch(operation_job("market.sync_universe")))
        self.assertEqual(result["status"], "dispatch_pending")
        store.mark_dispatch_pending.assert_awaited_once_with(
            JOB_ID, error_code="OPERATION_JOB_DISPATCH_PENDING"
        )

    def test_cancellation_before_external_operation_finishes_without_execution(self):
        cancelled = {**operation_job("market.sync_universe"), "status": "cancelled"}
        store = _LeaseExecutionStore(cancellation=cancelled)
        worker = principal(role="service_worker", principal_type="service")
        executor = AsyncMock(return_value={"should_not": "run"})
        with patch.object(OperationJobService, "_execute_claimed", executor):
            result = asyncio.run(OperationJobService(store=store).execute(JOB_ID, worker))
        self.assertEqual(result["status"], "cancelled")
        executor.assert_not_awaited()
        self.assertEqual([call[0] for call in store.calls], ["get", "claim", "cancel_if_requested"])

    def test_late_cancellation_does_not_hide_completed_result(self):
        store = _LeaseExecutionStore(cancellation=None)
        worker = principal(role="service_worker", principal_type="service")
        executor = AsyncMock(return_value={"external": "completed"})
        with patch.object(OperationJobService, "_execute_claimed", executor):
            result = asyncio.run(OperationJobService(store=store).execute(JOB_ID, worker))
        self.assertEqual(result["status"], "succeeded")
        executor.assert_awaited_once()
        self.assertEqual(store.calls[-1], ("complete", JOB_ID, {"external": "completed"}, "current-lease-token"))

    def test_zero_write_kline_backfill_is_a_non_retryable_job_failure(self):
        store = _LeaseExecutionStore(cancellation=None)
        store.current_job["job_type"] = "market.backfill_kline"
        worker = principal(role="service_worker", principal_type="service")
        executor = AsyncMock(
            side_effect=OperationJobPermanentFailure(
                "KLINE_BACKFILL_NO_DATA", "K线回填未写入任何有效数据"
            )
        )
        with patch.object(OperationJobService, "_execute_claimed", executor):
            result = asyncio.run(OperationJobService(store=store).execute(JOB_ID, worker))

        self.assertEqual(result["status"], "failed")
        failure = store.calls[-1]
        self.assertEqual(failure[0], "failure")
        self.assertEqual(failure[2]["error_code"], "KLINE_BACKFILL_NO_DATA")
        self.assertFalse(failure[2]["retryable"])

    def test_terminal_job_status_sql_casts_reused_status_parameter(self):
        source = (REPO_ROOT / "backend" / "app" / "jobs" / "service.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("SET status = CAST(:status AS varchar)", source)
        self.assertIn("CASE WHEN CAST(:status AS varchar) = 'succeeded'", source)

    def test_stale_lease_cannot_write_progress_or_result(self):
        source = (REPO_ROOT / "backend" / "app" / "jobs" / "service.py").read_text(encoding="utf-8")
        progress_section = source[source.index("async def update_progress") : source.index("async def cancel_if_requested")]
        complete_section = source[source.index("async def complete_with_result") : source.index("async def mark_dispatch_pending")]
        self.assertIn("lease_token = CAST(:lease_token AS uuid)", progress_section)
        self.assertIn("SELECT status, lease_token", complete_section)
        self.assertIn("FOR UPDATE", complete_section)
        self.assertIn("str(row.get(\"lease_token\") or \"\") != lease_token", complete_section)

    def test_completion_persists_result_and_success_in_one_transaction(self):
        source = (REPO_ROOT / "backend" / "app" / "jobs" / "service.py").read_text(encoding="utf-8")
        section = source[source.index("async def complete_with_result") : source.index("async def mark_dispatch_pending")]
        self.assertIn("async with get_db() as db", section)
        self.assertIn("INSERT INTO audit.async_job_results", section)
        self.assertIn("UPDATE audit.async_jobs", section)
        self.assertIn("status = 'succeeded'", section)
        self.assertIn('{"running", "cancel_requested"}', section)
        self.assertLess(section.index("INSERT INTO audit.async_job_results"), section.index("status = 'succeeded'"))

    def test_operation_recovery_is_scheduler_driven_without_fixed_celery_retry(self):
        task_source = (REPO_ROOT / "worker" / "tasks" / "jobs.py").read_text(encoding="utf-8")
        celery_source = (REPO_ROOT / "worker" / "celery_app.py").read_text(encoding="utf-8")
        operation_source = (REPO_ROOT / "backend" / "app" / "jobs" / "operations.py").read_text(encoding="utf-8")
        store_source = (REPO_ROOT / "backend" / "app" / "jobs" / "service.py").read_text(encoding="utf-8")
        recovery_section = store_source[
            store_source.index("async def recover_expired_leases") : store_source.index("async def list_dispatchable")
        ]
        self.assertIn('name="tasks.recover_operation_jobs"', task_source)
        self.assertIn("OperationJobService().recover_and_dispatch()", task_source)
        self.assertIn('"recover-operation-jobs-30s"', celery_source)
        self.assertIn('"task": "tasks.recover_operation_jobs"', celery_source)
        self.assertIn('"schedule": 30.0', celery_source)
        self.assertNotIn("self.retry", task_source)
        self.assertNotIn("countdown=15", task_source)
        self.assertIn("recover_expired_leases", operation_source)
        self.assertIn("list_dispatchable", operation_source)
        self.assertIn("status IN ('running', 'cancel_requested')", recovery_section)
        self.assertIn("if str(record[\"status\"]) == \"cancel_requested\"", recovery_section)
        self.assertIn("status = 'cancelled', error_code = 'JOB_CANCELLED'", recovery_section)

    def test_recovery_and_approval_binding_migrations_are_non_destructive(self):
        recovery = (REPO_ROOT / "backend" / "alembic" / "versions" / "032_operation_job_recovery.py").read_text(encoding="utf-8")
        approval = (REPO_ROOT / "backend" / "alembic" / "versions" / "033_operation_job_approval_binding.py").read_text(encoding="utf-8")
        for fragment in (
            'revision = "032"',
            'down_revision = "031"',
            "lease_token UUID",
            "lease_expires_at TIMESTAMPTZ",
            "WHERE status = 'running'",
            "raise RuntimeError",
        ):
            self.assertIn(fragment, recovery)
        for fragment in (
            'revision = "033"',
            'down_revision = "032"',
            "operation_approval_id UUID",
            "REFERENCES trade.execution_approvals(approval_id) ON DELETE RESTRICT",
            "UNIQUE INDEX uq_async_jobs_operation_approval",
            "raise RuntimeError",
        ):
            self.assertIn(fragment, approval)

    def test_reconcile_approval_failure_escapes_the_same_transaction_scope(self):
        context = _TransactionContext()
        store = _ReconcileStore()
        authorization = _ApprovedAuthorization(
            failure=ExecutionAuthorizationError("APPROVAL_INVALID", "approval rejected")
        )
        service = OperationJobService(store=store)
        with patch("app.jobs.operations.get_db", return_value=context), patch(
            "app.jobs.operations.ExecutionAuthorizationService", return_value=authorization
        ), patch("app.jobs.operations.dispatch_operation_job") as dispatch:
            with self.assertRaises(OperationJobInputError):
                asyncio.run(
                    service.submit_reconcile(
                        principal=principal(),
                        idempotency_key="reconcile-approval-failure-0001",
                        mode="paper",
                        approval_id="1d7b89d6-b77f-4fd9-a7e4-ae57db1a325e",
                    )
                )
        self.assertIsInstance(context.exit_error, ExecutionAuthorizationError)
        self.assertIs(store.enqueue_kwargs["db"], context.db)
        dispatch.assert_not_called()

    def test_reconcile_binds_approval_to_job_and_worker_rechecks_it(self):
        context = _TransactionContext()
        store = _ReconcileStore()
        authorization = _ApprovedAuthorization()
        request_principal = principal()
        service = OperationJobService(store=store)
        with patch("app.jobs.operations.get_db", return_value=context), patch(
            "app.jobs.operations.ExecutionAuthorizationService", return_value=authorization
        ), patch("app.jobs.operations.dispatch_operation_job"):
            job, created = asyncio.run(
                service.submit_reconcile(
                    principal=request_principal,
                    idempotency_key="reconcile-approval-binding-0001",
                    mode="paper",
                    approval_id="1d7b89d6-b77f-4fd9-a7e4-ae57db1a325e",
                )
            )
        self.assertTrue(created)
        self.assertEqual(job["job_type"], "trade.reconcile")
        self.assertIs(store.bind_kwargs["db"], context.db)
        self.assertEqual(store.bind_kwargs["job_id"], JOB_ID)
        self.assertEqual(authorization.kwargs["job_id"], JOB_ID)
        self.assertEqual(store.bind_kwargs["approval_id"], "7a10f24b-21a4-4b8e-af42-00af1d1c0c42")
        operation_source = (REPO_ROOT / "backend" / "app" / "jobs" / "operations.py").read_text(encoding="utf-8")
        self.assertIn("verify_consumed_operation_approval", operation_source)
        self.assertIn("job_id=job_id", operation_source)

    def test_operation_payload_validation_is_fail_closed(self):
        normalize = OperationJobService._normalize_payload
        with self.assertRaises(OperationJobInputError):
            normalize("market.backfill_kline", {"codes": "000001.SZ"})
        with self.assertRaises(OperationJobInputError):
            normalize("market.backfill_kline", {"codes": [None], "limit": 250})
        with self.assertRaises(OperationJobInputError):
            normalize("ai.analyze", {"code": "", "strategy_id": 1})
        with self.assertRaises(OperationJobInputError):
            normalize("trade.orders_sync", {"mode": "simulation"})
        with self.assertRaises(OperationJobUnsupported):
            normalize("unknown.operation", {})

    def test_operation_results_migration_is_append_only_and_restrictive(self):
        source = (REPO_ROOT / "backend" / "alembic" / "versions" / "031_operation_job_results.py").read_text(encoding="utf-8")
        for fragment in (
            'revision = "031"',
            'down_revision = "030"',
            "CREATE TABLE audit.async_job_results",
            "REFERENCES audit.async_jobs(job_id) ON DELETE RESTRICT",
            "result_hash CHAR(64)",
            "result_payload JSONB NOT NULL",
            "REVOKE UPDATE, DELETE",
            "raise RuntimeError",
        ):
            self.assertIn(fragment, source)

    def test_http_routes_do_not_run_long_operation_inline(self):
        stock_source = (REPO_ROOT / "backend" / "app" / "api" / "stock.py").read_text(encoding="utf-8")
        sync_section = stock_source[stock_source.index("async def sync_stock_universe") : stock_source.index('@router.get("/list")')]
        backfill_section = stock_source[stock_source.index("async def backfill_kline") : stock_source.index('@router.get("/{code}/profile")')]
        ai_source = (REPO_ROOT / "backend" / "app" / "api" / "ai.py").read_text(encoding="utf-8")
        ai_start = ai_source.index("async def analyze_stock")
        ai_section = ai_source[ai_start : ai_source.index('@router.get(', ai_start)]
        trade_source = (REPO_ROOT / "backend" / "app" / "api" / "trade.py").read_text(encoding="utf-8")
        order_section = trade_source[trade_source.index("async def sync_open_orders") : trade_source.index('@router.post("/orders/{order_id}/sync")')]
        for section in (sync_section, backfill_section, ai_section, order_section):
            self.assertIn("OperationJobService", section)
            self.assertIn('response.headers["Location"]', section)
        self.assertNotIn("seed_stocks", sync_section)
        operation_source = (REPO_ROOT / "backend" / "app" / "jobs" / "operations.py").read_text(encoding="utf-8")
        self.assertIn("seed_stocks(refresh_source=True)", operation_source)
        self.assertNotIn("KlineBackfillService", backfill_section)
        self.assertNotIn("AIService().analyze", ai_section)
        self.assertNotIn("sync_open_orders(", order_section.split("OperationJobService", 1)[1])

    def test_worker_uses_authenticated_service_worker_boundary(self):
        source = (REPO_ROOT / "worker" / "tasks" / "jobs.py").read_text(encoding="utf-8")
        for fragment in (
            'name="tasks.execute_operation_job"',
            "worker_api_headers()",
            "AuthService().authenticate",
            "await service.store.mark_stage",
            '"worker_authenticated"',
            "return await service.execute(job_id, principal)",
            "operation_job_duplicate_ignored",
        ):
            self.assertIn(fragment, source)
        self.assertNotIn("HttpBackendClient", source)


if __name__ == "__main__":
    unittest.main()
