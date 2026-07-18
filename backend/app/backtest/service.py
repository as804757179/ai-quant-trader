"""回测编排：加载 K 线 → 信号生成 → 引擎执行 → 落库。"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from datetime import date
from typing import Any

from sqlalchemy import text

from app.backtest.engine import BacktestEngine
from app.backtest.metrics import summarize_result
from app.backtest.corporate_actions import CorporateActionProcessor, CorporateActionRepository
from app.backtest.market_rules import AshareMarketRuleRegistry, SecurityStatusSnapshot
from app.backtest.schemas import BacktestConfig, BacktestResult
from app.backtest.trusted_calendar import TrustedTradingCalendar
from app.core.config import settings
from app.core.logging import FEATURE_BACKTEST, get_logger
from app.data.certified_kline_repository import CertifiedKlineRepository
from app.data.kline_contract import KlineContract
from app.db import get_db
from app.strategy.catalog import get_strategy_meta
from app.strategy.config_store import validate_strategy_params
from app.strategy.signals import make_signal_generator
from app.strategy.version_service import StrategyVersionError, StrategyVersionService

logger = get_logger(__name__, feature=FEATURE_BACKTEST)


_BUILTIN_STRATEGY_CODE = {
    "dual_ma": "builtin:dual_ma:v1",
    "bollinger": "builtin:bollinger:v1",
    "rsi": "builtin:rsi:v1",
    "macd": "builtin:macd:v1",
}
_BUILTIN_STRATEGY_FACTORY = {
    "dual_ma": "_make_dual_ma",
    "bollinger": "_make_bollinger",
    "rsi": "_make_rsi",
    "macd": "_make_macd",
}


class BacktestStrategyDisabled(ValueError):
    def __init__(
        self, message: str, code: str = "BACKTEST_STRATEGY_DISABLED"
    ) -> None:
        super().__init__(message)
        self.code = code


class BacktestService:
    def __init__(
        self,
        strategy_versions: StrategyVersionService | None = None,
        kline_repository: CertifiedKlineRepository | None = None,
    ) -> None:
        self.strategy_versions = strategy_versions or StrategyVersionService()
        self.kline_repository = kline_repository or CertifiedKlineRepository()
        self.engine = BacktestEngine()

    @staticmethod
    def _coerce_date(value: date | str) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("backtest dates must use ISO-8601 dates") from exc
        raise ValueError("backtest dates are required")

    @staticmethod
    def _canonical_stock_codes(stock_codes: list[str]) -> list[str]:
        if not stock_codes:
            raise ValueError("stock_codes 不能为空")
        codes = [KlineContract.canonical_symbol(code)[0] for code in stock_codes]
        if len(set(codes)) != len(codes):
            raise ValueError("stock_codes 不能包含重复标的")
        return codes

    @classmethod
    def validate_submission_input(
        cls,
        *,
        strategy_type: str,
        stock_codes: list[str],
        start_date: date | str,
        end_date: date | str,
        initial_cash: float = 1_000_000,
        params: dict[str, Any] | None = None,
        name: str | None = None,
        auto_backfill: bool | None = None,
        allow_synthetic: bool | None = None,
        requirement_profile: str | None = None,
        required_fields: list[str] | None = None,
        strategy_code: str | None = None,
    ) -> None:
        del name
        start = cls._coerce_date(start_date)
        end = cls._coerce_date(end_date)
        meta = get_strategy_meta(strategy_type)
        if not meta:
            raise ValueError(f"未知策略类型: {strategy_type}")
        if not requirement_profile or not required_fields:
            raise ValueError("backtest requirement_profile and required_fields are required")
        if requirement_profile != meta.get("requirement_profile") or set(
            required_fields
        ) != set(meta.get("required_fields") or []):
            raise ValueError("backtest data declaration does not match strategy fields")
        if strategy_code != _BUILTIN_STRATEGY_CODE.get(strategy_type):
            raise ValueError("backtest strategy_code must name the declared builtin version")
        if params is not None and not isinstance(params, dict):
            raise ValueError("backtest params must be an object")
        if start >= end:
            raise ValueError("start_date 必须早于 end_date")
        if float(initial_cash) <= 0:
            raise ValueError("initial_cash 必须大于 0")
        if auto_backfill:
            raise ValueError("可信回测禁止在执行请求内自动回填 K 线")
        if allow_synthetic:
            raise ValueError("可信回测禁止 Synthetic K 线")
        cls._canonical_stock_codes(stock_codes)

    @staticmethod
    def _assert_request_params_match_snapshot(
        *,
        strategy_type: str,
        params: dict[str, Any] | None,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_params = snapshot.get("params")
        if not isinstance(snapshot_params, dict):
            raise BacktestStrategyDisabled(
                "已审批策略快照参数不可用", "BACKTEST_STRATEGY_SNAPSHOT_UNAVAILABLE"
            )
        if params is None:
            return snapshot_params
        if not isinstance(params, dict):
            raise ValueError("backtest params must be an object")
        try:
            requested_params = validate_strategy_params(
                strategy_type, {**snapshot_params, **params}
            )
        except ValueError as exc:
            raise BacktestStrategyDisabled(
                str(exc), "BACKTEST_STRATEGY_CONFIG_MISMATCH"
            ) from exc
        if requested_params != snapshot_params:
            raise BacktestStrategyDisabled(
                "回测请求参数不能覆盖已审批策略版本",
                "BACKTEST_STRATEGY_CONFIG_MISMATCH",
            )
        return snapshot_params

    @staticmethod
    def _version_error_to_backtest(exc: StrategyVersionError) -> BacktestStrategyDisabled:
        code = (
            "BACKTEST_STRATEGY_DISABLED"
            if exc.code in {"STRATEGY_NOT_APPROVED_ENABLED", "STRATEGY_NOT_FOUND"}
            else "BACKTEST_STRATEGY_SNAPSHOT_UNAVAILABLE"
        )
        return BacktestStrategyDisabled(str(exc), code)

    async def resolve_enabled_strategy_snapshot(
        self,
        *,
        strategy_type: str,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        meta = get_strategy_meta(strategy_type)
        if not meta:
            raise ValueError(f"未知策略类型: {strategy_type}")
        if params is not None and not isinstance(params, dict):
            raise ValueError("backtest params must be an object")
        try:
            async with get_db() as db:
                snapshot = await self.strategy_versions.resolve_enabled_snapshot(
                    db, strategy_type=strategy_type
                )
        except StrategyVersionError as exc:
            raise self._version_error_to_backtest(exc) from exc
        self._assert_request_params_match_snapshot(
            strategy_type=strategy_type,
            params=params,
            snapshot=snapshot,
        )
        return snapshot

    async def verify_strategy_snapshot(
        self, strategy_config_snapshot: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not isinstance(strategy_config_snapshot, dict):
            raise BacktestStrategyDisabled(
                "回测任务缺少已审批策略快照",
                "BACKTEST_STRATEGY_SNAPSHOT_UNAVAILABLE",
            )
        try:
            async with get_db() as db:
                return await self.strategy_versions.verify_active_snapshot(
                    db, snapshot=strategy_config_snapshot
                )
        except StrategyVersionError as exc:
            raise self._version_error_to_backtest(exc) from exc

    @staticmethod
    def _builtin_strategy_source(strategy_type: str) -> str:
        from app.strategy import signals

        factory_name = _BUILTIN_STRATEGY_FACTORY.get(strategy_type)
        factory = getattr(signals, factory_name, None) if factory_name else None
        if factory is None:
            raise ValueError("builtin strategy source is unavailable")
        try:
            return "\n\n".join(
                (
                    inspect.getsource(signals._closes_up_to),
                    inspect.getsource(signals._sma),
                    inspect.getsource(signals._ema_series),
                    inspect.getsource(signals._qty_from_pct),
                    inspect.getsource(factory),
                )
            )
        except (OSError, TypeError) as exc:
            raise ValueError("builtin strategy source cannot be inspected") from exc

    async def _load_trusted_security_statuses(
        self, codes: list[str], start_date: date, end_date: date
    ) -> dict[str, SecurityStatusSnapshot]:
        """Require reviewed status coverage instead of inferring tradability."""
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT DISTINCT ON (stock_code)
                           stock_code, status, evidence_source, evidence_version,
                           effective_from, effective_to
                    FROM market.security_status_reviews
                    WHERE stock_code = ANY(:codes)
                      AND effective_from <= :start_date
                      AND effective_to >= :end_date
                      AND status IN ('normal_trade', 'ST')
                      AND btrim(evidence_source) <> ''
                      AND btrim(evidence_version) <> ''
                    ORDER BY stock_code, reviewed_at DESC
                    """
                ),
                {"codes": codes, "start_date": start_date, "end_date": end_date},
            )
            rows = {str(row["stock_code"]): dict(row) for row in result.mappings().all()}

        if set(rows) != set(codes):
            raise ValueError("可信回测缺少覆盖全区间的证券状态证据")

        snapshots: dict[str, SecurityStatusSnapshot] = {}
        for code in codes:
            row = rows[code]
            _, exchange = KlineContract.canonical_symbol(code)
            base = code.split(".", 1)[0]
            board = "GEM" if exchange == "SZ" and base.startswith(("300", "301")) else (
                "STAR" if exchange == "SH" and base.startswith(("688", "689")) else "MAIN"
            )
            snapshots[code] = SecurityStatusSnapshot(
                stock_code=code,
                exchange=exchange,
                board=board,
                security_status="ST" if row["status"] == "ST" else "NORMAL",
                effective_from=start_date,
                effective_to=end_date,
                suspended=False,
                price_limit_exempt=False,
                previous_close_valid=True,
                source_name=str(row["evidence_source"]),
                source_reference=str(row["evidence_version"]),
                status_version=str(row["evidence_version"]),
            )
        return snapshots

    @staticmethod
    async def _load_pit_corporate_actions(
        codes: list[str], end_date: date
    ) -> list[Any]:
        repository = CorporateActionRepository()
        events: list[Any] = []
        for code in codes:
            events.extend(await repository.visible_events(code, end_date))
        return sorted(events, key=lambda event: (event.stock_code, event.announcement_date, event.event_version))

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
        strategy_code: str | None = None,
        strategy_config_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start_date = self._coerce_date(start_date)
        end_date = self._coerce_date(end_date)
        self.validate_submission_input(
            strategy_type=strategy_type,
            stock_codes=stock_codes,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            params=params,
            name=name,
            auto_backfill=auto_backfill,
            allow_synthetic=allow_synthetic,
            requirement_profile=requirement_profile,
            required_fields=required_fields,
            strategy_code=strategy_code,
        )
        if strategy_config_snapshot is None:
            strategy_config_snapshot = await self.resolve_enabled_strategy_snapshot(
                strategy_type=strategy_type,
                params=params,
            )
        else:
            strategy_config_snapshot = await self.verify_strategy_snapshot(
                strategy_config_snapshot
            )
            if strategy_config_snapshot.get("strategy_type") != strategy_type:
                raise BacktestStrategyDisabled(
                    "回测策略类型与已审批快照不一致",
                    "BACKTEST_STRATEGY_SNAPSHOT_UNAVAILABLE",
                )
            self._assert_request_params_match_snapshot(
                strategy_type=strategy_type,
                params=params,
                snapshot=strategy_config_snapshot,
            )
        merged_params = strategy_config_snapshot["params"]
        if not settings.CERTIFIED_BACKTEST_EXECUTION_ENABLED:
            raise ValueError("Sprint06 仅允许 certified 数据可用性检查，真实回测执行仍关闭。")
        meta = get_strategy_meta(strategy_type)
        assert meta is not None
        assert requirement_profile is not None
        assert required_fields is not None
        canonical_codes = self._canonical_stock_codes(stock_codes)

        task_name = name or f"{meta['name']}:{','.join(canonical_codes[:3])}"
        universe_str = ",".join(canonical_codes)

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
            stock_codes=canonical_codes,
            start_date=str(start_date),
            end_date=str(end_date),
            initial_cash=initial_cash,
            auto_backfill=False,
            allow_synthetic=False,
            params=merged_params,
        )
        await self._update_task(task_id, status="running", progress=10)

        data_meta: dict[str, Any] = {
            "backfill": "disabled_for_trusted_backtest",
            "synthetic_used": False,
        }
        t0 = time.perf_counter()
        try:
            await self.kline_repository.assert_dataset_ready(
                canonical_codes,
                period="1d",
                adjustment="raw",
                research_use_scope="return_backtest",
                requirement_profile=requirement_profile,
                required_fields=required_fields,
                start_date=start_date,
                end_date=end_date,
            )
            bars = await self._load_bars(
                canonical_codes,
                start_date,
                end_date,
                requirement_profile=requirement_profile,
                required_fields=required_fields,
            )
            if not bars:
                raise ValueError("回测区间内无已认证且已授权的 K 线数据")

            trading_days, calendar_lineage = await TrustedTradingCalendar().get_days(
                ["SH", "SZ"], start_date, end_date
            )
            if not trading_days:
                raise ValueError("认证交易日历没有可用交易日")
            security_statuses = await self._load_trusted_security_statuses(
                canonical_codes, start_date, end_date
            )
            corporate_actions = await self._load_pit_corporate_actions(
                canonical_codes, end_date
            )
            source = self._builtin_strategy_source(strategy_type)

            config = BacktestConfig(
                start_date=start_date,
                end_date=end_date,
                universe=canonical_codes,
                initial_cash=initial_cash,
                trusted_mode=True,
                trusted_calendar=trading_days,
            )
            generator = make_signal_generator(
                strategy_type,
                canonical_codes,
                merged_params,
                initial_cash=initial_cash,
            )
            await self._update_task(task_id, progress=40)
            trusted_engine = BacktestEngine(
                rule_registry=AshareMarketRuleRegistry(),
                security_statuses=security_statuses,
            )
            result = trusted_engine.run(
                config,
                bars,
                signal_generator=generator,
                corporate_actions=corporate_actions,
                corporate_action_policy=CorporateActionProcessor.POLICY,
                strategy_code=source,
                financial_data_used=False,
            )
            result.metadata["trusted_lineage"] = {
                "calendar": calendar_lineage,
                "calendar_version": TrustedTradingCalendar.VERSION,
                "strategy_code": strategy_code,
                "strategy_source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "strategy_config_snapshot": strategy_config_snapshot,
                "corporate_action_policy": CorporateActionProcessor.POLICY,
                "corporate_action_count": len(corporate_actions),
                "market_rule_registry_version": AshareMarketRuleRegistry.VERSION,
            }
            await self._update_task(
                task_id,
                progress=80,
                lookahead_checked=True,
                lookahead_issues=[],
            )

            summary = summarize_result(result)
            await self._save_result(
                task_id,
                result,
                summary,
                strategy_type,
                merged_params,
                strategy_config_snapshot,
            )
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
                "strategy_config_snapshot": strategy_config_snapshot,
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
                           status, progress, error_msg, created_at, started_at, finished_at,
                           EXISTS (
                               SELECT 1 FROM backtest.results
                               WHERE task_id = backtest.tasks.id
                           ) AS result_available
                    FROM backtest.tasks
                    WHERE id = :id
                    """
                ),
                {"id": task_id},
            )
            task = row.mappings().first()
            if not task:
                raise ValueError(f"任务不存在: {task_id}")

        return {
            "task_id": task["id"],
            "name": task["name"],
            "status": task["status"],
            "progress": task["progress"],
            "error_msg": task["error_msg"],
            "result_available": bool(task["result_available"]),
            "start_date": str(task["start_date"]),
            "end_date": str(task["end_date"]),
            "universe": task["universe"],
            "initial_cash": float(task["initial_cash"] or 0),
            "created_at": task["created_at"].isoformat() if task.get("created_at") else None,
            "finished_at": task["finished_at"].isoformat() if task.get("finished_at") else None,
        }

    async def get_result(self, task_id: int) -> dict[str, Any]:
        """Return a completed task's immutable result separately from its status."""
        async with get_db() as db:
            row = await db.execute(
                text(
                    """
                    SELECT t.id, t.name, t.status, t.start_date, t.end_date,
                           t.universe, t.initial_cash, t.created_at, t.finished_at,
                           r.id AS result_id, r.total_return, r.annual_return,
                           r.max_drawdown, r.sharpe_ratio, r.calmar_ratio,
                           r.win_rate, r.total_trades, r.equity_curve, r.trade_list
                    FROM backtest.tasks t
                    LEFT JOIN LATERAL (
                        SELECT * FROM backtest.results
                        WHERE task_id = t.id
                        ORDER BY id DESC
                        LIMIT 1
                    ) r ON TRUE
                    WHERE t.id = :id
                    """
                ),
                {"id": task_id},
            )
            task = row.mappings().first()

        if not task:
            raise ValueError(f"任务不存在: {task_id}")
        if task["status"] != "done" or task["result_id"] is None:
            raise ValueError("任务结果不可用")

        equity_curve = task["equity_curve"]
        if isinstance(equity_curve, str):
            equity_curve = json.loads(equity_curve)
        trades = task["trade_list"]
        if isinstance(trades, str):
            trades = json.loads(trades)
        return {
            "task_id": task["id"],
            "result_id": task["result_id"],
            "name": task["name"],
            "status": task["status"],
            "start_date": str(task["start_date"]),
            "end_date": str(task["end_date"]),
            "universe": task["universe"],
            "initial_cash": float(task["initial_cash"] or 0),
            "created_at": task["created_at"].isoformat() if task.get("created_at") else None,
            "finished_at": task["finished_at"].isoformat() if task.get("finished_at") else None,
            "metrics": {
                "total_return": float(task["total_return"] or 0),
                "annual_return": float(task["annual_return"] or 0),
                "max_drawdown": float(task["max_drawdown"] or 0),
                "sharpe_ratio": float(task["sharpe_ratio"] or 0),
                "calmar_ratio": float(task["calmar_ratio"] or 0),
                "win_rate": float(task["win_rate"] or 0),
                "total_trades": task["total_trades"],
            },
            "equity_curve": equity_curve,
            "trades": trades,
        }

    async def list_tasks(
        self, *, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("回测任务分页参数非法")
        offset = (page - 1) * page_size
        async with get_db() as db:
            count_result = await db.execute(text("SELECT COUNT(*) AS total FROM backtest.tasks"))
            total = int(count_result.scalar() or 0)
            rows = await db.execute(
                text(
                    """
                    SELECT id, name, status, progress, start_date, end_date,
                           universe, created_at, finished_at, error_msg
                    FROM backtest.tasks
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page_size, "offset": offset},
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
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_more": offset + len(items) < total,
                "source": "backtest.tasks",
                "source_version": "backtest-task-list-v2",
            }

    async def get_validation_summary(self) -> dict[str, Any]:
        async with get_db() as db:
            counts_result = await db.execute(
                text(
                    """
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE status = 'done') AS done,
                           COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                           COUNT(*) FILTER (WHERE status IN ('pending','running')) AS active,
                           MAX(created_at) AS latest_task_at
                    FROM backtest.tasks
                    """
                )
            )
            counts = dict(counts_result.mappings().one())
            completed_result = await db.execute(
                text(
                    """
                    SELECT t.id AS task_id, t.name, t.start_date, t.end_date,
                           t.initial_cash, t.universe, t.created_at, t.finished_at,
                           t.lookahead_checked, t.lookahead_issues,
                           r.id AS result_id, r.total_return, r.annual_return,
                           r.max_drawdown, r.sharpe_ratio, r.calmar_ratio,
                           r.win_rate, r.total_trades, r.equity_curve,
                           r.trade_list, r.created_at AS result_created_at
                    FROM backtest.tasks t
                    JOIN LATERAL (
                        SELECT * FROM backtest.results
                        WHERE task_id = t.id
                        ORDER BY id DESC LIMIT 1
                    ) r ON TRUE
                    WHERE t.status = 'done'
                    ORDER BY t.id DESC
                    LIMIT 1
                    """
                )
            )
            completed = completed_result.mappings().first()

            readiness_items: list[dict[str, Any]] = []
            if completed:
                codes = [
                    value.strip()
                    for value in str(completed["universe"] or "").split(",")
                    if value.strip()
                ]
                if codes:
                    readiness_result = await db.execute(
                        text(
                            """
                            SELECT review_id, stock_code, period, date_from, date_to,
                                   adjustment, readiness_status, research_use_scope,
                                   requirement_profile, required_fields,
                                   policy_version, reviewed_at
                            FROM market.research_readiness_reviews
                            WHERE split_part(stock_code, '.', 1) = ANY(:codes)
                              AND period = '1d'
                              AND adjustment = 'raw'
                              AND research_use_scope = 'return_backtest'
                              AND date_from <= :start_date
                              AND date_to >= :end_date
                            ORDER BY stock_code, reviewed_at DESC, review_id DESC
                            """
                        ),
                        {
                            "codes": codes,
                            "start_date": completed["start_date"],
                            "end_date": completed["end_date"],
                        },
                    )
                    readiness_items = [
                        {
                            **dict(row),
                            "review_id": str(row["review_id"]),
                            "date_from": row["date_from"].isoformat(),
                            "date_to": row["date_to"].isoformat(),
                            "reviewed_at": row["reviewed_at"].isoformat(),
                        }
                        for row in readiness_result.mappings().all()
                    ]

        persisted_result = None
        if completed:
            equity_curve = completed["equity_curve"] or []
            trade_list = completed["trade_list"] or {}
            if isinstance(equity_curve, str):
                equity_curve = json.loads(equity_curve)
            if isinstance(trade_list, str):
                trade_list = json.loads(trade_list)
            hash_payload = {
                "start_date": completed["start_date"].isoformat(),
                "end_date": completed["end_date"].isoformat(),
                "initial_cash": str(completed["initial_cash"]),
                "universe": completed["universe"],
                "metrics": {
                    key: str(completed[key]) if completed[key] is not None else None
                    for key in (
                        "total_return",
                        "annual_return",
                        "max_drawdown",
                        "sharpe_ratio",
                        "calmar_ratio",
                        "win_rate",
                        "total_trades",
                    )
                },
                "equity_curve": equity_curve,
                "trade_list": trade_list,
            }
            result_hash = hashlib.sha256(
                json.dumps(
                    hash_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            strategy_payload = {
                "strategy_type": trade_list.get("strategy_type"),
                "params": trade_list.get("params") or {},
            }
            parameter_hash = hashlib.sha256(
                json.dumps(
                    strategy_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            blocking_reasons = []
            if not completed["lookahead_checked"]:
                blocking_reasons.append("历史任务未记录未来函数检查通过")
            blocking_reasons.extend(
                [
                    "历史任务未记录 dataset_hash",
                    "历史任务未记录策略、引擎和费用版本",
                    "历史任务未记录 Engine/Reference 对账",
                    "历史任务未保存完整 Requirement Profile 授权键",
                ]
            )
            if not readiness_items or any(
                item["readiness_status"] != "ready" for item in readiness_items
            ):
                blocking_reasons.append("当前匹配的 Readiness 审核未全部 ready")
            persisted_result = {
                "task_id": completed["task_id"],
                "result_id": completed["result_id"],
                "name": completed["name"],
                "date_from": completed["start_date"].isoformat(),
                "date_to": completed["end_date"].isoformat(),
                "universe": completed["universe"],
                "lookahead_checked": bool(completed["lookahead_checked"]),
                "lookahead_issues": completed["lookahead_issues"],
                "strategy_type": strategy_payload["strategy_type"],
                "parameter_hash": parameter_hash,
                "persisted_result_hash": result_hash,
                "result_hash_status": "reconstructed_from_persisted_result",
                "dataset_hash": None,
                "dataset_hash_status": "not_recorded_at_run_time",
                "strategy_version": None,
                "strategy_version_status": "not_recorded_at_run_time",
                "engine_version": None,
                "engine_version_status": "not_recorded_at_run_time",
                "cost_hash": None,
                "cost_hash_status": "not_recorded_at_run_time",
                "reference_comparison_status": "not_recorded_at_run_time",
                "validation_status": "blocked" if blocking_reasons else "validated",
                "blocking_reasons": blocking_reasons,
                "readiness_reviews": readiness_items,
                "created_at": completed["created_at"].isoformat(),
                "finished_at": (
                    completed["finished_at"].isoformat()
                    if completed["finished_at"]
                    else None
                ),
            }

        return {
            "summary": {
                "total": int(counts["total"] or 0),
                "done": int(counts["done"] or 0),
                "failed": int(counts["failed"] or 0),
                "active": int(counts["active"] or 0),
                "latest_task_at": (
                    counts["latest_task_at"].isoformat()
                    if counts.get("latest_task_at")
                    else None
                ),
            },
            "latest_persisted_result": persisted_result,
            "current_runtime_versions": {
                "engine": BacktestEngine.VERSION,
                "market_rules": AshareMarketRuleRegistry.VERSION,
                "trading_calendar": TrustedTradingCalendar.VERSION,
            },
            "validation_only": True,
            "not_for_investment": True,
            "public_execution_enabled": bool(
                settings.CERTIFIED_BACKTEST_EXECUTION_ENABLED
            ),
            "source": "backtest.tasks + backtest.results + readiness reviews",
            "source_version": "backtest-validation-summary-v1",
        }

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
        lookahead_checked: bool | None = None,
        lookahead_issues: list[dict[str, Any]] | None = None,
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
        if lookahead_checked is not None:
            sets.append("lookahead_checked = :lookahead_checked")
            params["lookahead_checked"] = lookahead_checked
        if lookahead_issues is not None:
            sets.append("lookahead_issues = CAST(:lookahead_issues AS jsonb)")
            params["lookahead_issues"] = json.dumps(lookahead_issues, ensure_ascii=False)
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
                "stock_code": row["stock_code"],
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
        strategy_config_snapshot: dict[str, Any],
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
                            "strategy_config_snapshot": strategy_config_snapshot,
                            "trusted_lineage": result.metadata.get("trusted_lineage"),
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
