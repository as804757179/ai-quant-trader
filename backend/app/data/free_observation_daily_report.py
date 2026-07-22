from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from app.core.config import settings
from app.data.free_observation_ledger import FreeObservationLedger, FreeObservationLedgerError
from app.data.free_observation_review import FreeObservationReview, FreeObservationReviewError
from app.data.tushare_free_observation import FREE_OBSERVATION_MODE
from app.shadow.contracts import RELEASE_LOCK_KEYS


class FreeObservationDailyReportError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FreeObservationDailyReport:
    """Build a read-only local summary of free-observation artifacts."""

    @classmethod
    def build(
        cls,
        *,
        candidate_document: dict[str, Any],
        ledger_document: dict[str, Any],
        review_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cls._assert_local_environment()
        candidate_hashes, candidates = cls._candidate(candidate_document)
        cls._ledger(ledger_document, candidate_document["result_hash"], candidate_hashes)
        review = cls._review(review_document, candidate_document["result_hash"])
        candidate_actions = Counter(str(candidate["would_action"]) for candidate in candidates)
        event_counts = Counter(str(event["event_type"]) for event in ledger_document["events"])
        payload = {
            "data_mode": FREE_OBSERVATION_MODE,
            "data_qualification": "unverified",
            "formal_use": False,
            "candidate_result_hash": candidate_document["result_hash"],
            "ledger_hash": ledger_document["ledger_hash"],
            "review_hash": review.get("review_hash") if review else None,
            "candidate_summary": dict(sorted(candidate_actions.items())),
            "observation_event_summary": dict(sorted(event_counts.items())),
            "account_snapshot": ledger_document["account_snapshot"],
            "direction_review_summary": cls._review_summary(review),
            "formal_write_counts": ledger_document["formal_write_counts"],
            "release_locks": ledger_document["release_locks"],
        }
        return {
            **payload,
            "observation_only": True,
            "tradable": False,
            "order_created": False,
            "research_readiness": "not_granted",
            "blocked_from": ["certified_store", "formal_p3", "formal_p4", "p5", "trade_execution"],
            "report_hash": cls._hash(payload),
        }

    @classmethod
    def _candidate(cls, document: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
        try:
            return FreeObservationReview._candidate_document(document)
        except FreeObservationReviewError as exc:
            raise FreeObservationDailyReportError(exc.code, str(exc)) from exc

    @classmethod
    def _ledger(cls, ledger: dict[str, Any], candidate_hash: str, candidate_batches: set[str]) -> None:
        try:
            FreeObservationLedger._validate_prior(ledger)
        except FreeObservationLedgerError as exc:
            raise FreeObservationDailyReportError(exc.code, str(exc)) from exc
        if ledger.get("candidate_result_hash") != candidate_hash or set(ledger.get("input_batch_hashes", [])) != candidate_batches:
            raise FreeObservationDailyReportError("FREE_OBSERVATION_REPORT_LINEAGE_MISMATCH", "账本未关联当前候选输入")
        if any(value != 0 for value in ledger.get("formal_write_counts", {}).values()):
            raise FreeObservationDailyReportError("FREE_OBSERVATION_REPORT_FORMAL_WRITE_INVALID", "观测账本包含正式写入计数")
        if any(ledger.get("release_locks", {}).get(key) is not False for key in RELEASE_LOCK_KEYS):
            raise FreeObservationDailyReportError("FREE_OBSERVATION_REPORT_LOCK_INVALID", "观测账本的发布或交易锁不为 false")

    @classmethod
    def _review(cls, document: dict[str, Any] | None, candidate_hash: str) -> dict[str, Any] | None:
        if document is None:
            return None
        if (
            document.get("data_mode") != FREE_OBSERVATION_MODE
            or document.get("data_qualification") != "unverified"
            or document.get("formal_use") is not False
            or document.get("candidate_result_hash") != candidate_hash
            or not isinstance(document.get("review_items"), list)
        ):
            raise FreeObservationDailyReportError("FREE_OBSERVATION_REPORT_REVIEW_INVALID", "方向复盘文件无效或未关联当前候选")
        expected = cls._hash({"candidate_result_hash": candidate_hash, "review_items": document["review_items"]})
        if document.get("review_hash") != expected:
            raise FreeObservationDailyReportError("FREE_OBSERVATION_REPORT_REVIEW_HASH_MISMATCH", "方向复盘 Hash 不一致")
        return document

    @staticmethod
    def _review_summary(review: dict[str, Any] | None) -> dict[str, int] | None:
        if review is None:
            return None
        return dict(sorted(Counter(str(item.get("outcome")) for item in review["review_items"]).items()))

    @staticmethod
    def _assert_local_environment() -> None:
        if settings.is_production() or settings.APP_ENV.strip().lower() not in {"development", "local_development"}:
            raise FreeObservationDailyReportError("FREE_OBSERVATION_LOCAL_ENV_REQUIRED", "免费观测报告仅允许 local_development")

    @staticmethod
    def _hash(payload: object) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
