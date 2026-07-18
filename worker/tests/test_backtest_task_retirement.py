import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from tasks.ai import run_backtest_task


class BacktestTaskRetirementTests(unittest.TestCase):
    def test_legacy_worker_task_fails_closed_without_http_backtest_call(self):
        with self.assertRaisesRegex(RuntimeError, "worker_backtest_task_retired"):
            run_backtest_task.run({"strategy_type": "dual_ma"})

        source = (ROOT / "worker" / "tasks" / "ai.py").read_text(encoding="utf-8")
        task_source = source[source.index("def run_backtest_task") :]
        self.assertNotIn("/api/v1/backtest/run", task_source)
        self.assertNotIn("httpx", task_source)


if __name__ == "__main__":
    unittest.main()
