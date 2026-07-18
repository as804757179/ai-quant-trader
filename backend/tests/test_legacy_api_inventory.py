import ast
import json
import os
import unittest
from pathlib import Path

from fastapi.routing import APIRoute, APIWebSocketRoute

os.environ.setdefault("SECRET_KEY", "legacy-api-inventory-test")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.main import app
from app.core.auth import route_access


REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = (
    REPO_ROOT
    / "docs"
    / "api"
    / "legacy-api-ledger.json"
)
DATA_SERVICE_PATH = REPO_ROOT / "a-stock-data" / "service" / "main.py"


def load_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def route_pairs(scope: dict) -> set[tuple[str, str]]:
    return {
        (item["method"], item["path"])
        for item in scope["interfaces"]
    }


def collect_internal_data_routes() -> set[tuple[str, str]]:
    tree = ast.parse(DATA_SERVICE_PATH.read_text(encoding="utf-8"))
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            if not isinstance(decorator.func.value, ast.Name):
                continue
            if decorator.func.value.id != "app":
                continue
            if decorator.func.attr.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not decorator.args:
                continue
            path_arg = decorator.args[0]
            if not isinstance(path_arg, ast.Constant) or not isinstance(path_arg.value, str):
                continue
            routes.add((decorator.func.attr.upper(), path_arg.value))
    return routes


class LegacyApiInventoryTests(unittest.TestCase):
    def setUp(self):
        self.ledger = load_ledger()
        self.scopes = self.ledger["scopes"]

    def test_main_http_routes_match_ledger(self):
        actual: set[tuple[str, str]] = set()
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            if not (route.path.startswith("/api/v1/") or route.path == "/metrics"):
                continue
            for method in route.methods:
                actual.add((method, route.path))

        expected = route_pairs(self.scopes["main_http"])
        self.assertEqual(actual, expected)
        self.assertEqual(
            len(expected), self.scopes["main_http"]["expected_count"]
        )

    def test_main_websocket_routes_match_ledger(self):
        actual = {
            ("WEBSOCKET", route.path)
            for route in app.routes
            if isinstance(route, APIWebSocketRoute) and route.path.startswith("/ws/")
        }
        expected = route_pairs(self.scopes["main_websocket"])
        self.assertEqual(actual, expected)
        self.assertEqual(
            len(expected), self.scopes["main_websocket"]["expected_count"]
        )

    def test_internal_data_routes_match_ledger(self):
        actual = collect_internal_data_routes()
        expected = route_pairs(self.scopes["internal_data_http"])
        self.assertEqual(actual, expected)
        self.assertEqual(
            len(expected), self.scopes["internal_data_http"]["expected_count"]
        )

    def test_ledger_entries_have_governance_metadata(self):
        required = {
            "id",
            "method",
            "path",
            "owner",
            "risk_level",
            "disposition",
            "lifecycle",
            "consumer_state",
            "consumers",
            "known_issues",
            "verification",
        }
        allowed_consumer_states = {
            "known",
            "external_unknown",
            "no_repository_consumer",
        }
        consumer_registry = self.ledger["consumer_registry"]
        entries = [
            item
            for scope in self.scopes.values()
            for item in scope["interfaces"]
        ]

        self.assertEqual(len(entries), self.ledger["total_expected"])
        self.assertEqual(len({item["id"] for item in entries}), len(entries))
        for item in entries:
            self.assertTrue(required.issubset(item))
            self.assertIn(item["consumer_state"], allowed_consumer_states)
            self.assertIsInstance(item["consumers"], list)
            self.assertIsInstance(item["known_issues"], list)
            for consumer_id in item["consumers"]:
                self.assertIn(consumer_id, consumer_registry)

    def test_main_http_routes_have_declared_security_access(self):
        auth_session_routes = {
            ("POST", "/api/v1/auth/session"),
            ("GET", "/api/v1/auth/me"),
            ("DELETE", "/api/v1/auth/session"),
        }
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            if not (route.path.startswith("/api/v1/") or route.path == "/metrics"):
                continue
            for method in route.methods:
                access = route_access(method, route.path)
                self.assertFalse(access.undeclared, (method, route.path))
                if (method, route.path) == ("GET", "/api/v1/health"):
                    self.assertTrue(access.public)
                elif (method, route.path) in auth_session_routes:
                    self.assertFalse(access.public)
                    self.assertIsNone(access.scope)
                else:
                    self.assertFalse(access.public, (method, route.path))
                    self.assertIsNotNone(access.scope, (method, route.path))

    def test_ledger_preserves_the_original_boundary_count(self):
        self.assertEqual(self.ledger["original_total_expected"], 76)
        self.assertEqual(self.ledger["total_expected"], 115)


if __name__ == "__main__":
    unittest.main()
