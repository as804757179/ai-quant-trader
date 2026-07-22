from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

from app.core.config import settings
from app.data.free_observation_review import FreeObservationReview
from app.data.tushare_free_observation import FREE_OBSERVATION_MODE
from app.shadow.contracts import RELEASE_LOCK_KEYS


class FreeObservationReviewHistoryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FreeObservationReviewHistory:
    """Summarize local direction reviews without creating a strategy change or trading instruction."""

    @classmethod
    def summarize(cls, *, review_documents: list[dict[str, Any]]) -> dict[str, Any]:
        cls._assert_local_environment()
        cls._assert_release_locks_closed()
        if not review_documents:
            raise FreeObservationReviewHistoryError("FREE_OBSERVATION_REVIEW_HISTORY_REQUIRED", "至少需要一份方向复盘文件")
        candidate_hashes: set[str] = set()
        review_hashes: list[str] = []
        counters: dict[str, Counter[str]] = defaultdict(Counter)
        for document in review_documents:
            candidate_hash, review_hash, items = cls._review(document)
            if candidate_hash in candidate_hashes:
                raise FreeObservationReviewHistoryError("FREE_OBSERVATION_REVIEW_HISTORY_DUPLICATE", "复盘候选结果重复")
            candidate_hashes.add(candidate_hash)
            review_hashes.append(review_hash)
            for item in items:
                counters[str(item["would_action"])][str(item["outcome"])] += 1
        summaries = {action: cls._summary(counter) for action, counter in sorted(counters.items())}
        payload = {
            "data_mode": FREE_OBSERVATION_MODE,
            "data_qualification": "unverified",
            "formal_use": False,
            "input_candidate_result_hashes": sorted(candidate_hashes),
            "input_review_hashes": sorted(review_hashes),
            "direction_summary": summaries,
            "optimization_status": "blocked",
            "parameter_change_candidates": [],
            "blocked_reasons": ["unverified_free_observation_data", "formal_replay_not_admitted"],
        }
        return {
            **payload,
            "observation_only": True,
            "tradable": False,
            "order_created": False,
            "research_readiness": "not_granted",
            "blocked_from": ["certified_store", "formal_p3", "formal_p4", "p5", "trade_execution"],
            "history_hash": cls._hash(payload),
        }

    @classmethod
    def _review(cls, document: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
        candidate_hash = document.get("candidate_result_hash")
        review_hash = document.get("review_hash")
        items = document.get("review_items")
        if (
            document.get("data_mode") != FREE_OBSERVATION_MODE
            or document.get("data_qualification") != "unverified"
            or document.get("formal_use") is not False
            or not isinstance(candidate_hash, str)
            or len(candidate_hash) != 64
            or not isinstance(review_hash, str)
            or len(review_hash) != 64
            or not isinstance(items, list)
        ):
            raise FreeObservationReviewHistoryError("FREE_OBSERVATION_REVIEW_HISTORY_INVALID", "方向复盘文件不完整或不属于免费观测")
        expected = FreeObservationReview._hash({"candidate_result_hash": candidate_hash, "review_items": items})
        if review_hash != expected:
            raise FreeObservationReviewHistoryError("FREE_OBSERVATION_REVIEW_HISTORY_HASH_MISMATCH", "方向复盘 Hash 不一致")
        allowed_actions = {"BUY_OBSERVATION", "SELL_OBSERVATION", "HOLD"}
        allowed_outcomes = {"DIRECTION_MATCHED", "DIRECTION_MISSED", "HOLD_NOT_SCORED", "REALIZATION_PENDING", "BASELINE_UNAVAILABLE"}
        if any(item.get("would_action") not in allowed_actions or item.get("outcome") not in allowed_outcomes for item in items):
            raise FreeObservationReviewHistoryError("FREE_OBSERVATION_REVIEW_HISTORY_INVALID", "方向复盘项包含无效动作或结果")
        return candidate_hash, review_hash, items

    @staticmethod
    def _summary(counter: Counter[str]) -> dict[str, int | float | None]:
        matched, missed = counter["DIRECTION_MATCHED"], counter["DIRECTION_MISSED"]
        scored = matched + missed
        return {
            "matched": matched,
            "missed": missed,
            "pending": counter["REALIZATION_PENDING"],
            "unscored": counter["HOLD_NOT_SCORED"] + counter["BASELINE_UNAVAILABLE"],
            "scored": scored,
            "direction_match_rate": round(matched / scored, 6) if scored else None,
        }

    @staticmethod
    def _assert_local_environment() -> None:
        if settings.is_production() or settings.APP_ENV.strip().lower() not in {"development", "local_development"}:
            raise FreeObservationReviewHistoryError("FREE_OBSERVATION_LOCAL_ENV_REQUIRED", "免费观测复盘汇总仅允许 local_development")

    @staticmethod
    def _assert_release_locks_closed() -> None:
        if any(bool(getattr(settings, key)) for key in RELEASE_LOCK_KEYS):
            raise FreeObservationReviewHistoryError("FREE_OBSERVATION_RELEASE_LOCK_INVALID", "发布或交易锁未保持 false")

    @staticmethod
    def _hash(payload: object) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
