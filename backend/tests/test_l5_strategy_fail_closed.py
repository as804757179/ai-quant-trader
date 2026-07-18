from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.api.strategy import StrategyCreateRequest, StrategyUpdateRequest
from app.strategy.config_store import (
    StrategyConfigError,
    StrategyConfigStore,
    validate_strategy_params,
)


class StrategyFailClosedTests(unittest.TestCase):
    def test_missing_config_defaults_to_disabled(self):
        with TemporaryDirectory() as temp_dir:
            store = StrategyConfigStore(Path(temp_dir) / "strategy_config.json")
            self.assertTrue(all(not item["enabled"] for item in store.list_strategies()))

    def test_malformed_or_invalid_config_does_not_fall_back_to_enabled(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "strategy_config.json"
            path.write_text("{", encoding="utf-8")
            store = StrategyConfigStore(path)
            with self.assertRaises(StrategyConfigError):
                store.list_strategies()

            path.write_text(
                '{"dual_ma":{"enabled":"false","params":{}}}',
                encoding="utf-8",
            )
            with self.assertRaises(StrategyConfigError):
                store.get("dual_ma")

    def test_unknown_invalid_and_crossed_params_are_rejected(self):
        with TemporaryDirectory() as temp_dir:
            store = StrategyConfigStore(Path(temp_dir) / "strategy_config.json")
            with self.assertRaises(ValueError):
                store.update("dual_ma", params={"unknown": 1})
            with self.assertRaises(ValueError):
                store.update("dual_ma", params={"fast_period": 20})
            with self.assertRaises(ValueError):
                store.update("rsi", params={"oversold": 80})
            with self.assertRaises(ValueError):
                validate_strategy_params(
                    "bollinger",
                    {"period": 20, "std_mult": float("nan"), "position_pct": 0.2},
                )

    def test_valid_partial_update_persists_normalized_full_params(self):
        with TemporaryDirectory() as temp_dir:
            store = StrategyConfigStore(Path(temp_dir) / "strategy_config.json")
            saved = store.update("dual_ma", enabled=True, params={"fast_period": 10})

            self.assertTrue(saved["enabled"])
            self.assertEqual(saved["params"]["fast_period"], 10)
            self.assertEqual(saved["params"]["slow_period"], 20)
            self.assertTrue(store.path.exists())

    def test_request_models_forbid_unknown_top_level_fields(self):
        with self.assertRaises(ValidationError):
            StrategyCreateRequest.model_validate({"type": "dual_ma", "extra": True})
        with self.assertRaises(ValidationError):
            StrategyUpdateRequest.model_validate({"enabled": True, "extra": True})


if __name__ == "__main__":
    unittest.main()
