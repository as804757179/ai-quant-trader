import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("SECRET_KEY", "p3-shadow-read-api-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.api import shadow  # noqa: E402


class P3ShadowReadApiContractTests(unittest.TestCase):
    def test_shadow_routes_are_read_only(self):
        expected = {
            "/runs",
            "/runs/{run_id}",
            "/runs/{run_id}/decisions",
            "/decisions/{decision_id}/evidence",
        }
        routes = {route.path: route.methods for route in shadow.router.routes}
        self.assertEqual(set(routes), expected)
        self.assertTrue(all(methods == {"GET"} for methods in routes.values()))

    def test_read_api_exposes_lineage_and_safety_without_execution_imports(self):
        source = (REPO_ROOT / "backend/app/api/shadow.py").read_text(encoding="utf-8")
        self.assertIn("data_mode_semantics", source)
        self.assertIn("list_decision_evidence", source)
        self.assertNotIn("app.trade", source)
        self.assertNotIn("simulation_trader", source)
        self.assertNotIn("create_order", source)

    def test_main_mounts_only_shadow_read_router(self):
        source = (REPO_ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        self.assertIn('prefix="/api/v1/shadow"', source)


if __name__ == "__main__":
    unittest.main()
