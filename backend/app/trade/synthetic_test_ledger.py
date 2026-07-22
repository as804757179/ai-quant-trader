from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from app.core.config import settings
from app.data.p3_replay_profile import STATUS as P3_PROFILE_STATUS, is_runner_usable
from app.shadow.contracts import RELEASE_LOCK_KEYS, ShadowContractError
from app.shadow.test_execution import TestOnlyShadowRunner
from app.shadow.test_fixtures import (
    TEST_FIXTURE_GENERATOR_VERSION,
    TEST_ONLY_FIXTURE_KIND,
    TEST_ONLY_PROVIDER,
    TEST_ONLY_SOURCE,
    TestOnlyFixtureProvider,
    test_only_now,
)


SYNTHETIC_PAPER_RULESET_VERSION = "p4-synthetic-paper-rules-v1"
TEST_ACCOUNT_ID = "test:p4-synthetic-paper-account-v1"
TEST_ACTOR_ID = "test:local-strategy-admin"
TEST_CURRENCY = "CNY"
INITIAL_CASH = Decimal("100000.00")
SLIPPAGE_PER_SHARE = Decimal("0.01")
FEE_RATE = Decimal("0.001")
MIN_FEE = Decimal("0.01")
_CENT = Decimal("0.01")
_EVENT_EPOCH = datetime(2026, 7, 22, 9, 30, tzinfo=timezone.utc)


class SyntheticPaperError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SyntheticExecutionReference:
    fixture_kind: str
    provider: str
    source: str
    generator_version: str
    information_cutoff: datetime
    available_at: datetime
    execution_price: Decimal
    manifest_hash: str
    dataset_hash: str
    input_snapshot_hash: str
    row_hashes: tuple[str, ...]
    reference_hash: str
    network_request_count: int


@dataclass(frozen=True)
class SyntheticLedgerEvent:
    sequence: int
    event_type: str
    order_id: str | None
    actor_id: str
    occurred_at: datetime
    payload: dict[str, object]
    payload_hash: str


@dataclass(frozen=True)
class SyntheticOrderReceipt:
    order_id: str
    request_hash: str
    idempotency_key: str


@dataclass(frozen=True)
class SyntheticReconciliationResult:
    matched: bool
    expected_hash: str
    reconstructed_hash: str
    difference: str | None


class SyntheticPaperLedger:
    """In-memory, test-only append-only ledger with no database or provider capability."""

    def __init__(
        self,
        *,
        environment: str = "local_development",
        initial_cash: Decimal = INITIAL_CASH,
    ) -> None:
        app_environment = settings.APP_ENV.strip().lower()
        if (
            environment != "local_development"
            or settings.is_production()
            or app_environment not in {"development", "local_development"}
        ):
            raise SyntheticPaperError(
                "P4_TEST_ONLY_ENV_REQUIRED",
                "synthetic/test-only 账务仅允许 local_development，拒绝非本地或 production 环境",
            )
        if initial_cash <= 0:
            raise SyntheticPaperError("P4_TEST_INITIAL_CASH_INVALID", "测试初始资金必须为正数")
        self.environment = environment
        self.initial_cash = self._money(initial_cash)
        self._events: list[SyntheticLedgerEvent] = []
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._assert_formal_state()
        self._append(
            "ledger_initialized",
            None,
            TEST_ACTOR_ID,
            {
                "account_id": TEST_ACCOUNT_ID,
                "currency": TEST_CURRENCY,
                "initial_cash": str(self.initial_cash),
                "ruleset_version": SYNTHETIC_PAPER_RULESET_VERSION,
                "fixture_kind": TEST_ONLY_FIXTURE_KIND,
            },
        )

    @property
    def events(self) -> tuple[SyntheticLedgerEvent, ...]:
        return tuple(self._events)

    @staticmethod
    def build_execution_reference(
        *,
        information_cutoff: datetime | None = None,
        provider: TestOnlyFixtureProvider | None = None,
    ) -> SyntheticExecutionReference:
        cutoff = information_cutoff or test_only_now()
        fixture_provider = provider or TestOnlyFixtureProvider()
        if not isinstance(fixture_provider, TestOnlyFixtureProvider):
            raise SyntheticPaperError(
                "P4_TEST_ONLY_INPUT_REQUIRED",
                "synthetic 账务仅接受内置 synthetic/test-only fixture Provider",
            )
        request = TestOnlyShadowRunner.build_request(information_cutoff=cutoff)
        try:
            shadow_result = TestOnlyShadowRunner(fixture_provider).execute(
                run_id="test:p4-synthetic-reference", request=request
            )
        except ShadowContractError as exc:
            raise SyntheticPaperError(exc.code, str(exc)) from exc
        if fixture_provider.network_request_count != 0:
            raise SyntheticPaperError(
                "P4_EXTERNAL_PROVIDER_FORBIDDEN",
                "synthetic/test-only 执行参考不得访问外部 Provider",
            )
        batch = fixture_provider.load(information_cutoff=cutoff)
        visible = tuple(
            bar
            for bar in batch.bars
            if bar.trading_at <= cutoff and bar.available_at is not None and bar.available_at <= cutoff
        )
        if not visible:
            raise SyntheticPaperError("P4_SYNTHETIC_REFERENCE_UNAVAILABLE", "没有可见的 synthetic 执行参考")
        price = SyntheticPaperLedger._money(Decimal(str(visible[-1].close)))
        payload = {
            "fixture_kind": batch.fixture_kind,
            "provider": TEST_ONLY_PROVIDER,
            "source": TEST_ONLY_SOURCE,
            "generator_version": TEST_FIXTURE_GENERATOR_VERSION,
            "information_cutoff": cutoff.isoformat(),
            "available_at": visible[-1].available_at.isoformat(),
            "execution_price": str(price),
            "manifest_hash": shadow_result.input_manifest_hash,
            "dataset_hash": shadow_result.dataset_hash,
            "input_snapshot_hash": shadow_result.input_snapshot_hash,
            "row_hashes": list(shadow_result.row_hashes),
        }
        return SyntheticExecutionReference(
            fixture_kind=batch.fixture_kind,
            provider=TEST_ONLY_PROVIDER,
            source=TEST_ONLY_SOURCE,
            generator_version=TEST_FIXTURE_GENERATOR_VERSION,
            information_cutoff=cutoff,
            available_at=visible[-1].available_at,
            execution_price=price,
            manifest_hash=shadow_result.input_manifest_hash,
            dataset_hash=shadow_result.dataset_hash,
            input_snapshot_hash=shadow_result.input_snapshot_hash,
            row_hashes=shadow_result.row_hashes,
            reference_hash=SyntheticPaperLedger._hash(payload),
            network_request_count=fixture_provider.network_request_count,
        )

    def submit_order(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        stock_code: str,
        side: Literal["BUY", "SELL"],
        quantity: int,
        limit_price: Decimal,
        reference: SyntheticExecutionReference,
        reason: str,
    ) -> SyntheticOrderReceipt:
        self._assert_formal_state()
        self._assert_test_actor(actor_id)
        self._validate_reference(reference)
        if not idempotency_key or not reason:
            raise SyntheticPaperError("P4_TEST_REQUEST_INCOMPLETE", "幂等键和创建原因不能为空")
        if not stock_code.startswith("TEST:"):
            raise SyntheticPaperError("P4_TEST_ONLY_INPUT_REQUIRED", "仅允许 test-only 股票代码")
        if side not in {"BUY", "SELL"} or quantity <= 0:
            raise SyntheticPaperError("P4_TEST_ORDER_INVALID", "测试订单方向或数量无效")
        normalized_limit = self._money(limit_price)
        if normalized_limit <= 0:
            raise SyntheticPaperError("P4_TEST_ORDER_INVALID", "测试订单限价必须为正数")
        payload = {
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
            "stock_code": stock_code,
            "side": side,
            "quantity": quantity,
            "limit_price": str(normalized_limit),
            "reference_hash": reference.reference_hash,
            "reason": reason,
            "ruleset_version": SYNTHETIC_PAPER_RULESET_VERSION,
            "fixture_kind": TEST_ONLY_FIXTURE_KIND,
        }
        request_hash = self._hash(payload)
        existing = self._idempotency.get(idempotency_key)
        if existing is not None:
            existing_hash, existing_order_id = existing
            if existing_hash != request_hash:
                raise SyntheticPaperError(
                    "P4_TEST_IDEMPOTENCY_CONFLICT",
                    "相同幂等键对应不同请求 Hash，已拒绝重复提交",
                )
            return SyntheticOrderReceipt(existing_order_id, existing_hash, idempotency_key)
        order_id = f"test:p4-order:{request_hash[:24]}"
        self._append("submitted", order_id, actor_id, {**payload, "request_hash": request_hash})
        self._idempotency[idempotency_key] = (request_hash, order_id)
        return SyntheticOrderReceipt(order_id, request_hash, idempotency_key)

    def approve_order(
        self,
        *,
        order_id: str,
        actor_id: str,
        approved: bool,
        reason: str,
        single_operator_exception: bool = False,
    ) -> None:
        self._assert_formal_state()
        self._assert_test_actor(actor_id)
        state = self.rebuild()
        order = self._get_order(state, order_id)
        if order["status"] != "submitted":
            raise SyntheticPaperError("P4_TEST_APPROVAL_STATE_INVALID", "订单当前状态不允许审批")
        same_actor = actor_id == order["submitter_id"]
        if same_actor and not single_operator_exception:
            raise SyntheticPaperError(
                "P4_TEST_SEPARATION_OF_DUTIES_REQUIRED",
                "同一测试主体审批必须显式声明 local_development 单人例外",
            )
        reserve = Decimal("0.00")
        freeze_quantity = 0
        if approved and order["side"] == "BUY":
            reserve = self._money(
                Decimal(order["limit_price"]) * int(order["quantity"])
                + self._fee(Decimal(order["limit_price"]) * int(order["quantity"]))
            )
            if self._cash_available(state) < reserve:
                raise SyntheticPaperError("P4_TEST_INSUFFICIENT_CASH", "测试账户可用资金不足，拒绝接受订单")
        elif approved:
            position = state["positions"].get(order["stock_code"], self._empty_position())
            freeze_quantity = int(order["quantity"])
            if int(position["available_quantity"]) < freeze_quantity:
                raise SyntheticPaperError("P4_TEST_INSUFFICIENT_AVAILABLE_QTY", "测试账户可用持仓不足，拒绝接受卖单")
        payload = {
            "approved": approved,
            "reason": reason,
            "single_operator_exception": bool(same_actor and single_operator_exception),
            "separation_of_duties": not same_actor,
            "environment": self.environment,
        }
        self._append("approval", order_id, actor_id, payload)
        if not approved:
            return
        if order["side"] == "BUY":
            self._append("cash_frozen", order_id, actor_id, {"amount": str(reserve)})
        else:
            self._append("quantity_frozen", order_id, actor_id, {"quantity": freeze_quantity})

    def execute_order(self, *, order_id: str, reference: SyntheticExecutionReference) -> bool:
        self._assert_formal_state()
        self._validate_reference(reference)
        state = self.rebuild()
        order = self._get_order(state, order_id)
        if order["status"] != "accepted":
            raise SyntheticPaperError("P4_TEST_EXECUTION_STATE_INVALID", "订单未经批准接受，不能执行")
        if order["reference_hash"] != reference.reference_hash:
            raise SyntheticPaperError("P4_TEST_EXECUTION_REFERENCE_MISMATCH", "订单与执行参考 Hash 不一致")
        base_price = reference.execution_price
        execution_price = self._money(
            base_price + SLIPPAGE_PER_SHARE if order["side"] == "BUY" else base_price - SLIPPAGE_PER_SHARE
        )
        limit_price = Decimal(order["limit_price"])
        executable = execution_price <= limit_price if order["side"] == "BUY" else execution_price >= limit_price
        if not executable:
            self._append("unfilled", order_id, TEST_ACTOR_ID, {"execution_price": str(execution_price)})
            return False
        quantity = int(order["quantity"])
        notional = self._money(execution_price * quantity)
        fee = self._fee(notional)
        if order["side"] == "BUY":
            reserve = Decimal(order["reserved_cash"])
            actual = self._money(notional + fee)
            if reserve < actual:
                raise SyntheticPaperError("P4_TEST_ACCOUNT_INVARIANT_FAILED", "冻结资金不足以覆盖测试成交")
            payload = {
                "execution_price": str(execution_price),
                "quantity": quantity,
                "notional": str(notional),
                "fee": str(fee),
                "cash_delta": str(-actual),
                "frozen_cash_delta": str(-reserve),
                "total_quantity_delta": quantity,
                "available_quantity_delta": 0,
                "frozen_quantity_delta": 0,
                "reference_hash": reference.reference_hash,
            }
        else:
            payload = {
                "execution_price": str(execution_price),
                "quantity": quantity,
                "notional": str(notional),
                "fee": str(fee),
                "cash_delta": str(self._money(notional - fee)),
                "frozen_cash_delta": "0.00",
                "total_quantity_delta": -quantity,
                "available_quantity_delta": 0,
                "frozen_quantity_delta": -quantity,
                "reference_hash": reference.reference_hash,
            }
        self._append("filled", order_id, TEST_ACTOR_ID, payload)
        return True

    def cancel_order(self, *, order_id: str, actor_id: str, reason: str) -> None:
        self._assert_formal_state()
        self._assert_test_actor(actor_id)
        state = self.rebuild()
        order = self._get_order(state, order_id)
        if order["status"] not in {"accepted", "unfilled"}:
            raise SyntheticPaperError("P4_TEST_CANCEL_STATE_INVALID", "订单当前状态不能撤单")
        if order["side"] == "BUY":
            payload = {"reason": reason, "release_cash": order["reserved_cash"], "release_quantity": 0}
        else:
            payload = {"reason": reason, "release_cash": "0.00", "release_quantity": order["reserved_quantity"]}
        self._append("cancelled", order_id, actor_id, payload)

    def release_t1(self, *, order_id: str, actor_id: str) -> None:
        self._assert_formal_state()
        self._assert_test_actor(actor_id)
        state = self.rebuild()
        order = self._get_order(state, order_id)
        if order["status"] != "filled" or order["side"] != "BUY":
            raise SyntheticPaperError("P4_TEST_SETTLEMENT_STATE_INVALID", "仅已成交买单可执行 test-only T+1 释放")
        quantity = int(order["quantity"])
        self._append("t1_released", order_id, actor_id, {"quantity": quantity})

    def rebuild(self) -> dict[str, object]:
        state: dict[str, object] = {
            "account_id": TEST_ACCOUNT_ID,
            "currency": TEST_CURRENCY,
            "cash": self.initial_cash,
            "frozen_cash": Decimal("0.00"),
            "positions": {},
            "orders": {},
        }
        expected_sequence = 1
        for event in self._events:
            if event.sequence != expected_sequence or event.payload_hash != self._hash(event.payload):
                raise SyntheticPaperError("P4_TEST_EVENT_HASH_MISMATCH", "测试账务事件序列或 Hash 不一致")
            expected_sequence += 1
            self._apply_event(state, event)
            self._assert_invariants(state)
        return state

    def reconcile(self, *, expected_snapshot: dict[str, object] | None = None) -> SyntheticReconciliationResult:
        reconstructed = self.rebuild()
        expected = expected_snapshot or reconstructed
        expected_hash = self.snapshot_hash(expected)
        reconstructed_hash = self.snapshot_hash(reconstructed)
        return SyntheticReconciliationResult(
            matched=expected_hash == reconstructed_hash,
            expected_hash=expected_hash,
            reconstructed_hash=reconstructed_hash,
            difference=None if expected_hash == reconstructed_hash else "P4_SYNTHETIC_RECONCILIATION_MISMATCH",
        )

    def reconcile_or_raise(self, *, expected_snapshot: dict[str, object] | None = None) -> SyntheticReconciliationResult:
        result = self.reconcile(expected_snapshot=expected_snapshot)
        if not result.matched:
            raise SyntheticPaperError(
                "P4_SYNTHETIC_RECONCILIATION_MISMATCH",
                "测试账务重建与期望快照不一致，已 fail-closed",
            )
        return result

    def audit_report(self) -> dict[str, object]:
        state = self.rebuild()
        reconciliation = self.reconcile_or_raise()
        locks = self._release_locks()
        report = {
            "environment": self.environment,
            "fixture_kind": TEST_ONLY_FIXTURE_KIND,
            "ruleset_version": SYNTHETIC_PAPER_RULESET_VERSION,
            "account_id": TEST_ACCOUNT_ID,
            "event_hashes": [event.payload_hash for event in self._events],
            "event_count": len(self._events),
            "snapshot_hash": self.snapshot_hash(state),
            "reconciliation": {
                "matched": reconciliation.matched,
                "expected_hash": reconciliation.expected_hash,
                "reconstructed_hash": reconciliation.reconstructed_hash,
            },
            "formal_write_counts": {
                "order": 0,
                "execution": 0,
                "capital": 0,
                "position": 0,
                "external_provider": 0,
            },
            "release_locks": locks,
            "formal_p3_replay": "blocked/deferred",
            "formal_p4": "not_authorized",
            "profile": {"status": P3_PROFILE_STATUS, "runner_usable": is_runner_usable()},
        }
        report["audit_report_hash"] = self._hash(report)
        return report

    @staticmethod
    def snapshot_hash(snapshot: dict[str, object]) -> str:
        return SyntheticPaperLedger._hash(SyntheticPaperLedger._canonical_snapshot(snapshot))

    def _append(self, event_type: str, order_id: str | None, actor_id: str, payload: dict[str, object]) -> None:
        sequence = len(self._events) + 1
        self._events.append(
            SyntheticLedgerEvent(
                sequence=sequence,
                event_type=event_type,
                order_id=order_id,
                actor_id=actor_id,
                occurred_at=_EVENT_EPOCH + timedelta(seconds=sequence),
                payload=payload,
                payload_hash=self._hash(payload),
            )
        )

    def _apply_event(self, state: dict[str, object], event: SyntheticLedgerEvent) -> None:
        orders = state["orders"]
        positions = state["positions"]
        assert isinstance(orders, dict) and isinstance(positions, dict)
        if event.event_type == "ledger_initialized":
            return
        if event.order_id is None:
            raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "订单事件缺少 order_id")
        if event.event_type == "submitted":
            if event.order_id in orders:
                raise SyntheticPaperError("P4_TEST_EVENT_DUPLICATE", "测试订单提交事件重复")
            orders[event.order_id] = {
                "status": "submitted",
                "submitter_id": event.payload["actor_id"],
                "stock_code": event.payload["stock_code"],
                "side": event.payload["side"],
                "quantity": event.payload["quantity"],
                "limit_price": event.payload["limit_price"],
                "reference_hash": event.payload["reference_hash"],
                "reserved_cash": "0.00",
                "reserved_quantity": 0,
                "filled_price": None,
                "fee": "0.00",
            }
            return
        order = self._get_order(state, event.order_id)
        if event.event_type == "approval":
            if order["status"] != "submitted":
                raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "审批事件状态不合法")
            order["status"] = "accepted" if event.payload["approved"] else "rejected"
        elif event.event_type == "cash_frozen":
            if order["status"] != "accepted" or order["side"] != "BUY":
                raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "资金冻结事件状态不合法")
            amount = Decimal(str(event.payload["amount"]))
            state["frozen_cash"] = self._money(Decimal(state["frozen_cash"]) + amount)
            order["reserved_cash"] = str(amount)
        elif event.event_type == "quantity_frozen":
            if order["status"] != "accepted" or order["side"] != "SELL":
                raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "持仓冻结事件状态不合法")
            quantity = int(event.payload["quantity"])
            position = positions.setdefault(order["stock_code"], self._empty_position())
            position["available_quantity"] -= quantity
            position["frozen_quantity"] += quantity
            order["reserved_quantity"] = quantity
        elif event.event_type == "unfilled":
            if order["status"] != "accepted":
                raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "未成交事件状态不合法")
            order["status"] = "unfilled"
        elif event.event_type == "filled":
            if order["status"] != "accepted":
                raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "成交事件状态不合法")
            quantity = int(event.payload["quantity"])
            position = positions.setdefault(order["stock_code"], self._empty_position())
            state["cash"] = self._money(Decimal(state["cash"]) + Decimal(str(event.payload["cash_delta"])))
            state["frozen_cash"] = self._money(
                Decimal(state["frozen_cash"]) + Decimal(str(event.payload["frozen_cash_delta"]))
            )
            position["total_quantity"] += int(event.payload["total_quantity_delta"])
            position["available_quantity"] += int(event.payload["available_quantity_delta"])
            position["frozen_quantity"] += int(event.payload["frozen_quantity_delta"])
            order["status"] = "filled"
            order["filled_price"] = event.payload["execution_price"]
            order["fee"] = event.payload["fee"]
            if quantity != int(order["quantity"]):
                raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "test-only 不支持部分成交")
        elif event.event_type == "cancelled":
            if order["status"] not in {"accepted", "unfilled"}:
                raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "撤单事件状态不合法")
            release_cash = Decimal(str(event.payload["release_cash"]))
            release_quantity = int(event.payload["release_quantity"])
            state["frozen_cash"] = self._money(Decimal(state["frozen_cash"]) - release_cash)
            if release_quantity:
                position = positions.setdefault(order["stock_code"], self._empty_position())
                position["available_quantity"] += release_quantity
                position["frozen_quantity"] -= release_quantity
            order["status"] = "cancelled"
            order["reserved_cash"] = "0.00"
            order["reserved_quantity"] = 0
        elif event.event_type == "t1_released":
            if order["status"] != "filled" or order["side"] != "BUY":
                raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "T+1 释放事件状态不合法")
            position = positions.setdefault(order["stock_code"], self._empty_position())
            position["available_quantity"] += int(event.payload["quantity"])
        else:
            raise SyntheticPaperError("P4_TEST_EVENT_INVALID", "未知 test-only 账务事件")

    def _assert_invariants(self, state: dict[str, object]) -> None:
        cash = Decimal(state["cash"])
        frozen_cash = Decimal(state["frozen_cash"])
        if cash < 0 or frozen_cash < 0 or frozen_cash > cash:
            raise SyntheticPaperError("P4_TEST_ACCOUNT_INVARIANT_FAILED", "测试账户现金或冻结资金不变量失败")
        positions = state["positions"]
        assert isinstance(positions, dict)
        for position in positions.values():
            total = int(position["total_quantity"])
            available = int(position["available_quantity"])
            frozen = int(position["frozen_quantity"])
            if min(total, available, frozen) < 0 or available + frozen > total:
                raise SyntheticPaperError("P4_TEST_ACCOUNT_INVARIANT_FAILED", "测试持仓数量不变量失败")

    def _assert_formal_state(self) -> None:
        if P3_PROFILE_STATUS != "draft" or is_runner_usable():
            raise SyntheticPaperError("P4_FORMAL_PROFILE_STATE_CHANGED", "正式 P3 Profile 不再是 draft/disabled")
        locks = self._release_locks()
        if any(locks.values()):
            raise SyntheticPaperError("P4_RELEASE_LOCK_CHANGED", "发布或交易锁必须保持 false")

    def _validate_reference(self, reference: SyntheticExecutionReference) -> None:
        if (
            reference.fixture_kind != TEST_ONLY_FIXTURE_KIND
            or reference.provider != TEST_ONLY_PROVIDER
            or reference.source != TEST_ONLY_SOURCE
            or reference.generator_version != TEST_FIXTURE_GENERATOR_VERSION
            or reference.network_request_count != 0
            or not reference.row_hashes
        ):
            raise SyntheticPaperError("P4_TEST_ONLY_INPUT_REQUIRED", "执行参考不是已验证的 synthetic/test-only 输入")
        payload = {
            "fixture_kind": reference.fixture_kind,
            "provider": reference.provider,
            "source": reference.source,
            "generator_version": reference.generator_version,
            "information_cutoff": reference.information_cutoff.isoformat(),
            "available_at": reference.available_at.isoformat(),
            "execution_price": str(reference.execution_price),
            "manifest_hash": reference.manifest_hash,
            "dataset_hash": reference.dataset_hash,
            "input_snapshot_hash": reference.input_snapshot_hash,
            "row_hashes": list(reference.row_hashes),
        }
        if reference.available_at > reference.information_cutoff or reference.reference_hash != self._hash(payload):
            raise SyntheticPaperError("P4_TEST_EXECUTION_REFERENCE_INVALID", "执行参考的时间或 Hash 无效")

    @staticmethod
    def _get_order(state: dict[str, object], order_id: str) -> dict[str, object]:
        orders = state["orders"]
        assert isinstance(orders, dict)
        order = orders.get(order_id)
        if not isinstance(order, dict):
            raise SyntheticPaperError("P4_TEST_ORDER_NOT_FOUND", "测试订单不存在")
        return order

    @staticmethod
    def _empty_position() -> dict[str, int]:
        return {"total_quantity": 0, "available_quantity": 0, "frozen_quantity": 0}

    @staticmethod
    def _cash_available(state: dict[str, object]) -> Decimal:
        return SyntheticPaperLedger._money(Decimal(state["cash"]) - Decimal(state["frozen_cash"]))

    @staticmethod
    def _fee(notional: Decimal) -> Decimal:
        return max(MIN_FEE, SyntheticPaperLedger._money(notional * FEE_RATE))

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)

    @staticmethod
    def _assert_test_actor(actor_id: str) -> None:
        if not actor_id.startswith("test:"):
            raise SyntheticPaperError("P4_TEST_ACTOR_REQUIRED", "仅允许 test-only 人工责任主体")

    @staticmethod
    def _release_locks() -> dict[str, bool]:
        return {key: bool(getattr(settings, key)) for key in RELEASE_LOCK_KEYS}

    @staticmethod
    def _canonical_snapshot(value: object) -> object:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {str(key): SyntheticPaperLedger._canonical_snapshot(item) for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [SyntheticPaperLedger._canonical_snapshot(item) for item in value]
        return value

    @staticmethod
    def _hash(payload: object) -> str:
        return hashlib.sha256(
            json.dumps(
                SyntheticPaperLedger._canonical_snapshot(payload),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
