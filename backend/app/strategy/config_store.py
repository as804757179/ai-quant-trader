"""策略启用状态与参数覆盖 — JSON 文件持久化。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.strategy.catalog import STRATEGY_CATALOG, get_strategy_meta


def _default_path() -> Path:
    raw = os.getenv("STRATEGY_CONFIG_PATH", "")
    if raw:
        return Path(raw)
    # backend/app/strategy -> 项目根或 /app
    base = Path(__file__).resolve().parents[2]
    return base / "data" / "strategy_config.json"


class StrategyConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()

    def _load_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_raw(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_strategies(self) -> list[dict[str, Any]]:
        raw = self._load_raw()
        items: list[dict[str, Any]] = []
        for stype, meta in STRATEGY_CATALOG.items():
            override = raw.get(stype) or {}
            params = {**meta["default_params"], **(override.get("params") or {})}
            items.append(
                {
                    "type": stype,
                    "name": meta["name"],
                    "description": meta["description"],
                    "scenario": meta["scenario"],
                    "enabled": bool(override.get("enabled", True)),
                    "params": params,
                    "default_params": meta["default_params"],
                    "param_schema": meta.get("param_schema", {}),
                }
            )
        return items

    def get(self, strategy_type: str) -> dict[str, Any] | None:
        meta = get_strategy_meta(strategy_type)
        if not meta:
            return None
        raw = self._load_raw()
        override = raw.get(strategy_type) or {}
        return {
            "type": strategy_type,
            "name": meta["name"],
            "description": meta["description"],
            "scenario": meta["scenario"],
            "enabled": bool(override.get("enabled", True)),
            "params": {**meta["default_params"], **(override.get("params") or {})},
            "default_params": meta["default_params"],
            "param_schema": meta.get("param_schema", {}),
        }

    def update(
        self,
        strategy_type: str,
        *,
        enabled: bool | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if strategy_type not in STRATEGY_CATALOG:
            raise ValueError(f"未知策略类型: {strategy_type}")
        raw = self._load_raw()
        entry = dict(raw.get(strategy_type) or {})
        if enabled is not None:
            entry["enabled"] = enabled
        if params is not None:
            merged = dict(entry.get("params") or {})
            merged.update(params)
            entry["params"] = merged
        raw[strategy_type] = entry
        self._save_raw(raw)
        result = self.get(strategy_type)
        assert result is not None
        return result
