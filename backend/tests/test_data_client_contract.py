import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.data.client import DataClient, DataFetchResult


class _Response:
    def __init__(self, payload=None, json_error: Exception | None = None):
        self.payload = payload
        self.json_error = json_error

    def raise_for_status(self):
        return None

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class _AsyncClient:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error

    async def request(self, *args, **kwargs):
        if self.error is not None:
            raise self.error
        return self.response


class DataClientContractTests(unittest.TestCase):
    def test_typed_result_distinguishes_data_outcomes(self):
        client = object.__new__(DataClient)

        async def fund_flow_result(payload):
            client._request_typed = AsyncMock(
                return_value=DataFetchResult(
                    status="success",
                    data=payload,
                    provenance={"service": "a-stock-data", "path": "/fund-flow/000001"},
                )
            )
            return await client.fetch_fund_flow_result("000001", days=7)

        success = asyncio.run(
            fund_flow_result({"success": True, "data": [{"date": "2026-07-16"}]})
        )
        self.assertEqual(success.status, "success")
        self.assertIsNone(success.error_code)
        self.assertFalse(success.retryable)
        self.assertEqual(success.provenance["service"], "a-stock-data")

        no_data = asyncio.run(fund_flow_result({"success": True, "data": []}))
        self.assertEqual(no_data.status, "no_data")
        self.assertEqual(no_data.error_code, "NO_DATA")

        malformed = asyncio.run(fund_flow_result({"success": True, "data": "bad"}))
        self.assertEqual(malformed.status, "malformed_response")
        self.assertEqual(malformed.error_code, "MALFORMED_RESPONSE")

        malformed_shape = asyncio.run(fund_flow_result({"success": True, "data": {}}))
        self.assertEqual(malformed_shape.status, "malformed_response")

        validation = asyncio.run(
            fund_flow_result({"success": True, "data": [{"date": "2026-07-16"}, "bad"]})
        )
        self.assertEqual(validation.status, "validation_failed")
        self.assertEqual(validation.error_code, "DATA_VALIDATION_FAILED")

    def test_typed_request_distinguishes_timeout_fetch_failure_and_bad_json(self):
        timeout_client = object.__new__(DataClient)
        timeout_client.MAX_RETRIES = 1
        timeout_client._client = AsyncMock(
            return_value=_AsyncClient(error=httpx.ReadTimeout("timeout"))
        )
        timeout = asyncio.run(timeout_client._request_typed("GET", "/quotes"))
        self.assertEqual(timeout.status, "timeout")
        self.assertEqual(timeout.error_code, "UPSTREAM_TIMEOUT")
        self.assertTrue(timeout.retryable)

        failure_client = object.__new__(DataClient)
        failure_client._client = AsyncMock(
            return_value=_AsyncClient(
                response=_Response(
                    {
                        "success": False,
                        "error_code": "PROVIDER_UNAVAILABLE",
                        "retryable": True,
                        "meta": {"provider": "tencent"},
                    }
                )
            )
        )
        failure = asyncio.run(failure_client._request_typed("GET", "/quotes"))
        self.assertEqual(failure.status, "fetch_failed")
        self.assertEqual(failure.error_code, "PROVIDER_UNAVAILABLE")
        self.assertTrue(failure.retryable)
        self.assertEqual(failure.provenance["provider"], "tencent")

        malformed_client = object.__new__(DataClient)
        malformed_client._client = AsyncMock(
            return_value=_AsyncClient(response=_Response(json_error=ValueError("bad json")))
        )
        malformed = asyncio.run(malformed_client._request_typed("GET", "/quotes"))
        self.assertEqual(malformed.status, "malformed_response")
        self.assertEqual(malformed.error_code, "MALFORMED_RESPONSE")

    def test_stock_snapshot_read_and_refresh_command_are_separate(self):
        client = object.__new__(DataClient)
        client._request_typed = AsyncMock(
            return_value=DataFetchResult(
                status="success",
                data={"success": True, "data": [{"code": "600000"}]},
            )
        )
        snapshot = asyncio.run(client.fetch_stock_list_result())
        self.assertTrue(snapshot.success)
        client._request_typed.assert_awaited_once_with("GET", "/stock/list")

        client._request_typed.reset_mock()
        command_token = "contract-test-command-token-at-least-32-bytes"
        with patch("app.data.client.settings.A_STOCK_DATA_COMMAND_TOKEN", command_token):
            refresh = asyncio.run(client.refresh_stock_list_result())
        self.assertTrue(refresh.success)
        client._request_typed.assert_awaited_once_with(
            "POST",
            "/internal/stock-list/refresh",
            headers={"X-Stock-Refresh-Token": command_token},
            timeout=120.0,
        )

    def test_kline_request_declares_raw_internal_semantics(self):
        client = object.__new__(DataClient)
        client._request_typed = AsyncMock(
            return_value=DataFetchResult(
                status="success", data={"success": True, "data": []}
            )
        )
        result = asyncio.run(client.fetch_kline_result("600000", "1d", 20))
        self.assertEqual(result.status, "no_data")
        client._request_typed.assert_awaited_once_with(
            "GET",
            "/kline/600000",
            params={"period": "1d", "limit": 20, "adjustment": "raw"},
        )

    def test_quote_result_preserves_observed_provenance(self):
        client = object.__new__(DataClient)
        client._request_typed = AsyncMock(
            return_value=DataFetchResult(
                status="success",
                data={
                    "success": True,
                    "data": {"price": 10.0},
                    "meta": {"quality_status": "observed", "source": "memory_cache"},
                },
            )
        )
        result = asyncio.run(client.fetch_quote_result("000001"))
        self.assertTrue(result.success)
        self.assertEqual(result.provenance["quality_status"], "observed")
        self.assertEqual(result.provenance["source"], "memory_cache")


if __name__ == "__main__":
    unittest.main()
