import asyncio
import json
import os
import unittest

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "l1-ws-integration-test-secret"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["WS_REDIS_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.core.auth import AuthService, Principal, set_auth_service_for_testing  # noqa: E402
from app.main import app  # noqa: E402
from app.ws.manager import WebSocketManager, ws_manager  # noqa: E402


class RecorderSocket:
    def __init__(self):
        self.messages: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.messages.append(payload)


class WebSocketIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.principal = Principal(
            principal_id="00000000-0000-0000-0000-000000000001",
            display_name="viewer",
            principal_type="human",
            role="viewer",
            scopes=frozenset({"market:stream"}),
            source="session",
            credential_id="00000000-0000-0000-0000-000000000010",
        )

        async def load_credential(token: str):
            return self.principal if token == "valid-token" else None

        set_auth_service_for_testing(AuthService(credential_loader=load_credential))

    def tearDown(self):
        set_auth_service_for_testing(None)

    def test_authorized_client_can_ping_and_rejections_leave_no_connection(self):
        headers = {
            "Origin": "http://localhost:3000",
            "Authorization": "Bearer valid-token",
        }
        with TestClient(app) as client:
            with client.websocket_connect("/ws/quotes/000001", headers=headers) as websocket:
                websocket.send_text("ping")
                self.assertEqual(websocket.receive_text(), "pong")

            with self.assertRaises(WebSocketDisconnect) as no_token:
                with client.websocket_connect(
                    "/ws/quotes/000001",
                    headers={"Origin": "http://localhost:3000"},
                ):
                    pass
            self.assertEqual(no_token.exception.code, 4401)

            with self.assertRaises(WebSocketDisconnect) as no_scope:
                with client.websocket_connect(
                    "/ws/alerts",
                    headers=headers,
                ):
                    pass
            self.assertEqual(no_scope.exception.code, 4403)

            with self.assertRaises(WebSocketDisconnect) as query_credential:
                with client.websocket_connect(
                    "/ws/quotes/000001?token=forbidden",
                    headers=headers,
                ):
                    pass
            self.assertEqual(query_credential.exception.code, 4403)
            self.assertEqual(ws_manager.connection_count, 0)

    def test_each_channel_requires_its_own_scope_before_accepting_messages(self):
        channels = (
            ("/ws/quotes/000001", "market:stream"),
            ("/ws/signals", "ai:stream"),
            ("/ws/alerts", "risk:stream"),
            ("/ws/portfolio?mode=paper", "portfolio:stream"),
        )

        async def load_credential(token: str):
            for index, (_path, scope) in enumerate(channels):
                if token == f"token-{index}":
                    return Principal(
                        principal_id=f"00000000-0000-0000-0000-{index + 1:012d}",
                        display_name=scope,
                        principal_type="human",
                        role="viewer",
                        scopes=frozenset({scope}),
                        source="session",
                        credential_id=f"00000000-0000-0000-0000-{index + 10:012d}",
                    )
            return None

        set_auth_service_for_testing(AuthService(credential_loader=load_credential))
        with TestClient(app) as client:
            for index, (path, _scope) in enumerate(channels):
                headers = {
                    "Origin": "http://localhost:3000",
                    "Authorization": f"Bearer token-{index}",
                }
                with client.websocket_connect(path, headers=headers) as websocket:
                    websocket.send_text("ping")
                    self.assertEqual(websocket.receive_text(), "pong", path)
        self.assertEqual(ws_manager.connection_count, 0)

    def test_broadcast_adds_event_version_without_redis(self):
        manager = WebSocketManager(redis_url="redis://localhost:6379/15")
        recorder = RecorderSocket()
        manager._connections["quotes:000001"] = [recorder]  # noqa: SLF001
        sent = asyncio.run(manager.broadcast("quotes:000001", {"price": 10.2}))
        self.assertEqual(sent, 1)
        payload = json.loads(recorder.messages[0])
        self.assertEqual(payload["event_version"], "1")
        self.assertEqual(payload["_channel"], "quotes:000001")


if __name__ == "__main__":
    unittest.main()
