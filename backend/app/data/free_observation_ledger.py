from __future__ import annotations

import hashlib
import json
from decimal import ROUND_DOWN, Decimal
from typing import Any

from app.core.config import settings
from app.data.free_observation_dual_ma import FreeObservationDualMaEvaluator, FreeObservationEvaluationError
from app.data.free_observation_review import FreeObservationReview, FreeObservationReviewError
from app.data.tushare_free_observation import FREE_OBSERVATION_MODE
from app.shadow.contracts import RELEASE_LOCK_KEYS


FREE_OBSERVATION_LEDGER_RULESET_VERSION = "free-observation-ledger-rules-v1"
_CENT = Decimal("0.01")


class FreeObservationLedgerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FreeObservationLedger:
    """Build a local observation account only; it has no order, execution, or database capability."""

    @classmethod
    def apply(
        cls,
        *,
        candidate_document: dict[str, Any],
        artifacts: list[dict[str, Any]],
        initial_cash: Decimal | None = None,
        prior_ledger: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cls._assert_local_environment()
        cls._assert_release_locks_closed()
        candidate_hashes, candidates, position_pct = cls._candidate_document(candidate_document)
        indexed = cls._artifacts(artifacts)
        if not candidate_hashes.issubset(indexed):
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_INPUT_MISSING", "候选关联的观测批次缺失")
        state = cls._prior_state(prior_ledger, initial_cash)
        events = list(state["events"])
        for candidate in sorted(candidates, key=lambda item: str(item["stock_code"])):
            cls._apply_candidate(events, state, candidate, candidate_hashes, indexed, position_pct)
        snapshot = cls._snapshot(state)
        payload = {
            "data_mode": FREE_OBSERVATION_MODE,
            "data_qualification": "unverified",
            "formal_use": False,
            "ruleset_version": FREE_OBSERVATION_LEDGER_RULESET_VERSION,
            "candidate_result_hash": candidate_document["result_hash"],
            "input_batch_hashes": sorted(candidate_hashes),
            "events": events,
            "account_snapshot": snapshot,
            "formal_write_counts": cls._formal_write_counts(),
            "release_locks": cls._release_locks(),
        }
        return {
            **payload,
            "observation_only": True,
            "tradable": False,
            "order_created": False,
            "research_readiness": "not_granted",
            "execution_reference": "unverified_observed_close_only",
            "fee_model": "unavailable_not_inferred",
            "reconciliation": {
                "matched": cls._snapshot(cls._rebuild(events, state["initial_cash"])) == snapshot,
                "source": "same_append_only_observation_events",
            },
            "blocked_from": ["certified_store", "formal_p3", "formal_p4", "p5", "trade_execution"],
            "ledger_hash": cls._hash(payload),
        }

    @classmethod
    def _candidate_document(cls, document: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]], Decimal]:
        try:
            hashes, candidates = FreeObservationReview._candidate_document(document)
        except FreeObservationReviewError as exc:
            raise FreeObservationLedgerError(exc.code, str(exc)) from exc
        if any(candidate.get("would_action") not in {"BUY_OBSERVATION", "SELL_OBSERVATION", "HOLD"} for candidate in candidates):
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_INPUT_INVALID", "候选动作无效")
        try:
            position_pct = Decimal(str(document["strategy_reference"]["params"]["position_pct"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_INPUT_INVALID", "候选缺少不可变仓位参数") from exc
        if not Decimal("0") < position_pct <= Decimal("1"):
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_INPUT_INVALID", "候选仓位参数无效")
        return hashes, candidates, position_pct

    @classmethod
    def _artifacts(cls, artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        try:
            return FreeObservationReview._artifacts(artifacts)
        except FreeObservationReviewError as exc:
            raise FreeObservationLedgerError(exc.code, str(exc)) from exc

    @classmethod
    def _prior_state(cls, prior: dict[str, Any] | None, initial_cash: Decimal | None) -> dict[str, Any]:
        if prior is None:
            if initial_cash is None or initial_cash <= 0:
                raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_INITIAL_CASH_REQUIRED", "首次运行必须提供正数初始虚拟资金")
            cash = cls._money(initial_cash)
            state = {"initial_cash": cash, "cash": cash, "positions": {}, "events": [], "last_trade_date": None}
            cls._append(
                state["events"],
                "observation_account_initialized",
                "0000-00-00",
                {"initial_cash": str(cash), "currency": "CNY", "ruleset_version": FREE_OBSERVATION_LEDGER_RULESET_VERSION},
            )
            return state
        cls._validate_prior(prior)
        if initial_cash is not None:
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_PRIOR_CONFLICT", "续跑账本不得再次提供初始虚拟资金")
        initial = cls._money(Decimal(str(prior["account_snapshot"]["initial_cash"])))
        rebuilt = cls._rebuild(prior["events"], initial)
        if cls._snapshot(rebuilt) != prior["account_snapshot"]:
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_RECONCILIATION_MISMATCH", "既有观测账本无法由事件重建")
        return rebuilt

    @classmethod
    def _apply_candidate(
        cls,
        events: list[dict[str, Any]],
        state: dict[str, Any],
        candidate: dict[str, Any],
        hashes: set[str],
        indexed: dict[str, list[dict[str, Any]]],
        position_pct: Decimal,
    ) -> None:
        stock_code = candidate["stock_code"]
        baseline = FreeObservationReview._latest_row(indexed, hashes, stock_code)
        if baseline is None:
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_PRICE_MISSING", "候选缺少对应的观测收盘价")
        trade_date = baseline["trade_date"]
        if state["last_trade_date"] is not None and trade_date < state["last_trade_date"]:
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_TIME_REGRESSION", "观测账本拒绝交易日倒退")
        state["last_trade_date"] = max(filter(None, (state["last_trade_date"], trade_date)))
        action = candidate["would_action"]
        if action == "HOLD":
            cls._append(events, "observation_held", trade_date, {"stock_code": stock_code, "candidate_reason": candidate.get("reason_code")})
            return
        position = state["positions"].get(stock_code)
        price = cls._money(Decimal(str(baseline["close"])))
        if action == "BUY_OBSERVATION":
            if position is not None and position["quantity"] > 0:
                cls._append(events, "observation_open_skipped", trade_date, {"stock_code": stock_code, "reason": "position_already_open"})
                return
            allocation = state["cash"] * position_pct
            quantity = int((allocation / price / Decimal("100")).to_integral_value(rounding=ROUND_DOWN)) * 100
            if quantity <= 0:
                cls._append(events, "observation_open_skipped", trade_date, {"stock_code": stock_code, "reason": "insufficient_virtual_cash"})
                return
            amount = cls._money(price * quantity)
            state["cash"] = cls._money(state["cash"] - amount)
            state["positions"][stock_code] = {"quantity": quantity, "acquired_trade_date": trade_date, "reference_price": str(price)}
            cls._append(events, "observation_position_opened", trade_date, {"stock_code": stock_code, "quantity": quantity, "reference_close": str(price), "amount": str(amount)})
            return
        if position is None or position["quantity"] <= 0:
            cls._append(events, "observation_close_skipped", trade_date, {"stock_code": stock_code, "reason": "no_open_position"})
            return
        if trade_date <= position["acquired_trade_date"]:
            cls._append(events, "observation_close_skipped", trade_date, {"stock_code": stock_code, "reason": "t_plus_one_not_available"})
            return
        quantity = position["quantity"]
        amount = cls._money(price * quantity)
        state["cash"] = cls._money(state["cash"] + amount)
        del state["positions"][stock_code]
        cls._append(events, "observation_position_closed", trade_date, {"stock_code": stock_code, "quantity": quantity, "reference_close": str(price), "amount": str(amount)})

    @classmethod
    def _rebuild(cls, events: list[dict[str, Any]], initial_cash: Decimal) -> dict[str, Any]:
        state = {"initial_cash": initial_cash, "cash": initial_cash, "positions": {}, "events": list(events), "last_trade_date": None}
        for event in events:
            event_type, payload, trade_date = event["event_type"], event["payload"], event["trade_date"]
            if trade_date != "0000-00-00":
                state["last_trade_date"] = max(filter(None, (state["last_trade_date"], trade_date)))
            if event_type == "observation_position_opened":
                state["cash"] = cls._money(state["cash"] - Decimal(payload["amount"]))
                state["positions"][payload["stock_code"]] = {"quantity": payload["quantity"], "acquired_trade_date": trade_date, "reference_price": payload["reference_close"]}
            elif event_type == "observation_position_closed":
                state["cash"] = cls._money(state["cash"] + Decimal(payload["amount"]))
                state["positions"].pop(payload["stock_code"], None)
        return state

    @classmethod
    def _snapshot(cls, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "initial_cash": str(state["initial_cash"]),
            "cash": str(state["cash"]),
            "positions": {key: value for key, value in sorted(state["positions"].items())},
            "last_trade_date": state["last_trade_date"],
        }

    @classmethod
    def _validate_prior(cls, prior: dict[str, Any]) -> None:
        if (
            prior.get("data_mode") != FREE_OBSERVATION_MODE
            or prior.get("formal_use") is not False
            or prior.get("ruleset_version") != FREE_OBSERVATION_LEDGER_RULESET_VERSION
        ):
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_PRIOR_INVALID", "既有账本不属于免费观测账本")
        required = {key: prior.get(key) for key in ("events", "account_snapshot", "ledger_hash")}
        if not isinstance(required["events"], list) or not isinstance(required["account_snapshot"], dict):
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_PRIOR_INVALID", "既有观测账本不完整")
        payload = {key: prior.get(key) for key in ("data_mode", "data_qualification", "formal_use", "ruleset_version", "candidate_result_hash", "input_batch_hashes", "events", "account_snapshot", "formal_write_counts", "release_locks")}
        if prior["ledger_hash"] != cls._hash(payload):
            raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_HASH_MISMATCH", "既有观测账本 Hash 不一致")

    @staticmethod
    def _append(events: list[dict[str, Any]], event_type: str, trade_date: str, payload: dict[str, Any]) -> None:
        event = {"sequence": len(events) + 1, "event_type": event_type, "trade_date": trade_date, "payload": payload}
        event["event_hash"] = FreeObservationLedger._hash(event)
        events.append(event)

    @staticmethod
    def _assert_local_environment() -> None:
        if settings.is_production() or settings.APP_ENV.strip().lower() not in {"development", "local_development"}:
            raise FreeObservationLedgerError("FREE_OBSERVATION_LOCAL_ENV_REQUIRED", "免费观测账本仅允许 local_development")

    @staticmethod
    def _formal_write_counts() -> dict[str, int]:
        return {"order": 0, "execution": 0, "capital": 0, "position": 0, "external_provider": 0}

    @staticmethod
    def _release_locks() -> dict[str, bool]:
        return {key: bool(getattr(settings, key)) for key in RELEASE_LOCK_KEYS}

    @classmethod
    def _assert_release_locks_closed(cls) -> None:
        if any(cls._release_locks().values()):
            raise FreeObservationLedgerError(
                "FREE_OBSERVATION_RELEASE_LOCK_INVALID",
                "发布或交易锁未保持 false，拒绝运行免费观测账本",
            )

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(_CENT)

    @staticmethod
    def _hash(payload: object) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
