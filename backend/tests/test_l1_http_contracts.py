import asyncio
import os
import unittest
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, HTTPException, Query

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "l1-http-contract-test-secret"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["API_ALLOW_ANONYMOUS_READS"] = "true"

from app.core.auth import Principal, set_auth_service_for_testing  # noqa: E402
from app.core.response import APIProblem, error, ok, register_exception_handlers  # noqa: E402
from app.api import ai as ai_api, stock as stock_api, trade as trade_api  # noqa: E402
from app.data.client import DataFetchResult  # noqa: E402
from app.main import app  # noqa: E402


LEGACY_EXECUTION_MUTATIONS = {
    "/api/v1/backtest/run": "backtest:run",
    "/api/v1/ai/600000.SH/analyze": "ai:run",
    "/api/v1/trade/order": "trade:order.create",
    "/api/v1/trade/simulation/release-t1": "trade:simulation.operate",
    "/api/v1/trade/order/cancel": "trade:order.cancel",
    "/api/v1/trade/orders/sync": "trade:broker.sync",
    "/api/v1/trade/orders/order-contract/sync": "trade:broker.sync",
    "/api/v1/trade/reconcile": "trade:reconcile",
    "/api/v1/jobs/2cfb98c0-5a7a-4c4b-8cf2-4c689dfa14f6/cancel": "jobs:cancel",
    "/api/v1/jobs/2cfb98c0-5a7a-4c4b-8cf2-4c689dfa14f6/execute": "jobs:execute",
}


def request(application: FastAPI, method: str, path: str, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


class HttpContractTests(unittest.TestCase):
    def test_market_read_routes_preserve_typed_data_contracts(self):
        class StockService:
            async def get_stock_list(self, **_kwargs):
                return {"total": 1, "items": [{"code": "000001", "name": "平安银行"}]}

            async def get_quote_result(self, _code):
                return DataFetchResult(
                    status="success",
                    data={"code": "000001", "price": 10.5},
                    provenance={"source": "database", "quality_status": "observed"},
                )

            async def get_kline(self, _code, _period, _limit, _adj):
                return [{"date": "2026-07-18", "close": 10.5}]

            async def get_fund_flow_result(self, _code, _days):
                return DataFetchResult(status="no_data", data=[], error_code="NO_DATA")

            async def get_news_result(self, _code, _limit):
                return DataFetchResult(
                    status="no_data",
                    data=[],
                    error_code="NO_DATA",
                    provenance={"content_scope": "announcement_compatibility_only"},
                )

        app.dependency_overrides[stock_api.get_stock_service] = StockService
        try:
            listing = request(app, "GET", "/api/v1/stock/list?page=1&page_size=5")
            quote = request(app, "GET", "/api/v1/stock/000001/quote")
            kline = request(app, "GET", "/api/v1/stock/000001/kline?period=1d&limit=5&adj=qfq")
            fund_flow = request(app, "GET", "/api/v1/stock/000001/fund-flow?days=5")
            news = request(app, "GET", "/api/v1/stock/000001/news?limit=5")
        finally:
            app.dependency_overrides.pop(stock_api.get_stock_service, None)

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["data"]["total"], 1)
        self.assertEqual(quote.headers["X-Data-Status"], "success")
        self.assertEqual(quote.json()["data"]["price"], 10.5)
        self.assertEqual(kline.json()["data"][0]["close"], 10.5)
        self.assertEqual(fund_flow.headers["X-Data-Status"], "no_data")
        self.assertEqual(fund_flow.json()["data"], [])
        self.assertEqual(news.headers["X-Data-Content-Scope"], "announcement_compatibility_only")
        self.assertEqual(news.json()["data"], [])

    def test_ai_signal_read_routes_keep_empty_signal_and_history_contracts(self):
        class AIService:
            async def get_current_valid_signal(self, _code):
                return None

            async def get_signal_history(self, code, *, days):
                return SimpleNamespace(
                    model_dump=lambda: {"stock_code": code, "days": days, "total": 0, "items": []}
                )

            async def close(self):
                return None

        app.dependency_overrides[ai_api.get_ai_service] = AIService
        try:
            latest = request(app, "GET", "/api/v1/ai/000001/latest-signal")
            history = request(app, "GET", "/api/v1/ai/000001/signal-history?days=30")
        finally:
            app.dependency_overrides.pop(ai_api.get_ai_service, None)

        self.assertEqual(latest.status_code, 200)
        self.assertIsNone(latest.json()["data"])
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["data"], {"stock_code": "000001", "days": 30, "total": 0, "items": []})

    def test_main_app_rejects_uncredentialed_mutation_with_root_error_contract(self):
        response = request(app, "POST", "/api/v1/screener/screen", json={})
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["data"], None)
        self.assertEqual(body["error_code"], "UNAUTHORIZED")
        self.assertEqual(response.headers["x-request-id"], body["request_id"])
        self.assertNotIn("detail", body)

    def test_legacy_execution_mutations_reject_anonymous_requests_before_handlers(self):
        for path in LEGACY_EXECUTION_MUTATIONS:
            with self.subTest(path=path):
                response = request(app, "POST", path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["error_code"], "UNAUTHORIZED")

    def test_legacy_execution_mutations_reject_insufficient_scope_before_handlers(self):
        principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="limited",
            principal_type="human",
            role="viewer",
            scopes=frozenset({"market:read"}),
            source="session",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

        class AuthService:
            async def authenticate(self, *_args, **_kwargs):
                return principal

            def validate_csrf(self, *_args, **_kwargs):
                return None

        set_auth_service_for_testing(AuthService())
        try:
            for path in LEGACY_EXECUTION_MUTATIONS:
                with self.subTest(path=path):
                    response = request(
                        app,
                        "POST",
                        path,
                        headers={"Authorization": "Bearer limited-token"},
                    )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json()["error_code"], "FORBIDDEN")
        finally:
            set_auth_service_for_testing(None)

    def test_main_app_preserves_development_read_only_access(self):
        response = request(app, "GET", "/api/v1/screener/presets")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["contract_version"], "2026-07-16")
        self.assertEqual(body["data"]["total"], len(body["data"]["items"]))
        self.assertTrue(body["data"]["items"])
        self.assertTrue({"id", "name", "description"}.issubset(body["data"]["items"][0]))

    def test_order_detail_and_simulation_sync_keep_legacy_boundaries(self):
        principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="trade-contract",
            principal_type="service",
            role="admin",
            scopes=frozenset({"trade:read", "trade:broker.sync"}),
            source="credential",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

        class AuthService:
            async def authenticate(self, *_args, **_kwargs):
                return principal

        testcase = self

        class TradeService:
            async def get_order(self, _order_id):
                return None

            async def sync_order(self, order_id, mode):
                testcase.assertEqual(mode, "simulation")
                return {"order_id": order_id, "changed": False, "message": "simulation 无需同步"}

        service = TradeService()
        set_auth_service_for_testing(AuthService())
        app.dependency_overrides[trade_api.get_trade_service] = lambda: service
        try:
            missing = request(
                app,
                "GET",
                "/api/v1/trade/orders/00000000-0000-0000-0000-000000000099",
            )
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()["error_code"], "ORDER_NOT_FOUND")

            sync = request(
                app,
                "POST",
                "/api/v1/trade/orders/00000000-0000-0000-0000-000000000099/sync?mode=simulation",
            )
            self.assertEqual(sync.status_code, 200)
            self.assertFalse(sync.json()["data"]["changed"])
        finally:
            app.dependency_overrides.pop(trade_api.get_trade_service, None)
            set_auth_service_for_testing(None)

    def test_order_cancel_rejects_non_uuid_before_approval_lookup(self):
        response = request(
            app,
            "POST",
            "/api/v1/trade/order/cancel",
            json={
                "order_id": "legacy-missing-order",
                "mode": "simulation",
                "execution_authorization_id": "approval-contract",
            },
        )

        self.assertEqual(response.status_code, 401)

        principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="trader",
            principal_type="human",
            role="trader",
            scopes=frozenset({"trade:order.cancel"}),
            source="session",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

        class AuthService:
            async def authenticate(self, *_args, **_kwargs):
                return principal

            def validate_csrf(self, *_args, **_kwargs):
                return None

        set_auth_service_for_testing(AuthService())
        try:
            response = request(
                app,
                "POST",
                "/api/v1/trade/order/cancel",
                headers={"Authorization": "Bearer trader-token"},
                json={
                    "order_id": "legacy-missing-order",
                    "mode": "simulation",
                    "execution_authorization_id": "approval-contract",
                },
            )
        finally:
            set_auth_service_for_testing(None)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error_code"], "VALIDATION_ERROR")

    def test_main_app_keeps_only_liveness_public(self):
        health = request(app, "GET", "/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["kind"], "liveness")

        metrics = request(app, "GET", "/metrics")
        self.assertEqual(metrics.status_code, 401)
        self.assertFalse(metrics.json()["success"])

    def test_metrics_and_readiness_reject_a_credential_without_their_scopes(self):
        principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="limited",
            principal_type="human",
            role="viewer",
            scopes=frozenset({"market:read"}),
            source="session",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

        class AuthService:
            async def authenticate(self, *_args, **_kwargs):
                return principal

            def validate_csrf(self, *_args, **_kwargs):
                return None

        set_auth_service_for_testing(AuthService())
        try:
            for path in ("/metrics", "/api/v1/readiness"):
                response = request(
                    app,
                    "GET",
                    path,
                    headers={"Authorization": "Bearer limited-token"},
                )
                self.assertEqual(response.status_code, 403, path)
                self.assertEqual(response.json()["error_code"], "FORBIDDEN", path)
        finally:
            set_auth_service_for_testing(None)

    def test_error_handlers_normalize_http_validation_and_internal_failures(self):
        test_app = FastAPI()
        register_exception_handlers(test_app)

        @test_app.get("/problem")
        async def problem(status_code: int = Query(400)):
            raise APIProblem("拒绝", "GATE_REJECTED", status_code)

        @test_app.get("/http")
        async def http_problem():
            raise HTTPException(status_code=409, detail="must not be exposed")

        @test_app.get("/validation")
        async def validation(value: int = Query(..., ge=1)):
            return {"value": value}

        @test_app.get("/boom")
        async def boom():
            raise RuntimeError("database password must not be exposed")

        expected = {
            401: "GATE_REJECTED",
            403: "GATE_REJECTED",
            409: "GATE_REJECTED",
            429: "GATE_REJECTED",
            502: "GATE_REJECTED",
            503: "GATE_REJECTED",
        }
        for status_code, code in expected.items():
            response = request(
                test_app,
                "GET",
                f"/problem?status_code={status_code}",
                headers={"X-Request-ID": "contract-request-id"},
            )
            self.assertEqual(response.status_code, status_code)
            body = response.json()
            self.assertFalse(body["success"])
            self.assertEqual(body["error_code"], code)
            self.assertEqual(body["request_id"], "contract-request-id")
            self.assertEqual(response.headers["x-request-id"], "contract-request-id")
            if status_code >= 500:
                self.assertNotEqual(body["message"], "拒绝")

        conflict = request(test_app, "GET", "/http")
        self.assertEqual(conflict.status_code, 409)
        self.assertNotIn("must not be exposed", conflict.text)

        validation = request(test_app, "GET", "/validation?value=0")
        self.assertEqual(validation.status_code, 422)
        self.assertEqual(validation.json()["error_code"], "VALIDATION_ERROR")
        self.assertTrue(validation.json()["field_errors"])

        not_found = request(test_app, "GET", "/not-found")
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json()["error_code"], "NOT_FOUND")

        boom = request(test_app, "GET", "/boom")
        self.assertEqual(boom.status_code, 500)
        self.assertEqual(boom.json()["error_code"], "INTERNAL_ERROR")
        self.assertNotIn("database password", boom.text)

    def test_error_function_raises_a_root_contract_problem(self):
        with self.assertRaises(APIProblem) as raised:
            error("无效", "INVALID", 422)
        self.assertEqual(raised.exception.code, "INVALID")


if __name__ == "__main__":
    unittest.main()
