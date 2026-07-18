import asyncio
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "worker"))

from worker.services.backend_client import (  # noqa: E402
    HttpBackendClient,
    create_backend_client,
    worker_api_headers,
)


class WorkerCredentialContractTests(unittest.TestCase):
    def test_missing_worker_credential_does_not_fall_back_to_legacy_api_key(self):
        with patch.dict(os.environ, {"API_KEY": "legacy-key"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "worker_api_credential_missing"):
                worker_api_headers()

    def test_weak_or_placeholder_worker_credential_is_rejected(self):
        for credential in ("test", "replace-with-secure-random-credential", "a" * 31):
            with self.subTest(credential=credential), patch.dict(
                os.environ, {"WORKER_API_CREDENTIAL": credential}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "worker_api_credential_invalid"):
                    worker_api_headers()

    def test_http_analysis_uses_only_worker_service_credential(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"success": True, "data": {"signal": {}}})

        async def scenario() -> None:
            client = HttpBackendClient(base_url="http://backend")
            await client._client.aclose()  # noqa: SLF001
            client._client = httpx.AsyncClient(  # noqa: SLF001
                base_url="http://backend",
                transport=httpx.MockTransport(handler),
            )
            try:
                await client.analyze("600000")
            finally:
                await client.close()

        with patch.dict(
            os.environ,
            {"WORKER_API_CREDENTIAL": "aqp_" + "a" * 43, "API_KEY": "legacy-key"},
            clear=True,
        ):
            asyncio.run(scenario())

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].headers["authorization"], "Bearer aqp_" + "a" * 43)
        self.assertNotIn("x-api-key", requests[0].headers)

    def test_client_factory_requires_credential_and_disallows_production_direct_mode(self):
        with patch.dict(os.environ, {"WORKER_BACKEND_MODE": "http"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "worker_api_credential_missing"):
                create_backend_client()
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "WORKER_BACKEND_MODE": "direct"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "worker_direct_backend_mode_forbidden_in_production"
            ):
                create_backend_client()

    def test_morning_screening_uses_shared_service_credential_helper(self):
        source = (ROOT / "worker" / "tasks" / "ai.py").read_text(encoding="utf-8")
        self.assertIn("from services.backend_client import worker_api_headers", source)
        self.assertIn("headers = worker_api_headers()", source)
        self.assertNotIn('os.getenv("API_KEY", "")', source)


if __name__ == "__main__":
    unittest.main()
