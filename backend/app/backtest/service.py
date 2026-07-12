"""回测编排：加载 K 线 → 信号生成 → 引擎执行 → 落库。"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from sqlalchemy import text

from app.backtest.engine import BacktestEngine
from app.backtest.metrics import summarize_result
from app.backtest.schemas import BacktestConfig, BacktestResult
from app.core.config import settings
from app.core.logging import FEATURE_BACKTEST, get_logger
from app.data.certified_kline_repository import CertifiedKlineRepository
from app.data.kline_backfill import KlineBackfillService
from app.db import get_db
from app.strategy.catalog import get_strategy_meta
from app.strategy.config_store import StrategyConfigStore
from app.strategy.signals import make_signal_generator

logger = get_logger(__name__, feature=FEATURE_BACKTEST)


class BacktestService:
    def __init__(
        self,
        config_store: StrategyConfigStore | None = None,
        kline_repository: CertifiedKlineRepository | None = None,
    ) -> None:
        self.config_store = config_store or StrategyConfigStore()
        self.kline_repository = kline_repository or CertifiedKlineRepository()
        self.engine = BacktestEngine()

    async def create_and_run(
        self,
        *,
        strategy_type: str,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
        initial_cash: float = 1_000_000,
        params: dict[str, Any] | None = None,
        name: str | None = None,
        auto_backfill: bool | None = None,
        allow_synthetic: bool | None = None,
        requirement_profile: str | None = None,
        required_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        if not settings.CERTIFIED_BACKTEST_EXECUTION_ENABLED:
            raise ValueError("Sprint06 仅允许 certified 数据可用性检查，真实回测执行仍关闭。")
        meta = get_strategy_meta(strategy_type)
        if not meta:
            raise ValueError(f"未知策略类型: {strategy_type}")
        if not requirement_profile or not required_fields:
            raise ValueError("backtest requirement_profile and required_fields are required")
        if requirement_profile != meta.get("requirement_profile") or set(
            required_fields
        ) != set(meta.get("required_fields") or []):
            raise ValueError("backtest data declaration does not match strategy fields")
        if not stock_codes:
            raise ValueError("stock_codes 不能为空")
        if start_date >= end_date:
            raise ValueError("start_date 必须早于 end_date")

        do_backfill = (
            settings.BACKTEST_AUTO_BACKFILL if auto_backfill is None else auto_backfill
        )
        use_synthetic = (
            settings.BACKTEST_ALLOW_SYNTHETIC_KLINE
            if allow_synthetic is None
            else allow_synthetic
        )
        if use_synthetic and not settings.SYNTHETIC_KLINE_SMOKE_TEST:
            raise ValueError(
                "Synthetic Kline 仅允许在 SYNTHETIC_KLINE_SMOKE_TEST=true 的 Smoke Test 环境中使用"
            )

        stored = self.config_store.get(strategy_type) or {}
        merged_params = {
            **meta["default_params"],
            **(stored.get("params") or {}),
            **(params or {}),
        }
        task_name = name or f"{meta['name']}:{','.join(stock_codes[:3])}"
        universe_str = ",".join(stock_codes)

        task_id = await self._create_task(
            name=task_name,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            universe=universe_str,
            strategy_type=strategy_type,
        )
        logger.info(
            "backtest_task_created",
            task_id=task_id,
            strategy_type=strategy_type,
            stock_codes=stock_codes,
            start_date=str(start_date),
            end_date=str(end_date),
            initial_cash=initial_cash,
            auto_backfill=do_backfill,
            allow_synthetic=use_synthetic,
            params=merged_params,
        )
        await self._update_task(task_id, status="running", progress=10)

        data_meta: dict[str, Any] = {"backfill": None, "synthetic_used": False}
        t0 = time.perf_counter()
        try:
            await self.kline_repository.assert_dataset_ready(
                stock_codes,
                period="1d",
                adjustment="raw",
                research_use_scope="return_backtest",
                requirement_profile=requirement_profile,
                required_fields=required_fields,
                start_date=start_date,
                end_date=end_date,
            )
            if do_backfill:
                bf = KlineBackfillService()
                try:
                    ensure = await bf.ensure_range(
                        stock_codes,
                        start_date,
                        end_date,
                        allow_synthetic=use_synthetic,
                    )
                    data_meta["backfill"] = ensure
                    if ensure.get("stats") and ensure["stats"].get("synthetic", 0) > 0:
                        data_meta["synthetic_used"] = True
                finally:
                    await bf.close()
                await self._update_task(task_id, progress=25)

            bars = await self._load_bars(
                stock_codes,
                start_date,
                end_date,
                requirement_profile=requirement_profile,
                required_fields=required_fields,
            )
            if not bars and use_synthetic:
                # 无 DB 或写入失败时，直接用内存合成 K 线跑通回测
                from app.data.kline_backfill import generate_synthetic_klines

                rows = []
                for code in stock_codes:
                    for k in generate_synthetic_klines(code, start_date, end_date):
                        rows.append(
                            {
                                "stock_code": code,
                                "trade_date": k["time"][:10],
                                "open": k["open"],
                                "high": k["high"],
                                "low": k["low"],
                                "close": k["close"],
                                "volume": k["volume"],
                                "amount": k["amount"],
                            }
                        )
                raise ValueError("当前标的/时间区间无已认证历史数据，禁止真实回测。")

            if data_meta["synthetic_used"]:
                data_meta["warning"] = "该回测结果不能作为投资依据。"
                logger.warning(
                    "backtest_synthetic_kline_used",
                    task_id=task_id,
                    warning=data_meta["warning"],
                )

            if not bars:
                raise ValueError(
                    "回测区间内无可用 K 线数据。请先 POST /stock/backfill-kline "
                    "或开启 BACKTEST_ALLOW_SYNTHETIC_KLINE"
                )

            config = BacktestConfig(
                start_date=start_date,
                end_date=end_date,
                universe=stock_codes,
                initial_cash=initial_cash,
            )
            generator = make_signal_generator(
                strategy_type,
                stock_codes,
                merged_params,
                initial_cash=initial_cash,
            )
            await self._update_task(task_id, progress=40)
            result = self.engine.run(config, bars, signal_generator=generator)
            await self._update_task(task_id, progress=80)

            summary = summarize_result(result)
            await self._save_result(task_id, result, summary, strategy_type, merged_params)
            await self._update_task(
                task_id,
                status="done",
                progress=100,
                finished=True,
            )
            elapsed = time.perf_counter() - t0
            try:
                from app.monitoring.metrics import record_backtest

                record_backtest("done", elapsed)
            except Exception:
                pass
            logger.info(
                "backtest_task_done",
                task_id=task_id,
                strategy_type=strategy_type,
                elapsed_sec=round(elapsed, 3),
                trade_count=len(result.trades),
                synthetic_used=data_meta.get("synthetic_used"),
                total_return=summary.get("total_return"),
                max_drawdown=summary.get("max_drawdown"),
                sharpe=summary.get("sharpe"),
            )
            return {
                "task_id": task_id,
                "status": "done",
                "strategy_type": strategy_type,
                "params": merged_params,
                "data_meta": data_meta,
                "metrics": summary,
                "equity_curve": [
                    {
                        "trade_date": p.trade_date.isoformat(),
                        "cash": round(p.cash, 2),
                        "market_value": round(p.market_value, 2),
                        "total_assets": round(p.total_assets, 2),
                        "daily_return": round(p.daily_return, 6),
                    }
                    for p in result.equity_curve
                ],
                "trades": [
                    {
                        "stock_code": t.stock_code,
                        "side": t.side,
                        "signal_date": t.signal_date.isoformat(),
                        "execution_date": t.execution_date.isoformat(),
                        "quantity": t.quantity,
                        "fill_price": t.fill_price,
                        "status": t.status,
                        "fail_reason": t.fail_reason,
                        "commission": t.commission,
                    }
                    for t in result.trades
                ],
            }
        except Exception as exc:
            logger.error("backtest_failed", task_id=task_id, error=str(exc), exc_info=True)
            await self._update_task(
                task_id,
                status="failed",
                progress=100,
                error_msg=str(exc),
                finished=True,
            )
            try:
                from app.monitoring.metrics import record_backtest

                record_backtest("failed", time.perf_counter() - t0)
            except Exception:
                pass
            raise

    async def get_status(self, task_id: int) -> dict[str, Any]:
        async with get_db() as db:
            row = await db.execute(
                text(
                    """
                    SELECT id, name, start_date, end_date, initial_cash, universe,
                           status, progress, error_msg, created_at, started_at, finished_at
                    FROM backtest.tasks WHERE id = :id
                    """
                ),
                {"id": task_id},
            )
            task = row.mappings().first()
            if not task:
                raise ValueError(f"任务不存在: {task_id}")

            result_row = await db.execute(
                text(
                    """
                    SELECT total_return, annual_return, max_drawdown, sharpe_ratio,
                           calmar_ratio, win_rate, total_trades, equity_curve, trade_list
                    FROM backtest.results
                    WHERE task_id = :id
                    ORDER BY id DESC LIMIT 1
                    """
                ),
                {"id": task_id},
            )
            result = result_row.mappings().first()

        payload: dict[str, Any] = {
            "task_id": task["id"],
            "name": task["name"],
            "status": task["status"],
            "progress": task["progress"],
            "error_msg": task["error_msg"],
            "start_date": str(task["start_date"]),
            "end_date": str(task["end_date"]),
            "universe": task["universe"],
            "initial_cash": float(task["initial_cash"] or 0),
            "created_at": task["created_at"].isoformat() if task.get("created_at") else None,
            "finished_at": task["finished_at"].isoformat() if task.get("finished_at") else None,
        }
        if result:
            payload["metrics"] = {
                "total_return": float(result["total_return"] or 0),
                "annual_return": float(result["annual_return"] or 0),
                "max_drawdown": float(result["max_drawdown"] or 0),
                "sharpe_ratio": float(result["sharpe_ratio"] or 0),
                "calmar_ratio": float(result["calmar_ratio"] or 0),
                "win_rate": float(result["win_rate"] or 0),
                "total_trades": result["total_trades"],
            }
            eq = result["equity_curve"]
            if isinstance(eq, str):
                eq = json.loads(eq)
            payload["equity_curve"] = eq
            trades = result["trade_list"]
            if isinstance(trades, str):
                trades = json.loads(trades)
            payload["trades"] = trades
        return payload

    async def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        async with get_db() as db:
            rows = await db.execute(
                text(
                    """
                    SELECT id, name, status, progress, start_date, end_date,
                           universe, created_at, finished_at, error_msg
                    FROM backtest.tasks
                    ORDER BY id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            items = []
            for r in rows.mappings().all():
                items.append(
                    {
                        "task_id": r["id"],
                        "name": r["name"],
                        "status": r["status"],
                        "progress": r["progress"],
                        "start_date": str(r["start_date"]),
                        "end_date": str(r["end_date"]),
                        "universe": r["universe"],
                        "created_at": r["created_at"].isoformat()
                        if r.get("created_at")
                        else None,
                        "error_msg": r["error_msg"],
                    }
                )
            return items

    async def _create_task(
        self,
        *,
        name: str,
        start_date: date,
        end_date: date,
        initial_cash: float,
        universe: str,
        strategy_type: str,
    ) -> int:
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    INSERT INTO backtest.tasks
                    (name, start_date, end_date, initial_cash, universe, status, progress, started_at)
                    VALUES
                    (:name, :start_date, :end_date, :initial_cash, :universe, 'pending', 0, NOW())
                    RETURNING id
                    """
                ),
                {
                    "name": f"[{strategy_type}] {name}",
                    "start_date": start_date,
                    "end_date": end_date,
                    "initial_cash": initial_cash,
                    "universe": universe,
                },
            )
            task_id = result.scalar_one()
            return int(task_id)

    async def _update_task(
        self,
        task_id: int,
        *,
        status: str | None = None,
        progress: int | None = None,
        error_msg: str | None = None,
        finished: bool = False,
    ) -> None:
        sets = []
        params: dict[str, Any] = {"id": task_id}
        if status is not None:
            sets.append("status = :status")
            params["status"] = status
        if progress is not None:
            sets.append("progress = :progress")
            params["progress"] = progress
        if error_msg is not None:
            sets.append("error_msg = :error_msg")
            params["error_msg"] = error_msg
        if finished:
            sets.append("finished_at = NOW()")
        if not sets:
            return
        async with get_db() as db:
            await db.execute(
                text(f"UPDATE backtest.tasks SET {', '.join(sets)} WHERE id = :id"),
                params,
            )

    async def _load_bars(
        self,
        codes: list[str],
        start_date: date,
        end_date: date,
        *,
        requirement_profile: str | None,
        required_fields: list[str] | None,
    ) -> dict[str, dict[date, Any]]:
        await self.kline_repository.assert_dataset_ready(
            codes,
            period="1d",
            adjustment="raw",
            research_use_scope="return_backtest",
            requirement_profile=requirement_profile,
            required_fields=required_fields,
            start_date=start_date,
            end_date=end_date,
        )
        stored = await self.kline_repository.get_bars_for_profile(
            codes,
            period="1d",
            adjustment="raw",
            research_use_scope="return_backtest",
            requirement_profile=requirement_profile,
            required_fields=required_fields,
            start_date=start_date,
            end_date=end_date,
        )
        rows = [
            {
                **row,
                "stock_code": row["stock_code"].split(".", 1)[0],
                "trade_date": row["trading_date"],
            }
            for row in stored
        ]
                    # prev_close: 用前一日 close 近似

        # 补 prev_close
        by_code: dict[str, list[dict]] = {}
        for r in rows:
            by_code.setdefault(r["stock_code"], []).append(r)
        for code, items in by_code.items():
            items.sort(key=lambda x: x["trade_date"])
            prev = None
            for item in items:
                item["prev_close"] = prev
                prev = float(item["close"])

        flat = [item for items in by_code.values() for item in items]
        return BacktestEngine.bars_from_rows(flat)

    async def _save_result(
        self,
        task_id: int,
        result: BacktestResult,
        summary: dict[str, Any],
        strategy_type: str,
        params: dict[str, Any],
    ) -> None:
        equity = [
            {
                "trade_date": p.trade_date.isoformat(),
                "total_assets": round(p.total_assets, 2),
                "cash": round(p.cash, 2),
                "market_value": round(p.market_value, 2),
                "daily_return": round(p.daily_return, 6),
            }
            for p in result.equity_curve
        ]
        trades = [
            {
                "stock_code": t.stock_code,
                "side": t.side,
                "signal_date": t.signal_date.isoformat(),
                "execution_date": t.execution_date.isoformat(),
                "quantity": t.quantity,
                "fill_price": t.fill_price,
                "status": t.status,
                "fail_reason": t.fail_reason,
            }
            for t in result.trades
        ]
        async with get_db() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO backtest.results
                    (task_id, total_return, annual_return, max_drawdown, sharpe_ratio,
                     calmar_ratio, win_rate, total_trades, equity_curve, trade_list)
                    VALUES
                    (:task_id, :total_return, :annual_return, :max_drawdown, :sharpe_ratio,
                     :calmar_ratio, :win_rate, :total_trades,
                     CAST(:equity_curve AS jsonb), CAST(:trade_list AS jsonb))
                    """
                ),
                {
                    "task_id": task_id,
                    "total_return": summary["total_return"],
                    "annual_return": summary["annual_return"],
                    "max_drawdown": summary["max_drawdown"],
                    "sharpe_ratio": summary["sharpe_ratio"],
                    "calmar_ratio": summary["calmar_ratio"],
                    "win_rate": summary["win_rate"],
                    "total_trades": summary["total_trades"],
                    "equity_curve": json.dumps(equity, ensure_ascii=False),
                    "trade_list": json.dumps(
                        {
                            "strategy_type": strategy_type,
                            "params": params,
                            "trades": trades,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            )


def run_backtest_in_memory(
    *,
    strategy_type: str,
    bars_by_stock: dict,
    start_date: date,
    end_date: date,
    stock_codes: list[str],
    initial_cash: float = 1_000_000,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """纯内存回测（单元测试 / 无 DB）。"""
    meta = get_strategy_meta(strategy_type)
    if not meta:
        raise ValueError(f"未知策略: {strategy_type}")
    merged = {**meta["default_params"], **(params or {})}
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        universe=stock_codes,
        initial_cash=initial_cash,
    )
    gen = make_signal_generator(
        strategy_type, stock_codes, merged, initial_cash=initial_cash
    )
    engine = BacktestEngine()
    result = engine.run(config, bars_by_stock, signal_generator=gen)
    return {
        "metrics": summarize_result(result),
        "filled_trades": result.filled_trades,
        "trading_days": result.trading_days,
        "total_return": result.total_return,
    }
