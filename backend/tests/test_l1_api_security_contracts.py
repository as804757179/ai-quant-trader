import asyncio
import os
import unittest
from unittest.mock import patch

from starlette.requests import Request

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "l1-api-security-contract-test-secret"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["API_ALLOW_ANONYMOUS_READS"] = "true"

from app.core.auth import (  # noqa: E402
    KNOWN_SCOPES,
    ROLE_SCOPES,
    AuthFailure,
    AuthService,
    Principal,
    _digest,
    api_security_middleware,
    route_access,
    set_auth_service_for_testing,
)
from app.core.config import Settings  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class ApiSecurityContractTests(unittest.TestCase):
    def setUp(self):
        self.viewer = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="viewer",
            principal_type="human",
            role="viewer",
            scopes=ROLE_SCOPES["viewer"],
            source="credential",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

    def test_missing_credential_is_rejected_when_anonymous_is_not_allowed(self):
        with self.assertRaises(AuthFailure) as raised:
            run(AuthService().authenticate({}, {}, allow_anonymous=False))
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.code, "UNAUTHORIZED")

    def test_injected_credential_loader_is_shared_auth_seam(self):
        async def load_credential(token: str):
            return self.viewer if token == "valid-token" else None

        service = AuthService(credential_loader=load_credential)
        principal = run(
            service.authenticate(
                {"Authorization": "Bearer valid-token"},
                {},
                allow_anonymous=False,
            )
        )
        self.assertEqual(principal.principal_id, self.viewer.principal_id)
        self.assertTrue(principal.has_scope("market:read"))

    def test_anonymous_principal_is_read_only(self):
        principal = run(AuthService().authenticate({}, {}, allow_anonymous=True))
        self.assertTrue(principal.is_anonymous)
        self.assertTrue(principal.has_scope("market:read"))
        self.assertFalse(principal.has_scope("trade:order.create"))

    def test_session_csrf_validation_fails_closed(self):
        service = AuthService()
        session_principal = Principal(
            principal_id=self.viewer.principal_id,
            display_name=self.viewer.display_name,
            principal_type="human",
            role="viewer",
            scopes=self.viewer.scopes,
            source="session",
            credential_id=self.viewer.credential_id,
            session_id="00000000-0000-0000-0000-000000000020",
            csrf_digest=_digest("csrf", "valid-csrf"),
        )
        service.validate_csrf(session_principal, "valid-csrf")
        with self.assertRaises(AuthFailure) as raised:
            service.validate_csrf(session_principal, "invalid-csrf")
        self.assertEqual(raised.exception.code, "CSRF_INVALID")
        self.assertEqual(raised.exception.status_code, 403)

    def test_human_bearer_is_limited_to_session_bootstrap(self):
        class AuthService:
            async def authenticate(self, *_args, **_kwargs):
                return self.viewer

            def validate_csrf(self, *_args, **_kwargs):
                return None

        auth_service = AuthService()
        auth_service.viewer = self.viewer
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/risk/fuse/activate",
                "raw_path": b"/api/v1/risk/fuse/activate",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
            }
        )

        async def call_next(_request):
            raise AssertionError("人类 Bearer 不应进入业务处理器")

        set_auth_service_for_testing(auth_service)
        try:
            response = run(api_security_middleware(request, call_next))
        finally:
            set_auth_service_for_testing(None)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"HUMAN_SESSION_REQUIRED", response.body)

    def test_role_scope_sets_are_explicit_and_service_worker_cannot_order(self):
        self.assertNotIn("*", KNOWN_SCOPES)
        for role, scopes in ROLE_SCOPES.items():
            self.assertTrue(scopes.issubset(KNOWN_SCOPES), role)
            self.assertNotIn("*", scopes, role)
        self.assertNotIn("trade:order.create", ROLE_SCOPES["service_worker"])
        self.assertNotIn("trade:order.cancel", ROLE_SCOPES["service_worker"])

    def test_route_scope_matrix_is_fail_closed(self):
        self.assertTrue(route_access("GET", "/api/v1/health").public)
        expected_scopes = {
            ("POST", "/api/v1/stock/sync-universe"): "market:operate",
            ("POST", "/api/v1/stock/backfill-kline"): "market:operate",
            ("POST", "/api/v1/ai/000001/analyze"): "ai:run",
            ("POST", "/api/v1/risk/fuse/activate"): "risk:fuse.activate",
            ("POST", "/api/v1/risk/fuse/recover"): "risk:fuse.recover",
            ("POST", "/api/v1/risk/alerts/test-dingtalk"): "system:notify.test",
            ("POST", "/api/v1/research/evidence/example/reviews"): "research:review.append",
            ("POST", "/api/v1/backtest/run"): "backtest:run",
            ("POST", "/api/v1/trade/order"): "trade:order.create",
            ("POST", "/api/v1/trade/simulation/release-t1"): "trade:simulation.operate",
            ("POST", "/api/v1/trade/order/cancel"): "trade:order.cancel",
            ("POST", "/api/v1/trade/orders/sync"): "trade:broker.sync",
            ("POST", "/api/v1/trade/orders/example/sync"): "trade:broker.sync",
            ("POST", "/api/v1/trade/reconcile"): "trade:reconcile",
            ("GET", "/api/v1/readiness"): "system:readiness.read",
            ("GET", "/metrics"): "system:metrics.read",
        }
        for (method, path), scope in expected_scopes.items():
            self.assertEqual(route_access(method, path).scope, scope, path)
        self.assertTrue(route_access("POST", "/api/v1/unknown").undeclared)

    def test_production_security_configuration_rejects_open_defaults(self):
        base = {
            "APP_ENV": "production",
            "SECRET_KEY": "x" * 32,
            "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
            "REDIS_URL": "redis://localhost:6379/0",
        }
        with self.assertRaises(RuntimeError):
            Settings(**base, API_ALLOW_ANONYMOUS_READS=True).validate_api_security_settings()
        with self.assertRaises(RuntimeError):
            Settings(
                **base,
                API_ALLOW_ANONYMOUS_READS=False,
                API_LEGACY_KEY_MIGRATION_ENABLED=True,
            ).validate_api_security_settings()
        Settings(
            **base,
            API_ALLOW_ANONYMOUS_READS=False,
            API_LEGACY_KEY_MIGRATION_ENABLED=False,
        ).validate_api_security_settings()

    def test_scope_rejection_records_authenticated_actor_without_raw_credential(self):
        class AuthService:
            async def authenticate(self, *_args, **_kwargs):
                return self.viewer

            def validate_csrf(self, *_args, **_kwargs):
                return None

        auth_service = AuthService()
        auth_service.viewer = self.viewer
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/risk/fuse/activate",
                "raw_path": b"/api/v1/risk/fuse/activate",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
            }
        )
        request.state.request_id = "auth-rejection-contract"

        async def call_next(_request):
            raise AssertionError("越权请求不应进入业务处理器")

        set_auth_service_for_testing(auth_service)
        try:
            with patch("app.core.auth.logger.warning") as warning:
                response = run(api_security_middleware(request, call_next))
        finally:
            set_auth_service_for_testing(None)

        self.assertEqual(response.status_code, 403)
        event = warning.call_args.kwargs
        self.assertEqual(event["principal_id"], self.viewer.principal_id)
        self.assertEqual(event["credential_id"], self.viewer.credential_id)
        self.assertEqual(event["request_id"], "auth-rejection-contract")
        self.assertNotIn("valid-token", str(event))


if __name__ == "__main__":
    unittest.main()
