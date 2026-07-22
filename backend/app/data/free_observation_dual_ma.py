from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.data.tushare_free_observation import FREE_OBSERVATION_MODE
from app.strategy.version_service import StrategyVersionError, StrategyVersionService


class FreeObservationEvaluationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FreeObservationCandidate:
    stock_code: str
    would_action: str
    reason_code: str
    observed_at: datetime
    fast_sma: float | None
    slow_sma: float | None
    observation_only: bool = True
    tradable: bool = False
    order_created: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "would_action": self.would_action,
            "reason_code": self.reason_code,
            "observed_at": self.observed_at.isoformat(),
            "fast_sma": self.fast_sma,
            "slow_sma": self.slow_sma,
            "observation_only": self.observation_only,
            "tradable": self.tradable,
            "order_created": self.order_created,
        }


@dataclass(frozen=True)
class FreeObservationEvaluation:
    strategy_reference: dict[str, Any]
    input_batch_hashes: tuple[str, ...]
    candidates: tuple[FreeObservationCandidate, ...]
    result_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_mode": FREE_OBSERVATION_MODE,
            "data_qualification": "unverified",
            "formal_use": False,
            "research_readiness": "not_granted",
            "input_batch_hashes": list(self.input_batch_hashes),
            "strategy_reference": self.strategy_reference,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "result_hash": self.result_hash,
            "blocked_from": ["certified_store", "formal_p3", "formal_p4", "p5", "trade_execution"],
        }


class FreeObservationDualMaEvaluator:
    """Evaluate free-observation artifacts without creating a backtest or trade signal."""

    @classmethod
    def evaluate(
        cls,
        *,
        artifacts: list[dict[str, Any]],
        strategy_snapshot: dict[str, Any],
    ) -> FreeObservationEvaluation:
        strategy_reference, fast_period, slow_period = cls._strategy_reference(strategy_snapshot)
        rows_by_stock, batch_hashes, observed_at = cls._validated_rows(artifacts)
        candidates = tuple(
            cls._candidate(
                stock_code=stock_code,
                rows=rows,
                observed_at=observed_at,
                fast_period=fast_period,
                slow_period=slow_period,
            )
            for stock_code, rows in sorted(rows_by_stock.items())
        )
        payload = {
            "strategy_reference": strategy_reference,
            "input_batch_hashes": batch_hashes,
            "candidates": [candidate.as_dict() for candidate in candidates],
        }
        return FreeObservationEvaluation(
            strategy_reference=strategy_reference,
            input_batch_hashes=tuple(batch_hashes),
            candidates=candidates,
            result_hash=cls._hash(payload),
        )

    @classmethod
    def _strategy_reference(cls, snapshot: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
        if snapshot.get("strategy_type") != "dual_ma":
            raise FreeObservationEvaluationError("FREE_OBSERVATION_STRATEGY_INVALID", "仅支持 dual_ma 不可变策略快照")
        try:
            enabled, params = StrategyVersionService._verified_config(
                strategy_type="dual_ma",
                enabled=snapshot.get("enabled"),
                params=snapshot.get("params"),
                catalog_hash=snapshot.get("catalog_hash"),
                config_hash=snapshot.get("config_hash"),
            )
        except StrategyVersionError as exc:
            raise FreeObservationEvaluationError("FREE_OBSERVATION_STRATEGY_INVALID", str(exc)) from exc
        if not enabled:
            raise FreeObservationEvaluationError("FREE_OBSERVATION_STRATEGY_INVALID", "策略快照必须为 enabled=true")
        identifiers = ("strategy_id", "version_id", "version", "config_hash", "catalog_hash")
        if any(snapshot.get(key) in (None, "") for key in identifiers):
            raise FreeObservationEvaluationError("FREE_OBSERVATION_STRATEGY_INVALID", "策略快照引用不完整")
        reference = {key: snapshot[key] for key in ("strategy_type", *identifiers)}
        reference["params"] = params
        return reference, int(params["fast_period"]), int(params["slow_period"])

    @classmethod
    def _validated_rows(
        cls, artifacts: list[dict[str, Any]]
    ) -> tuple[dict[str, list[dict[str, Any]]], list[str], datetime]:
        if not artifacts:
            raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_REQUIRED", "至少需要一个免费观测批次")
        rows_by_stock: dict[str, list[dict[str, Any]]] = {}
        batch_hashes: list[str] = []
        observed_values: list[datetime] = []
        seen: set[tuple[str, str]] = set()
        for artifact in artifacts:
            if artifact.get("data_mode") != FREE_OBSERVATION_MODE:
                raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "输入不是 free_observation 批次")
            if artifact.get("data_qualification") != "unverified" or artifact.get("formal_use") is not False:
                raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测批次不得伪装为正式可用数据")
            if artifact.get("available_at") is not None or artifact.get("available_at_status") != "unverified":
                raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测批次不得推测 available_at")
            rows = artifact.get("rows")
            if not isinstance(rows, list) or not rows:
                raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测批次缺少日线行")
            expected_batch_hash = cls._hash(
                {
                    "provider": artifact.get("provider"),
                    "source": artifact.get("source"),
                    "dataset_version": artifact.get("dataset_version"),
                    "trade_date": artifact.get("trade_date"),
                    "raw_payload_hash": artifact.get("raw_payload_hash"),
                    "rows": rows,
                }
            )
            if artifact.get("batch_hash") != expected_batch_hash:
                raise FreeObservationEvaluationError("FREE_OBSERVATION_HASH_MISMATCH", "观测批次 Hash 不一致")
            try:
                fetched_at = datetime.fromisoformat(str(artifact["fetched_at"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测批次缺少 fetched_at") from exc
            if fetched_at.tzinfo is None:
                raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测批次 fetched_at 必须包含时区")
            batch_hashes.append(expected_batch_hash)
            observed_values.append(fetched_at)
            for row in rows:
                if not isinstance(row, dict):
                    raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测日线行无效")
                row_without_hash = {key: value for key, value in row.items() if key != "row_hash"}
                if row.get("row_hash") != cls._hash(row_without_hash):
                    raise FreeObservationEvaluationError("FREE_OBSERVATION_HASH_MISMATCH", "观测日线 row Hash 不一致")
                stock_code = row.get("ts_code")
                trading_date = row.get("trade_date")
                if not isinstance(stock_code, str) or not isinstance(trading_date, str):
                    raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测日线行缺少股票或交易日期")
                if trading_date != artifact.get("trade_date", "").replace("-", ""):
                    raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "日线行交易日期与批次不一致")
                try:
                    close = float(row["close"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测日线行 close 无效") from exc
                if close <= 0:
                    raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_INVALID", "观测日线行 close 必须为正数")
                key = (stock_code, trading_date)
                if key in seen:
                    raise FreeObservationEvaluationError("FREE_OBSERVATION_INPUT_DUPLICATE", "观测日线存在重复股票交易日")
                seen.add(key)
                rows_by_stock.setdefault(stock_code, []).append({"trade_date": trading_date, "close": close})
        for rows in rows_by_stock.values():
            rows.sort(key=lambda item: item["trade_date"])
        return rows_by_stock, sorted(batch_hashes), max(observed_values)

    @staticmethod
    def _candidate(
        *,
        stock_code: str,
        rows: list[dict[str, Any]],
        observed_at: datetime,
        fast_period: int,
        slow_period: int,
    ) -> FreeObservationCandidate:
        closes = [row["close"] for row in rows]
        if len(closes) < slow_period + 1:
            return FreeObservationCandidate(stock_code, "HOLD", "INSUFFICIENT_UNVERIFIED_HISTORY", observed_at, None, None)
        fast_now = sum(closes[-fast_period:]) / fast_period
        slow_now = sum(closes[-slow_period:]) / slow_period
        fast_previous = sum(closes[-fast_period - 1:-1]) / fast_period
        slow_previous = sum(closes[-slow_period - 1:-1]) / slow_period
        if fast_previous <= slow_previous and fast_now > slow_now:
            return FreeObservationCandidate(stock_code, "BUY_OBSERVATION", "DUAL_MA_GOLDEN_CROSS_UNVERIFIED", observed_at, fast_now, slow_now)
        if fast_previous >= slow_previous and fast_now < slow_now:
            return FreeObservationCandidate(stock_code, "SELL_OBSERVATION", "DUAL_MA_DEATH_CROSS_UNVERIFIED", observed_at, fast_now, slow_now)
        return FreeObservationCandidate(stock_code, "HOLD", "DUAL_MA_NO_CROSS_UNVERIFIED", observed_at, fast_now, slow_now)

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
