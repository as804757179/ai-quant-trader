import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.trade.base_trader import OrderRequest, OrderResult
from app.trade.live_trader import LiveTrader
from app.trade.order_event_bridge import OrderEventBridge
from app.trade.order_manager import OrderManager
from app.trade.order_sync import OrderSyncService
from app.trade.qmt.adapter import BrokerOrder


class _ExecuteResult:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount


class _RecordingDb:
    def __init__(self, update_rowcount=1):
        self.update_rowcount = update_rowcount
        self.calls = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "UPDATE trade.orders" in sql:
            return _ExecuteResult(self.update_rowcount)
        return _ExecuteResult()


class _PartialAdapter:
    name = "test"

    def __init__(self, status="PARTIAL"):
        self.status = status

    async def submit_order(self, **_kwargs):
        return BrokerOrder(
            broker_order_id="PARTIAL-1",
            stock_code="600000",
            side="BUY",
            quantity=1_000,
            status=self.status,
            filled_quantity=300,
            avg_fill_price=10.0,
            message="partial",
        )

    def emit_order_event(self, _order):
        return None


class _CancelAdapter:
    name = "test"

    async def cancel_order(self, _broker_order_id):
        return True

    async def query_order(self, _broker_order_id):
        return BrokerOrder(
            broker_order_id="BROKER-1",
            stock_code="600000",
            side="BUY",
            quantity=1_000,
            status="CANCELLED",
            filled_quantity=300,
            avg_fill_price=10.0,
        )


class _MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _LookupDb:
    def __init__(self, row):
        self.row = row

    async def execute(self, _statement, _params=None):
        return _MappingResult(self.row)


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class OrderFillSemanticsTests(unittest.TestCase):
    @staticmethod
    def _order(
        *, status="SUBMITTED", filled_quantity=0, avg_fill_price=0.0, commission=0.0
    ):
        return {
            "id": "order-1",
            "stock_code": "600000",
            "side": "BUY",
            "quantity": 1_000,
            "status": status,
            "filled_quantity": filled_quantity,
            "avg_fill_price": avg_fill_price,
            "commission": commission,
            "broker_order_id": "BROKER-1",
        }

    def _sync_snapshot(self, db, order, remote):
        async def run():
            syncer = OrderSyncService(db, object(), mode="paper")
            syncer._trader._sync_fill_to_local = AsyncMock()
            with (
                patch(
                    "app.trade.order_sync.recompute_account_assets",
                    new_callable=AsyncMock,
                ),
                patch(
                    "app.trade.order_sync.publish_portfolio_update",
                    new_callable=AsyncMock,
                ),
                patch(
                    "app.trade.order_sync.publish_alert",
                    new_callable=AsyncMock,
                ),
                patch("app.core.config.settings.AUTO_RECONCILE_ON_FILL", False),
            ):
                detail = await syncer.apply_broker_snapshot("order-1", order, remote)
            return detail, syncer._trader._sync_fill_to_local

        return asyncio.run(run())

    def test_order_result_defaults_to_zero_when_not_filled(self):
        self.assertEqual(
            OrderResult(order_id="order-1", status="SUBMITTED").filled_quantity,
            0,
        )

    def test_idempotent_api_result_returns_stored_cumulative_fill_quantity(self):
        manager = OrderManager(
            _LookupDb(
                {
                    "id": "order-1",
                    "status": "PARTIAL",
                    "filled_quantity": 400,
                }
            ),
            object(),
            object(),
            {},
        )
        result = asyncio.run(manager._find_by_idempotency("key", "paper"))
        self.assertEqual(result["filled_quantity"], 400)

    def test_live_trader_returns_actual_partial_fill_quantity(self):
        async def run():
            db = _RecordingDb()
            trader = LiveTrader(db, _PartialAdapter(status="FILLED"), mode="paper")
            trader._connected = True
            trader._sync_fill_to_local = AsyncMock()
            with patch(
                "app.trade.live_trader.recompute_account_assets",
                new_callable=AsyncMock,
            ):
                result = await trader.submit_order(
                    OrderRequest(
                        stock_code="600000",
                        side="BUY",
                        order_type="LIMIT",
                        quantity=1_000,
                        limit_price=10.0,
                    )
                )
            return result, db, trader._sync_fill_to_local

        result, db, sync_fill = asyncio.run(run())
        self.assertEqual(result.status, "PARTIAL")
        self.assertEqual(result.filled_quantity, 300)
        self.assertEqual(sync_fill.await_args.kwargs["quantity"], 300)
        insert_params = next(
            params for sql, params in db.calls if "INSERT INTO trade.orders" in sql
        )
        self.assertEqual(insert_params["filled_quantity"], 300)

    def test_partial_snapshots_apply_only_the_cumulative_delta(self):
        first_db = _RecordingDb()
        first, first_sync = self._sync_snapshot(
            first_db,
            self._order(),
            BrokerOrder(
                broker_order_id="BROKER-1",
                stock_code="600000",
                side="BUY",
                quantity=1_000,
                status="PARTIAL",
                filled_quantity=400,
                avg_fill_price=10.0,
            ),
        )
        self.assertEqual(first["filled_quantity"], 400)
        self.assertEqual(first["filled_quantity_delta"], 400)
        self.assertEqual(first["commission"], 5.0)
        self.assertEqual(first_sync.await_args.kwargs["quantity"], 400)
        self.assertEqual(first_sync.await_args.kwargs["commission"], 5.0)

        duplicate_db = _RecordingDb()
        duplicate, duplicate_sync = self._sync_snapshot(
            duplicate_db,
            self._order(
                status="PARTIAL",
                filled_quantity=400,
                avg_fill_price=10.0,
                commission=5.0,
            ),
            BrokerOrder(
                broker_order_id="BROKER-1",
                stock_code="600000",
                side="BUY",
                quantity=1_000,
                status="PARTIAL",
                filled_quantity=400,
                avg_fill_price=10.0,
            ),
        )
        self.assertFalse(duplicate["changed"])
        duplicate_sync.assert_not_awaited()
        self.assertEqual(duplicate_db.calls, [])

        next_db = _RecordingDb()
        next_detail, next_sync = self._sync_snapshot(
            next_db,
            self._order(
                status="PARTIAL",
                filled_quantity=400,
                avg_fill_price=10.0,
                commission=5.0,
            ),
            BrokerOrder(
                broker_order_id="BROKER-1",
                stock_code="600000",
                side="BUY",
                quantity=1_000,
                status="PARTIAL",
                filled_quantity=700,
                avg_fill_price=11.0,
            ),
        )
        self.assertEqual(next_detail["filled_quantity"], 700)
        self.assertEqual(next_detail["filled_quantity_delta"], 300)
        self.assertEqual(next_sync.await_args.kwargs["quantity"], 300)
        self.assertAlmostEqual(next_sync.await_args.kwargs["fill_price"], 3700 / 300)
        self.assertEqual(next_sync.await_args.kwargs["commission"], 0.0)

    def test_full_snapshot_applies_remaining_delta_once(self):
        detail, sync_fill = self._sync_snapshot(
            _RecordingDb(),
            self._order(
                status="PARTIAL",
                filled_quantity=700,
                avg_fill_price=11.0,
                commission=5.0,
            ),
            BrokerOrder(
                broker_order_id="BROKER-1",
                stock_code="600000",
                side="BUY",
                quantity=1_000,
                status="FILLED",
                filled_quantity=1_000,
                avg_fill_price=12.0,
            ),
        )
        self.assertTrue(detail["fully_filled"])
        self.assertEqual(detail["filled_quantity"], 1_000)
        self.assertEqual(detail["filled_quantity_delta"], 300)
        self.assertEqual(sync_fill.await_args.kwargs["quantity"], 300)
        self.assertAlmostEqual(sync_fill.await_args.kwargs["fill_price"], 4300 / 300)
        self.assertEqual(sync_fill.await_args.kwargs["commission"], 0.0)

    def test_terminal_partial_snapshot_remains_open_and_keeps_fee_cumulative(self):
        detail, sync_fill = self._sync_snapshot(
            _RecordingDb(),
            self._order(),
            BrokerOrder(
                broker_order_id="BROKER-1",
                stock_code="600000",
                side="BUY",
                quantity=1_000,
                status="FILLED",
                filled_quantity=300,
                avg_fill_price=10.0,
            ),
        )

        self.assertEqual(detail["new_status"], "PARTIAL")
        self.assertFalse(detail["fully_filled"])
        self.assertEqual(detail["commission"], 5.0)
        self.assertEqual(sync_fill.await_args.kwargs["commission"], 5.0)

    def test_cancel_uses_cumulative_broker_snapshot_instead_of_local_terminal_write(self):
        class _SnapshotSyncer:
            calls = []

            def __init__(self, *_args, **_kwargs):
                pass

            async def apply_broker_snapshot(self, order_id, order, remote):
                self.calls.append((order_id, order, remote))
                return {"changed": True, "new_status": "CANCELLED"}

        db = _RecordingDb()
        db.execute = AsyncMock(return_value=_MappingResult(self._order()))
        trader = LiveTrader(db, _CancelAdapter(), mode="paper")
        trader._connected = True

        with patch("app.trade.order_sync.OrderSyncService", _SnapshotSyncer):
            result = asyncio.run(trader.cancel_order("order-1"))

        self.assertTrue(result)
        self.assertEqual(len(_SnapshotSyncer.calls), 1)
        _, local_order, remote = _SnapshotSyncer.calls[0]
        self.assertEqual(local_order["filled_quantity"], 0)
        self.assertEqual(remote.filled_quantity, 300)
        self.assertFalse(
            any("SET status = 'CANCELLED'" in sql for sql, _ in db.calls)
        )

    def test_concurrent_snapshot_does_not_duplicate_local_ledger(self):
        detail, sync_fill = self._sync_snapshot(
            _RecordingDb(update_rowcount=0),
            self._order(),
            BrokerOrder(
                broker_order_id="BROKER-1",
                stock_code="600000",
                side="BUY",
                quantity=1_000,
                status="PARTIAL",
                filled_quantity=400,
                avg_fill_price=10.0,
            ),
        )
        self.assertFalse(detail["changed"])
        self.assertEqual(detail["reason"], "concurrent_order_update")
        sync_fill.assert_not_awaited()

    def test_per_trade_callback_without_cumulative_snapshot_is_not_applied(self):
        local = {
            "id": "order-1",
            "stock_code": "600000",
            "side": "BUY",
            "quantity": 1_000,
            "status": "PARTIAL",
            "filled_quantity": 400,
            "avg_fill_price": 10.0,
            "broker_order_id": "BROKER-1",
        }

        class _Syncer:
            apply_called = False

            def __init__(self, *_args, **_kwargs):
                pass

            async def sync_order_by_id(self, _order_id):
                return {"changed": False, "new_status": "PARTIAL"}

            async def apply_broker_snapshot(self, *_args):
                self.apply_called = True
                raise AssertionError("逐笔成交回调不得直接落库")

        bridge = OrderEventBridge()
        bridge._adapter_for_mode = lambda _mode: object()
        with (
            patch(
                "app.trade.order_event_bridge.get_db",
                return_value=_DbContext(_LookupDb(local)),
            ),
            patch("app.trade.order_event_bridge.OrderSyncService", _Syncer),
        ):
            result = asyncio.run(
                bridge.handle_broker_order(
                    "paper",
                    BrokerOrder(
                        broker_order_id="BROKER-1",
                        stock_code="600000",
                        side="BUY",
                        quantity=100,
                        status="FILLED",
                        filled_quantity=100,
                        avg_fill_price=10.0,
                        raw={"source": "on_stock_trade"},
                    ),
                )
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "non_cumulative_trade_callback")


if __name__ == "__main__":
    unittest.main()
