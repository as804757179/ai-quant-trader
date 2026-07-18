import asyncio
import os
import unittest
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import Response

os.environ.setdefault("SECRET_KEY", "l7-deprecation-telemetry-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core.auth import (
    AuthService,
    Principal,
    api_security_middleware,
    emit_legacy_route_review_telemetry,
    legacy_route_review_id,
    set_auth_service_for_testing,
)


class LegacyRouteReviewTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="reviewer",
            principal_type="human",
            role="risk_admin",
            scopes=frozenset({"strategy:write", "system:notify.test"}),
            source="credential",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

    def tearDown(self):
        set_auth_service_for_testing(None)

    def test_review_ids_cover_first_deprecation_review_routes(self):
        self.assertEqual(
            legacy_route_review_id("POST", "/api/v1/strategy/create"),
            "strategy-create",
        )
        self.assertEqual(
            legacy_route_review_id("POST", "/api/v1/strategy/dual_ma/update"),
            "strategy-update",
        )
        self.assertEqual(
            legacy_route_review_id("POST", "/api/v1/trade/simulation/release-t1"),
            "simulation-release-t1",
        )
        self.assertEqual(
            legacy_route_review_id("POST", "/api/v1/risk/alerts/test-dingtalk"),
            "risk-dingtalk-test",
        )
        self.assertEqual(
            legacy_route_review_id("WEBSOCKET", "/ws/quotes/000001"),
            "ws-quotes",
        )
        self.assertEqual(
            legacy_route_review_id("WEBSOCKET", "/ws/signals"),
            "ws-signals",
        )
        self.assertEqual(
            legacy_route_review_id("WEBSOCKET", "/ws/alerts"),
            "ws-alerts",
        )
        self.assertEqual(
            legacy_route_review_id("WEBSOCKET", "/ws/portfolio"),
            "ws-portfolio",
        )
        self.assertIsNone(
            legacy_route_review_id("POST", "/api/v1/strategy/versions/7/approve")
        )

    def test_review_telemetry_uses_authenticated_consumer_identity(self):
        with patch("app.core.auth.logger.warning") as warning:
            emit_legacy_route_review_telemetry(
                "POST",
                "/api/v1/trade/simulation/release-t1",
                self.principal,
                request_id="request-1",
                client="127.0.0.1",
                user_agent="contract-test",
            )

        warning.assert_called_once_with(
            "legacy_route_review_invoked",
            review_id="simulation-release-t1",
            method="POST",
            path="/api/v1/trade/simulation/release-t1",
            principal_id=self.principal.principal_id,
            principal_type="human",
            credential_id=self.principal.credential_id,
            auth_source="credential",
            request_id="request-1",
            client="127.0.0.1",
            user_agent="contract-test",
        )

    def test_non_review_route_does_not_emit_telemetry(self):
        with patch("app.core.auth.logger.warning") as warning:
            emit_legacy_route_review_telemetry(
                "GET",
                "/api/v1/health",
                self.principal,
            )

        warning.assert_not_called()

    def test_http_middleware_emits_before_invoking_review_route(self):
        async def load_credential(token: str):
            return self.principal if token == "valid-token" else None

        async def call_next(_request):
            return Response(status_code=204)

        self.principal = Principal(
            **{
                **self.principal.__dict__,
                "principal_type": "service",
                "role": "admin",
                "scopes": frozenset({"trade:simulation.operate"}),
            }
        )
        set_auth_service_for_testing(AuthService(credential_loader=load_credential))
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/trade/simulation/release-t1",
                "raw_path": b"/api/v1/trade/simulation/release-t1",
                "query_string": b"",
                "headers": [
                    (b"authorization", b"Bearer valid-token"),
                    (b"user-agent", b"contract-test"),
                ],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
            }
        )
        request.state.request_id = "request-1"

        with patch("app.core.auth.logger.warning") as warning:
            response = asyncio.run(api_security_middleware(request, call_next))

        self.assertEqual(response.status_code, 204)
        warning.assert_called_once_with(
            "legacy_route_review_invoked",
            review_id="simulation-release-t1",
            method="POST",
            path="/api/v1/trade/simulation/release-t1",
            principal_id=self.principal.principal_id,
            principal_type="service",
            credential_id=self.principal.credential_id,
            auth_source="credential",
            request_id="request-1",
            client="127.0.0.1",
            user_agent="contract-test",
        )


if __name__ == "__main__":
    unittest.main()
