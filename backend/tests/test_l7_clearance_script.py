import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class LegacyApiClearanceScriptTests(unittest.TestCase):
    def test_clearance_script_requires_ledger_and_runtime_acceptance(self):
        source = (
            ROOT / "scripts" / "verify_legacy_api_clearance.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn("Test-LedgerClearance", source)
        self.assertIn('consumer_state -eq "external_unknown"', source)
        self.assertIn('lifecycle -eq "review"', source)
        self.assertIn('verification -eq "route_only"', source)
        self.assertIn("verify_legacy_api_l0.ps1", source)
        self.assertIn("verify_legacy_api_l4.ps1", source)
        self.assertIn("test_l7_deprecation_telemetry", source)
        self.assertIn("npm run typecheck", source)
        self.assertIn("npm run build", source)
        self.assertIn(r"scripts\start-local.ps1", source)
        self.assertIn(r"scripts\stop-local.ps1", source)
        self.assertIn("LEGACY_API_CLEARANCE=PASS", source)

    def test_static_only_mode_cannot_claim_clearance_pass(self):
        source = (
            ROOT / "scripts" / "verify_legacy_api_clearance.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn("param([switch]$StaticOnly)", source)
        self.assertIn("LEGACY_API_CLEARANCE=BLOCKED", source)
        self.assertIn("if ($StaticOnly)", source)


if __name__ == "__main__":
    unittest.main()
