import os
import sys
import unittest
from pathlib import Path
os.environ.setdefault("SECRET_KEY", "p3-profile-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data.p3_replay_profile import CONTRACT, FORBIDDEN_FIELDS, STATUS, is_runner_usable

class P3ReplayProfileTests(unittest.TestCase):
    def test_profile_remains_draft_and_runner_cannot_use_it(self):
        self.assertEqual(STATUS, "draft")
        self.assertFalse(is_runner_usable())
        self.assertIn("realtime", FORBIDDEN_FIELDS)
        self.assertIn("available_at", CONTRACT["required_fields"])

if __name__ == "__main__":
    unittest.main()
