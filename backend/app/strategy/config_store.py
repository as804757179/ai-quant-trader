"""策略启用状态与参数覆盖 — JSON 文件持久化。"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from app.strategy.catalog import STRATEGY_CATALOG, get_strategy_meta


class StrategyConfigError(ValueError):
    def __init__(self, message: str, code: str = "STRATEGY_CONFIG_INVALID") -> None:
        super().__init__(message)
        self.code = code


def validate_strategy_params(
    strategy_type: str,
    params: dict[str, Any],
    *,
    require_complete: bool = True,
) -> dict[str, Any]:
    meta = get_strategy_meta(strategy_type)
    if not meta:
        raise ValueError(f"未知策略类型: {strategy_type}")
    if not isinstance(params, dict):
        raise ValueError("策略参数必须是对象")

    schema = meta.get("param_schema") or {}
    unknown = sorted(set(params) - set(schema))
    if unknown:
        raise ValueError(f"策略参数包含未知字段: {','.join(unknown)}")

    missing = sorted(set(schema) - set(params))
    if require_complete and missing:
        raise ValueError(f"策略参数缺少字段: {','.join(missing)}")

    normalized: dict[str, Any] = {}
    for key, value in params.items():
        definition = schema[key]
        expected_type = definition.get("type")
        if expected_type == "int":
            if type(value) is not int:
                raise ValueError(f"策略参数 {key} 必须是整数")
            normalized_value: int | float = value
        elif expected_type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"策略参数 {key} 必须是有限数值")
            normalized_value = float(value)
            if not math.isfinite(normalized_value):
                raise ValueError(f"策略参数 {key} 必须是有限数值")
        else:
            raise ValueError(f"策略参数 {key} 的目录定义无效")

        minimum = definition.get("min")
        maximum = definition.get("max")
        if minimum is not None and normalized_value < minimum:
            raise ValueError(f"策略参数 {key} 不能小于 {minimum}")
        if maximum is not None and normalized_value > maximum:
            raise ValueError(f"策略参数 {key} 不能大于 {maximum}")
        normalized[key] = normalized_value

    if require_complete:
        if strategy_type in {"dual_ma", "macd"} and (
            normalized["fast_period"] >= normalized["slow_period"]
        ):
            raise ValueError("策略参数 fast_period 必须小于 slow_period")
        if strategy_type == "rsi" and normalized["oversold"] >= normalized["overbought"]:
            raise ValueError("策略参数 oversold 必须小于 overbought")
    return normalized


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
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StrategyConfigError("策略配置文件不是有效 JSON") from exc
        except OSError as exc:
            raise StrategyConfigError(
                "策略配置文件不可读取", "STRATEGY_CONFIG_UNAVAILABLE"
            ) from exc
        return self._validate_raw(raw)

    def _save_raw(self, data: dict[str, Any]) -> None:
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        except OSError as exc:
            raise StrategyConfigError(
                "策略配置文件不可写入", "STRATEGY_CONFIG_UNAVAILABLE"
            ) from exc

    @staticmethod
    def _default_entry(strategy_type: str) -> dict[str, Any]:
        meta = get_strategy_meta(strategy_type)
        if not meta:
            raise ValueError(f"未知策略类型: {strategy_type}")
        return {
            "enabled": False,
            "params": validate_strategy_params(
                strategy_type, dict(meta["default_params"])
            ),
        }

    @classmethod
    def _validate_raw(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise StrategyConfigError("策略配置文件根节点必须是对象")

        normalized: dict[str, Any] = {}
        for strategy_type, entry in raw.items():
            if strategy_type not in STRATEGY_CATALOG:
                raise StrategyConfigError(f"策略配置包含未知类型: {strategy_type}")
            if not isinstance(entry, dict):
                raise StrategyConfigError(f"策略 {strategy_type} 配置必须是对象")
            unknown = sorted(set(entry) - {"enabled", "params"})
            if unknown:
                raise StrategyConfigError(
                    f"策略 {strategy_type} 配置包含未知字段: {','.join(unknown)}"
                )
            enabled = entry.get("enabled", False)
            if type(enabled) is not bool:
                raise StrategyConfigError(f"策略 {strategy_type} 的 enabled 必须是布尔值")
            stored_params = entry.get("params", {})
            if not isinstance(stored_params, dict):
                raise StrategyConfigError(f"策略 {strategy_type} 的 params 必须是对象")
            meta = STRATEGY_CATALOG[strategy_type]
            try:
                params = validate_strategy_params(
                    strategy_type,
                    {**meta["default_params"], **stored_params},
                )
            except ValueError as exc:
                raise StrategyConfigError(
                    f"策略 {strategy_type} 参数无效: {exc}"
                ) from exc
            normalized[strategy_type] = {"enabled": enabled, "params": params}
        return normalized

    def list_strategies(self) -> list[dict[str, Any]]:
        raw = self._load_raw()
        items: list[dict[str, Any]] = []
        for stype, meta in STRATEGY_CATALOG.items():
            override = raw.get(stype) or self._default_entry(stype)
            items.append(
                {
                    "type": stype,
                    "name": meta["name"],
                    "description": meta["description"],
                    "scenario": meta["scenario"],
                    "requirement_profile": meta["requirement_profile"],
                    "required_fields": meta["required_fields"],
                    "enabled": override["enabled"],
                    "params": override["params"],
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
        override = raw.get(strategy_type) or self._default_entry(strategy_type)
        return {
            "type": strategy_type,
            "name": meta["name"],
            "description": meta["description"],
            "scenario": meta["scenario"],
            "requirement_profile": meta["requirement_profile"],
            "required_fields": meta["required_fields"],
            "enabled": override["enabled"],
            "params": override["params"],
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
        entry = dict(raw.get(strategy_type) or self._default_entry(strategy_type))
        if enabled is not None:
            if type(enabled) is not bool:
                raise ValueError("enabled 必须是布尔值")
            entry["enabled"] = enabled
        if params is not None:
            if not isinstance(params, dict):
                raise ValueError("策略参数必须是对象")
            merged = dict(entry["params"])
            merged.update(params)
            entry["params"] = validate_strategy_params(strategy_type, merged)
        raw[strategy_type] = entry
        self._save_raw(raw)
        result = self.get(strategy_type)
        assert result is not None
        return result
