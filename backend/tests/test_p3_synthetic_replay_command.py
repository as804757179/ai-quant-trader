from __future__ import annotations

import subprocess
import sys
import json
import tempfile
from pathlib import Path
import unittest


class SyntheticReplayCommandTests(unittest.TestCase):
    def test_explicit_command_is_deterministic_and_test_only(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script = backend_root / "scripts" / "verify_synthetic_shadow_replay.py"
        result = subprocess.run(
            [sys.executable, str(script), "--confirm-test-only"],
            cwd=backend_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"deterministic": true', result.stdout)
        self.assertIn('"formal_replay": "blocked/deferred"', result.stdout)
        self.assertIn('"network_request_count": 0', result.stdout)
        self.assertIn('"runner_usable": false', result.stdout)
        self.assertIn('"future_data_excluded": true', result.stdout)
        self.assertIn('"parameter_snapshot": {', result.stdout)
        self.assertIn('"parameter_hash":', result.stdout)
        self.assertRegex(result.stdout, r'"audit_report_hash": "[0-9a-f]{64}"')
        self.assertEqual(result.stdout.count('"blocked": true'), 12)

    def test_command_requires_explicit_confirmation(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script = backend_root / "scripts" / "verify_synthetic_shadow_replay.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=backend_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--confirm-test-only", result.stderr)

    def test_command_rejects_production_environment(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script = backend_root / "scripts" / "verify_synthetic_shadow_replay.py"
        environment = dict(__import__("os").environ)
        environment["APP_ENV"] = "production"
        result = subprocess.run(
            [sys.executable, str(script), "--confirm-test-only"],
            cwd=backend_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("production", result.stderr)

    def test_command_writes_new_audit_file_without_overwrite(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script = backend_root / "scripts" / "verify_synthetic_shadow_replay.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "synthetic-audit.json"
            command = [
                sys.executable,
                str(script),
                "--confirm-test-only",
                "--output",
                str(output_path),
            ]
            first = subprocess.run(
                command,
                cwd=backend_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertRegex(saved["audit_report_hash"], r"^[0-9a-f]{64}$")
            second = subprocess.run(
                command,
                cwd=backend_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(second.returncode, 2)
            self.assertIn("拒绝覆盖", second.stderr)


if __name__ == "__main__":
    unittest.main()
