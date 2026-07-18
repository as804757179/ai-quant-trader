import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from services.data_client import DataClient, DataFetchResult


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
    def test_fund_flow_uses_registered_internal_data_route(self):
        client = object.__new__(DataClient)
        client._request = AsyncMock(return_value={"success": True, "data": []})

        result = asyncio.run(client.fetch_fund_flow("000001", days=7))

        self.assertEqual(result, [])
        client._request.assert_awaited_once_with(
            "GET", "/fund-flow/000001", params={"days": 7}
        )

    def test_kline_declares_raw_internal_semantics(self):
        client = object.__new__(DataClient)
        client._request_typed = AsyncMock(
            return_value=DataFetchResult(
                status="success", data={"success": True, "data": []}
            )
        )

        result = asyncio.run(client.fetch_kline_result("000001", period="1d", limit=20))

        self.assertEqual(result.status, "no_data")
        client._request_typed.assert_awaited_once_with(
            "GET",
            "/kline/000001",
            params={"period": "1d", "limit": 20, "adjustment": "raw"},
        )

    def test_typed_result_distinguishes_data_outcomes(self):
        client = object.__new__(DataClient)
        client.MAX_RETRIES = 1

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
        timeout_client._client = _AsyncClient(error=httpx.ReadTimeout("timeout"))
        timeout = asyncio.run(timeout_client._request_typed("GET", "/quotes"))
        self.assertEqual(timeout.status, "timeout")
        self.assertEqual(timeout.error_code, "UPSTREAM_TIMEOUT")
        self.assertTrue(timeout.retryable)

        failure_client = object.__new__(DataClient)
        failure_client.MAX_RETRIES = 1
        failure_client._client = _AsyncClient(
            response=_Response(
                {
                    "success": False,
                    "error_code": "PROVIDER_UNAVAILABLE",
                    "retryable": True,
                    "meta": {"provider": "tencent"},
                }
            )
        )
        failure = asyncio.run(failure_client._request_typed("GET", "/quotes"))
        self.assertEqual(failure.status, "fetch_failed")
        self.assertEqual(failure.error_code, "PROVIDER_UNAVAILABLE")
        self.assertTrue(failure.retryable)
        self.assertEqual(failure.provenance["provider"], "tencent")

        malformed_client = object.__new__(DataClient)
        malformed_client.MAX_RETRIES = 1
        malformed_client._client = _AsyncClient(
            response=_Response(json_error=ValueError("bad json"))
        )
        malformed = asyncio.run(malformed_client._request_typed("GET", "/quotes"))
        self.assertEqual(malformed.status, "malformed_response")
        self.assertEqual(malformed.error_code, "MALFORMED_RESPONSE")


if __name__ == "__main__":
    unittest.main()
