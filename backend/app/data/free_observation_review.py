from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.data.free_observation_dual_ma import (
    FreeObservationDualMaEvaluator,
    FreeObservationEvaluationError,
)
from app.data.tushare_free_observation import FREE_OBSERVATION_MODE


class FreeObservationReviewError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FreeObservationReviewItem:
    stock_code: str
    would_action: str
    baseline_trade_date: str | None
    realization_trade_date: str | None
    close_change_pct: float | None
    outcome: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "would_action": self.would_action,
            "baseline_trade_date": self.baseline_trade_date,
            "realization_trade_date": self.realization_trade_date,
            "close_change_pct": self.close_change_pct,
            "outcome": self.outcome,
            "observation_only": True,
            "tradable": False,
            "order_created": False,
        }


class FreeObservationReview:
    """Score free-observation direction only; this is not PnL or paper-trading accounting."""

    @classmethod
    def evaluate(cls, *, candidate_document: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        candidate_hashes, candidates = cls._candidate_document(candidate_document)
        indexed = cls._artifacts(artifacts)
        if not candidate_hashes.issubset(indexed):
            raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_INPUT_MISSING", "候选关联的观测批次缺失")
        items = []
        for candidate in candidates:
            stock_code = candidate.get("stock_code")
            action = candidate.get("would_action")
            if not isinstance(stock_code, str) or not isinstance(action, str):
                raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_INVALID", "候选记录缺少股票或动作")
            baseline = cls._latest_row(indexed, candidate_hashes, stock_code)
            realization = cls._first_later_row(indexed, stock_code, baseline["trade_date"] if baseline else None)
            items.append(cls._item(stock_code, action, baseline, realization))
        payload = {
            "candidate_result_hash": candidate_document["result_hash"],
            "review_items": [item.as_dict() for item in items],
        }
        return {
            "data_mode": FREE_OBSERVATION_MODE,
            "data_qualification": "unverified",
            "formal_use": False,
            "research_readiness": "not_granted",
            "candidate_result_hash": candidate_document["result_hash"],
            "review_items": [item.as_dict() for item in items],
            "review_hash": cls._hash(payload),
            "blocked_from": ["certified_store", "formal_p3", "formal_p4", "p5", "trade_execution"],
        }

    @classmethod
    def _candidate_document(cls, document: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
        if (
            document.get("data_mode") != FREE_OBSERVATION_MODE
            or document.get("data_qualification") != "unverified"
            or document.get("formal_use") is not False
        ):
            raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_INVALID", "复盘输入不是未认证免费观测候选")
        hashes = document.get("input_batch_hashes")
        candidates = document.get("candidates")
        if not isinstance(hashes, list) or not hashes or not isinstance(candidates, list):
            raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_INVALID", "候选输入不完整")
        expected_hash = cls._hash(
            {
                "strategy_reference": document.get("strategy_reference"),
                "input_batch_hashes": hashes,
                "candidates": candidates,
            }
        )
        if document.get("result_hash") != expected_hash:
            raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_HASH_MISMATCH", "候选结果 Hash 不一致")
        if any(not isinstance(value, str) or len(value) != 64 for value in hashes):
            raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_INVALID", "候选批次 Hash 无效")
        return set(hashes), candidates

    @classmethod
    def _artifacts(cls, artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        indexed: dict[str, list[dict[str, Any]]] = {}
        for artifact in artifacts:
            try:
                rows_by_stock, hashes, _ = FreeObservationDualMaEvaluator._validated_rows([artifact])
            except FreeObservationEvaluationError as exc:
                raise FreeObservationReviewError(exc.code, str(exc)) from exc
            batch_hash = hashes[0]
            if batch_hash in indexed:
                raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_DUPLICATE", "复盘输入存在重复观测批次")
            indexed[batch_hash] = [
                {"stock_code": stock_code, **row}
                for stock_code, rows in rows_by_stock.items()
                for row in rows
            ]
        if not indexed:
            raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_INPUT_MISSING", "复盘缺少观测批次")
        return indexed

    @staticmethod
    def _latest_row(indexed: dict[str, list[dict[str, Any]]], hashes: set[str], stock_code: str) -> dict[str, Any] | None:
        rows = [row for batch_hash in hashes for row in indexed[batch_hash] if row["stock_code"] == stock_code]
        return max(rows, key=lambda row: row["trade_date"]) if rows else None

    @staticmethod
    def _first_later_row(
        indexed: dict[str, list[dict[str, Any]]], stock_code: str, baseline_trade_date: str | None
    ) -> dict[str, Any] | None:
        if baseline_trade_date is None:
            return None
        rows = [
            row
            for batch_rows in indexed.values()
            for row in batch_rows
            if row["stock_code"] == stock_code and row["trade_date"] > baseline_trade_date
        ]
        return min(rows, key=lambda row: row["trade_date"]) if rows else None

    @staticmethod
    def _item(
        stock_code: str,
        action: str,
        baseline: dict[str, Any] | None,
        realization: dict[str, Any] | None,
    ) -> FreeObservationReviewItem:
        if baseline is None:
            return FreeObservationReviewItem(stock_code, action, None, None, None, "BASELINE_UNAVAILABLE")
        if realization is None:
            return FreeObservationReviewItem(stock_code, action, baseline["trade_date"], None, None, "REALIZATION_PENDING")
        change_pct = round((float(realization["close"]) / float(baseline["close"]) - 1) * 100, 6)
        if action == "BUY_OBSERVATION":
            outcome = "DIRECTION_MATCHED" if change_pct > 0 else "DIRECTION_MISSED"
        elif action == "SELL_OBSERVATION":
            outcome = "DIRECTION_MATCHED" if change_pct < 0 else "DIRECTION_MISSED"
        else:
            outcome = "HOLD_NOT_SCORED"
        return FreeObservationReviewItem(
            stock_code, action, baseline["trade_date"], realization["trade_date"], change_pct, outcome
        )

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
