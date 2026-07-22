import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class P4SyntheticPaperCommandTests(unittest.TestCase):
    def _environment(self, *, app_env: str = "local_development") -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(
            {
                "APP_ENV": app_env,
                "SECRET_KEY": "p4-synthetic-command-test-secret-key-32chars",
                "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
                "REDIS_URL": "redis://localhost:6379/0",
            }
        )
        return environment

    def test_command_requires_confirmation_and_is_deterministic(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script = backend_root / "scripts" / "verify_synthetic_paper_ledger.py"
        rejected = subprocess.run(
            [sys.executable, str(script)],
            cwd=backend_root,
            env=self._environment(),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("--confirm-test-only", rejected.stderr)
        result = subprocess.run(
            [sys.executable, str(script), "--confirm-test-only"],
            cwd=backend_root,
            env=self._environment(),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["deterministic"])
        self.assertEqual(len(set(payload["run_hashes"])), 1)
        self.assertTrue(payload["reconciliation"]["matched"])
        self.assertTrue(payload["non_synthetic_rejected"])
        self.assertEqual(set(payload["formal_write_counts"].values()), {0})
        self.assertTrue(all(value is False for value in payload["release_locks"].values()))

    def test_command_rejects_production_and_refuses_overwrite(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script = backend_root / "scripts" / "verify_synthetic_paper_ledger.py"
        production = subprocess.run(
            [sys.executable, str(script), "--confirm-test-only"],
            cwd=backend_root,
            env=self._environment(app_env="production"),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(production.returncode, 1)
        self.assertIn("local_development", production.stderr)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "p4-synthetic-audit.json"
            command = [sys.executable, str(script), "--confirm-test-only", "--output", str(output_path)]
            first = subprocess.run(
                command,
                cwd=backend_root,
                env=self._environment(),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(json.loads(output_path.read_text(encoding="utf-8"))["reconciliation"]["matched"])
            second = subprocess.run(
                command,
                cwd=backend_root,
                env=self._environment(),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(second.returncode, 2)
            self.assertIn("拒绝覆盖", second.stderr)


if __name__ == "__main__":
    unittest.main()
