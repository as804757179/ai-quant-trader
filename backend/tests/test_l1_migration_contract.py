import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "024_api_principal_and_contract_governance.py"
)


class ApiPrincipalMigrationContractTests(unittest.TestCase):
    def test_migration_is_append_only_and_contains_hashed_authentication_state(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn('revision = "024"', source)
        self.assertIn('down_revision = "023"', source)
        for fragment in (
            "CREATE SCHEMA IF NOT EXISTS auth",
            "CREATE TABLE auth.principals",
            "CREATE TABLE auth.api_credentials",
            "CREATE TABLE auth.api_sessions",
            "token_digest CHAR(64)",
            "session_digest CHAR(64)",
            "csrf_digest CHAR(64)",
            "REVOKE UPDATE, DELETE ON auth.api_credentials FROM PUBLIC",
        ):
            self.assertIn(fragment, source)

        downgrade = re.search(r"def downgrade\(\) -> None:\n(?P<body>[\s\S]+)$", source)
        self.assertIsNotNone(downgrade)
        self.assertNotIn("DROP TABLE", downgrade.group("body"))
        self.assertIn("cannot be downgraded destructively", downgrade.group("body"))


if __name__ == "__main__":
    unittest.main()
