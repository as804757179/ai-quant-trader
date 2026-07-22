import argparse
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "principal-only-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.provision_api_principal import principal_only_request_hash


def args(**overrides):
    data = {"display_name": "local-strategy-admin", "role": "strategy_admin", "principal_type": "human", "metadata_json": '{"purpose":"strategy_governance","created_for":"P3_strategy_activation","environment":"local_development"}', "reason": "P3 governance bootstrap", "bootstrap_operator": "confirmed-operator", "owner_confirmed_by_user": True}
    data.update(overrides)
    return argparse.Namespace(**data)


class PrincipalOnlyProvisioningTests(unittest.TestCase):
    def test_request_hash_is_stable_and_changes_with_payload(self):
        self.assertEqual(principal_only_request_hash(args()), principal_only_request_hash(args()))
        self.assertNotEqual(principal_only_request_hash(args(reason="other")), principal_only_request_hash(args()))

    def test_source_keeps_principal_only_separate_from_credential_insert(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "provision_api_principal.py").read_text(encoding="utf-8")
        body = source[source.index("async def provision_principal_only"):source.index("async def provision(")]
        self.assertNotIn("auth.api_credentials", body)
        self.assertIn("AUTH_PRINCIPAL_BOOTSTRAPPED", body)
        self.assertIn("owner_confirmed_by_user", body)
        self.assertIn("idempotency_key", body)


if __name__ == "__main__":
    unittest.main()
