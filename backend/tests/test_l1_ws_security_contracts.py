import asyncio
import os
import unittest
from unittest.mock import patch

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "l1-ws-contract-test-secret"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from app.core.auth import (  # noqa: E402
    AuthService,
    Principal,
    WebSocketAuthFailure,
    authenticate_websocket,
    set_auth_service_for_testing,
)


class FakeWebSocket:
    def __init__(self, *, origin: str | None, authorization: str | None = None):
        self.headers = {}
        if origin is not None:
            self.headers["origin"] = origin
        if authorization is not None:
            self.headers["authorization"] = authorization
        self.cookies = {}


def run(coro):
    return asyncio.run(coro)


class WebSocketSecurityContractTests(unittest.TestCase):
    def tearDown(self):
        set_auth_service_for_testing(None)

    def test_authorized_scope_and_origin_are_accepted(self):
        principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="viewer",
            principal_type="human",
            role="viewer",
            scopes=frozenset({"market:stream"}),
            source="session",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

        async def load_credential(token: str):
            return principal if token == "valid-token" else None

        set_auth_service_for_testing(AuthService(credential_loader=load_credential))
        actual = run(
            authenticate_websocket(
                FakeWebSocket(
                    origin="http://localhost:3000",
                    authorization="Bearer valid-token",
                ),
                "market:stream",
            )
        )
        self.assertEqual(actual.principal_id, principal.principal_id)

    def test_human_bearer_is_rejected_for_websocket(self):
        principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="viewer",
            principal_type="human",
            role="viewer",
            scopes=frozenset({"market:stream"}),
            source="credential",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

        async def load_credential(_token: str):
            return principal

        set_auth_service_for_testing(AuthService(credential_loader=load_credential))
        with self.assertRaises(WebSocketAuthFailure) as raised:
            run(
                authenticate_websocket(
                    FakeWebSocket(
                        origin="http://localhost:3000",
                        authorization="Bearer valid-token",
                    ),
                    "market:stream",
                )
            )
        self.assertEqual(raised.exception.close_code, 4403)
        self.assertEqual(raised.exception.code, "HUMAN_SESSION_REQUIRED")

    def test_missing_credential_is_closed_with_4401(self):
        set_auth_service_for_testing(AuthService())
        with self.assertRaises(WebSocketAuthFailure) as raised:
            run(
                authenticate_websocket(
                    FakeWebSocket(origin="http://localhost:3000"),
                    "market:stream",
                )
            )
        self.assertEqual(raised.exception.close_code, 4401)

    def test_invalid_origin_and_scope_are_closed_with_4403(self):
        principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="viewer",
            principal_type="human",
            role="viewer",
            scopes=frozenset({"market:stream"}),
            source="session",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

        async def load_credential(token: str):
            return principal

        set_auth_service_for_testing(AuthService(credential_loader=load_credential))
        with self.assertRaises(WebSocketAuthFailure) as origin_error:
            run(
                authenticate_websocket(
                    FakeWebSocket(
                        origin="http://untrusted.example",
                        authorization="Bearer valid-token",
                    ),
                    "market:stream",
                )
            )
        self.assertEqual(origin_error.exception.close_code, 4403)
        with patch("app.core.auth.logger.warning") as warning:
            with self.assertRaises(WebSocketAuthFailure) as scope_error:
                run(
                    authenticate_websocket(
                        FakeWebSocket(
                            origin="http://localhost:3000",
                            authorization="Bearer valid-token",
                        ),
                        "risk:stream",
                    )
                )
        self.assertEqual(scope_error.exception.close_code, 4403)
        event = warning.call_args.kwargs
        self.assertEqual(event["principal_id"], principal.principal_id)
        self.assertEqual(event["credential_id"], principal.credential_id)
        self.assertEqual(event["required_scope"], "risk:stream")


if __name__ == "__main__":
    unittest.main()
